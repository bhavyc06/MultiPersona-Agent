import hashlib
import json

from backend.db.redis_client import get_redis

_PREFIX = "rag:"


def query_hash(query: str) -> str:
    return hashlib.sha256(query.encode()).hexdigest()[:16]


async def get_cached(q_hash: str) -> list[dict] | None:
    redis = await get_redis()
    raw = await redis.get(f"{_PREFIX}{q_hash}")
    if raw is None:
        return None
    return json.loads(raw)


async def set_cached(q_hash: str, chunks: list[dict], ttl: int = 3600) -> None:
    redis = await get_redis()
    await redis.setex(f"{_PREFIX}{q_hash}", ttl, json.dumps(chunks))
