from langgraph.graph import END, StateGraph
from langgraph.checkpoint.memory import MemorySaver

from backend.graph.state import ChatState
from backend.graph.nodes import (
    ai_architect_node,
    ai_engineer_node,
    ask_human_node,
    custom_persona_node,
    data_engineer_node,
    data_scientist_node,
    framing_node,
    project_manager_node,
    roster_selection_node,
    solution_architect_node,
    solution_engineer_node,
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

    # 3. Terminated or solution produced?
    if state.get("termination_reason") or state.get("solution_document"):
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

    return "synthesis"  # safe fallback


def build_graph(checkpointer=None):
    g = StateGraph(ChatState)

    # Nodes
    g.add_node("supervisor", supervisor_node)
    g.add_node("framing", framing_node)
    g.add_node("roster_selection", roster_selection_node)
    g.add_node("synthesis", synthesis_node)
    g.add_node("human_input", ask_human_node)
    for name, fn in EXPERT_NODES.items():
        g.add_node(name, fn)

    # Entry point
    g.set_entry_point("supervisor")

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

    # Synthesis ends the graph
    g.add_edge("synthesis", END)

    return g.compile(checkpointer=checkpointer or MemorySaver())


# Fallback for direct script/test runs; overwritten by init_graph() at startup
graph = build_graph()


async def init_graph(checkpointer=None) -> None:
    """Called once from lifespan. Rebinds module-level `graph` to Postgres-backed instance."""
    global graph
    graph = build_graph(checkpointer=checkpointer)
