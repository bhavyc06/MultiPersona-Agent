#!/usr/bin/env python
"""
Phase 3 checkpoint — cross-session memory.

7 assertions across 3 parts:
  PART 1 (assertions 1-4): compression runs, MemoryEntry written to DB
  PART 2 (assertions 5-6): second session for same user injects prior memory
  PART 3 (assertion 7):    different user sees no cross-user memory

Runtime: ~12-15 minutes (Part 1 needs full session_complete).
"""
import asyncio
import json
import time
import uuid as uuid_module
from pathlib import Path

import httpx
from sqlalchemy import select

BASE = "http://localhost:8000"

USER_A_EMAIL = "mem_user_a@example.com"
USER_B_EMAIL = "mem_user_b@example.com"
USER_A_PASS = "MemUserA1!"
USER_B_PASS = "MemUserB1!"

PROBLEM_1 = "Build a real-time ML feature store"
PROBLEM_2 = "Design a streaming feature pipeline for fraud detection"
PROBLEM_B = "Create a REST API for a mobile app"

_DOMAIN_KEYWORDS = ["feature", "ML", "Redis", "Kafka", "pipeline", "stream", "model"]

# Pre-canned answers for each round (indexed by round number 1-3)
_ANSWERS = {
    PROBLEM_1: {
        1: {"0": "Sub-50ms p99 online serving latency, 50k QPS peak",
            "1": "AWS, existing Kafka pipeline, Snowflake warehouse",
            "2": "Both online inference and offline training pipelines",
            "3": "4 engineers, 6-month window, prefer managed services"},
        2: {"0": "~500 features, 500GB daily ingest, user + item features",
            "1": "No strict PII — standard AWS data residency",
            "2": "Redis available; Spark clusters for batch",
            "3": "15-minute feature refresh SLA for online store"},
        3: {"0": "Open to Feast or Tecton; avoid full custom build",
            "1": "Kafka Streams already in use for event processing",
            "2": "SageMaker for model training and serving",
            "3": "99.9% uptime target"},
    },
    PROBLEM_2: {
        1: {"0": "Real-time fraud scoring, sub-100ms p99",
            "1": "Kafka events, AWS, existing ML platform",
            "2": "Online inference — features needed at transaction time",
            "3": "3 engineers, 4-month delivery"},
        2: {"0": "~200 features per transaction, 20k TPS",
            "1": "Must integrate with existing Spark feature engineering jobs",
            "2": "Low false-positive rate critical — compliance requirement",
            "3": "30-day feature history window required"},
        3: {"0": "Flink preferred for stateful stream processing",
            "1": "Redis Cluster already deployed in fraud platform",
            "2": "Point-in-time correctness required for model training",
            "3": "GDPR compliance — EU data residency"},
    },
    PROBLEM_B: {
        1: {"0": "User auth, product listing, order management endpoints",
            "1": "REST JSON API, Node.js or Python backend",
            "2": "10k daily active users at launch",
            "3": "iOS and Android clients"},
        2: {"0": "JWT auth, standard CRUD, push notifications",
            "1": "PostgreSQL for data, Redis for sessions",
            "2": "AWS deployment, ECS or Lambda",
            "3": "2 engineers, 2-month delivery"},
        3: {"0": "OpenAPI spec required for mobile team",
            "1": "No PII beyond email/profile — standard security",
            "2": "GraphQL not needed — REST sufficient",
            "3": "Rate limiting and versioning required"},
    },
}


