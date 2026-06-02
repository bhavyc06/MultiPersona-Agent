"""
Cross-session memory retrieval.

Embeds an incoming problem, searches the user's MemoryEntry rows by cosine
similarity, and returns the top-N decrypted summaries for scratchpad injection.
"""
import asyncio
import logging
import uuid as uuid_module

import numpy as np
from sqlalchemy import select

from backend.db.postgres import AsyncSessionLocal
from backend.memory.encryption import decrypt_text
from backend.models import MemoryEntry

logger = logging.getLogger(__name__)

_SIMILARITY_THRESHOLD = 0.65


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    norm_a = np.linalg.norm(va)
    norm_b = np.linalg.norm(vb)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


async def get_relevant_memories(
    user_id: str,
    problem: str,
    top_n: int = 2,
) -> list[str]:
    """
    Return up to top_n prior session summaries relevant to `problem`.
    Returns [] if no memories exist for this user or none exceed the threshold.

    SECURITY: strict WHERE user_id = :uid filter + assert before decrypt.
    NEVER cross-contaminate users.
    """
    from backend.rag.service import get_rag_service

    # 1. Embed the query
    svc = get_rag_service()
    query_embedding: list[float] = await asyncio.to_thread(svc.embed, problem)

    # 2. Fetch all entries for this user only
    user_uuid = uuid_module.UUID(user_id)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(MemoryEntry).where(MemoryEntry.user_id == user_uuid)
        )
        entries = result.scalars().all()

    if not entries:
        return []

    # 3-4. Score and filter
    scored: list[tuple[float, MemoryEntry]] = []
    for entry in entries:
        if entry.embedding is None:
            continue

        # SECURITY: assert ownership before any processing (CLAUDE.md §16)
        assert str(entry.user_id) == str(user_uuid), (
            f"Cross-user memory leak detected: expected {user_uuid}, got {entry.user_id}"
        )

        sim = _cosine_similarity(query_embedding, list(entry.embedding))
        if sim >= _SIMILARITY_THRESHOLD:
            scored.append((sim, entry))

    # 5. Sort descending, take top_n
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_n]

    # 6. Decrypt summaries
    memories: list[str] = []
    for sim, entry in top:
        try:
            summary = decrypt_text(entry.summary)
            memories.append(f"Session summary: {summary}")
            logger.info(
                f"Memory retrieved for user {user_id}: "
                f"sim={sim:.3f} summary={summary[:60]!r}"
            )
        except Exception as exc:
            logger.warning(f"Failed to decrypt memory entry {entry.id}: {exc}")

    return memories
