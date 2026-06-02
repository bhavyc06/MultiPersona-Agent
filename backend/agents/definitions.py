from backend.agents.base_agent import AgentDefinition, load_system_prompt
from backend.config import settings

# Tool scoping per agent (CLAUDE.md §4 table)
_TOOLS: dict[str, list[str]] = {
    "data_engineer":      ["search_knowledge_base"],
    "data_scientist":     ["search_knowledge_base"],
    "solution_engineer":  ["search_knowledge_base"],
    "solution_architect": ["search_knowledge_base"],
    "ai_architect":       ["search_knowledge_base"],
    "ai_engineer":        ["search_knowledge_base"],
    "ui_builder":         ["search_knowledge_base", "generate_ui_mockup"],
    "project_manager":    ["estimate_timeline"],
}

_DISPLAY_NAMES: dict[str, str] = {
    "data_engineer":      "Data Engineer",
    "data_scientist":     "Data Scientist",
    "solution_engineer":  "Solution Engineer",
    "solution_architect": "Solution Architect",
    "ai_architect":       "AI Architect",
    "ai_engineer":        "AI Engineer",
    "ui_builder":         "Full-Stack / UI Builder",
    "project_manager":    "Project Manager",
}


def get_agent_definition(role: str) -> AgentDefinition:
    if role not in _TOOLS:
        raise ValueError(f"Unknown agent role: {role}")
    return AgentDefinition(
        role=role,
        display_name=_DISPLAY_NAMES[role],
        system_prompt=load_system_prompt(role),
        tools=_TOOLS[role],
        model=settings.model_sonnet,
        max_tokens=2000,
    )


def get_all_definitions() -> dict[str, AgentDefinition]:
    return {role: get_agent_definition(role) for role in _TOOLS}
