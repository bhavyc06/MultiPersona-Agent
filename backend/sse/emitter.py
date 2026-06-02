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
