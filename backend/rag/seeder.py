import asyncio
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

SEED_DIR = Path("knowledge_base/seed_data")


def _seed_blocking() -> None:
    """Synchronous seed — run inside asyncio.to_thread to avoid blocking the event loop."""
    from backend.rag.service import get_rag_service

    svc = get_rag_service()

    existing = svc.collection.count()
    if existing >= 10:
        logger.info(f"Knowledge base already seeded ({existing} chunks). Skipping.")
        return

    if not SEED_DIR.exists():
        logger.warning(f"Seed data directory not found: {SEED_DIR}")
        return

    md_files = sorted(SEED_DIR.glob("*.md"))
    if not md_files:
        logger.warning(f"No .md files found in {SEED_DIR}")
        return

    logger.info(f"Seeding knowledge base from {len(md_files)} files...")
    total_chunks = 0

    for path in md_files:
        t0 = time.monotonic()
        text = path.read_text(encoding="utf-8")
        count = svc.index_document(
            doc_id=path.stem,
            text=text,
            metadata={"source": path.name, "topic": path.stem},
        )
        elapsed = time.monotonic() - t0
        logger.info(f"  {path.name}: {count} chunks ({elapsed:.2f}s)")
        total_chunks += count

    logger.info(f"Knowledge base ready: {total_chunks} chunks from {len(md_files)} files")


async def seed_knowledge_base() -> None:
    """Seed KB documents into ChromaDB. Idempotent — skips if >= 10 chunks exist."""
    await asyncio.to_thread(_seed_blocking)
