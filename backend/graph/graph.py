from langgraph.graph import END, StateGraph
from langgraph.checkpoint.memory import MemorySaver

from backend.config import settings
from backend.graph.state import ChatState
from backend.graph.nodes import (
    ai_architect_node,
    ai_engineer_node,
    ask_human_node,
    cleanup_round_node,
    custom_persona_node,
    data_engineer_node,
    data_scientist_node,
    framing_node,
    project_manager_node,
    questionnaire_node,
    reviewer_node,
    roster_selection_node,
    solution_architect_node,
    solution_engineer_node,
    stage_transition_node,
    supervisor_node,
    synthesis_node,
    ui_builder_node,
)

EXPERT_NODES: dict = {
    "ai_architect":       ai_architect_node,
    "solution_architect": solution_architect_node,
    "data_engineer":      data_engineer_node,
    "data_scientist":     data_scientist_node,
    "ai_engineer":        ai_engineer_node,
    "solution_engineer":  solution_engineer_node,
    "ui_builder":         ui_builder_node,
    "project_manager":    project_manager_node,
    # Single generic node for all custom personas — dispatches by current_speaker
    "custom_persona":     custom_persona_node,
}


def route_from_supervisor(state: ChatState) -> str:
    """Conditional edge: supervisor decides where to route next."""
    # 1. Need framing first?
    if not state.get("enriched_problem"):
        return "framing"

    # 2. Need roster selection (runs once after framing)?
    if not state.get("roster"):
        return "roster_selection"

    # 3. Terminated or solution produced? — route through reviewer chain first
    if state.get("termination_reason") or state.get("solution_document"):
        if not state.get("reviewer_done"):
            return "reviewer"
        return "synthesis"

    # 4. Route to a named standard expert
    speaker = state.get("current_speaker")
    if speaker and speaker in EXPERT_NODES:
        return speaker

    # 5. Route to custom_persona node when current_speaker is a custom role
    if speaker:
        custom_roles = [p["role"] for p in state.get("custom_personas", [])]
        if speaker in custom_roles:
            return "custom_persona"

    # 6. Human input pause
    if state.get("awaiting_human"):
        return "human_input"

    # FIX-P0.1: fallback bypassed reviewer — now routes through it
    # Every path to synthesis must pass through reviewer → cleanup_round first.
    if not state.get("reviewer_done"):
        return "reviewer"
    return "synthesis"


def _stage_can_close(state: ChatState) -> bool:
    """True iff current_stage has a verdict with passed=True."""
    verdict = (state.get("current_stage") or {}).get("verdict")
    return verdict is not None and verdict.get("passed") is True


def route_from_cleanup(state: ChatState) -> str:
    """
    PHASE-B.2: structural invariant — "no verdict object, no close."
    PHASE-B.3: pass branch routes to stage_transition_node.
    FIX-C: re-audit path is now reachable.

    Ordering:
      1. Passing verdict  → stage_transition  (descend or bottom-out)
      2. Genuine resource hard-stop → synthesis immediately
         Only timeout and budget_exceeded are true hard stops — the session
         physically cannot continue. consensus/consensus_by_supervisor mean
         "deliberation converged", which is exactly when a failed verdict
         SHOULD re-audit after cleanup, not bail.
      3. Failed verdict, retry budget remaining → reviewer  (re-audit)
      4. Retry budget exhausted → synthesis
    """
    # 1. Passing verdict always closes the stage.
    if _stage_can_close(state):
        return "stage_transition"

    # 2. Genuine hard stops — wall-clock or token budget truly exhausted.
    HARD_STOPS = {"timeout", "budget_exceeded"}
    if state.get("termination_reason") in HARD_STOPS:
        return "synthesis"

    # 3. Failed verdict — re-audit if retry budget remains.
    verdict     = (state.get("current_stage") or {}).get("verdict") or {}
    retry_count = verdict.get("retry_count", 0)
    if retry_count < settings.max_audit_retries_per_stage:
        return "reviewer"

    # 4. Retry budget exhausted → synthesize with what we have.
    return "synthesis"


def route_from_stage_transition(state: ChatState) -> str:
    """
    PHASE-B.3: route based on stage_transition_node's decision.
    Bottom-out (or cap-hit) → synthesis. Descent → supervisor for new stage.
    """
    if state.get("stage_bottomed_out"):
        return "synthesis"
    return "supervisor"


def route_from_questionnaire(state: ChatState) -> str:
    """
    TASK-2.2: questionnaire is now the graph entry point.
    framing_node no longer receives raw problem_statement directly — it reads
    problem_brief (produced here) via the Step 7 fallback chain.
    """
    if state.get("questionnaire_done"):
        return "framing"
    return "questionnaire"  # loop: ask another question


def build_graph(checkpointer=None):
    g = StateGraph(ChatState)

    # Nodes
    g.add_node("questionnaire", questionnaire_node)
    g.add_node("supervisor", supervisor_node)
    g.add_node("framing", framing_node)
    g.add_node("roster_selection", roster_selection_node)
    g.add_node("synthesis", synthesis_node)
    g.add_node("human_input", ask_human_node)
    g.add_node("reviewer", reviewer_node)
    g.add_node("cleanup_round", cleanup_round_node)
    g.add_node("stage_transition", stage_transition_node)
    for name, fn in EXPERT_NODES.items():
        g.add_node(name, fn)

    # TASK-2.2: questionnaire is now the entry point (replaces supervisor as first node)
    g.set_entry_point("questionnaire")

    # Questionnaire loop: ask questions until done, then hand off to framing
    g.add_conditional_edges(
        "questionnaire",
        route_from_questionnaire,
        {"framing": "framing", "questionnaire": "questionnaire"},
    )

    # Supervisor conditional routing
    g.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            **{k: k for k in EXPERT_NODES},
            "framing":           "framing",
            "roster_selection":  "roster_selection",
            "synthesis":         "synthesis",
            "human_input":       "human_input",
            "reviewer":          "reviewer",
        },
    )

    # Framing returns to supervisor after interrupt() resumes
    g.add_edge("framing", "supervisor")

    # Roster selection returns to supervisor for first expert dispatch
    g.add_edge("roster_selection", "supervisor")

    # All experts (including custom_persona) and human_input return to supervisor
    for name in EXPERT_NODES:
        g.add_edge(name, "supervisor")
    g.add_edge("human_input", "supervisor")

    # Reviewer chain: reviewer → cleanup_round → route_from_cleanup
    # PHASE-B.2: pass branch → stage_transition (PHASE-B.3); exhaustion → synthesis directly
    g.add_edge("reviewer", "cleanup_round")
    g.add_conditional_edges(
        "cleanup_round",
        route_from_cleanup,
        {"synthesis": "synthesis", "reviewer": "reviewer", "stage_transition": "stage_transition"},
    )

    # stage_transition: bottom-out → synthesis; descend → supervisor
    g.add_conditional_edges(
        "stage_transition",
        route_from_stage_transition,
        {"synthesis": "synthesis", "supervisor": "supervisor"},
    )

    # Synthesis ends the graph
    g.add_edge("synthesis", END)

    return g.compile(checkpointer=checkpointer or MemorySaver())


# Fallback for direct script/test runs; overwritten by init_graph() at startup
graph = build_graph()


async def init_graph(checkpointer=None) -> None:
    """Called once from lifespan. Rebinds module-level `graph` to Postgres-backed instance."""
    global graph
    graph = build_graph(checkpointer=checkpointer)
