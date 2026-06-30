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
}
