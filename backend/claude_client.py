import asyncio
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass

from backend.config import settings


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

        # asyncio.to_thread runs the blocking subprocess.run in a thread pool,
        # keeping the uvicorn event loop non-blocking on Windows (SelectorEventLoop
        # does not support asyncio.create_subprocess_exec).
        try:
            import logfire
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                _span_ctx = logfire.span("claude.complete", model=model, max_tokens=max_tokens)
        except Exception:
            from contextlib import nullcontext
            _span_ctx = nullcontext()

        with _span_ctx:
            result: subprocess.CompletedProcess = await asyncio.to_thread(_call)

        if result.returncode != 0:
            raise RuntimeError(
                f"claude CLI failed (returncode={result.returncode}): "
                f"{result.stderr[:500]}"
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
        raise NotImplementedError(
            "ApiClaudeAdapter requires ANTHROPIC_API_KEY and the anthropic SDK. "
            "Set USE_CLI=false and implement this adapter in backend/claude_client.py "
            "at production time."
        )


def get_adapter() -> ClaudeAdapter | ApiClaudeAdapter:
    if settings.use_cli:
        return ClaudeAdapter()
    return ApiClaudeAdapter()
