import asyncio
import json
from datetime import datetime
from pathlib import Path

SESSIONS_DIR = Path("data/sessions")

# Per-session write locks to prevent concurrent scratchpad corruption
_locks: dict[str, asyncio.Lock] = {}


def _path(session_id: str) -> Path:
    return SESSIONS_DIR / session_id / "scratchpad.json"


def _lock(session_id: str) -> asyncio.Lock:
    if session_id not in _locks:
        _locks[session_id] = asyncio.Lock()
    return _locks[session_id]


async def initialize_scratchpad(
    session_id: str,
    problem: str,
    memory_ctx: list[str] | None = None,
    rag_chunks: list[dict] | None = None,
    clarification_context: dict | None = None,
) -> Path:
    path = _path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Default clarification_context when not provided (CLAUDE.md §10)
    if clarification_context is None:
        clarification_context = {
            "rounds": [],
            "enriched_problem": problem,
            "is_complete": False,
        }

    # Full schema from CLAUDE.md §10
    data = {
        "session_id": session_id,
        "problem_statement": problem,          # raw original — never modified
        "clarification_context": clarification_context,   # NEW — agents use enriched_problem here
        "complexity": None,
        "memory_context": memory_ctx or [],
        "rag_chunks": rag_chunks or [],
        "decision_log": [],
        "open_questions": [],
        "agent_outputs": {},
        "phase_plan": [],
    }

    async with _lock(session_id):
        path.write_text(json.dumps(data, indent=2))

    return path


async def read_scratchpad(session_id: str) -> dict:
    async with _lock(session_id):
        return json.loads(_path(session_id).read_text())


async def write_agent_output(session_id: str, agent_role: str, output: dict) -> None:
    async with _lock(session_id):
        path = _path(session_id)
        data = json.loads(path.read_text())
        data["agent_outputs"][agent_role] = output
        path.write_text(json.dumps(data, indent=2))


async def append_decision(
    session_id: str, decision: str, locked_by: str, phase: int
) -> None:
    # Decision log is append-only — never mutate existing entries (CLAUDE.md §10)
    async with _lock(session_id):
        path = _path(session_id)
        data = json.loads(path.read_text())
        data["decision_log"].append(
            {
                "decision": decision,
                "locked_by": locked_by,
                "phase": phase,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )
        path.write_text(json.dumps(data, indent=2))


async def set_complexity(session_id: str, complexity: str) -> None:
    async with _lock(session_id):
        path = _path(session_id)
        data = json.loads(path.read_text())
        data["complexity"] = complexity
        path.write_text(json.dumps(data, indent=2))


async def set_phase_plan(session_id: str, phase_plan: list[dict]) -> None:
    async with _lock(session_id):
        path = _path(session_id)
        data = json.loads(path.read_text())
        data["phase_plan"] = phase_plan
        path.write_text(json.dumps(data, indent=2))


async def merge_phase_outputs(session_id: str, phase: int) -> None:
    """Collect open questions from all agent outputs into the top-level list."""
    async with _lock(session_id):
        path = _path(session_id)
        data = json.loads(path.read_text())
        merged: set[str] = set(data.get("open_questions", []))
        for output in data["agent_outputs"].values():
            for q in output.get("open_questions", []):
                merged.add(q)
        data["open_questions"] = list(merged)
        path.write_text(json.dumps(data, indent=2))


async def update_rag_chunks(session_id: str, chunks: list[dict]) -> None:
    """Replace the rag_chunks field with freshly retrieved KB results."""
    async with _lock(session_id):
        path = _path(session_id)
        data = json.loads(path.read_text())
        data["rag_chunks"] = chunks
        path.write_text(json.dumps(data, indent=2))


async def get_scratchpad_token_count(session_id: str) -> int:
    """Rough token estimate for budget checks — 1 token ≈ 4 chars."""
    return len(_path(session_id).read_text()) // 4


async def summarize_if_large(session_id: str) -> bool:
    """
    If the scratchpad exceeds 8 000 estimated tokens, compress agent_outputs
    with a Haiku call to keep downstream context lean.

    Returns True if summarization was performed.
    Called by phase_barrier after Phase 2 completes (CLAUDE.md §15).
    """
    token_count = await get_scratchpad_token_count(session_id)
    if token_count <= 8000:
        return False

    from backend.claude_client import get_adapter
    from backend.config import settings

    adapter = get_adapter()

    async with _lock(session_id):
        path = _path(session_id)
        data = json.loads(path.read_text())
        outputs = data.get("agent_outputs", {})
        if not outputs:
            return False

        outputs_text = json.dumps(outputs, indent=1)[:4000]

        try:
            response = await adapter.complete(
                system_prompt=(
                    "You are a summarizer. Given agent outputs from a consulting session, "
                    "produce a compact 200-word summary of the key recommendations and "
                    "decisions. Return ONLY plain text, no JSON."
                ),
                user_prompt=f"Summarize:\n{outputs_text}",
                model=settings.model_haiku,
                max_tokens=400,
            )
        except Exception:
            return False  # summarization failure is non-fatal

        data["agent_outputs"] = {
            "_summary": {
                "recommended_approach": response.text,
                "decisions_to_lock": [],
                "open_questions": [],
                "risks": ["(summarized — see decision_log for locked decisions)"],
            }
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    return True
