"""
Post-session memory compressor.

Distils a completed session's public transcript into a compact encrypted summary
and stores it as a MemoryEntry in PostgreSQL for future sessions to recall.
"""
import asyncio
import json
import logging
import re
import uuid as uuid_module

from backend.claude_client import get_adapter
from backend.config import settings
from backend.db.postgres import AsyncSessionLocal
from backend.memory.encryption import encrypt_text
from backend.models import MemoryEntry

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


async def _build_summary_from_db(session_id: str) -> str:
    """
    Assemble a ≤3000-char summary input from DB rows.
    Reads: sessions (enriched_problem / problem_statement),
           decisions (locked, with provenance),
           agent_messages (public, ordered by turn).
    Returns "" if the session has no public messages.
    """
    from sqlalchemy import select as _select
    from backend.models import (
        AgentMessage as _AM,
        Decision as _Dec,
        Session as _Sess,
    )

    async with AsyncSessionLocal() as db:
        sid = uuid_module.UUID(session_id)

        sess = await db.get(_Sess, sid)

        msg_result = await db.execute(
            _select(_AM)
            .where(_AM.session_id == sid, _AM.is_private == False)  # noqa: E712
            .order_by(_AM.phase.asc())
        )
        messages = msg_result.scalars().all()

        dec_result = await db.execute(
            _select(_Dec)
            .where(_Dec.session_id == sid, _Dec.state == "locked")
        )
        decisions = dec_result.scalars().all()

    if not messages:
        return ""

    parts: list[str] = []

    problem = (sess.enriched_problem or sess.problem_statement) if sess else ""
    if problem:
        parts.append(f"Problem:\n{problem[:500]}")

    if decisions:
        dec_lines = [
            f"- [{d.provenance or '?'}] {d.proposed_by}: {d.text[:100]}"
            for d in decisions[:15]
        ]
        parts.append("Locked Decisions:\n" + "\n".join(dec_lines))

    for msg in messages:
        parts.append(f"{msg.agent_role}: {msg.content[:200]}")

    return "\n\n".join(parts)[:3000]


async def _extract_owner_rulings(session_id: str) -> list[dict]:
    """
    PHASE-C.4a: Query locked decisions with provenance in ('moderator', 'human')
    for this session. These represent the owner's explicit rulings (escalation
    choices, moderator interventions) that should be durable across sessions.

    Returns a list of {"text": str, "provenance": str} dicts, max 10.
    Single write site for owner_rulings in key_entities (G4).
    """
    from sqlalchemy import select as _sel
    from backend.models import Decision as _Dec

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            _sel(_Dec)
            .where(
                _Dec.session_id == uuid_module.UUID(session_id),
                _Dec.state == "locked",
                _Dec.provenance.in_(["moderator", "human"]),
            )
            .order_by(_Dec.created_at.asc())
        )
        decisions = result.scalars().all()

    return [
        {"text": d.text, "provenance": d.provenance}
        for d in decisions[:10]
    ]


async def compress_session(session_id: str, user_id: str) -> MemoryEntry | None:
    """
    Compress a completed session into an encrypted MemoryEntry.
    Called fire-and-forget from synthesis_node after session_complete.
    Returns None if the session has no public messages.

    # TOKEN RISK: one Sonnet call per session, max_tokens=500
    # Does NOT store raw transcript.
    """
    summary_input = await _build_summary_from_db(session_id)
    if not summary_input.strip():
        logger.warning(f"[{session_id}] compress_session: no public messages in DB")
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

    # Key entities extracted from summary text
    key_entities = _extract_key_entities(summary_text)

    # PHASE-C.4a: Owner rulings — distinct from summary, authoritative on return.
    # Single write site (G4): only written here, never overwritten.
    owner_rulings = await _extract_owner_rulings(session_id)

    # Embed the summary using the already-loaded sentence-transformers model
    from backend.rag.service import get_rag_service
    svc = get_rag_service()
    embedding: list[float] = await asyncio.to_thread(svc.embed, summary_text)

    # Encrypt fields at rest
    encrypted_summary  = encrypt_text(summary_text)
    encrypted_entities = encrypt_text(json.dumps(key_entities))
    encrypted_rulings  = encrypt_text(json.dumps(owner_rulings)) if owner_rulings else None

    # key_entities stores: entities + owner_rulings (same JSON column, no migration)
    key_entities_payload: dict = {"encrypted": encrypted_entities}
    if encrypted_rulings:
        key_entities_payload["owner_rulings"] = encrypted_rulings

    # Write MemoryEntry to PostgreSQL
    try:
        async with AsyncSessionLocal() as db:
            entry = MemoryEntry(
                user_id=uuid_module.UUID(user_id),
                session_id=uuid_module.UUID(session_id),
                summary=encrypted_summary,
                key_entities=key_entities_payload,
                embedding=embedding,
            )
            db.add(entry)
            await db.commit()
            await db.refresh(entry)

        logger.info(
            f"[{session_id}] Memory compressed: "
            f"{len(summary_text)} chars → {len(embedding)}-dim embedding, "
            f"{len(key_entities)} entities, {len(owner_rulings)} owner rulings"
        )
        return entry

    except Exception as exc:
        logger.error(f"[{session_id}] compress_session: DB write failed: {exc}")
        return None
