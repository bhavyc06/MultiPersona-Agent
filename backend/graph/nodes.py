"""
backend/graph/nodes.py — Phase 3: MoE gating, intelligent routing,
consensus detection, rolling summarisation.
"""
import asyncio
import json
import logging
import re
import uuid as uuid_module
from pathlib import Path

from backend.claude_client import get_adapter
from backend.config import settings
from backend.graph.contradiction import detect_contradiction
from backend.graph.state import ChatState
from backend.sse.emitter import (
    HUMAN_INPUT_RECEIVED,
    HUMAN_INPUT_REQUIRED,
    PAUSE_ARMED,
    SESSION_COMPLETE,
    emit,
    emit_message,
    emit_session_status,
)

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

ALL_EXPERTS = [
    "ai_architect",
    "solution_architect",
    "data_engineer",
    "data_scientist",
    "ai_engineer",
    "solution_engineer",
    "ui_builder",
    "project_manager",
]

DEFAULT_ROSTER = [
    "solution_architect",
    "solution_engineer",
    "project_manager",
]

# ── Phase 8: per-session side-channel flags checked by supervisor_node ────────
# Keyed by session_id (str). Set by /pause and /finalize endpoints.
# supervisor_node checks at entry — works whether graph is running or paused.
_pause_requests: set[str] = set()
_finalize_requests: set[str] = set()
# _steer_pending mirrors ask_human_node's _ask_human_questions pattern:
# tracks sessions between the first run (pause flag consumed, interrupt raises)
# and the second run (LangGraph replay, interrupt returns the steering text).
_steer_pending: dict[str, bool] = {}
# Tracks sessions whose roster has been announced to the frontend via SSE.
# Prevents double-emission when both roster_selection_node AND supervisor_node
# could fire roster_selected (roster_selection_node sets the flag; supervisor_node
# fires only when the roster was pre-set and roster_selection_node was skipped).
_roster_announced: set[str] = set()

# ── Per-session cost / token accumulator ──────────────────────────────────────
# Populated by _record_usage() after every adapter.complete() call.
# Keyed by session_id; cleaned up by synthesis_node after SESSION_COMPLETE emit.
_session_cost: dict[str, dict] = {}

# ── Per-session output token budget accumulator (FIX-8) ───────────────────────
# Tracks total output tokens per session. Checked by supervisor_node before
# dispatching the next expert. Cleaned up by _persist_status in sessions.py
# when session reaches COMPLETED or FAILED.
# FIX-8: deep fix (native max_tokens) deferred to Bedrock migration in claude_client.py
_session_token_totals: dict[str, int] = {}


def _record_usage(session_id: str, response, role: str = "") -> None:
    """Accumulate token + cost data from a ClaudeResponse into _session_cost."""
    acc = _session_cost.setdefault(session_id, {
        "total_cost_usd":        0.0,
        "input_tokens":          0,
        "output_tokens":         0,
        "cache_creation_tokens": 0,
        "cache_read_tokens":     0,
        "total_duration_ms":     0,
        "by_model":              {},
    })
    acc["total_cost_usd"]        += getattr(response, "cost_usd",              0.0)
    acc["input_tokens"]          += getattr(response, "input_tokens",           0)
    acc["output_tokens"]         += getattr(response, "output_tokens",          0)
    acc["cache_creation_tokens"] += getattr(response, "cache_creation_tokens",  0)
    acc["cache_read_tokens"]     += getattr(response, "cache_read_tokens",      0)
    acc["total_duration_ms"]     += getattr(response, "duration_ms",            0)

    model_key = getattr(response, "model", None) or "unknown"
    if model_key not in acc["by_model"]:
        acc["by_model"][model_key] = {
            "cost_usd":     0.0,
            "input_tokens":  0,
            "output_tokens": 0,
            "calls":         0,
        }
    bm = acc["by_model"][model_key]
    bm["cost_usd"]     += getattr(response, "cost_usd",     0.0)
    bm["input_tokens"]  += getattr(response, "input_tokens",  0)
    bm["output_tokens"] += getattr(response, "output_tokens", 0)
    bm["calls"]         += 1

_AGENT_MD_DIR = Path(".claude/agents")

_FRAMING_SYSTEM = (
    "You are a consulting intake specialist. Generate 2-4 specific, "
    "actionable clarifying questions for the given technical problem. "
    "Each question should uncover information that would materially change "
    "the recommended solution. Return JSON only: "
    '{"questions": ["question 1", "question 2", ...]}'
)

_SYNTHESIS_SYSTEM = (
    "You are the lead consulting architect. Synthesize the expert discussion "
    "into a comprehensive solution document. Be concrete and specific — "
    "reference the actual technologies and decisions from the conversation.\n\n"
    "Return ONLY a valid JSON object with this schema:\n"
    '{"executive_summary": "...", "recommended_architecture": "...", '
    '"key_decisions": ["..."], "implementation_phases": ["..."], '
    '"risks": ["..."], "open_items": ["..."]}'
)

# Turn ceiling raised for group chat (consensus will usually fire earlier)
_TURN_CEILING = 20


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_persona(role: str) -> str:
    path = _AGENT_MD_DIR / f"{role}.md"
    if path.exists():
        return path.read_text()
    return (
        f"You are the {role.replace('_', ' ').title()} "
        f"in a multi-agent consulting group chat with other specialists. "
        f"Read what others have said, build on their points, and challenge "
        f"proposals where you see a problem.\n\n"
        f"Respond with ONLY valid JSON: "
        f'{{"message": "...", "reasoning": "...", '
        f'"proposed_decisions": [], "open_questions": []}}'
    )


def _build_expert_context(state: ChatState, role: str) -> str:
    problem = state.get("enriched_problem") or state["problem_statement"]
    lines: list[str] = []

    memory_context = state.get("memory_context", [])
    if memory_context:
        lines.append("## Prior Session Context (from this user's past sessions)")
        for m in memory_context:
            lines.append(f"- {m}")
        lines.append("(Use as background only — not current requirements.)")
        lines.append("")

    lines.append(f"## Problem Statement\n{problem}\n")

    if state.get("rolling_summary"):
        lines += ["## Prior Discussion Summary", state["rolling_summary"], ""]

    pub = [m for m in state.get("messages", []) if not m.get("is_private", False)]
    if pub:
        recent = pub[-10:]
        lines.append("## Recent Expert Discussion")
        for m in recent:
            lines.append(f"**{m['role']} (turn {m.get('turn', 0)})**: {m['content']}")
        lines.append("")

    locked = [d for d in state.get("decisions", []) if d.get("state") == "locked"]
    if locked:
        lines.append("## Locked Decisions (do NOT re-open)")
        for d in locked:
            lines.append(f"- {d['text']}")
        lines.append("")

    if state.get("rag_chunks"):
        lines.append("## Relevant Reference Material")
        for chunk in state["rag_chunks"][:3]:
            lines.append(
                f"[{chunk.get('source', 'KB')}]: "
                f"{chunk.get('content', '')[:300]}"
            )
        lines.append("")

    lines.append(
        f"As the {role.replace('_', ' ').title()}, provide your expert analysis. "
        "Be specific and actionable. Build on or challenge what others have said."
    )
    return "\n".join(lines)


