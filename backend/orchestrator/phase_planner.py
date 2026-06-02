from dataclasses import dataclass, field

# Agent role identifiers (snake_case, matching .claude/agents/*.md filenames)
ARCH_AGENTS = ["ai_architect", "solution_architect"]
DATA_AGENTS = ["data_engineer", "data_scientist"]
BUILD_AGENTS = ["ai_engineer", "solution_engineer", "ui_builder"]
PLAN_AGENTS = ["project_manager"]


@dataclass
class Phase:
    phase_number: int
    name: str
    agents: list[str] = field(default_factory=list)
    parallel: bool = True

    def to_dict(self) -> dict:
        return {
            "phase": self.phase_number,
            "name": self.name,
            "agents": self.agents,
            "parallel": self.parallel,
        }


def build_phase_plan(complexity: str) -> list[Phase]:
    """Build phase plan from complexity tier. CLAUDE.md §5."""
    if complexity == "simple":
        # 1 substantive phase (2-3 agents) + plan
        return [
            Phase(1, "Frame + Build", agents=["ai_architect", "solution_engineer"], parallel=True),
            Phase(2, "Plan", agents=PLAN_AGENTS, parallel=False),
        ]

    if complexity == "standard":
        # 2-3 phases, subset of agents
        return [
            Phase(1, "Frame", agents=ARCH_AGENTS, parallel=True),
            Phase(2, "Build", agents=["ai_engineer", "solution_engineer"], parallel=True),
            Phase(3, "Plan", agents=PLAN_AGENTS, parallel=False),
        ]

    # complex: all 4 phases + full team
    return [
        Phase(1, "Frame", agents=ARCH_AGENTS, parallel=True),
        Phase(2, "Data", agents=DATA_AGENTS, parallel=True),
        Phase(3, "Build", agents=BUILD_AGENTS, parallel=True),
        Phase(4, "Plan", agents=PLAN_AGENTS, parallel=False),
    ]
