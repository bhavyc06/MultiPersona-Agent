from dataclasses import dataclass

from backend.orchestrator.phase_planner import Phase

_ARCH_AGENTS = {"ai_architect", "solution_architect"}
_IMPL_AGENTS = {"ai_engineer", "solution_engineer", "ui_builder", "data_engineer", "data_scientist"}
_PM = "project_manager"


@dataclass
class GuardrailError:
    rule: str
    message: str


def validate_phase_plan(plan: list[Phase]) -> list[GuardrailError]:
    """Validate phase plan against CLAUDE.md §4 guardrail rules."""
    errors: list[GuardrailError] = []

    if not plan:
        return [GuardrailError("empty_plan", "Phase plan is empty")]

    ordered: list[tuple[int, str]] = [
        (phase.phase_number, agent)
        for phase in plan
        for agent in phase.agents
    ]

    arch_phases = [p for p, a in ordered if a in _ARCH_AGENTS]
    impl_phases = [p for p, a in ordered if a in _IMPL_AGENTS]

    # Rule 1: Architecture agents must run before implementation agents
    if arch_phases and impl_phases and min(impl_phases) < min(arch_phases):
        errors.append(GuardrailError(
            "arch_before_impl",
            "Implementation agents appear in an earlier phase than architecture agents",
        ))

    # Rule 2: Project Manager must be the last substantive agent
    all_agents = [a for phase in plan for a in phase.agents]
    if _PM in all_agents and all_agents[-1] != _PM:
        errors.append(GuardrailError(
            "pm_last",
            "Project Manager must be the final agent across all phases",
        ))

    # Rule 3: No phase may have more than 4 agents (budget safety)
    for phase in plan:
        if len(phase.agents) > 4:
            errors.append(GuardrailError(
                "phase_too_large",
                f"Phase {phase.phase_number} '{phase.name}' has {len(phase.agents)} agents (max 4)",
            ))

    return errors


def apply_corrections(plan: list[Phase], errors: list[GuardrailError]) -> list[Phase]:
    """Auto-correct guardrail violations. Raises if correction is impossible."""
    rules = {e.rule for e in errors}

    if "pm_last" in rules:
        # Remove PM from wherever it appears and append a dedicated final phase
        for phase in plan:
            if _PM in phase.agents:
                phase.agents = [a for a in phase.agents if a != _PM]
        plan = [p for p in plan if p.agents]  # drop now-empty phases
        plan.append(Phase(
            phase_number=len(plan) + 1,
            name="Plan",
            agents=[_PM],
            parallel=False,
        ))

    if "arch_before_impl" in rules:
        # Collect arch agents and put them in a new first phase
        arch_agents: list[str] = []
        for phase in plan:
            found = [a for a in phase.agents if a in _ARCH_AGENTS]
            phase.agents = [a for a in phase.agents if a not in _ARCH_AGENTS]
            arch_agents.extend(found)
        plan = [p for p in plan if p.agents]
        plan.insert(0, Phase(1, "Frame", agents=arch_agents, parallel=True))
        for i, p in enumerate(plan, 1):
            p.phase_number = i

    if "phase_too_large" in rules:
        new_plan: list[Phase] = []
        for phase in plan:
            agents = list(phase.agents)
            while agents:
                chunk, agents = agents[:4], agents[4:]
                new_plan.append(Phase(
                    phase_number=0,  # renumbered below
                    name=phase.name,
                    agents=chunk,
                    parallel=phase.parallel,
                ))
        for i, p in enumerate(new_plan, 1):
            p.phase_number = i
        plan = new_plan

    return plan
