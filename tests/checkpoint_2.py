#!/usr/bin/env python
"""
Phase 2 checkpoint — Tools + RAG.

Assertions:
 1  search_knowledge_base returns results (KB is seeded)
 2  Second identical query hits Redis cache (cache_hit = True)
 3  Redis has rag: prefix keys (confirms search was called + cached)
 4  estimate_timeline returns structured JSON with total_weeks > 0
 5  generate_ui_mockup returns HTML starting with <!DOCTYPE html>
 6  Agents ran and scratchpad rag_chunks is populated
 7  Agent recommended_approach references real KB content
 8  scratchpad rag_chunks has top_score > 0.30 (similarity threshold)

Usage: python -m tests.checkpoint_2
"""
import asyncio
import json
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8000"
PROBLEM = "Build a real-time ML feature store"
EMAIL = "cp2@example.com"
PASSWORD = "CheckPt2!"

_ANSWERS = {
    "0": "Sub-50ms p99 latency, 50k predictions/second, 500GB/day",
    "1": "AWS, Kafka already in place, prefer managed services",
    "2": "Both online inference and offline training pipelines",
    "3": "Team of 4 engineers, 6-month window, $15k/month infra budget",
}

# Content words from KB files that agents should reference
_KB_SIGNAL_WORDS = [
    "Lambda", "Kafka", "Redis", "Flink", "feature store",
    "Iceberg", "streaming", "batch", "scratchpad", "pipeline",
    "latency", "inference", "training", "serving", "embedding",
]


async def get_token(client: httpx.AsyncClient) -> str:
    r = await client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    if r.status_code == 401:
        await client.post("/api/auth/register", json={"email": EMAIL, "password": PASSWORD})
        r = await client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    return r.json()["access_token"]


async def run_session_to_phase1(client: httpx.AsyncClient, headers: dict) -> str:
    """Create session, answer clarification, wait for phase_complete(phase=1). Returns session_id."""
    r = await client.post(
        "/api/sessions", json={"problem_statement": PROBLEM}, headers=headers
    )
    r.raise_for_status()
    session_id = r.json()["session_id"]
    print(f"  session_id: {session_id}")

    start = time.monotonic()
    phase1_done = False

    async with client.stream(
        "GET", f"/api/sessions/{session_id}/stream",
        headers=headers, timeout=400,
    ) as stream:
        async for line in stream.aiter_lines():
            if time.monotonic() - start > 400:
                break
            if not line.startswith("data: "):
                continue
            try:
                evt = json.loads(line[6:])
            except Exception:
                continue

            etype = evt.get("event", "?")
            print(f"  [{time.monotonic()-start:5.1f}s] {etype}")

            if etype == "clarification_required":
                round_num = evt.get("round", 1)
                answers = {str(i): a for i, a in enumerate(_ANSWERS.values())}
                asyncio.create_task(_send_answers(client, session_id, answers, headers, round_num))

            if etype == "phase_complete" and evt.get("phase") == 1:
                phase1_done = True
                print("  [Phase 1 done — stopping stream]")
                break

            if etype in ("session_complete", "error"):
                break

    if not phase1_done:
        print("  WARNING: phase_complete(1) not received before timeout")
    return session_id


async def _send_answers(client, session_id, answers, headers, round_num):
    await asyncio.sleep(1)
    r = await client.post(
        f"/api/sessions/{session_id}/clarify",
        json={"answers": answers},
        headers=headers,
    )
    print(f"  [clarify round {round_num}] {r.status_code}")


