import asyncio
import logging

from backend.rag.cache import get_cached, query_hash, set_cached
from backend.rag.service import get_rag_service

logger = logging.getLogger(__name__)


async def search_knowledge_base(query: str, top_k: int = 5) -> list[dict]:
    """
    Vector search over the technical KB with Redis caching.

    Flow:
      1. Hash query → check Redis (key: rag:{hash})
      2. Cache hit  → return immediately, log cache_hit=True
      3. Cache miss → embed + search (top-10) → cross-encoder rerank (top-k)
                   → cache result (TTL 1 hour)
    """
    q_hash = query_hash(query)

    cached = await get_cached(q_hash)
    if cached is not None:
        logger.info(f"RAG cache_hit=True  hash={q_hash} chunks={len(cached)} query={query[:60]!r}")
        return cached

    logger.info(f"RAG cache_hit=False hash={q_hash} query={query[:60]!r}")

    svc = get_rag_service()
    raw = await asyncio.to_thread(svc.search, query, 10)
    ranked = await asyncio.to_thread(svc.rerank, query, raw, top_k)

    logger.info(
        f"RAG results: {len(ranked)} chunks, "
        f"top_score={ranked[0]['score'] if ranked else 0:.3f}"
    )

    await set_cached(q_hash, ranked, ttl=3600)
    return ranked
