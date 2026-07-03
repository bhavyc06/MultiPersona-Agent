import asyncio
import json
from collections import defaultdict

# SSE event type constants — CLAUDE.md §8
CLARIFICATION_REQUIRED = "clarification_required"
CLARIFICATION_COMPLETE = "clarification_complete"
SESSION_STARTED = "session_started"
PHASE_START = "phase_start"
AGENT_START = "agent_start"
TOKEN = "token"
AGENT_END = "agent_end"
PHASE_COMPLETE = "phase_complete"
SCRATCHPAD_UPDATE = "scratchpad_update"
SESSION_COMPLETE = "session_complete"
ERROR = "error"

# Phase 4 events
CONTRADICTION = "contradiction"
ARBITRATION_REQUIRED = "arbitration_required"
ARBITRATION = "arbitration"
DECISION_LOCKED = "decision_locked"

# Phase 5 events
HUMAN_INPUT_REQUIRED = "human_input_required"
HUMAN_INPUT_RECEIVED = "human_input_received"

# Phase 8 events
PAUSE_REQUESTED = "pause_requested"   # immediate ACK when /pause endpoint is hit
PAUSE_ARMED = "pause_armed"           # emitted by supervisor just before interrupt()
PERSONA_ADDED = "persona_added"       # emitted when a custom persona joins mid-session

_TERMINAL_EVENTS = {SESSION_COMPLETE, ERROR}

# Per-session unbounded queues (created on first emit or first stream open)
_queues: dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)


async def emit(session_id: str, event_type: str, data: dict) -> None:
    await _queues[session_id].put({"event": event_type, **data})


async def session_event_stream(session_id: str):
    """Async generator consumed by the SSE stream endpoint."""
    queue = _queues[session_id]

    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=30.0)
        except asyncio.TimeoutError:
            yield ": keep-alive\n\n"
            continue

        if event is None:  # explicit close sentinel
            break

        yield f"data: {json.dumps(event)}\n\n"

        if event.get("event") in _TERMINAL_EVENTS:
            break

    _queues.pop(session_id, None)


async def close_stream(session_id: str) -> None:
    """Push the close sentinel so session_event_stream exits cleanly."""
    await _queues[session_id].put(None)


# ── v3.0 helper emitters ──────────────────────────────────────────────────────

async def emit_message(
    session_id: str,
    role: str,
    content: str,
    turn: int,
    is_private: bool = False,
) -> None:
    """Emit a single chat message over SSE."""
    await emit(session_id, "message", {
        "role": role,
        "content": content,
        "turn": turn,
        "is_private": is_private,
    })


async def emit_decision(session_id: str, decision: dict) -> None:
    """Emit a decision state change over SSE."""
    await emit(session_id, "decision", decision)


async def emit_session_status(session_id: str, status: str, **kwargs) -> None:
    """Emit a session lifecycle event (agent_thinking, synthesizing, etc.)."""
    await emit(session_id, status, kwargs)