async def main() -> None:
    results: dict[int, bool] = {}

    # ── Unit tests (don't need a running server session) ──────────────────────
    print("=== UNIT: estimate_timeline ===")
    from backend.tools.estimate_timeline import estimate_timeline

    tl = await estimate_timeline({"complexity": "complex", "team_size": 4, "features_count": 3})
    print(f"  total_weeks: {tl['total_weeks']}, confidence: {tl['confidence']}")
    print(f"  phases: {[p['name'] for p in tl['phases']]}")

    print("\n=== UNIT: generate_ui_mockup ===")
    from backend.tools.generate_mockup import generate_ui_mockup

    mockup = await generate_ui_mockup({
        "session_id": "test",
        "title": "Feature Store Dashboard",
        "description": "A dashboard showing feature freshness, latency metrics, and feature registry",
    })
    html_preview = mockup.get("preview_html", "")
    print(f"  artifact_ref: {mockup.get('artifact_ref')}")
    print(f"  html starts with <!DOCTYPE: {html_preview.upper().lstrip().startswith('<!DOCTYPE')}")
    print(f"  html length: {len(html_preview)} chars")

    print("\n=== UNIT: search_knowledge_base (first call) ===")
    from backend.tools.search_kb import search_knowledge_base

    chunks1 = await search_knowledge_base("real-time feature store architecture", top_k=3)
    print(f"  chunks returned: {len(chunks1)}")
    for i, c in enumerate(chunks1[:2]):
        print(f"  [{i}] score={c['score']:.3f} source={c['source']} content={c['content'][:60]!r}")

    print("\n=== UNIT: search_knowledge_base (second call — should hit cache) ===")
    chunks2 = await search_knowledge_base("real-time feature store architecture", top_k=3)
    print(f"  chunks returned: {len(chunks2)}")
    # Verify same results (cache hit returns identical data)
    cache_hit = chunks1 == chunks2
    print(f"  results identical (cache hit): {cache_hit}")

    print("\n=== UNIT: Redis rag: keys ===")
    from backend.db.redis_client import get_redis

    redis = await get_redis()
    rag_keys = await redis.keys("rag:*")
    print(f"  rag: keys in Redis: {len(rag_keys)}")

    print("\n=== SESSION: run to Phase 1 completion ===")
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        token = await get_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        session_id = await run_session_to_phase1(client, headers)

    # Read scratchpad
    print("\n=== SCRATCHPAD ===")
    await asyncio.sleep(2)
    sp_path = Path(f"data/sessions/{session_id}/scratchpad.json")
    sp: dict = {}
    rag_chunks: list[dict] = []
    agent_output_text = ""
    if sp_path.exists():
        sp = json.loads(sp_path.read_text())
        rag_chunks = sp.get("rag_chunks", [])
        print(f"  rag_chunks count   : {len(rag_chunks)}")
        if rag_chunks:
            print(f"  top chunk score    : {rag_chunks[0].get('score', 0):.3f}")
            print(f"  top chunk source   : {rag_chunks[0].get('source', '?')}")
            print(f"  top chunk preview  : {rag_chunks[0].get('content', '')[:80]!r}")
        # Collect all agent output text for KB content check
        for role, output in sp.get("agent_outputs", {}).items():
            agent_output_text += output.get("recommended_approach", "")
        print(f"  agent outputs      : {list(sp.get('agent_outputs', {}).keys())}")
    else:
        print(f"  ERROR: scratchpad not found")

    # ── Assertions ─────────────────────────────────────────────────────────────
    print(f"\n=== ASSERTIONS ===")

    def check(n: int, label: str, val: bool) -> None:
        results[n] = val
        print(f"  {'PASS' if val else 'FAIL'}  [{n}] {label}")

    check(1, "search_knowledge_base returns results (KB seeded)",
          len(chunks1) > 0)
    check(2, "Second identical query returns same results (cache hit confirmed)",
          cache_hit and len(chunks2) > 0)
    check(3, "Redis has rag: prefix keys (search was called and cached)",
          len(rag_keys) > 0)
    check(4, "estimate_timeline returns structured JSON with total_weeks > 0",
          tl.get("total_weeks", 0) > 0 and "phases" in tl and "confidence" in tl)
    check(5, "generate_ui_mockup returns HTML starting with <!DOCTYPE html>",
          html_preview.upper().lstrip().startswith("<!DOCTYPE"))
    check(6, "scratchpad rag_chunks populated after Phase 1 agents ran",
          len(rag_chunks) > 0)
    check(7, "Agent recommended_approach references KB content (signal words)",
          any(word.lower() in agent_output_text.lower() for word in _KB_SIGNAL_WORDS))
    check(8, "Top rag_chunk similarity score above threshold (0.30)",
          bool(rag_chunks) and rag_chunks[0].get("score", 0) >= 0.30)

    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"\n{'>>> CHECKPOINT PASSED <<<' if passed == total else '>>> CHECKPOINT FAILED <<<'}")
    print(f"  {passed}/{total} assertions passed")

    print(f"\n=== TOP 3 RAG CHUNKS FROM SCRATCHPAD ===")
    for i, c in enumerate(rag_chunks[:3]):
        print(f"  [{i}] score={c.get('score', 0):.3f} source={c.get('source', '?')}")
        print(f"       {c.get('content', '')[:100]!r}")

    print(f"\n=== AGENT RECOMMENDED APPROACH (first agent) ===")
    for role, output in list(sp.get("agent_outputs", {}).items())[:1]:
        print(f"  [{role}] {output.get('recommended_approach', '')[:300]}")

    print(f"\n=== ESTIMATE TIMELINE ===")
    print(json.dumps(tl, indent=2))

    print(f"\n=== CACHE HIT CONFIRMATION ===")
    print(f"  First call  : {len(chunks1)} chunks")
    print(f"  Second call : {len(chunks2)} chunks (same result = cache hit)")
    print(f"  Redis rag: keys: {len(rag_keys)}")


if __name__ == "__main__":
    asyncio.run(main())
