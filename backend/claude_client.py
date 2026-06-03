import asyncio
import json
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass

from backend.config import settings

logger = logging.getLogger(__name__)

# PROMPT CACHING NOTE:
# The Anthropic API supports cache_control: {"type": "ephemeral"} on system
# prompts, cutting cached-input cost by ~90% when the same system prompt is
# reused across calls (as happens with the 8 identical persona prompts).
#
# This is implemented automatically when ApiClaudeAdapter is used (production).
# The CLI adapter cannot use prompt caching — it has no API-level cache control.
#
# At production swap (USE_CLI=false), add cache_control to all 8 persona system
# prompts inside AgentDefinition.system_prompt, e.g.:
#
#   messages=[
#     {
#       "role": "user",
#       "content": [
#         {
#           "type": "text",
#           "text": system_prompt,
#           "cache_control": {"type": "ephemeral"},   # ← add this
#         },
#         {"type": "text", "text": user_prompt},
#       ],
#     }
#   ]
#
# Target: cached_token_ratio > 50% on persona calls (CLAUDE.md §15).

_MAX_RETRIES = 3
_BASE_DELAY = 1.0  # seconds


@dataclass
class ClaudeResponse:
    text: str
    estimated_tokens: int


def _resolve_claude_cmd() -> str:
    """Find the claude CLI binary, resolving .cmd wrapper on Windows npm installs."""
    if sys.platform == "win32":
        # npm installs on Windows create claude.cmd, not claude.exe
        found = shutil.which("claude.cmd") or shutil.which("claude")
    else:
        found = shutil.which("claude")
    if not found:
        raise RuntimeError(
            "claude CLI not found in PATH. "
            "Install with: npm install -g @anthropic-ai/claude-code"
        )
    return found


_CLAUDE_CMD = _resolve_claude_cmd()


class ClaudeAdapter:
    """
    Calls the claude CLI as a subprocess via asyncio.to_thread (Windows-safe).
    Used when USE_CLI=true (prototyping phase — no ANTHROPIC_API_KEY required).
    Retries up to _MAX_RETRIES times with exponential backoff on failure.

    TOKEN RISK: exponential backoff can triple the wall-clock time for a failed
    call (1s + 2s + 4s). The 240s session timeout acts as the ultimate backstop.
    """

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
    ) -> ClaudeResponse:
        combined = f"{system_prompt}\n\n{user_prompt}"

        def _call() -> subprocess.CompletedProcess:
            # Pass prompt via stdin rather than -p arg.
            # With -p, the claude CLI injects CLAUDE.md project context, causing the
            # model to respond as "Claude Code" rather than the persona we define.
            # Stdin piping skips that context injection and honours our system prompt.
            return subprocess.run(
                [_CLAUDE_CMD, "--model", model, "--output-format", "json"],
                input=combined,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )

        try:
            import logfire
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                _span_ctx = logfire.span("claude.complete", model=model, max_tokens=max_tokens)
        except Exception:
            from contextlib import nullcontext
            _span_ctx = nullcontext()

        # ── Retry with exponential backoff (task 5.5) ─────────────────────────
        result: subprocess.CompletedProcess | None = None
        with _span_ctx:
            for attempt in range(_MAX_RETRIES):
                result = await asyncio.to_thread(_call)
                if result.returncode == 0:
                    break
                if attempt < _MAX_RETRIES - 1:
                    delay = _BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"Claude CLI failed (attempt {attempt + 1}/{_MAX_RETRIES}), "
                        f"retrying in {delay}s — rc={result.returncode}"
                    )
                    await asyncio.sleep(delay)
            else:
                raise RuntimeError(
                    f"claude CLI failed after {_MAX_RETRIES} attempts: "
                    f"{result.stderr[:300]}"
                )

        data = json.loads(result.stdout)
        text = data["result"]

        # TOKEN RISK: CLI does not return usage metadata. Tokens are estimated from
        # character counts (len/4). Actual usage (prompt + completion) will be
        # significantly higher. Replace with API usage fields at production time.
        estimated_tokens = len(combined) // 4 + len(text) // 4

        return ClaudeResponse(text=text, estimated_tokens=estimated_tokens)


class ApiClaudeAdapter:
    """Production adapter using the Anthropic SDK. Not implemented during CLI prototyping."""

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
    ) -> ClaudeResponse:
        # When implementing: pass system_prompt as a separate content block with
        # cache_control: {"type": "ephemeral"} so identical persona prompts are
        # cached across calls, reducing input token costs by ~90%.
        # See PROMPT CACHING NOTE at the top of this file for full implementation guide.
        raise NotImplementedError(
            "ApiClaudeAdapter requires ANTHROPIC_API_KEY and the anthropic SDK. "
            "Set USE_CLI=false and implement this adapter in backend/claude_client.py "
            "at production time."
        )


def get_adapter() -> ClaudeAdapter | ApiClaudeAdapter:
    if settings.use_cli:
        return ClaudeAdapter()
    return ApiClaudeAdapter()
