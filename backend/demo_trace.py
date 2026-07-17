"""
backend/demo_trace.py — human-readable narration logger for live demos.

Emits one clean line per architectural event via a dedicated "demo_trace"
logger (no timestamp/module clutter, just the message) and optionally as
an SSE "trace" event so a UI panel can display the live trace.

Usage (sync or async context):
    from backend.demo_trace import dtrace
    dtrace(session_id, "[EXPERT]    ▶ solution_architect speaking (turn 3)...")

The SSE emit is fire-and-forget (create_task) — never blocks.
Gated by settings.demo_trace; set False in production to silence all lines.
"""
import logging

from backend.config import settings

# ── Dedicated logger — clean format, no timestamp/module noise ──────────────
_trace_logger = logging.getLogger("demo_trace")
_trace_logger.propagate = False  # don't double-print to root logger

if not _trace_logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(message)s"))
    _trace_logger.addHandler(_h)
    _trace_logger.setLevel(logging.DEBUG)


def dtrace(session_id: str, line: str) -> None:
    """
    Emit a demo-narration trace line.
    - Logs to the demo_trace logger (visible in the console with no clutter).
    - If an asyncio event loop is running, also fire-and-forget an SSE
      "trace" event so a frontend panel can display the live narration.
    - No-op if settings.demo_trace is False.
    """
    if not settings.demo_trace:
        return

    tag = session_id[:8] if session_id else "????????"
    _trace_logger.info(f"[{tag}] {line}")
    # SSE "trace" emission disabled — console-only for demo narration.