def _parse_expert_response(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    try:
        data = json.loads(text)
        return {
            "message":            str(data.get("message", text[:800])),
            "reasoning":          str(data.get("reasoning", "")),
            "proposed_decisions": list(data.get("proposed_decisions", [])),
            "open_questions":     list(data.get("open_questions", [])),
            "needs_human_input":  bool(data.get("needs_human_input", False)),
        }
    except json.JSONDecodeError:
        return {
            "message":            text[:1000],
            "reasoning":          "",
            "proposed_decisions": [],
            "open_questions":     [],
            "needs_human_input":  False,
        }


def _parse_json_safe(text: str, fallback: dict) -> dict:
    text = text.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return fallback


async def _persist_message(
    session_id: str,
    role: str,
    content: str,
    is_private: bool,
    turn: int,
    tokens_used: int = 0,
) -> None:
    try:
        import uuid as _uuid
        from backend.db.postgres import AsyncSessionLocal
        from backend.models import AgentMessage
        async with AsyncSessionLocal() as db:
            msg = AgentMessage(
                session_id=_uuid.UUID(session_id),
                agent_role=role,
                phase=turn,
                content=content,
                is_private=is_private,
                tokens_used=tokens_used,
            )
            db.add(msg)
            await db.commit()
    except Exception as exc:
        logger.warning(f"[{session_id}] agent_messages insert failed: {exc}")


# ── Consensus detection ────────────────────────────────────────────────────────

def _check_consensus(state: ChatState) -> bool:
    """
    Returns True when the group can synthesise now.
    Conditions (all must be true):
      1. Every expert in the selected roster has spoken at least once.
      2. No EFFECTIVE (non-superseded) decisions remain in "proposed"
         or "challenged" state.
    """
    roster = state.get("roster") or DEFAULT_ROSTER
    speakers = {
        m["role"]
        for m in state.get("messages", [])
        if not m.get("is_private") and m["role"] in roster
    }
    all_spoke = all(r in speakers for r in roster)

    # Only look at live (non-superseded) decisions
    effective = _get_effective_decisions(state.get("decisions", []))
    no_pending = not any(
        d.get("state") in ("proposed", "challenged")
        for d in effective
    )
    return all_spoke and no_pending


# ── Intelligent supervisor routing ────────────────────────────────────────────

async def _supervisor_route(state: ChatState) -> str:
    """
    Decide who speaks next using a Sonnet call.
    Returns an expert role name, "synthesis", or "ask_human".
    Falls back to the next unheard roster member on error.
    """
    roster = state.get("roster") or DEFAULT_ROSTER
    pub = [m for m in state.get("messages", []) if not m.get("is_private")]
    last_msgs = pub[-5:]

    # Include custom personas in the effective roster for routing decisions
    custom_personas = state.get("custom_personas", [])
    custom_roles = [p["role"] for p in custom_personas]
    effective_roster = roster + [r for r in custom_roles if r not in roster]

    speakers_so_far = list(dict.fromkeys(
        m["role"] for m in pub if m["role"] in effective_roster
    ))
    remaining = [r for r in effective_roster if r not in speakers_so_far]

    proposed = [d["text"] for d in state.get("decisions", []) if d.get("state") == "proposed"]
    locked_count = sum(1 for d in state.get("decisions", []) if d.get("state") == "locked")

    # Build custom persona description block for the routing LLM
    custom_desc = ""
    if custom_personas:
        custom_desc = "\n\nCustom expert personas (may also be selected as next speaker):\n" + "\n".join([
            f"- {p['role']} ({p['display_name']}): {p['system_prompt'][:120]}..."
            for p in custom_personas
        ])

    prompt = (
        f"You are facilitating an expert consulting group chat.\n\n"
        f"Problem: {(state.get('enriched_problem') or state['problem_statement'])[:300]}\n\n"
        f"Expert roster: {roster}\n"
        f"Already spoken: {speakers_so_far}\n"
        f"Remaining to speak: {remaining}\n\n"
        f"Last messages:\n"
        + "\n".join(f"- {m['role']}: {m['content'][:150]}" for m in last_msgs)
        + f"\n\nProposed decisions (not locked): {proposed[:5]}\n"
        f"Locked decisions: {locked_count}\n"
        f"Open questions: {state.get('open_questions', [])[-3:]}\n"
        f"Turn count: {state['turn_count']}"
        + custom_desc
        + "\n\nRules:\n"
        "- project_manager speaks last, after all technical experts\n"
        "- If an expert raised a specific question another expert should answer, route there\n"
        "- If all roster members have spoken and the problem is well covered, return \"synthesis\"\n"
        "- Custom personas may be selected at any point when their expertise is relevant\n"
        "- If a specific human question arises, return \"ask_human\"\n\n"
        'Respond with ONLY valid JSON: {"next": "expert_role_or_synthesis_or_ask_human", "reason": "one sentence"}'
    )

    adapter = get_adapter()
    try:
        response = await adapter.complete(
            system_prompt="You are a meeting facilitator.",
            user_prompt=prompt,
            model=settings.model_sonnet,
            max_tokens=200,
        )
        _record_usage(state["session_id"], response, "routing")
        data = _parse_json_safe(response.text, {"next": "synthesis"})
        next_speaker = data.get("next", "synthesis")
        reason = data.get("reason", "")
        logger.info(
            f"[{state['session_id']}] supervisor → {next_speaker}: {reason}"
        )
        return next_speaker
    except Exception as exc:
        logger.warning(f"[{state['session_id']}] supervisor routing failed: {exc}")
        # Fallback: next unheard expert, or synthesis
        for r in roster:
            if r not in speakers_so_far:
                return r
        return "synthesis"


# ── Rolling summarisation (Option B — summary only, no message replacement) ───

async def _maybe_summarize(state: ChatState, session_id: str) -> dict:
    """
    If public message count > 15, summarise oldest 10 into rolling_summary.
    Returns {"rolling_summary": "..."} or {} if no action taken.
    Uses Haiku (cheap). Does NOT modify messages (append-only constraint).
    """
    pub = [m for m in state.get("messages", []) if not m.get("is_private")]
    if len(pub) <= 15:
        return {}

    to_summarize = pub[:10]
    text = "\n".join(
        f"{m['role']}: {m['content'][:300]}" for m in to_summarize
    )
    adapter = get_adapter()
    try:
        resp = await adapter.complete(
            system_prompt=(
                "Summarize this expert discussion in 2-3 sentences. "
                "Focus on decisions made and key recommendations. Plain text only."
            ),
            user_prompt=text,
            model=settings.model_haiku,
            max_tokens=200,
        )
        _record_usage(session_id, resp, "summary")
        existing = state.get("rolling_summary", "")
        new_summary = (
            f"{existing}\n{resp.text}".strip() if existing else resp.text
        )
        logger.info(f"[{session_id}] rolled up {len(to_summarize)} messages into summary")
        return {"rolling_summary": new_summary}
    except Exception as exc:
        logger.warning(f"[{session_id}] rolling summary failed: {exc}")
        return {}


# ── Roster selection node ─────────────────────────────────────────────────────

async def roster_selection_node(state: ChatState) -> dict:
    """
    MoE gating: select which experts this problem genuinely needs.
    Called once, right after framing completes and before any expert speaks.
    Makes one Sonnet call (max_tokens=300).
    """
    session_id = state["session_id"]
    adapter = get_adapter()

    prompt = (
        "You are selecting the expert team for a consulting engagement.\n\n"
        f"Problem: {state['enriched_problem']}\n\n"
        "Available experts:\n"
        "- ai_architect: AI/ML strategy, model selection, MLOps\n"
        "- solution_architect: System design, components, patterns\n"
        "- data_engineer: Pipelines, ingestion, storage, schemas\n"
        "- data_scientist: Statistics, modeling, experimentation\n"
        "- ai_engineer: LLM integration, RAG, inference pipelines\n"
        "- solution_engineer: Build feasibility, implementation\n"
        "- ui_builder: Frontend/backend proposals, UI mockups\n"
        "- project_manager: Timeline, sequencing, risk, scope\n\n"
        "Select ONLY the experts genuinely needed. "
        "A simple CRUD API needs 3-4 experts. A full ML platform needs 6-8.\n\n"
        "Rules:\n"
        "- Always include project_manager (speaks last)\n"
        "- Always include solution_architect for any system design\n"
        "- Include data experts only if data pipelines are central\n"
        "- Include AI experts only if AI/ML is required\n"
        "- Minimum 3 experts, maximum 8\n\n"
        'Respond with ONLY valid JSON: {"roster": ["expert_role_1", "expert_role_2", ...]}'
    )

    roster: list[str] = []
    try:
        response = await adapter.complete(
            system_prompt="You are a consulting team selector.",
            user_prompt=prompt,
            model=settings.model_sonnet,
            max_tokens=300,
        )
        _record_usage(session_id, response, "roster")
        data = _parse_json_safe(response.text, {"roster": []})
        raw = [r for r in data.get("roster", []) if r in ALL_EXPERTS]

        # Enforce: always end with project_manager
        if "project_manager" in raw:
            raw.remove("project_manager")
        raw.append("project_manager")

        # Enforce minimum
        roster = raw if len(raw) >= 3 else ["solution_architect", "solution_engineer", "project_manager"]
    except Exception as exc:
        logger.warning(f"[{session_id}] roster_selection failed: {exc}")
        roster = ["solution_architect", "solution_engineer", "project_manager"]

    logger.info(f"[{session_id}] roster selected: {roster}")

    # Persist roster to DB sessions table
    try:
        import uuid as _uuid
        from backend.db.postgres import AsyncSessionLocal
        from backend.models import Session
        async with AsyncSessionLocal() as db:
            sess = await db.get(Session, _uuid.UUID(session_id))
            if sess:
                sess.roster = roster
                await db.commit()
    except Exception as exc:
        logger.warning(f"[{session_id}] roster DB persist failed: {exc}")

    _roster_announced.add(session_id)   # guard supervisor_node from double-emitting
    await emit_session_status(session_id, "roster_selected", roster=roster)
    return {"roster": roster}


# ── Supervisor node ───────────────────────────────────────────────────────────

async def supervisor_node(state: ChatState) -> dict:
    """
    Intelligent router. Phase 3 implementation:
    1. Consensus detection — terminate cleanly when experts agree.
    2. Hard ceiling at _TURN_CEILING turns.
    3. LLM-based routing via _supervisor_route.
    4. Rolling summary update.
    Phase 5 additions: delegate-to-supervisor arbitration branch,
    human-directed question detection.
    """
    session_id = state["session_id"]
    turn = state["turn_count"]

    roster = state.get("roster") or DEFAULT_ROSTER
    logger.info(
        f"[ROUTE] [{session_id}] supervisor_node entry: "
        f"turn={turn}, "
        f"current_speaker={state.get('current_speaker')!r}, "
        f"awaiting_human={state.get('awaiting_human')}, "
        f"messages={len(state.get('messages', []))}, "
        f"roster={roster}"
    )

    # ── Phase 5: arbitration branch signals ───────────────────────────────────
    human_input = state.get("human_input") or ""
    if human_input == "[DELEGATE_TO_SUPERVISOR]":
        challenged = [
            d for d in state.get("decisions", [])
            if d.get("state") == "challenged"
        ]
        if challenged:
            import uuid as _uuid_arb
            locks = [
                {
                    "id":            str(_uuid_arb.uuid4()),
                    "text":          d["text"],
                    "proposed_by":   d["proposed_by"],
                    "state":         "locked",
                    "provenance":    "orchestrator",
                    "supersedes_id": d["id"],
                }
                for d in challenged
            ]
            asyncio.create_task(_persist_decisions_db(session_id, locks))
            logger.info(
                f"[{session_id}] delegate branch: locking "
                f"{len(locks)} challenged decisions"
            )
            next_spk = await _supervisor_route(state)
            return {
                "decisions":     locks,
                "human_input":   None,
                "current_speaker": next_spk,
            }

    # ── Phase 7: user-triggered finalize ─────────────────────────────────────
    if human_input == "[USER_FINALIZE]":
        proposed = [
            d for d in state.get("decisions", [])
            if d.get("state") == "proposed"
        ]
        locks: list[dict] = []
        if proposed:
            import uuid as _uuid_fin
            locks = [
                {
                    "id":            str(_uuid_fin.uuid4()),
                    "text":          d["text"],
                    "proposed_by":   d["proposed_by"],
                    "state":         "locked",
                    "provenance":    "human",
                    "supersedes_id": d["id"],
                }
                for d in proposed
            ]
            asyncio.create_task(_persist_decisions_db(session_id, locks))
        logger.info(f"[{session_id}] [USER_FINALIZE] — routing to synthesis")
        await emit_session_status(session_id, "synthesizing")
        return {
            **({"decisions": locks} if locks else {}),
            "human_input":        None,
            "termination_reason": "user_finalize",
            "current_speaker":    None,
        }

    # ── Phase 8: flag-based finalize (works on running graph, no double-stream) ──
    if session_id in _finalize_requests:
        _finalize_requests.discard(session_id)
        proposed = [
            d for d in state.get("decisions", [])
            if d.get("state") == "proposed"
        ]
        fin_locks: list[dict] = []
        if proposed:
            import uuid as _uuid_fin2
            fin_locks = [
                {
                    "id":            str(_uuid_fin2.uuid4()),
                    "text":          d["text"],
                    "proposed_by":   d["proposed_by"],
                    "state":         "locked",
                    "provenance":    "human",
                    "supersedes_id": d["id"],
                }
                for d in proposed
            ]
            asyncio.create_task(_persist_decisions_db(session_id, fin_locks))
        logger.info(f"[{session_id}] _finalize_requests — routing to synthesis")
        await emit_session_status(session_id, "synthesizing")
        return {
            **({"decisions": fin_locks} if fin_locks else {}),
            "human_input":        None,
            "termination_reason": "user_finalize",
            "current_speaker":    None,
        }

    # ── Phase 8: user-initiated pause + steer (two-phase, mirrors ask_human_node)
    #
    # LangGraph re-runs the node from the top on resume, so interrupt() cannot
    # be called in a simple if/else — the flag check would fail on the second run.
    # Pattern: Phase 1 fires on the first run (consumes flag, emits SSE, marks
    # pending), Phase 2 fires on BOTH runs (interrupt raises on run 1, returns
    # the steering text on run 2). Only code AFTER interrupt() executes on run 2.
    _steer_prompt = "What direction should the team take next?"

    # Phase 1 — first run only: consume flag, notify frontend, mark pending
    if session_id in _pause_requests and session_id not in _steer_pending:
        _pause_requests.discard(session_id)
        _steer_pending[session_id] = True
        await emit(session_id, PAUSE_ARMED, {"prompt": _steer_prompt})
        logger.info(f"[{session_id}] user pause — pausing for steering input")

    # Phase 2 — both runs: interrupt() raises on run 1, returns text on run 2
    if session_id in _steer_pending:
        from langgraph.types import interrupt
        steering_text = str(interrupt({"type": "steering", "prompt": _steer_prompt}))

        # Everything below only executes on the SECOND run (after resume)
        _steer_pending.pop(session_id, None)

        msg = {
            "role":       "human",
            "content":    f"[Steered] {steering_text}",
            "turn":       turn,
            "is_private": False,
        }
        await emit_message(session_id, "human", msg["content"], turn, is_private=False)
        asyncio.create_task(
            _persist_message(session_id, "human", msg["content"], False, turn)
        )

        updated_problem = (
            (state.get("enriched_problem") or state["problem_statement"])
            + f"\n\n--- MID-SESSION USER DIRECTIVE ---\n{steering_text}\n"
            + "(All experts must incorporate this directive going forward.)"
        )

        next_spk = await _supervisor_route(state)
        return {
            "messages":         [msg],
            "enriched_problem": updated_problem,
            "human_input":      None,
            "current_speaker":  next_spk,
        }

    # Framing or roster_selection needed — handled by route_from_supervisor
    if not state.get("enriched_problem") or not state.get("roster"):
        return {}

    # Announce the roster to the frontend if roster_selection_node was skipped
    # (i.e., a pre-set roster was provided — manual mode or pre-session custom personas).
    # roster_selection_node sets _roster_announced before emitting; if the session
    # arrives here without going through roster_selection_node, we emit once now.
    # Custom persona definitions are included so the frontend can register emoji/color.
    if session_id not in _roster_announced:
        _roster_announced.add(session_id)
        await emit_session_status(
            session_id,
            "roster_selected",
            roster=list(state.get("roster", [])),
            custom_personas=state.get("custom_personas", []),
        )

    # Rolling summarisation (only updates rolling_summary, not messages)
    summary_update = await _maybe_summarize(state, session_id)

    # ── Wall-clock timeout guard (FIX-5: primary mechanism, supervisor owns this) ──
    import time as _time
    _start = state.get("session_start_time")
    if _start is not None:
        _elapsed = _time.time() - _start
        _timeout = settings.session_timeout_seconds
        if _elapsed >= _timeout:
            logger.warning(
                "[%s] hit wall-clock timeout after %.0fs — forcing synthesis",
                session_id, _elapsed,
            )
            await emit(session_id, "phase_event", {
                "event":           "timeout_forced_synthesis",
                "elapsed_seconds": round(_elapsed),
                "timeout_seconds": _timeout,
            })
            import uuid as _uuid_timeout
            timeout_locks = [
                {
                    "id":            str(_uuid_timeout.uuid4()),
                    "text":          d["text"],
                    "proposed_by":   d["proposed_by"],
                    "state":         "locked",
                    "provenance":    "timeout",
                    "supersedes_id": d["id"],
                }
                for d in state.get("decisions", [])
                if d.get("state") == "proposed"
            ]
            if timeout_locks:
                asyncio.create_task(_persist_decisions_db(session_id, timeout_locks))
            await emit_session_status(session_id, "synthesizing")
            return {
                **summary_update,
                **({"decisions": timeout_locks} if timeout_locks else {}),
                "termination_reason": "timeout",
                "current_speaker":    None,
            }

    # ── Phase 4: Contradiction detection ──────────────────────────────────────
    # Skip when fewer than 2 different experts have spoken (can't contradict
    # yourself) or on the first turn (nothing proposed by others yet).
    pub_speakers = {
        m["role"] for m in state.get("messages", [])
        if not m.get("is_private")
        and m["role"] in (state.get("roster") or DEFAULT_ROSTER)
    }
    if (state["turn_count"] > 1
            and len(pub_speakers) >= 2
            and state.get("decisions")
            and _session_contradiction_count.get(
                session_id, 0) < 6):
        pub = [m for m in state.get("messages", []) if not m.get("is_private")]
        last_speaker = pub[-1]["role"] if pub else None

        if last_speaker:
            # Effective (non-superseded) decisions only, to avoid
            # re-triggering a contradiction already being debated.
            effective_all = _get_effective_decisions(state.get("decisions", []))

            # Decisions proposed by the last speaker (live ones only)
            new_proposed = [
                d["text"] for d in effective_all
                if d.get("state") == "proposed"
                and d.get("proposed_by") == last_speaker
            ]
            # Prior effective decisions from OTHER experts
            prior_effective = [
                d for d in effective_all
                if d.get("proposed_by") != last_speaker
                and d.get("state") in ("proposed", "locked")
            ]

            if new_proposed and prior_effective:
                conflict = await detect_contradiction(
                    new_proposed,
                    prior_effective,
                    state.get("enriched_problem", ""),
                    session_id,
                )

                if conflict:
                    # Increment session total
                    _session_contradiction_count[session_id] = \
                        _session_contradiction_count.get(
                            session_id, 0) + 1

                    conflict_id = conflict["conflicts_with_id"]
                    rounds_used = _challenge_rounds.get(conflict_id, 0)

                    if rounds_used < 2:
                        # Route back to original proposer for debate
                        rounds_used += 1
                        _challenge_rounds[conflict_id] = rounds_used
                        original_proposer = conflict["conflicts_with_by"]

                        await emit(session_id, "contradiction", {
                            "conflict":           conflict,
                            "round":              rounds_used,
                            "challenged_by":      last_speaker,
                            "original_proposer":  original_proposer,
                        })

                        # Mark the challenged decision (new superseding entry)
                        challenged_entry = next(
                            (d for d in state["decisions"] if d["id"] == conflict_id),
                            None,
                        )
                        new_challenged = []
                        if challenged_entry:
                            import uuid as _uuid_c
                            new_challenged = [{
                                **challenged_entry,
                                "id":            str(_uuid_c.uuid4()),
                                "state":         "challenged",
                                "supersedes_id": conflict_id,
                            }]

                        asyncio.create_task(_persist_challenge_round(
                            conflict_id, session_id,
                            last_speaker, rounds_used, "pending",
                        ))

                        logger.info(
                            f"[{session_id}] contradiction — routing to "
                            f"{original_proposer} (round {rounds_used}/2): "
                            f"{conflict['summary']}"
                        )
                        return {
                            **summary_update,
                            **({"decisions": new_challenged} if new_challenged else {}),
                            "current_speaker": original_proposer,
                        }

                    else:
                        # 2 rounds exhausted — supervisor arbitrates
                        logger.info(
                            f"[{session_id}] deadlock after 2 rounds — "
                            f"supervisor locking decision"
                        )
                        await emit(session_id, "arbitration", {
                            "conflict":    conflict,
                            "resolution":  "supervisor_decided",
                            "note": (
                                "Locked by supervisor after 2 debate rounds. "
                                "Phase 5 will add full human arbitration UI."
                            ),
                        })
                        locked = _lock_decision(
                            state["decisions"], conflict_id, "orchestrator"
                        )
                        asyncio.create_task(_persist_challenge_round(
                            conflict_id, session_id,
                            "supervisor", 3, "orchestrator_decided",
                        ))
                        return {
                            **summary_update,
                            **({"decisions": locked} if locked else {}),
                            "current_speaker": await _supervisor_route(state),
                        }
    elif (_session_contradiction_count.get(
            session_id, 0) >= 6
          and state["turn_count"] > 1):
        logger.info(
            f"[{session_id}] contradiction cap (6) reached "
            f"— skipping detection, routing normally"
        )

    # ── Phase 5: human-directed question detection ────────────────────────────
    # Only pause for human input when an expert explicitly sets needs_human_input=true
    # in their JSON output. Keyword-scanning ordinary discussion text is removed
    # because terms like "user", "requirement", "budget" appear in every expert
    # message and caused false-positive hangs.
    _pub_for_human_check = [
        m for m in state.get("messages", []) if not m.get("is_private")
    ]
    _last_msg = _pub_for_human_check[-1] if _pub_for_human_check else {}
    logger.info(
        f"[ROUTE] [{session_id}] human-signal check: "
        f"last_speaker={_last_msg.get('role')!r}, "
        f"needs_human_input={_last_msg.get('needs_human_input', False)}"
    )
    if _last_msg.get("needs_human_input"):
        _unresolved = [
            q for q in state.get("open_questions", [])
            if not q.startswith("[RESOLVED]")
        ]
        logger.info(
            f"[ROUTE] [{session_id}] explicit needs_human_input from "
            f"{_last_msg.get('role')!r} — routing ask_human, "
            f"unresolved_qs={len(_unresolved)}"
        )
        return {
            **summary_update,
            "awaiting_human": True,
            "current_speaker": None,
        }

    # ── Consensus check ────────────────────────────────────────────────────────
    if _check_consensus(state):
        logger.info(f"[{session_id}] consensus reached — locking proposals + synthesising")

        # Direct filter — no supersession logic needed here.
        # We look at ALL entries with state="proposed"; later entries win
        # if the same decision text was re-proposed.
        import uuid as _uuid_lock
        all_proposed = [
            d for d in state.get("decisions", [])
            if d.get("state") == "proposed"
        ]
        decisions_to_lock = [
            {
                "id":            str(_uuid_lock.uuid4()),
                "text":          d["text"],
                "proposed_by":   d["proposed_by"],
                "state":         "locked",
                "provenance":    "converged",
                "supersedes_id": d["id"],
            }
            for d in all_proposed
        ]
        logger.info(
            f"[{session_id}] consensus: all_proposed={len(all_proposed)}, "
            f"decisions_to_lock={len(decisions_to_lock)}"
        )
        if decisions_to_lock:
            asyncio.create_task(
                _persist_decisions_db(session_id, decisions_to_lock)
            )

        await emit_session_status(session_id, "synthesizing")
        return {
            **summary_update,
            **({"decisions": decisions_to_lock} if decisions_to_lock else {}),
            "termination_reason": "consensus",
            "current_speaker": None,
        }

    # FIX-8: session-level token budget guard — force synthesis when budget exceeded
    if _session_token_totals.get(session_id, 0) >= settings.session_token_budget:
        logger.warning(
            f"[{session_id}] token budget exceeded "
            f"({_session_token_totals.get(session_id, 0)} >= {settings.session_token_budget})"
        )
        import uuid as _uuid_budget
        budget_locks = [
            {
                "id":            str(_uuid_budget.uuid4()),
                "text":          d["text"],
                "proposed_by":   d["proposed_by"],
                "state":         "locked",
                "provenance":    "budget_ceiling",
                "supersedes_id": d["id"],
            }
            for d in state.get("decisions", [])
            if d.get("state") == "proposed"
        ]
        if budget_locks:
            asyncio.create_task(_persist_decisions_db(session_id, budget_locks))
        await emit_session_status(session_id, "synthesizing")
        return {
            **summary_update,
            **({"decisions": budget_locks} if budget_locks else {}),
            "termination_reason": "budget_exceeded",
            "current_speaker": None,
        }

    # Hard ceiling — lock any remaining proposed decisions before synthesis
    if turn >= _TURN_CEILING or state.get("solution_document"):
        logger.warning(f"[{session_id}] turn ceiling hit ({turn})")
        import uuid as _uuid_ceil
        ceiling_locks = [
            {
                "id":            str(_uuid_ceil.uuid4()),
                "text":          d["text"],
                "proposed_by":   d["proposed_by"],
                "state":         "locked",
                "provenance":    "ceiling",
                "supersedes_id": d["id"],
            }
            for d in state.get("decisions", [])
            if d.get("state") == "proposed"
        ]
        if ceiling_locks:
            asyncio.create_task(_persist_decisions_db(session_id, ceiling_locks))

        await emit_session_status(session_id, "synthesizing")
        return {
            **summary_update,
            **({"decisions": ceiling_locks} if ceiling_locks else {}),
            "termination_reason": "ceiling",
            "current_speaker": None,
        }

    # ── Helper: lock all remaining proposed decisions before synthesis ────────────
    def _make_synthesis_locks(provenance: str) -> list[dict]:
        import uuid as _uuid_s
        proposed = [d for d in state.get("decisions", []) if d.get("state") == "proposed"]
        locked = [
            {
                "id":            str(_uuid_s.uuid4()),
                "text":          d["text"],
                "proposed_by":   d["proposed_by"],
                "state":         "locked",
                "provenance":    provenance,
                "supersedes_id": d["id"],
            }
            for d in proposed
        ]
        if locked:
            asyncio.create_task(_persist_decisions_db(session_id, locked))
        return locked

    # Intelligent routing
    next_speaker = await _supervisor_route(state)
    logger.info(
        f"[ROUTE] [{session_id}] _supervisor_route returned: next_speaker={next_speaker!r}"
    )

    if next_speaker == "synthesis":
        locks = _make_synthesis_locks("consensus_by_supervisor")
        logger.info(f"[{session_id}] supervisor→synthesis: locking {len(locks)} proposed decisions")
        await emit_session_status(session_id, "synthesizing")
        return {
            **summary_update,
            **({"decisions": locks} if locks else {}),
            "termination_reason": "consensus_by_supervisor",
            "current_speaker": None,
        }

    if next_speaker in ("ask_human", "human_input"):
        # Phase 5 will implement human mid-session pausing; for now continue
        # by picking the next unheard expert
        roster = state.get("roster") or DEFAULT_ROSTER
        pub = [m for m in state.get("messages", []) if not m.get("is_private")]
        heard = {m["role"] for m in pub if m["role"] in roster}
        fallback = next((r for r in roster if r not in heard), "synthesis")
        if fallback == "synthesis":
            locks = _make_synthesis_locks("consensus_by_supervisor")
            await emit_session_status(session_id, "synthesizing")
            return {
                **summary_update,
                **({"decisions": locks} if locks else {}),
                "termination_reason": "consensus_by_supervisor",
                "current_speaker": None,
            }
        next_speaker = fallback

    # Validate the returned speaker is in the roster or is a custom persona
    roster = state.get("roster") or DEFAULT_ROSTER
    _custom_roles = [p["role"] for p in state.get("custom_personas", [])]
    if next_speaker not in ALL_EXPERTS and next_speaker not in _custom_roles:
        # Unexpected response — fall back to first unheard
        pub = [m for m in state.get("messages", []) if not m.get("is_private")]
        heard = {m["role"] for m in pub if m["role"] in roster}
        next_speaker = next((r for r in roster if r not in heard), "synthesis")
        if next_speaker == "synthesis":
            locks = _make_synthesis_locks("ceiling")
            await emit_session_status(session_id, "synthesizing")
            return {
                **summary_update,
                **({"decisions": locks} if locks else {}),
                "termination_reason": "ceiling",
                "current_speaker": None,
            }

    await emit_session_status(session_id, "agent_thinking", agent=next_speaker)
    return {
        **summary_update,
        "current_speaker": next_speaker,
    }


# ── Phase 4: per-session challenge round counters ─────────────────────────────
# Maps decision_id → number of debate rounds consumed (max 2).
_challenge_rounds: dict[str, int] = {}

# Total contradiction rounds fired per session.
# Cap at 6 to prevent runaway loops on ambiguous problems.
_session_contradiction_count: dict[str, int] = {}


# ── Phase 4 helpers ───────────────────────────────────────────────────────────

async def _persist_decisions_db(session_id: str, decisions: list[dict]) -> None:
    """
    Upsert a list of decision dicts into the decisions table.
    Uses INSERT ... ON CONFLICT DO UPDATE so re-runs are idempotent.
    Fire-and-forget — non-fatal on error.
    """
    if not decisions:
        return
    try:
        import uuid as _uuid
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from backend.db.postgres import AsyncSessionLocal
        from backend.models import Decision as DecisionModel
        async with AsyncSessionLocal() as db:
            for d in decisions:
                stmt = pg_insert(DecisionModel).values(
                    id=_uuid.UUID(d["id"]),
                    session_id=_uuid.UUID(session_id),
                    text=d["text"],
                    proposed_by=d.get("proposed_by", "unknown"),
                    state=d.get("state", "proposed"),
                    provenance=d.get("provenance"),
                    supersedes_id=(
                        _uuid.UUID(d["supersedes_id"])
                        if d.get("supersedes_id") else None
                    ),
                ).on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "state":      d.get("state", "proposed"),
                        "provenance": d.get("provenance"),
                    },
                )
                await db.execute(stmt)
            await db.commit()
    except Exception as exc:
        logger.warning(f"[{session_id}] decisions DB upsert failed: {exc}")


