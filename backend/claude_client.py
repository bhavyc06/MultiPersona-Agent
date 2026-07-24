"""
AWS Bedrock Converse API adapter.
Replaces the claude CLI subprocess path (v3 migration, Wave 1+).

Model ARNs: APAC cross-region inference profiles, ap-south-1
  Opus 4.5  : xz6f6fgbpcmy
  Sonnet 4.5: tvbo89xo0vxp
  Haiku 4.5 : mokx0bgyqra7

Known differences from CLI path:
- cost_usd is always 0.0 (Bedrock Converse does not return per-call cost)
- Latency: 2-10s per call (vs 60-120s CLI)
- Auth: AWS credentials via env vars, not interactive claude login
- max_tokens: enforced natively by Bedrock (Fix #8 truncation still applies
  as a belt-and-suspenders guard)
"""

import asyncio
import logging
from dataclasses import dataclass

import aioboto3
from botocore.config import Config as _BotocoreConfig
from botocore.exceptions import ClientError, ConnectTimeoutError, ReadTimeoutError

from backend.config import settings

logger = logging.getLogger(__name__)

# ── Model ARNs — APAC cross-region inference profiles (ap-south-1) ───────────
OPUS_ARN   = "arn:aws:bedrock:ap-south-1:654654399581:application-inference-profile/xz6f6fgbpcmy"
SONNET_ARN = "arn:aws:bedrock:ap-south-1:654654399581:application-inference-profile/tvbo89xo0vxp"
HAIKU_ARN  = "arn:aws:bedrock:ap-south-1:654654399581:application-inference-profile/mokx0bgyqra7"

AWS_REGION = "ap-south-1"

_MAX_RETRIES = 3
_BASE_DELAY  = 1.0  # seconds; doubles each retry: 1s → 2s → 4s

# Bedrock service error codes that warrant a single transient retry (distinct from throttle).
_TRANSIENT_ERROR_CODES = frozenset({
    "InternalServerException",
    "ServiceUnavailableException",
    "ModelTimeoutException",
})

# Single shared session — Session() is cheap and stateless (no network call)
_boto_session = aioboto3.Session()


@dataclass
class ClaudeResponse:
    """
    Identical to the v2 CLI dataclass — all callers use attribute access,
    so the shape must not change.
    """
    text: str
    estimated_tokens:      int
    input_tokens:          int   = 0
    output_tokens:         int   = 0
    cache_creation_tokens: int   = 0   # always 0 — Bedrock Converse has no prompt cache billing
    cache_read_tokens:     int   = 0   # always 0
    cost_usd:              float = 0.0  # always 0.0 — Bedrock Converse does not return per-call cost
    duration_ms:           int   = 0   # not reported by Bedrock Converse
    model:                 str   = ""


def _resolve_model(model: str) -> str:
    """
    Map whatever model string a caller passes → Bedrock inference profile ARN.

    ARN pass-through: if the string is already an ARN (starts with "arn:"),
    return it directly — this is how config.model_sonnet/opus/haiku values
    are used now that config is the single source of truth for model IDs.

    Legacy substring matching handles short strings like "sonnet"/"opus"/"haiku".
    Falls back to SONNET_ARN with a warning if no pattern matches.
    """
    if model.startswith("arn:"):
        return model  # already a fully-qualified ARN — pass through
    m = model.lower()
    if "opus" in m:
        return OPUS_ARN
    if "haiku" in m:
        return HAIKU_ARN
    if "sonnet" in m:
        return SONNET_ARN
    logger.warning("_resolve_model: unknown model string %r — falling back to SONNET_ARN", model)
    return SONNET_ARN


def _to_bedrock_messages(messages: list[dict]) -> list[dict]:
    """
    Convert OpenAI-style messages [{"role": str, "content": str}]
    to Bedrock Converse format [{"role": str, "content": [{"text": str}]}].

    Merges consecutive same-role messages by joining with a newline — Bedrock
    Converse requires strictly alternating user/assistant turns.
    """
    merged: list[dict] = []
    for msg in messages:
        role    = msg["role"]
        content = msg["content"]
        if merged and merged[-1]["role"] == role:
            # Same role as previous — merge content rather than create a new turn
            merged[-1]["content"][0]["text"] += "\n" + content
        else:
            merged.append({"role": role, "content": [{"text": content}]})
    return merged