async def get_token(client: httpx.AsyncClient, email: str, password: str) -> str:
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    if r.status_code == 401:
        await client.post("/api/auth/register", json={"email": email, "password": password})
        r = await client.post("/api/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]


async def _send_answers(client, session_id, answers, headers, round_num):
    await asyncio.sleep(1)
    try:
        r = await client.post(
            f"/api/sessions/{session_id}/clarify",
            json={"answers": answers},
            headers=headers,
        )
        print(f"  [clarify round {round_num}] {r.status_code}")
    except Exception as exc:
        print(f"  [clarify round {round_num}] ERROR: {exc}")


async def run_to_session_complete(
    client: httpx.AsyncClient,
    headers: dict,
    problem: str,
    max_seconds: int = 600,
) -> str:
    """Create session, answer all clarification rounds, wait for session_complete."""
    r = await client.post("/api/sessions", json={"problem_statement": problem}, headers=headers)
    r.raise_for_status()
    session_id = r.json()["session_id"]
    print(f"  session_id: {session_id}")

    start = time.monotonic()
    completed = False

    async with client.stream(
        "GET", f"/api/sessions/{session_id}/stream",
        headers=headers, timeout=max_seconds + 10,
    ) as stream:
        async for line in stream.aiter_lines():
            if time.monotonic() - start > max_seconds:
                print(f"  [stream timeout at {time.monotonic()-start:.0f}s]")
                break
            if not line.startswith("data: "):
                continue
            try:
                evt = json.loads(line[6:])
            except Exception:
                continue

            etype = evt.get("event", "?")
            elapsed = time.monotonic() - start
            print(f"  [{elapsed:5.1f}s] {etype}")

            if etype == "clarification_required":
                round_num = evt.get("round", 1)
                answers = _ANSWERS.get(problem, {}).get(round_num, {
                    str(i): "Standard best practice approach"
                    for i in range(len(evt.get("questions", [])))
                })
                asyncio.create_task(_send_answers(client, session_id, answers, headers, round_num))

            elif etype == "session_complete":
                completed = True
                print("  [session_complete received]")
                break

            elif etype == "error":
                print(f"  [ERROR] {evt.get('message')}")
                break

    if not completed:
        print("  WARNING: session_complete not received before timeout")
    return session_id


async def run_to_session_started(
    client: httpx.AsyncClient,
    headers: dict,
    problem: str,
    max_seconds: int = 300,
) -> str:
    """Create session, answer clarification, wait for session_started."""
    r = await client.post("/api/sessions", json={"problem_statement": problem}, headers=headers)
    r.raise_for_status()
    session_id = r.json()["session_id"]
    print(f"  session_id: {session_id}")

    start = time.monotonic()
    started = False

    async with client.stream(
        "GET", f"/api/sessions/{session_id}/stream",
        headers=headers, timeout=max_seconds + 10,
    ) as stream:
        async for line in stream.aiter_lines():
            if time.monotonic() - start > max_seconds:
                print(f"  [stream timeout at {time.monotonic()-start:.0f}s]")
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
                answers = _ANSWERS.get(problem, {}).get(round_num, {
                    str(i): "Standard approach"
                    for i in range(len(evt.get("questions", [])))
                })
                asyncio.create_task(_send_answers(client, session_id, answers, headers, round_num))

            elif etype == "session_started":
                started = True
                print("  [session_started — stopping stream]")
                break

            elif etype in ("session_complete", "error"):
                break

    if not started:
        print("  WARNING: session_started not received")
    return session_id


async def poll_memory_entry(user_id_str: str, timeout: int = 90) -> "MemoryEntry | None":
    """Poll DB until a MemoryEntry exists for this user or timeout expires."""
    from backend.db.postgres import AsyncSessionLocal
    from backend.models import MemoryEntry

    user_uuid = uuid_module.UUID(user_id_str)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(MemoryEntry).where(MemoryEntry.user_id == user_uuid)
                .order_by(MemoryEntry.created_at.desc())
                .limit(1)
            )
            entry = result.scalar_one_or_none()
            if entry is not None:
                return entry
        await asyncio.sleep(3)
    return None


async def get_user_id_from_token(client: httpx.AsyncClient, token: str) -> str:
    """Decode JWT to extract user_id sub claim."""
    import base64, json as _json
    parts = token.split(".")
    payload_b64 = parts[1] + "=="  # pad
    payload = _json.loads(base64.b64decode(payload_b64))
    return payload["sub"]