async def _persist_challenge_round(
    decision_id: str,
    session_id: str,
    challenger: str,
    round_number: int,
    outcome: str,
) -> None:
    """Write a ChallengeRound row to the DB (fire-and-forget)."""
    try:
        import uuid as _uuid
        from backend.db.postgres import AsyncSessionLocal
        from backend.models import ChallengeRound
        async with AsyncSessionLocal() as db:
            cr = ChallengeRound(
                decision_id=_uuid.UUID(decision_id),
                challenger=challenger,
                round_number=round_number,
                outcome=outcome,
            )
            db.add(cr)
            await db.commit()
    except Exception as exc:
        logger.warning(f"[{session_id}] ChallengeRound persist failed: {exc}")


def _lock_decision(decisions: list[dict], decision_id: str, provenance: str) -> list[dict]:
    """
    Return a new superseding entry with state='locked'.
    The original stays in the append-only list; the new entry points
    back via supersedes_id.
    """
    target = next((d for d in decisions if d["id"] == decision_id), None)
    if not target:
        return []
    import uuid as _uuid
    return [{
        "id":            str(_uuid.uuid4()),
        "text":          target["text"],
        "proposed_by":   target["proposed_by"],
        "state":         "locked",
        "provenance":    provenance,
        "supersedes_id": decision_id,
    }]