class ClaudeAdapter:
    """
    AWS Bedrock Converse adapter.
    Public interface is identical to the former CLI adapter — no caller changes required.
    use_cli in config.py is now a no-op (deprecated); this class is always returned
    by get_adapter() regardless of that flag.
    """

    async def complete(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
        model: str = "",
        max_tokens: int = 2000,
        session_id: str = "",
        # New-interface aliases (used by direct Bedrock callers / smoke tests)
        system: str | None = None,
        messages: list[dict] | None = None,
    ) -> ClaudeResponse:
        # Resolve dual-interface: accept both old (system_prompt/user_prompt)
        # and new (system/messages) call patterns without breaking either.
        resolved_system = system or system_prompt
        if messages:
            bedrock_messages = _to_bedrock_messages(messages)
        else:
            bedrock_messages = _to_bedrock_messages([{"role": "user", "content": user_prompt}])

        arn = _resolve_model(model)
        _botocore_cfg = _BotocoreConfig(
            read_timeout=settings.bedrock_read_timeout_seconds,
            connect_timeout=settings.bedrock_read_timeout_seconds,
        )
        _transient_retried = False  # allow ONE retry for timeout / 5xx (not throttle)

        for attempt in range(_MAX_RETRIES):
            try:
                async with _boto_session.client(
                    "bedrock-runtime",
                    region_name=AWS_REGION,
                    config=_botocore_cfg,
                ) as client:
                    raw = await client.converse(
                        modelId=arn,
                        system=[{"text": resolved_system}],
                        messages=bedrock_messages,
                        inferenceConfig={
                            "maxTokens": max_tokens,
                            "temperature": 0.7,
                        },
                    )

                content       = raw["output"]["message"]["content"][0]["text"]
                input_tokens  = raw["usage"]["inputTokens"]
                output_tokens = raw["usage"]["outputTokens"]

                return ClaudeResponse(
                    text=content,
                    estimated_tokens=input_tokens + output_tokens,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_creation_tokens=0,
                    cache_read_tokens=0,
                    cost_usd=0.0,
                    duration_ms=0,
                    model=arn,
                )

            except ClientError as exc:
                error_code = exc.response["Error"]["Code"]
                error_msg  = exc.response["Error"]["Message"]

                if error_code == "ThrottlingException" and attempt < _MAX_RETRIES - 1:
                    delay = _BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "Bedrock ThrottlingException (attempt %d/%d) — retrying in %.0fs "
                        "[session=%s model=%s]",
                        attempt + 1, _MAX_RETRIES, delay, session_id, arn,
                    )
                    await asyncio.sleep(delay)
                    continue

                if error_code in _TRANSIENT_ERROR_CODES and not _transient_retried:
                    _transient_retried = True
                    logger.warning(
                        "Bedrock transient error [%s] — retrying in 2s [session=%s model=%s]",
                        error_code, session_id, arn,
                    )
                    await asyncio.sleep(2.0)
                    continue

                # Non-retryable ClientError or exhausted retries — log ARN privately, raise sanitized.
                logger.error(
                    "Bedrock ClientError [%s]: %s (session=%s, model=%s)",
                    error_code, error_msg, session_id, arn,
                )
                raise RuntimeError(
                    f"Bedrock ClientError [{error_code}]: {error_msg}"
                ) from exc

            except (ReadTimeoutError, ConnectTimeoutError) as exc:
                if not _transient_retried:
                    _transient_retried = True
                    logger.warning(
                        "Bedrock network timeout (%s) — retrying in 2s [session=%s model=%s]",
                        type(exc).__name__, session_id, arn,
                    )
                    await asyncio.sleep(2.0)
                    continue
                logger.error(
                    "Bedrock network timeout after retry (%s) [session=%s model=%s]",
                    type(exc).__name__, session_id, arn,
                )
                raise RuntimeError(
                    f"Bedrock network timeout: {type(exc).__name__}"
                ) from exc

        # Reached only if all retries were ThrottlingException
        logger.error(
            "Bedrock ThrottlingException: all %d retries exhausted (session=%s, model=%s)",
            _MAX_RETRIES, session_id, arn,
        )
        raise RuntimeError(
            f"Bedrock ThrottlingException: all {_MAX_RETRIES} retries exhausted"
        )


def get_adapter() -> ClaudeAdapter:
    # use_cli in config.py is deprecated — Bedrock adapter is always returned
    return ClaudeAdapter()
