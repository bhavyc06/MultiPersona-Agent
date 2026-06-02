import asyncio
import json
import re
from dataclasses import dataclass, field

from backend.claude_client import get_adapter
from backend.config import settings
from backend.sse.emitter import CLARIFICATION_REQUIRED, emit

# ── System prompts (CLAUDE.md §7.2) ─────────────────────────────────────────

_QUESTION_SYSTEM = (
    "You are a consulting intake specialist. Given a technical problem and any prior Q&A, "
    "identify the 2-4 most critical unknowns that would materially change the technical approach.\n\n"
    "Rules:\n"
    "- Ask only questions whose answers would significantly affect architecture or implementation.\n"
    "- Do not ask questions already answered in prior rounds.\n"
    "- If you have enough information to scope a complete solution, return an empty list.\n"
    "- Keep questions concise and specific.\n\n"
    "Respond ONLY with valid JSON — no markdown, no preamble:\n"
    '{"questions": ["question 1", "question 2"]}'
)

_READINESS_SYSTEM = (
    "Given a technical problem and the clarifications provided, determine whether there is "
    "enough information to scope a complete technical solution.\n\n"
    "Respond ONLY with valid JSON:\n"
    '{"ready": true} or {"ready": false}'
)

# ── Per-session answer queues ────────────────────────────────────────────────

_answer_queues: dict[str, asyncio.Queue] = {}


def get_answer_queue(session_id: str) -> asyncio.Queue:
    if session_id not in _answer_queues:
        _answer_queues[session_id] = asyncio.Queue(maxsize=1)
    return _answer_queues[session_id]


def cleanup_answer_queue(session_id: str) -> None:
    _answer_queues.pop(session_id, None)


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class ClarificationRound:
    round: int
    questions: list[str]
    answers: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"round": self.round, "questions": self.questions, "answers": self.answers}


@dataclass
class ClarificationResult:
    enriched_problem: str
    rounds: list[ClarificationRound]
    is_complete: bool


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_prior_rounds(rounds: list[ClarificationRound]) -> str:
    if not rounds:
        return "(none)"
    lines = []
    for r in rounds:
        for i, q in enumerate(r.questions):
            a = r.answers.get(str(i), "(no answer)")
            lines.append(f"Q: {q}\nA: {a}")
    return "\n".join(lines)


def _parse_json(text: str, fallback: dict) -> dict:
    text = text.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return fallback


def _build_enriched_problem(problem: str, rounds: list[ClarificationRound]) -> str:
    parts = [f"Original Problem: {problem}"]
    if rounds:
        parts.append("\nClarifications Provided:")
        for r in rounds:
            parts.append(f"\nRound {r.round}:")
            for i, q in enumerate(r.questions):
                a = r.answers.get(str(i), "(no answer provided)")
                parts.append(f"Q: {q}\nA: {a}")
    return "\n".join(parts)


# ── Main loop ─────────────────────────────────────────────────────────────────

async def run_clarification_loop(
    session_id: str,
    problem: str,
    max_rounds: int = 3,
) -> ClarificationResult:
    """
    Runs up to max_rounds of Sonnet question generation + user answer collection
    + Haiku readiness checks. Returns a ClarificationResult with the enriched
    problem string that downstream agents use as their primary input.

    # TOKEN RISK: up to 3 Sonnet (max_tokens=600) + 3 Haiku (max_tokens=100) CLI
    # calls run before any persona agent. Billed before session classification.
    """
    adapter = get_adapter()
    rounds: list[ClarificationRound] = []
    is_complete = False

    for round_num in range(1, max_rounds + 1):
        try:
            import logfire
            round_span = logfire.span(
                "clarification.round",
                session_id=session_id,
                round=round_num,
                max_rounds=max_rounds,
            )
        except Exception:
            from contextlib import nullcontext
            round_span = nullcontext()

        with round_span:
            prior_qa = _format_prior_rounds(rounds)
            user_msg = f"Problem: {problem}\n\nPrior Q&A:\n{prior_qa}"

            # Step 1 — Sonnet: generate clarifying questions
            q_response = await adapter.complete(
                system_prompt=_QUESTION_SYSTEM,
                user_prompt=user_msg,
                model=settings.model_sonnet,
                max_tokens=600,
            )
            q_data = _parse_json(q_response.text, {"questions": []})
            questions: list[str] = q_data.get("questions", [])

            if not questions:
                # Model signals no further clarification needed
                is_complete = True
                break

            # Step 2 — emit clarification_required SSE
            await emit(session_id, CLARIFICATION_REQUIRED, {
                "questions": questions,
                "round": round_num,
                "max_rounds": max_rounds,
            })

            # Step 3 — await user answers (timeout = 5 min per CLAUDE.md §7.2)
            try:
                raw_answers: dict[str, str] = await asyncio.wait_for(
                    get_answer_queue(session_id).get(),
                    timeout=float(settings.clarification_answer_timeout_seconds),
                )
            except asyncio.TimeoutError:
                raw_answers = {}

            this_round = ClarificationRound(
                round=round_num,
                questions=questions,
                answers=raw_answers,
            )
            rounds.append(this_round)

            # Step 4 — Haiku: readiness check
            all_qa = _format_prior_rounds(rounds)
            haiku_user = f"Problem: {problem}\n\nClarifications:\n{all_qa}"
            r_response = await adapter.complete(
                system_prompt=_READINESS_SYSTEM,
                user_prompt=haiku_user,
                model=settings.model_haiku,
                max_tokens=100,
            )
            r_data = _parse_json(r_response.text, {"ready": False})

            if r_data.get("ready", False):
                is_complete = True
                break
            # else: round == max_rounds → loop terminates naturally

    try:
        import logfire
        logfire.info("clarification.complete",
            session_id=session_id,
            rounds_taken=len(rounds),
            is_complete=is_complete)
    except Exception:
        pass

    enriched = _build_enriched_problem(problem, rounds)
    return ClarificationResult(
        enriched_problem=enriched,
        rounds=rounds,
        is_complete=is_complete,
    )