def _get_effective_decisions(decisions: list[dict]) -> list[dict]:
    """
    Return only the 'live' decisions — those whose id does not appear
    as the supersedes_id of any other entry.
    Handles the append-only invariant: each state change adds a new
    superseding entry; we exclude the entries being superseded.
    """
    superseded_ids = {d["supersedes_id"] for d in decisions if d.get("supersedes_id")}
    return [d for d in decisions if d["id"] not in superseded_ids]


# ── Framing questions cache ───────────────────────────────────────────────────
_framing_questions: dict[str, list[str]] = {}


# ── Framing node ─────────────────────────────────────────────────────────────

async def framing_node(state: ChatState) -> dict:
    from langgraph.types import interrupt

    session_id = state["session_id"]
    problem = state["problem_statement"]
    adapter = get_adapter()

    if session_id not in _framing_questions:
        logger.info(f"[{session_id}] framing: generating clarifying questions")
        try:
            q_resp = await adapter.complete(
                system_prompt=_FRAMING_SYSTEM,
                user_prompt=f"Technical problem: {problem}",
                model=settings.model_sonnet,
                max_tokens=500,
            )
            _record_usage(session_id, q_resp, "framing")
            q_data = _parse_json_safe(q_resp.text, {"questions": []})
            questions: list[str] = q_data.get("questions", [])
            if not questions:
                questions = [
                    "What is the expected scale (users, transactions/sec, data volume)?",
                    "What is the primary tech stack and cloud provider?",
                    "What are the key constraints (budget, timeline, existing systems)?",
                ]
        except Exception as exc:
            logger.warning(f"[{session_id}] framing question generation failed: {exc}")
            questions = [
                "What is the expected scale?",
                "What is the existing infrastructure?",
                "What are the key constraints?",
            ]

        _framing_questions[session_id] = questions
        await emit_session_status(session_id, "clarification_required", questions=questions)
        logger.info(f"[{session_id}] framing: waiting for user answers")
    else:
        questions = _framing_questions[session_id]
        logger.info(f"[{session_id}] framing: resuming with cached questions")

    answer = interrupt({"questions": questions, "type": "clarification"})

    enriched = (
        f"Original Problem: {problem}\n\n"
        f"Clarifications Provided:\n{answer}"
    )

    rag_chunks: list[dict] = []
    try:
        from backend.tools.search_kb import search_knowledge_base
        rag_chunks = await search_knowledge_base(enriched[:400], top_k=5)
    except Exception as exc:
        logger.warning(f"[{session_id}] framing RAG failed: {exc}")

    _framing_questions.pop(session_id, None)

    await emit_session_status(session_id, "clarification_complete", enriched_problem=enriched[:200])

    return {
        "enriched_problem": enriched,
        "awaiting_human": False,
        "rag_chunks": rag_chunks,
    }


