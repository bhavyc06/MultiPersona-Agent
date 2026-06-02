import json
import logging
import re

from backend.agents.base_agent import AgentDefinition
from backend.claude_client import get_adapter
from backend.scratchpad.manager import read_scratchpad, update_rag_chunks, write_agent_output
from backend.sse.emitter import AGENT_END, AGENT_START, TOKEN, emit
from backend.tools.search_kb import search_knowledge_base

logger = logging.getLogger(__name__)

_REQUIRED_KEYS = {"recommended_approach", "decisions_to_lock", "open_questions", "risks"}


def _primary_problem(scratchpad: dict) -> str:
    """Return enriched_problem (or fallback to problem_statement)."""
    cc = scratchpad.get("clarification_context", {})
    return cc.get("enriched_problem") or scratchpad.get("problem_statement", "")


def _build_user_prompt(scratchpad: dict) -> str:
    return (
        "Current scratchpad context:\n\n"
        f"```json\n{json.dumps(scratchpad, indent=2)}\n```\n\n"
        "IMPORTANT INSTRUCTIONS:\n"
        "1. Read clarification_context.enriched_problem as your PRIMARY problem statement.\n"
        "2. Read rag_chunks — these are pre-fetched relevant technical reference materials.\n"
        "   Incorporate this context into your recommendations.\n"
        "3. Read decision_log — every entry is a LOCKED CONSTRAINT. Do NOT re-open any.\n"
        "4. Respond with valid JSON ONLY, matching the Output Schema in your system prompt."
    )


def _parse_output(text: str) -> dict | None:
    text = text.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    try:
        data = json.loads(text)
        if _REQUIRED_KEYS.issubset(data.keys()):
            return data
    except json.JSONDecodeError:
        pass
    return None


async def dispatch_agent(
    session_id: str,
    agent_def: AgentDefinition,
    phase_number: int,
) -> tuple[dict, int]:
    """
    Run one agent turn. Pre-fetches RAG context, emits SSE events.
    Returns (structured_output, estimated_tokens).
    Subagents CANNOT spawn subagents (CLAUDE.md §2 guardrail).
    """
    try:
        import logfire
        span_ctx = logfire.span(
            "agent.dispatch",
            session_id=session_id,
            agent_role=agent_def.role,
            phase=phase_number,
        )
    except Exception:
        from contextlib import nullcontext
        span_ctx = nullcontext()

    with span_ctx:
        await emit(session_id, AGENT_START, {
            "agent_role": agent_def.role,
            "phase": phase_number,
        })

        # ── Pre-fetch RAG context on behalf of agent (CLI agents can't call tools directly)
        scratchpad = await read_scratchpad(session_id)
        problem = _primary_problem(scratchpad)
        if problem:
            try:
                rag_chunks = await search_knowledge_base(problem, top_k=5)
                if rag_chunks:
                    await update_rag_chunks(session_id, rag_chunks)
                    # Re-read scratchpad with updated rag_chunks
                    scratchpad = await read_scratchpad(session_id)
            except Exception as exc:
                logger.warning(f"[{session_id}] RAG pre-fetch failed for {agent_def.role}: {exc}")

        user_prompt = _build_user_prompt(scratchpad)
        adapter = get_adapter()
        total_estimated_tokens = 0

        # ── First attempt ─────────────────────────────────────────────────────────
        try:
            response = await adapter.complete(
                system_prompt=agent_def.system_prompt,
                user_prompt=user_prompt,
                model=agent_def.model,
                max_tokens=agent_def.max_tokens,
            )
            total_estimated_tokens += response.estimated_tokens
        except Exception as exc:
            logger.error(f"[{session_id}] {agent_def.role} call failed: {exc}")
            fallback = _make_fallback(agent_def.role, str(exc))
            await write_agent_output(session_id, agent_def.role, fallback)
            await emit(session_id, AGENT_END, {"agent_role": agent_def.role, "decisions_locked": []})
            return fallback, 0

        await emit(session_id, TOKEN, {"agent_role": agent_def.role, "text": response.text})

        output = _parse_output(response.text)

        # ── Retry once on bad JSON ────────────────────────────────────────────────
        if output is None:
            logger.warning(f"[{session_id}] {agent_def.role} returned invalid JSON — retrying")
            retry_prompt = (
                user_prompt
                + "\n\nYour previous response was not valid JSON. "
                "Return ONLY a JSON object matching the Output Schema — nothing else."
            )
            try:
                retry = await adapter.complete(
                    system_prompt=agent_def.system_prompt,
                    user_prompt=retry_prompt,
                    model=agent_def.model,
                    max_tokens=agent_def.max_tokens,
                )
                total_estimated_tokens += retry.estimated_tokens
                output = _parse_output(retry.text)
            except Exception as exc:
                logger.error(f"[{session_id}] {agent_def.role} retry failed: {exc}")

        _used_fallback = False
        if output is None:
            output = _make_fallback(agent_def.role, "JSON parse failed after retry")
            _used_fallback = True
            try:
                import logfire
                logfire.warning("agent.fallback",
                    agent_role=agent_def.role,
                    reason="json_parse_failed")
            except Exception:
                pass

        if not _used_fallback:
            try:
                import logfire
                logfire.info("agent.output",
                    agent_role=agent_def.role,
                    decisions_count=len(output.get("decisions_to_lock", [])),
                    estimated_tokens=total_estimated_tokens)
            except Exception:
                pass

        await write_agent_output(session_id, agent_def.role, output)
        await emit(session_id, AGENT_END, {
            "agent_role": agent_def.role,
            "decisions_locked": output.get("decisions_to_lock", []),
        })

        return output, total_estimated_tokens


def _make_fallback(role: str, reason: str) -> dict:
    return {
        "recommended_approach": f"Agent {role} did not return valid output.",
        "decisions_to_lock": [],
        "open_questions": [],
        "risks": [f"{role} failed: {reason}"],
    }
