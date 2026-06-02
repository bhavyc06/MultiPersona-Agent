"""
Post-session memory compressor.

Distils a completed session's scratchpad into a compact encrypted summary
and stores it as a MemoryEntry in PostgreSQL for future sessions to recall.
"""
import asyncio
import json
import logging
import re
import uuid as uuid_module
from pathlib import Path

from backend.claude_client import get_adapter
from backend.config import settings
from backend.db.postgres import AsyncSessionLocal
from backend.memory.encryption import encrypt_text
from backend.models import MemoryEntry
from backend.scratchpad.manager import SESSIONS_DIR

logger = logging.getLogger(__name__)

_COMPRESS_SYSTEM = (
    "You are a memory compression specialist. Given a completed consulting session, "
    "produce a compact summary (150-200 words) capturing: the core problem, key decisions "
    "made, the recommended architecture, and any critical constraints. This summary will be "
    "used to recall context in future sessions. Be specific — include technology names, "
    "numbers, and architectural patterns. Do NOT include generic statements. "
    "Return ONLY the summary text, no JSON wrapper."
)

_DOMAIN_SIGNAL = re.compile(r"\b[A-Z][a-zA-Z]{3,}\b")


def _extract_key_entities(text: str) -> list[str]:
    """Extract capitalised domain terms (>4 chars) as entity signals, max 20."""
    seen: set[str] = set()
    entities: list[str] = []
    for word in _DOMAIN_SIGNAL.findall(text):
        if word not in seen:
            seen.add(word)
            entities.append(word)
            if len(entities) >= 20:
                break
    return entities


def _build_summary_input(scratchpad: dict) -> str:
    """Assemble a ≤3000-char input from the most information-dense scratchpad fields."""
    parts: list[str] = []

    enriched = (
        scratchpad.get("clarification_context", {}).get("enriched_problem")
        or scratchpad.get("problem_statement", "")
    )
    if enriched:
        parts.append(f"Problem:\n{enriched[:500]}")

    decisions = scratchpad.get("decision_log", [])
    if decisions:
        lines = [d.get("decision", "")[:100] for d in decisions[:10]]
        parts.append("Key Decisions:\n" + "\n".join(f"- {l}" for l in lines if l))

    agent_outputs = scratchpad.get("agent_outputs", {})
    for role, output in list(agent_outputs.items())[:4]:
        approach = output.get("recommended_approach", "")[:300]
        if approach:
            parts.append(f"{role}:\n{approach}")

    raw = "\n\n".join(parts)
    return raw[:3000]


async def compress_session(session_id: str, user_id: str) -> MemoryEntry | None:
    """
    Compress a completed session into an encrypted MemoryEntry.
    Called fire-and-forget from main_agent.py after session_complete.
    Returns None if scratchpad is missing or summary is empty.

    # TOKEN RISK: one Sonnet call per session, max_tokens=500
    # Does NOT store raw transcript or full scratchpad.
    """
    sp_path = SESSIONS_DIR / session_id / "scratchpad.json"
    if not sp_path.exists():
        logger.warning(f"[{session_id}] compress_session: scratchpad not found")
        return None

    try:
        scratchpad = json.loads(sp_path.read_text())
    except Exception as exc:
        logger.error(f"[{session_id}] compress_session: failed to read scratchpad: {exc}")
        return None

    summary_input = _build_summary_input(scratchpad)
    if not summary_input.strip():
        logger.warning(f"[{session_id}] compress_session: empty summary input")
        return None

    # Sonnet call — compress to 150-200 word summary
    adapter = get_adapter()
    try:
        response = await adapter.complete(
            system_prompt=_COMPRESS_SYSTEM,
            user_prompt=summary_input,
            model=settings.model_sonnet,
            max_tokens=500,
        )
    except Exception as exc:
        logger.error(f"[{session_id}] compress_session: Sonnet call failed: {exc}")
        return None

    summary_text = response.text.strip()
    if not summary_text:
        logger.warning(f"[{session_id}] compress_session: empty summary from Sonnet")
        return None

    # Key entities from summary + enriched problem
    enriched = (
        scratchpad.get("clarification_context", {}).get("enriched_problem")
        or scratchpad.get("problem_statement", "")
    )
    key_entities = _extract_key_entities(summary_text + " " + enriched)

    # Embed the summary using the already-loaded sentence-transformers model
    from backend.rag.service import get_rag_service
    svc = get_rag_service()
    embedding: list[float] = await asyncio.to_thread(svc.embed, summary_text)

    # Encrypt both fields at rest
    encrypted_summary = encrypt_text(summary_text)
    encrypted_entities = encrypt_text(json.dumps(key_entities))

    # Write MemoryEntry to PostgreSQL
    try:
        async with AsyncSessionLocal() as db:
            entry = MemoryEntry(
                user_id=uuid_module.UUID(user_id),
                session_id=uuid_module.UUID(session_id),
                summary=encrypted_summary,
                key_entities={"encrypted": encrypted_entities},
                embedding=embedding,
            )
            db.add(entry)
            await db.commit()
            await db.refresh(entry)

        logger.info(
            f"[{session_id}] Memory compressed: "
            f"{len(summary_text)} chars → {len(embedding)}-dim embedding, "
            f"{len(key_entities)} entities"
        )
        return entry

    except Exception as exc:
        logger.error(f"[{session_id}] compress_session: DB write failed: {exc}")
        return None