# ── Expert node ───────────────────────────────────────────────────────────────

async def _run_expert(
    state: ChatState,
    role: str,
    system_prompt_override: str | None = None,
    user_prompt_override: str | None = None,
) -> dict:
    session_id = state["session_id"]
    turn = state["turn_count"]
    adapter = get_adapter()

    logger.info(f"[{session_id}] {role} speaking (turn {turn})")

    # Use override when provided (custom personas) — otherwise load from .md file
    persona = system_prompt_override if system_prompt_override else _load_persona(role)
    context = user_prompt_override if user_prompt_override else _build_expert_context(state, role)

    # FIX-4C: per-expert KB grounding — was framing-only
    # Skip for targeted cleanup prompts (user_prompt_override already focused).
    if not user_prompt_override:
        try:
            from backend.tools.search_kb import search_knowledge_base as _search_kb
            _kb_problem = state.get("enriched_problem") or state.get("problem_statement", "")
            _kb_query = f"{role.replace('_', ' ')} {_kb_problem[:200]}"
            _kb_chunks = await _search_kb(query=_kb_query, top_k=3)
            if _kb_chunks:
                _kb_text = "\n\n".join(
                    f"[{c.get('source', 'KB')}]: {c.get('content', '')[:300]}"
                    for c in _kb_chunks
                )
                context = f"Relevant knowledge:\n{_kb_text}\n\n{context}"
        except Exception as _kb_exc:
            logger.warning(f"[{session_id}] {role} per-expert KB search failed: {_kb_exc}")

    _expert_tokens = 0
    try:
        response = await adapter.complete(
            system_prompt=persona,
            user_prompt=context,
            model=settings.model_sonnet,
            max_tokens=1500,
        )
        _record_usage(session_id, response, role)
        _expert_tokens = response.input_tokens + response.output_tokens

        # FIX-8: app-level budget accumulator — session-level token ceiling
        _session_token_totals[session_id] = (
            _session_token_totals.get(session_id, 0) + _expert_tokens
        )

        # FIX-8: app-level output truncation (deep fix deferred to Bedrock migration)
        # Try JSON parse first; truncate only if parse fails and text is oversized,
        # to avoid corrupting mid-valid-JSON.
        raw_text = response.text
        node_max_chars = 1500 * 4  # 1500 tokens × ~4 chars/token
        if len(raw_text) > node_max_chars:
            _clean = re.sub(r"^```[a-z]*\n?", "", raw_text.strip())
            _clean = re.sub(r"\n?```$", "", _clean).strip()
            try:
                json.loads(_clean)
                # Valid JSON despite length — leave intact to avoid corruption
            except json.JSONDecodeError:
                raw_text = raw_text[:node_max_chars]
                logger.warning("FIX-8: response truncated to %d chars for %s", node_max_chars, role)

        parsed = _parse_expert_response(raw_text)
    except Exception as exc:
        logger.error(f"[{session_id}] {role} Claude call failed: {exc}")
        parsed = {
            "message": f"[{role} encountered an error: {exc}]",
            "reasoning": "",
            "proposed_decisions": [],
            "open_questions": [],
            "needs_human_input": False,
        }

    message = parsed["message"]
    reasoning = parsed["reasoning"]
    proposed = parsed["proposed_decisions"]
    open_qs = parsed["open_questions"]
    needs_human_input = parsed["needs_human_input"]

    # Guard: CLI returned empty result — skip turn rather than emit empty bubble
    if not message.strip():
        logger.warning(
            f"[{session_id}] {role} returned EMPTY message at turn {turn} "
            f"(CLI empty result) — skipping turn"
        )
        await emit_message(
            session_id, "system",
            f"[{role.replace('_', ' ').title()} could not respond this turn — skipping]",
            turn, is_private=False,
        )
        return {
            "messages":        [],
            "decisions":       [],
            "open_questions":  [],
            "current_speaker": None,
            "turn_count":      turn + 1,
        }

    await emit_message(session_id, role, message, turn, is_private=False)

    asyncio.create_task(_persist_message(session_id, role, message, False, turn, _expert_tokens))
    if reasoning:
        asyncio.create_task(_persist_message(session_id, role, reasoning, True, turn))

    pub_msg = {
        "role": role,
        "content": message,
        "turn": turn,
        "is_private": False,
        "needs_human_input": needs_human_input,
    }
    priv_msg_list = (
        [{"role": role, "content": reasoning, "turn": turn, "is_private": True}]
        if reasoning else []
    )

    new_decisions = [
        {
            "id": str(uuid_module.uuid4()),
            "text": d,
            "proposed_by": role,
            "state": "proposed",
            "provenance": None,
            "supersedes_id": None,
        }
        for d in proposed
        if d.strip()
    ]

    for dec in new_decisions:
        asyncio.create_task(emit(session_id, "decision", dec))

    # Persist proposed decisions to DB so challenge_rounds FK is satisfiable
    if new_decisions:
        asyncio.create_task(_persist_decisions_db(session_id, new_decisions))

    return {
        "messages":        [pub_msg] + priv_msg_list,
        "decisions":       new_decisions,
        "open_questions":  open_qs,
        "current_speaker": None,
        "turn_count":      turn + 1,
    }


