import asyncio
import logging
import time

from sqlalchemy import update as sa_update

from backend.agents.definitions import get_agent_definition
from backend.agents.dispatcher import dispatch_agent
from backend.config import settings
from backend.db.postgres import AsyncSessionLocal
from backend.models import Session, SessionStatus, SolutionDocument
from backend.orchestrator.clarifier import (
    ClarificationResult,
    cleanup_answer_queue,
    run_clarification_loop,
)
from backend.orchestrator.classifier import classify_problem
from backend.orchestrator.guardrails import apply_corrections, validate_phase_plan
from backend.orchestrator.phase_barrier import run_phase_barrier
from backend.orchestrator.phase_planner import build_phase_plan
from backend.orchestrator.synthesizer import synthesize
from backend.scratchpad.manager import (
    SESSIONS_DIR,
    initialize_scratchpad,
    read_scratchpad,
    set_complexity,
    set_phase_plan,
)
from backend.sse.emitter import (
    CLARIFICATION_COMPLETE,
    ERROR,
    PHASE_START,
    SCRATCHPAD_UPDATE,
    SESSION_COMPLETE,
    SESSION_STARTED,
    emit,
)
from backend.tools.fetch_memory import fetch_memory

logger = logging.getLogger(__name__)

_HARD_STOP_TURNS = 12


async def update_session_status(session_id: str, status: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            sa_update(Session)
            .where(Session.id == session_id)
            .values(status=status)
        )
        await db.commit()


