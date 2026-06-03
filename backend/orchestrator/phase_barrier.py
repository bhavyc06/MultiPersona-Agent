import logging
import time

from backend.orchestrator.phase_planner import Phase
from backend.scratchpad.manager import append_decision, merge_phase_outputs, read_scratchpad
from backend.sse.emitter import PHASE_COMPLETE, emit

logger = logging.getLogger(__name__)


async def run_phase_barrier(
    session_id: str,
    phase: Phase,
    turn_count: int,
    start_time: float,
    session_timeout: int,
) -> tuple[list[str], bool]:
    """
    Post-phase merge and validation. Called after all agents in a phase have run.

    Returns (locked_decisions, force_synthesis).
    force_synthesis is True when the hard stop conditions are met:
      - turn_count >= 12  (CLAUDE.md §4 rule)
      - elapsed >= session_timeout
    """
    try:
        import logfire
        span_ctx = logfire.span(
            "phase.barrier",
            session_id=session_id,
            phase=phase.phase_number,
            agent_count=len(phase.agents),
        )
    except Exception:
        from contextlib import nullcontext
        span_ctx = nullcontext()

    with span_ctx:
        # Merge open questions from all agent outputs into scratchpad top-level list
        await merge_phase_outputs(session_id, phase.phase_number)

        # Read fresh scratchpad after merge
        scratchpad = await read_scratchpad(session_id)

        # Append each agent's decisions_to_lock to the append-only decision log
        locked: list[str] = []
        for role in phase.agents:
            output = scratchpad["agent_outputs"].get(role, {})
            for decision in output.get("decisions_to_lock", []):
                await append_decision(session_id, decision, role, phase.phase_number)
                locked.append(decision)

        logger.info(
            f"[{session_id}] Phase {phase.phase_number} barrier: {len(locked)} decisions locked"
        )

        try:
            import logfire
            logfire.info("phase.decisions_locked",
                phase=phase.phase_number,
                decisions_locked=len(locked))
        except Exception:
            pass

        await emit(session_id, PHASE_COMPLETE, {
            "phase": phase.phase_number,
            "decisions_locked": locked,
        })

        # Summarize scratchpad after Phase 2 if it's grown large (task 5.6)
        if phase.phase_number == 2:
            from backend.scratchpad.manager import summarize_if_large
            summarized = await summarize_if_large(session_id)
            if summarized:
                logger.info(
                    f"[{session_id}] Scratchpad summarized after Phase 2 (was >8000 tokens)"
                )

        elapsed = time.monotonic() - start_time
        force_synthesis = turn_count >= 12 or elapsed >= session_timeout

        return locked, force_synthesis
