from operator import add
from typing import Annotated, Optional, TypedDict


class ChatState(TypedDict):
    # Immutable problem context
    session_id: str
    user_id: str
    problem_statement: str
    enriched_problem: str          # grows after framing questions
    roster: Annotated[list[str], lambda a, b: b]  # overwrite (last write wins)

    # The public conversation channel
    # Each message: {"role": str, "content": str,
    #                "turn": int, "is_private": bool}
    messages: Annotated[list[dict], add]      # append only

    # Decision lifecycle record
    # Each entry: {"id": str, "text": str, "proposed_by": str,
    #              "state": str, "provenance": str|None,
    #              "supersedes_id": str|None}
    decisions: Annotated[list[dict], add]     # append only

    # Open questions that haven't been answered yet
    open_questions: Annotated[list[str], add]

    # The rolling summary of older turns (updated periodically)
    rolling_summary: str

    # Orchestrator control fields
    current_speaker: Optional[str]    # which expert speaks next
    turn_count: int
    awaiting_human: bool              # True when graph is paused
    human_input: Optional[str]        # injected when human responds
    termination_reason: Optional[str]

    # RAG context (populated once at session start)
    rag_chunks: Annotated[list[dict], add]

    # Prior-session summaries injected at session start (append-only)
    memory_context: Annotated[list[str], add]

    # Final output
    solution_document: Optional[dict]

    # User-created persona definitions (overwrite reducer — last write wins)
    # Each entry: {role, display_name, system_prompt, emoji, color}
    custom_personas: Annotated[list[dict], lambda a, b: b]

    # ── Independent reviewer fields (Pillar 4) ────────────────────────────────
    # Each finding: {"gap_type": "gap|conflict|risk|redundancy",
    #                "description": str, "agents_affected": list[str],
    #                "severity": "high"|"medium"|"low"}
    reviewer_findings: Annotated[list[dict], lambda a, b: b]  # overwrite
    reviewer_done: bool        # True once reviewer_node completes (or fails)
    cleanup_round_done: bool   # True once cleanup_round_node completes (or fails)

    # ── Wall-clock timeout (FIX-5) ────────────────────────────────────────────
    # unix timestamp set when the session is created (sessions.py initial_state).
    # supervisor_node reads this to enforce SESSION_TIMEOUT_SECONDS.
    session_start_time: Optional[float]


INITIAL_STATE: dict = {
    "messages": [],
    "decisions": [],
    "open_questions": [],
    "rolling_summary": "",
    "current_speaker": None,
    "turn_count": 0,
    "awaiting_human": False,
    "human_input": None,
    "termination_reason": None,
    "rag_chunks": [],
    "memory_context": [],
    "solution_document": None,
    "enriched_problem": "",
    "roster": [],
    "custom_personas": [],
    "reviewer_findings": [],
    "reviewer_done": False,
    "cleanup_round_done": False,
    "session_start_time": None,  # set to time.time() in sessions.py initial_state
}