async def run_session(session_id: str, problem: str, user_id: str) -> None:
    """
    Full session lifecycle per CLAUDE.md §5:
      clarifying → ready → classify → plan → scratchpad → running → phases → synthesis → completed
    Enforces hard stops: 12 agent turns OR 240s wall-clock timeout (agent execution only —
    clarification time is unbounded / user-controlled and does NOT count toward the limit).
    """
    # start_time / turn_count / cumulative_tokens are reset after SESSION_STARTED is emitted
    # so clarification wait time never consumes the agent execution budget.
    start_time: float = 0.0
    turn_count: int = 0
    cumulative_tokens: int = 0

    try:
        # ── Clarification ─────────────────────────────────────────────────────
        await update_session_status(session_id, SessionStatus.CLARIFYING.value)

        # TOKEN RISK: up to 3 × (Sonnet + Haiku) calls before agents start
        clarification: ClarificationResult = await run_clarification_loop(
            session_id=session_id,
            problem=problem,
            max_rounds=settings.clarification_max_rounds,
        )

        await emit(session_id, CLARIFICATION_COMPLETE, {
            "enriched_problem": clarification.enriched_problem,
            "rounds_taken": len(clarification.rounds),
        })
        await update_session_status(session_id, SessionStatus.READY.value)
        cleanup_answer_queue(session_id)

        # ── Fetch cross-session memory (stub returns [] until Phase 3) ────────
        memory_ctx = await fetch_memory(user_id, clarification.enriched_problem)

        # ── Classify + plan ───────────────────────────────────────────────────
        classification = await classify_problem(clarification.enriched_problem)
        complexity = classification["complexity"]

        phase_plan = build_phase_plan(complexity)
        errors = validate_phase_plan(phase_plan)
        if errors:
            logger.warning(f"[{session_id}] Guardrail corrections: {errors}")
            phase_plan = apply_corrections(phase_plan, errors)

        # ── Initialise scratchpad with clarification_context ──────────────────
        clarification_context = {
            "rounds": [r.to_dict() for r in clarification.rounds],
            "enriched_problem": clarification.enriched_problem,
            "is_complete": clarification.is_complete,
        }
        await initialize_scratchpad(
            session_id=session_id,
            problem=problem,
            memory_ctx=memory_ctx,
            clarification_context=clarification_context,
        )
        await set_complexity(session_id, complexity)
        await set_phase_plan(session_id, [p.to_dict() for p in phase_plan])

        # ── Start running ─────────────────────────────────────────────────────
        await update_session_status(session_id, SessionStatus.RUNNING.value)
        await emit(session_id, SESSION_STARTED, {
            "session_id": session_id,
            "complexity": complexity,
            "phase_plan": [p.to_dict() for p in phase_plan],
        })

        # Reset execution timer HERE — clarification time must not consume the agent budget
        start_time = time.monotonic()
        turn_count = 0
        cumulative_tokens = 0  # TOKEN RISK: estimated only (CLI adapter)
        logger.info(
            f"[{session_id}] Agent execution clock started. "
            f"Budget: {settings.session_timeout_seconds}s / {_HARD_STOP_TURNS} turns"
        )

        # ── Phase loop ────────────────────────────────────────────────────────
        force_synthesis = False

        for phase in phase_plan:
            elapsed = time.monotonic() - start_time
            if turn_count >= _HARD_STOP_TURNS or elapsed >= settings.session_timeout_seconds:
                logger.warning(f"[{session_id}] Hard stop before phase {phase.phase_number}")
                force_synthesis = True
                break

            # TOKEN RISK: token budget check (estimated tokens)
            if cumulative_tokens >= settings.session_token_budget:
                logger.warning(f"[{session_id}] TOKEN BUDGET EXCEEDED — forcing synthesis")
                force_synthesis = True
                break

            await emit(session_id, PHASE_START, {
                "phase": phase.phase_number,
                "agents": phase.agents,
                "parallel": phase.parallel,
            })
            await emit(session_id, SCRATCHPAD_UPDATE, {
                "field": "current_phase",
                "value": phase.phase_number,
            })

            if phase.parallel:
                results = await asyncio.gather(
                    *(
                        dispatch_agent(session_id, get_agent_definition(role), phase.phase_number)
                        for role in phase.agents
                    ),
                    return_exceptions=True,
                )
                for result in results:
                    if isinstance(result, tuple):
                        _, tokens = result
                        cumulative_tokens += tokens
                turn_count += len(phase.agents)
            else:
                for role in phase.agents:
                    elapsed = time.monotonic() - start_time
                    if (turn_count >= _HARD_STOP_TURNS
                            or elapsed >= settings.session_timeout_seconds):
                        force_synthesis = True
                        break
                    _output, tokens = await dispatch_agent(
                        session_id, get_agent_definition(role), phase.phase_number
                    )
                    cumulative_tokens += tokens
                    turn_count += 1

            _, force_synthesis = await run_phase_barrier(
                session_id=session_id,
                phase=phase,
                turn_count=turn_count,
                start_time=start_time,
                session_timeout=settings.session_timeout_seconds,
            )
            if force_synthesis:
                break

        # ── Synthesis ─────────────────────────────────────────────────────────
        logger.info(f"[{session_id}] Synthesising (tokens_so_far≈{cumulative_tokens})...")
        scratchpad = await read_scratchpad(session_id)
        solution_document = await synthesize(session_id, scratchpad)

        # Persist solution for the export endpoint
        import json as _json
        _sol_path = SESSIONS_DIR / session_id / "solution.json"
        _sol_path.write_text(_json.dumps(solution_document, ensure_ascii=False), encoding="utf-8")

        # ── Persist to solution_documents table (GAP B) ──────────────────────
        import uuid as _uuid
        try:
            async with AsyncSessionLocal() as db:
                sol = SolutionDocument(
                    session_id=_uuid.UUID(session_id),
                    structured_content=(
                        solution_document
                        if isinstance(solution_document, dict)
                        else {"content": solution_document}
                    ),
                )
                db.add(sol)
                await db.commit()
        except Exception as _db_exc:
            logger.warning(f"[{session_id}] solution_documents insert failed (non-fatal): {_db_exc}")

        elapsed = time.monotonic() - start_time
        await emit(session_id, SESSION_COMPLETE, {
            "solution_document": solution_document,
            "total_tokens": cumulative_tokens,  # TOKEN RISK: estimated
            "cost_usd": 0.0,
            "elapsed_seconds": round(elapsed, 2),
        })

        await update_session_status(session_id, SessionStatus.COMPLETED.value)
        logger.info(f"[{session_id}] Done in {elapsed:.1f}s, {turn_count} turns, ~{cumulative_tokens} est. tokens")

        # Fire-and-forget memory compression — does not block session completion
        from backend.memory.compressor import compress_session
        asyncio.create_task(compress_session(session_id, user_id))

    except Exception as exc:
        logger.exception(f"[{session_id}] Session error: {exc}")
        await update_session_status(session_id, SessionStatus.FAILED.value)
        await emit(session_id, ERROR, {
            "code": "session_error",
            "message": str(exc),
            "recoverable": False,
        })