def make_expert_node(role: str):
    async def node(state: ChatState) -> dict:
        return await _run_expert(state, role)
    node.__name__ = role
    return node


# ── Phase 8 Slice 6: Generic custom persona node ──────────────────────────────

async def custom_persona_node(state: ChatState) -> dict:
    """
    Single graph node that serves ALL custom personas.
    Reads the current_speaker role name, looks up its definition in
    state["custom_personas"], and calls _run_expert with the custom
    system_prompt. This avoids adding new graph nodes at runtime —
    the LangGraph topology is fixed; only state changes at runtime.
    """
    session_id = state["session_id"]
    role = state.get("current_speaker", "custom_persona")
    persona_defs = state.get("custom_personas", [])
    persona = next((p for p in persona_defs if p["role"] == role), None)

    if not persona:
        logger.warning(
            f"[{session_id}] custom persona '{role}' not found in state — skipping turn"
        )
        return {"turn_count": state.get("turn_count", 0) + 1}

    return await _run_expert(
        state,
        role=persona["role"],
        system_prompt_override=persona["system_prompt"],
    )


ai_architect_node       = make_expert_node("ai_architect")
solution_architect_node = make_expert_node("solution_architect")
data_engineer_node      = make_expert_node("data_engineer")
data_scientist_node     = make_expert_node("data_scientist")
ai_engineer_node        = make_expert_node("ai_engineer")
solution_engineer_node  = make_expert_node("solution_engineer")


async def project_manager_node(state: ChatState) -> dict:
    # FIX-4A: deterministic timeline call — was never invoked
    result = await _run_expert(state, "project_manager")
    session_id = state["session_id"]

    # Derive timeline inputs from the PM's response
    pm_text = ""
    for msg in result.get("messages", []):
        if msg.get("role") == "project_manager" and not msg.get("is_private"):
            pm_text = msg.get("content", "")
            break
    pm_lower = pm_text.lower()
    complexity = "complex" if "complex" in pm_lower else "simple" if "simple" in pm_lower else "standard"
    features_count = max(1, len(result.get("decisions", [])) or 3)
    scope = {"complexity": complexity, "team_size": 3, "features_count": features_count}

    try:
        from backend.tools.estimate_timeline import estimate_timeline
        timeline = await estimate_timeline(scope)
        await emit(session_id, "tool_result", {
            "agent": "project_manager",
            "tool": "estimate_timeline",
            "result": timeline,
        })
        tool_msg = {
            "role":       "project_manager",
            "content":    f"[TIMELINE ESTIMATE]\n{json.dumps(timeline, indent=2)}",
            "turn":       state.get("turn_count", 0),
            "is_private": True,
        }
        result = {**result, "messages": result.get("messages", []) + [tool_msg]}
        logger.info(f"[{session_id}] estimate_timeline fired: total_weeks={timeline.get('total_weeks')}")
    except Exception as exc:
        logger.error(f"[{session_id}] estimate_timeline failed: {exc}")

    return result


async def ui_builder_node(state: ChatState) -> dict:
    # FIX-4B: deterministic mockup call — was never invoked
    result = await _run_expert(state, "ui_builder")
    session_id = state["session_id"]

    # Derive mockup spec from the UI Builder's response
    ub_text = ""
    for msg in result.get("messages", []):
        if msg.get("role") == "ui_builder" and not msg.get("is_private"):
            ub_text = msg.get("content", "")
            break
    component_description = (ub_text[:300].strip() if ub_text else
                             "Dashboard interface for the proposed solution")
    spec = {
        "session_id":            session_id,
        "component_description": component_description,
        "tech_stack":            "React, TypeScript",
        "color_scheme":          "professional",
    }

    try:
        from backend.tools.generate_mockup import generate_ui_mockup
        mockup = await generate_ui_mockup(spec)
        artifact_ref  = mockup.get("artifact_ref", "")
        preview_html  = mockup.get("preview_html", "")

        # Persist to UiMockup table
        try:
            import uuid as _uuid_m
            from datetime import datetime as _dt
            from backend.db.postgres import AsyncSessionLocal
            from backend.models import UiMockup
            async with AsyncSessionLocal() as db:
                db.add(UiMockup(
                    session_id=_uuid_m.UUID(session_id),
                    artifact_ref=artifact_ref,
                    created_at=_dt.utcnow(),
                ))
                await db.commit()
        except Exception as _db_exc:
            logger.warning(f"[{session_id}] UiMockup DB persist failed: {_db_exc}")

        await emit(session_id, "tool_result", {
            "agent":      "ui_builder",
            "tool":       "generate_ui_mockup",
            "result":     {"html": preview_html, "artifact_ref": artifact_ref, "exportable": True},
        })
        tool_msg = {
            "role":       "ui_builder",
            "content":    f"[UI MOCKUP GENERATED] artifact_ref={artifact_ref}",
            "turn":       state.get("turn_count", 0),
            "is_private": True,
        }
        result = {**result, "messages": result.get("messages", []) + [tool_msg]}
        logger.info(f"[{session_id}] generate_ui_mockup fired: artifact_ref={artifact_ref}")
    except Exception as exc:
        logger.error(f"[{session_id}] generate_ui_mockup failed: {exc}")

    return result


# ── Independent reviewer node ────────────────────────────────────────────────

_REVIEWER_WINDOW = 40  # messages fed to reviewer (wider than synthesis window)