async def main() -> None:
    results: dict[int, bool] = {}

    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        # ── Auth for both users ──────────────────────────────────────────────
        print("=== AUTH ===")
        token_a = await get_token(client, USER_A_EMAIL, USER_A_PASS)
        token_b = await get_token(client, USER_B_EMAIL, USER_B_PASS)
        user_a_id = await get_user_id_from_token(client, token_a)
        user_b_id = await get_user_id_from_token(client, token_b)
        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}
        print(f"  User A id: {user_a_id}")
        print(f"  User B id: {user_b_id}")

        # ════════════════════════════════════════════════════════════════════
        # PART 1 — Run a full session as User A, wait for compression
        # ════════════════════════════════════════════════════════════════════
        print(f"\n=== PART 1: Full session as User A (waiting for session_complete) ===")
        session_a1 = await run_to_session_complete(
            client, headers_a, PROBLEM_1, max_seconds=600
        )

        print(f"\n  Polling DB for MemoryEntry (compress_session runs async, up to 90s)...")
        entry = await poll_memory_entry(user_a_id, timeout=90)

    # Assertions for Part 1
    print(f"\n=== PART 1 ASSERTIONS ===")

    def check(n: int, label: str, val: bool) -> None:
        results[n] = val
        print(f"  {'PASS' if val else 'FAIL'}  [{n}] {label}")

    check(1, "MemoryEntry exists in DB for User A", entry is not None)
    check(2, "entry.summary is non-empty (encrypted) string",
          bool(entry and entry.summary))

    has_embedding = bool(entry and entry.embedding and len(entry.embedding) > 0)
    check(3, "entry.embedding has length > 0", has_embedding)

    # Decrypt and check content
    decrypted_summary = ""
    if entry and entry.summary:
        try:
            from backend.memory.encryption import decrypt_text
            decrypted_summary = decrypt_text(entry.summary)
            print(f"\n  DECRYPTED SUMMARY:\n  {decrypted_summary[:400]}")
        except Exception as exc:
            print(f"  Decryption failed: {exc}")

    check(4, "Decrypted summary contains domain-specific content",
          any(kw.lower() in decrypted_summary.lower() for kw in _DOMAIN_KEYWORDS))

    # ════════════════════════════════════════════════════════════════════════
    # PART 2 — Related session for User A — should inject prior memory
    # ════════════════════════════════════════════════════════════════════════
    print(f"\n=== PART 2: Related session as User A (waiting for session_started) ===")
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        headers_a = {"Authorization": f"Bearer {token_a}"}
        session_a2 = await run_to_session_started(
            client, headers_a, PROBLEM_2, max_seconds=300
        )

    # Read scratchpad for session 2
    await asyncio.sleep(2)
    sp2_path = Path(f"data/sessions/{session_a2}/scratchpad.json")
    memory_context = []
    if sp2_path.exists():
        sp2 = json.loads(sp2_path.read_text())
        memory_context = sp2.get("memory_context", [])
        print(f"  memory_context entries: {len(memory_context)}")
        if memory_context:
            first = memory_context[0]
            summary_text = first.get("summary", "") if isinstance(first, dict) else str(first)
            print(f"  memory_context[0][:200]: {summary_text[:200]}")

    check(5, "User A session 2 scratchpad memory_context is non-empty",
          len(memory_context) > 0)
    check(6, "memory_context[0] contains domain content from session 1",
          bool(memory_context) and any(
              kw.lower() in (
                  memory_context[0].get("summary", "")
                  if isinstance(memory_context[0], dict)
                  else str(memory_context[0])
              ).lower()
              for kw in _DOMAIN_KEYWORDS
          ))

    # ════════════════════════════════════════════════════════════════════════
    # PART 3 — User B — must NOT see User A's memories
    # ════════════════════════════════════════════════════════════════════════
    print(f"\n=== PART 3: Isolation — User B session (waiting for session_started) ===")
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        headers_b = {"Authorization": f"Bearer {token_b}"}
        session_b = await run_to_session_started(
            client, headers_b, PROBLEM_B, max_seconds=300
        )

    await asyncio.sleep(2)
    sp_b_path = Path(f"data/sessions/{session_b}/scratchpad.json")
    b_memory_context = []
    if sp_b_path.exists():
        sp_b = json.loads(sp_b_path.read_text())
        b_memory_context = sp_b.get("memory_context", [])
        print(f"  User B memory_context: {b_memory_context}")

    check(7, "User B scratchpad memory_context is [] (no cross-user leak)",
          b_memory_context == [])

    # ════════════════════════════════════════════════════════════════════════
    # Summary
    # ════════════════════════════════════════════════════════════════════════
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"\n{'>>> CHECKPOINT PASSED <<<' if passed == total else '>>> CHECKPOINT FAILED <<<'}")
    print(f"  {passed}/{total} assertions passed")

    if decrypted_summary:
        print(f"\n=== DECRYPTED SUMMARY (full) ===\n{decrypted_summary}")

    print(f"\n=== MEMORY CONTEXT INJECTED IN PART 2 ===")
    for i, m in enumerate(memory_context):
        print(f"  [{i}] {str(m)[:200]}")

    print(f"\n=== USER B ISOLATION ===")
    print(f"  User B memory_context: {b_memory_context}")
    print(f"  Isolation: {'CLEAN' if b_memory_context == [] else 'LEAK DETECTED'}")


if __name__ == "__main__":
    asyncio.run(main())