_REVIEWER_SYSTEM = """
You are an independent reviewer. You were not part of the discussion
you are about to read. Your job is to read it cold and identify:
1. GAPS — important questions the team did not address
2. CONFLICTS — places where two experts contradict each other
3. RISKS — significant risks mentioned but not mitigated
4. REDUNDANCY — substantial overlap between expert outputs that
   could be consolidated

You do NOT propose solutions. You flag and describe. Be specific:
name the agents involved, quote the relevant claim, state the gap.
Be ruthless but fair. A finding of "looks good" is not useful.
Produce between 2 and 6 findings. No more than 6.

Return ONLY valid JSON:
{"findings": [{"gap_type": "gap|conflict|risk|redundancy", "description": "...", "agents_affected": ["role", ...], "severity": "high|medium|low"}], "overall_assessment": "..."}
""".strip()


async def reviewer_node(state: ChatState) -> dict:
    session_id = state["session_id"]
    adapter = get_adapter()

    logger.info(f"[{session_id}] reviewer starting")
    await emit(session_id, "agent_start", {"agent_role": "reviewer", "phase": "review"})

    problem = state.get("enriched_problem") or state["problem_statement"]
    all_pub = [m for m in state.get("messages", []) if not m.get("is_private", False)]
    pub = all_pub[-_REVIEWER_WINDOW:]

    conversation = "\n".join(
        f"**{m['role']} (turn {m.get('turn', 0)})**: {m['content']}"
        for m in pub
    ) or "(no expert discussion recorded)"

    locked = [d for d in state.get("decisions", []) if d.get("state") == "locked"]
    decisions_text = "\n".join(
        f"- [{d.get('provenance', '?')}] {d.get('proposed_by', '?')}: {d['text']}"
        for d in locked
    ) or "(none locked)"

    reviewer_prompt = (
        f"Problem: {problem}\n\n"
        f"Expert Discussion:\n{conversation}\n\n"
        f"Locked Decisions:\n{decisions_text}\n\n"
        "Produce your independent review findings as JSON."
    )

    findings: list[dict] = []
    overall_assessment = ""
    try:
        resp = await adapter.complete(
            system_prompt=_REVIEWER_SYSTEM,
            user_prompt=reviewer_prompt,
            model=settings.model_sonnet,
            max_tokens=1500,
        )
        _record_usage(session_id, resp, "reviewer")
        parsed = _parse_json_safe(resp.text, {"findings": [], "overall_assessment": ""})
        findings = parsed.get("findings", [])[:6]  # hard cap at 6
        overall_assessment = parsed.get("overall_assessment", "")
        logger.info(f"[{session_id}] reviewer: {len(findings)} findings")
    except Exception as exc:
        logger.warning(f"[{session_id}] reviewer failed — skipping: {exc}")

    await emit(session_id, "reviewer_complete", {
        "findings":            findings,
        "overall_assessment":  overall_assessment,
        "finding_count":       len(findings),
    })
    await emit(session_id, "agent_end", {"agent_role": "reviewer", "decisions_locked": []})

    return {
        "reviewer_findings": findings,
        "reviewer_done":     True,
    }


# ── Cleanup round node ────────────────────────────────────────────────────────

async def cleanup_round_node(state: ChatState) -> dict:
    session_id  = state["session_id"]
    findings    = state.get("reviewer_findings", [])

    # Only high-severity findings trigger cleanup turns
    high = [f for f in findings if f.get("severity") == "high"]

    # Collect unique affected agents in finding order, cap at 3 turns
    seen: list[str] = []
    for f in high:
        for agent in f.get("agents_affected", []):
            if agent not in seen:
                seen.append(agent)
    cleanup_agents = seen[:3]

    all_messages:  list[dict] = []
    all_decisions: list[dict] = []

    for agent in cleanup_agents:
        agent_findings = [f for f in high if agent in f.get("agents_affected", [])]
        finding_descs  = "\n".join(f"- {f['description']}" for f in agent_findings)
        targeted_prompt = (
            f"The reviewer flagged the following in your analysis:\n{finding_descs}\n\n"
            "Address this specifically in 200 words or fewer."
        )
        try:
            cleanup_result = await _run_expert(
                state,
                role=agent,
                user_prompt_override=targeted_prompt,
            )
            all_messages.extend(cleanup_result.get("messages", []))
            all_decisions.extend(cleanup_result.get("decisions", []))
        except Exception as exc:
            logger.error(f"[{session_id}] cleanup turn for {agent} failed: {exc}")

    await emit(session_id, "cleanup_complete", {
        "turns_taken":       len(cleanup_agents),
        "agents_addressed":  cleanup_agents,
    })

    return {
        "messages":            all_messages,
        "decisions":           all_decisions,
        "cleanup_round_done":  True,
        "turn_count":          state.get("turn_count", 0),  # don't increment — infrastructure turns
    }


# ── Synthesis node ────────────────────────────────────────────────────────────

async def synthesis_node(state: ChatState) -> dict:
    session_id = state["session_id"]
    adapter = get_adapter()

    logger.info(f"[{session_id}] synthesis starting")

    problem = state.get("enriched_problem") or state["problem_statement"]

    # FIX-10: was feeding full un-truncated transcript — quality risk on long sessions
    all_pub = [m for m in state.get("messages", []) if not m.get("is_private", False)]
    window = settings.synthesis_transcript_window
    dropped = all_pub[:-window] if len(all_pub) > window else []
    pub = all_pub[-window:]

    # Build opening context block — rolling_summary SUBSTITUTES for the dropped tail
    # rather than stacking on top of it (avoids double-counting the same content).
    rolling_summary = state.get("rolling_summary", "")
    dropped_summary = ""
    if dropped:
        if rolling_summary:
            # Use existing rolling summary as the stand-in for dropped messages
            dropped_summary = rolling_summary
        else:
            # No rolling summary exists — create one from the dropped tail (cheap Haiku call)
            dropped_text = "\n".join(
                f"{m['role']} (turn {m.get('turn', 0)}): {m['content'][:200]}"
                for m in dropped
            )
            try:
                _summ_resp = await adapter.complete(
                    system_prompt=(
                        "Summarize the key technical decisions and discussion points "
                        "from these expert conversation excerpts in 2-3 paragraphs."
                    ),
                    user_prompt=dropped_text,
                    model=settings.model_haiku,
                    max_tokens=500,
                )
                _record_usage(session_id, _summ_resp, "synthesis_summary")
                dropped_summary = _summ_resp.text
            except Exception as _summ_exc:
                logger.warning(f"[{session_id}] dropped-message summary failed: {_summ_exc}")
                dropped_summary = f"[{len(dropped)} earlier messages not shown]"

    # Collect locked decisions — iterate in reverse so the latest entry
    # per text wins; dedup by text to avoid counting superseded+new pairs.
    all_decisions = state.get("decisions", [])
    locked_states = [d.get("state") for d in all_decisions]
    logger.info(
        f"[{session_id}] synthesis entry: "
        f"{len(all_decisions)} decisions, states={locked_states}"
    )
    seen_texts: set[str] = set()
    locked: list[dict] = []
    for d in reversed(all_decisions):
        text = d.get("text", "")
        if d.get("state") == "locked" and text not in seen_texts:
            seen_texts.add(text)
            locked.append(d)
    logger.info(f"[{session_id}] synthesis: locked decisions found={len(locked)}")

    # Fallback: if no locked entries found, lock all proposed entries right
    # here in synthesis (handles the case where locking happened in the same
    # turn as synthesis routing)
    if not locked:
        import uuid as _uuid_syn
        logger.warning(
            f"[{session_id}] synthesis: no locked decisions "
            f"found, locking all proposed as fallback"
        )
        proposed_all = [d for d in all_decisions if d.get("state") == "proposed"]
        locked = [
            {
                "id":            str(_uuid_syn.uuid4()),
                "text":          d["text"],
                "proposed_by":   d["proposed_by"],
                "state":         "locked",
                "provenance":    "converged",
                "supersedes_id": d["id"],
            }
            for d in proposed_all
        ]
        if locked:
            asyncio.create_task(_persist_decisions_db(session_id, locked))

    # Build windowed conversation — prepend summary block if messages were dropped
    conv_parts = []
    if dropped_summary:
        conv_parts.append(f"[Summary of earlier exchanges]: {dropped_summary}")
    conv_parts.extend(
        f"**{m['role']} (turn {m.get('turn', 0)})**: {m['content']}"
        for m in pub
    )
    conversation = "\n".join(conv_parts) or "(no expert discussion recorded)"

    decisions_text = "\n".join(
        f"- [{d.get('provenance', '?')}] {d.get('proposed_by', '?')}: {d['text']}"
        for d in locked
    ) or "(none locked)"

    synthesis_user = (
        f"Problem: {problem}\n\n"
        f"Expert Discussion:\n{conversation}\n\n"
        f"Locked Decisions ({len(locked)} total):\n{decisions_text}\n\n"
        "Synthesize into a comprehensive solution document. "
        "Include ALL locked decisions verbatim in the key_decisions list."
    )

    # Part E: give synthesis explicit awareness of reviewer findings and cleanup
    if state.get("reviewer_findings"):
        findings_text = "\n".join(
            f"- [{f['gap_type'].upper()}] {f['description']}"
            for f in state["reviewer_findings"]
        )
        synthesis_user += f"\n\nReviewer findings addressed in cleanup:\n{findings_text}"

    # Part C (FIX-5): when synthesis is forced by timeout, flag the incomplete coverage
    if state.get("termination_reason") == "timeout":
        synthesis_preamble = (
            "Note: this session reached its time limit before all experts "
            "contributed. Synthesise the best possible solution from the "
            "experts who did contribute. Clearly note any workstreams that "
            "were not covered due to the time limit."
        )
    else:
        synthesis_preamble = ""
    effective_synthesis_system = (
        f"{synthesis_preamble}\n\n{_SYNTHESIS_SYSTEM}" if synthesis_preamble
        else _SYNTHESIS_SYSTEM
    )

    try:
        resp = await adapter.complete(
            system_prompt=effective_synthesis_system,
            user_prompt=synthesis_user,
            model=settings.model_opus,
            max_tokens=3000,
        )
        _record_usage(session_id, resp, "synthesis")
        doc = _parse_json_safe(resp.text, {
            "executive_summary":       "Synthesis completed.",
            "recommended_architecture": resp.text[:1000],
            "key_decisions":           [],
            "implementation_phases":   [],
            "risks":                   [],
            "open_items":              [],
        })
    except Exception as exc:
        logger.error(f"[{session_id}] synthesis Claude call failed: {exc}")
        doc = {
            "executive_summary":       f"Synthesis failed: {exc}",
            "recommended_architecture": "",
            "key_decisions":           [],
            "implementation_phases":   [],
            "risks":                   [str(exc)],
            "open_items":              [],
        }

    import json as _json
    sol_path = Path(f"data/sessions/{session_id}/solution.json")
    sol_path.parent.mkdir(parents=True, exist_ok=True)
    sol_path.write_text(_json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    try:
        import uuid as _uuid
        from sqlalchemy import select as _sd_select
        from backend.db.postgres import AsyncSessionLocal
        from backend.models import SolutionDocument
        async with AsyncSessionLocal() as db:
            # Idempotent: skip insert if a row already exists (guards double-synthesis)
            existing = await db.execute(
                _sd_select(SolutionDocument).where(
                    SolutionDocument.session_id == _uuid.UUID(session_id)
                )
            )
            if existing.scalar_one_or_none() is None:
                sd = SolutionDocument(
                    session_id=_uuid.UUID(session_id),
                    structured_content=doc,
                )
                db.add(sd)
                await db.commit()
            else:
                logger.info(
                    f"[{session_id}] solution_documents already exists — skipping insert"
                )
    except Exception as exc:
        logger.warning(f"[{session_id}] solution_documents insert failed: {exc}")

    # Persist locked decisions synchronously before emitting session_complete
    # so DB rows exist when the client queries immediately after the event.
    if locked:
        await _persist_decisions_db(session_id, locked)

    # Persist termination_reason to the sessions table
    _term = state.get("termination_reason") or "consensus"
    try:
        import uuid as _uuid_tr
        from sqlalchemy import update as _sa_update
        from backend.models import Session as _SessModel
        async with AsyncSessionLocal() as db:
            await db.execute(
                _sa_update(_SessModel)
                .where(_SessModel.id == _uuid_tr.UUID(session_id))
                .values(termination_reason=_term)
            )
            await db.commit()
        logger.info(f"[{session_id}] termination_reason persisted: {_term}")
    except Exception as _tr_exc:
        logger.warning(f"[{session_id}] termination_reason persist failed: {_tr_exc}")

    # Write accumulated token totals to Session DB row
    _cost_acc = _session_cost.get(session_id, {})
    try:
        import uuid as _uuid_tok
        from sqlalchemy import update as _sa_tok_upd
        from backend.models import Session as _SessModel_tok
        async with AsyncSessionLocal() as _db_tok:
            await _db_tok.execute(
                _sa_tok_upd(_SessModel_tok)
                .where(_SessModel_tok.id == _uuid_tok.UUID(session_id))
                .values(
                    total_input_tokens=_cost_acc.get("input_tokens", 0),
                    total_output_tokens=_cost_acc.get("output_tokens", 0),
                    cached_tokens=(
                        _cost_acc.get("cache_creation_tokens", 0)
                        + _cost_acc.get("cache_read_tokens", 0)
                    ),
                )
            )
            await _db_tok.commit()
    except Exception as _tok_exc:
        logger.warning(f"[{session_id}] token totals persist failed: {_tok_exc}")

    await emit(session_id, SESSION_COMPLETE, {
        "solution_document":     doc,
        "locked_decisions":      locked,
        # Legacy fields (kept for backward compat)
        "total_tokens":          _cost_acc.get("input_tokens", 0) + _cost_acc.get("output_tokens", 0),
        "cost_usd":              _cost_acc.get("total_cost_usd", 0.0),
        # Full usage breakdown for CostPanel
        "total_cost_usd":        _cost_acc.get("total_cost_usd", 0.0),
        "total_input_tokens":    _cost_acc.get("input_tokens", 0),
        "total_output_tokens":   _cost_acc.get("output_tokens", 0),
        "cache_creation_tokens": _cost_acc.get("cache_creation_tokens", 0),
        "cache_read_tokens":     _cost_acc.get("cache_read_tokens", 0),
        "total_duration_ms":     _cost_acc.get("total_duration_ms", 0),
        "by_model":              _cost_acc.get("by_model", {}),
    })
    _session_cost.pop(session_id, None)   # prevent unbounded growth

    try:
        from backend.memory.compressor import compress_session
        asyncio.create_task(compress_session(session_id, state["user_id"]))
    except Exception as exc:
        logger.warning(f"[{session_id}] memory compression task failed: {exc}")

    termination = state.get("termination_reason") or "consensus"
    logger.info(f"[{session_id}] synthesis complete, reason={termination}")
    return {"solution_document": doc, "termination_reason": termination}


# ── Phase 5: ask_human_node ───────────────────────────────────────────────────

# Per-session cache — prevents double-emit when LangGraph re-runs node on resume
_ask_human_questions: dict[str, str] = {}

# Safety net: cap how many times the graph may pause for human input per session.
# If an expert keeps emitting needs_human_input=true (e.g. bad prompt), this
# prevents an infinite interrupt loop.
_ask_human_count: dict[str, int] = {}
ASK_HUMAN_MAX = 2


async def ask_human_node(state: ChatState) -> dict:
    """
    Mid-conversation human input node.
    Uses interrupt() — same pattern as framing_node.
    Fires when an expert explicitly sets needs_human_input=true.
    Guarded by ASK_HUMAN_MAX to prevent infinite interrupt loops.
    """
    from langgraph.types import interrupt
    session_id = state["session_id"]

    open_qs = state.get("open_questions", [])
    unresolved = [q for q in open_qs if not q.startswith("[RESOLVED]")]

    # ── Safety cap ────────────────────────────────────────────────────────────
    count = _ask_human_count.get(session_id, 0)
    if count >= ASK_HUMAN_MAX:
        logger.warning(
            f"[ROUTE] [{session_id}] ask_human cap ({ASK_HUMAN_MAX}) reached "
            f"— auto-continuing without human input"
        )
        return {
            "messages": [],
            "open_questions": ([f"[RESOLVED] {unresolved[-1]}"] if unresolved else []),
            "awaiting_human": False,
            "human_input": None,
        }
    _ask_human_count[session_id] = count + 1

    question = (
        unresolved[-1] if unresolved
        else "Do you have any additional context to share?"
    )

    if session_id not in _ask_human_questions:
        _ask_human_questions[session_id] = question
        await emit(session_id, HUMAN_INPUT_REQUIRED, {
            "question": question,
            "turn": state["turn_count"],
        })
        logger.info(f"[{session_id}] ask_human: pausing for human input")

    answer = interrupt({"type": "human_input", "question": question})
    _ask_human_questions.pop(session_id, None)

    await emit(session_id, HUMAN_INPUT_RECEIVED, {
        "question": question,
        "answer": str(answer)[:200],
    })

    human_msg = {
        "role": "human",
        "content": f"[Human: {answer}]",
        "turn": state["turn_count"],
        "is_private": False,
    }
    asyncio.create_task(
        _persist_message(session_id, "human", human_msg["content"], False, state["turn_count"])
    )

    return {
        "messages": [human_msg],
        "open_questions": [f"[RESOLVED] {question}"],
        "awaiting_human": False,
        "human_input": str(answer),
    }
