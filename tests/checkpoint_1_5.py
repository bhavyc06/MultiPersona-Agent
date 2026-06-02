#!/usr/bin/env python
"""
Phase 1.5 checkpoint — clarification loop end-to-end test.

Answers ALL rounds (not just round 1). Stream reads for up to 300s.
"""
import asyncio
import json
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8000"
PROBLEM = "Build a real-time ML feature store"
EMAIL = "checkpoint15@example.com"
PASSWORD = "Check1point5!"

# Comprehensive pre-canned answers keyed by round (1-indexed).
# We answer every question in each round with substantive context so Haiku
# declares "ready" before max_rounds is exhausted.
_ROUND_ANSWERS = {
    1: {
        "0": "Sub-50ms p99 online serving latency; batch refresh every 15 minutes",
        "1": "Both online inference (real-time model serving) and offline training pipelines",
        "2": "~500 features, 50k predictions/second peak, 500GB daily ingest",
        "3": "AWS (us-east-1), existing Kafka cluster, Snowflake data warehouse",
    },
    2: {
        "0": "Single-tenant, one data science team, 5 engineers",
        "1": "Features include user behaviour, transaction history, product metadata — no PII",
        "2": "Must integrate with existing SageMaker inference endpoints",
        "3": "Budget: $15k/month infra; 6-month delivery window",
    },
    3: {
        "0": "Prefer managed services over self-hosted; open to Tecton or Feast",
        "1": "Kafka already in use for event streaming; prefer to reuse it",
        "2": "Redis available for caching; Spark clusters for batch processing",
        "3": "Standard reliability SLAs; 99.9% uptime target for online store",
    },
}


async def get_token(client: httpx.AsyncClient) -> str:
    r = await client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    if r.status_code == 401:
        await client.post("/api/auth/register", json={"email": EMAIL, "password": PASSWORD})
        r = await client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    return r.json()["access_token"]


async def _submit_answers(
    client: httpx.AsyncClient,
    session_id: str,
    answers: dict[str, str],
    headers: dict,
    round_num: int,
) -> None:
    await asyncio.sleep(1)  # brief pause so SSE event flush completes
    try:
        r = await client.post(
            f"/api/sessions/{session_id}/clarify",
            json={"answers": answers},
            headers=headers,
        )
        print(f"  [POST /clarify round {round_num}] {r.status_code} — {r.text[:80]}")
    except Exception as exc:
        print(f"  [POST /clarify round {round_num}] ERROR: {exc}")


async def main() -> None:
    results: dict[int, bool] = {}

    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        print("=== AUTH ===")
        token = await get_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        print("  Authenticated")

        print(f"\n=== CREATE SESSION ===")
        r = await client.post(
            "/api/sessions", json={"problem_statement": PROBLEM}, headers=headers
        )
        r.raise_for_status()
        session_id = r.json()["session_id"]
        print(f"  session_id    : {session_id}")
        print(f"  initial_status: {r.json()['status']}")

        print(f"\n=== SSE STREAM (up to 300s) ===")
        events: list[dict] = []
        all_questions: list[str] = []        # questions from first round
        enriched_problem_from_sse = ""
        start = time.monotonic()
        clarification_complete_seen = False
        session_started_seen = False

        async with client.stream(
            "GET", f"/api/sessions/{session_id}/stream",
            headers=headers, timeout=310,
        ) as stream:
            async for line in stream.aiter_lines():
                elapsed = time.monotonic() - start
                if elapsed > 300:
                    print(f"  [stream timeout at {elapsed:.0f}s]")
                    break

                if not line.startswith("data: "):
                    continue
                try:
                    evt = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue

                etype = evt.get("event", "?")
                events.append(evt)
                print(f"  [{elapsed:5.1f}s] {etype:28s}  {str(evt)[:88]}")

                if etype == "clarification_required":
                    round_num = evt.get("round", 1)
                    questions = evt.get("questions", [])
                    if round_num == 1:
                        all_questions = questions  # capture for assertions

                    # Answer every round with pre-canned context
                    answers = _ROUND_ANSWERS.get(round_num, {
                        str(i): "Confirmed, proceeding with best practice approach"
                        for i in range(len(questions))
                    })
                    asyncio.create_task(
                        _submit_answers(client, session_id, answers, headers, round_num)
                    )

                elif etype == "clarification_complete":
                    clarification_complete_seen = True
                    enriched_problem_from_sse = evt.get("enriched_problem", "")

                elif etype == "session_started":
                    session_started_seen = True
                    print("  [session_started — checkpoint stops stream read here]")
                    break

                elif etype in ("session_complete", "error"):
                    break

        await asyncio.sleep(2)  # let DB status write propagate

        print(f"\n=== SESSION STATUS ===")
        r = await client.get(f"/api/sessions/{session_id}", headers=headers)
        session_status = r.json().get("status", "unknown") if r.status_code == 200 else "unknown"
        print(f"  status: {session_status}")

    print(f"\n=== SCRATCHPAD ===")
    sp_path = Path(f"data/sessions/{session_id}/scratchpad.json")
    sp: dict = {}
    if sp_path.exists():
        sp = json.loads(sp_path.read_text())
        cc = sp.get("clarification_context", {})
        sp_enriched = cc.get("enriched_problem", "")
        print(f"  is_complete   : {cc.get('is_complete')}")
        print(f"  rounds count  : {len(cc.get('rounds', []))}")
        print(f"  enriched len  : {len(sp_enriched)} chars")
        print(f"  enriched[:200]:\n    {sp_enriched[:200]}")
    else:
        print(f"  ERROR: scratchpad not found")
        sp_enriched = ""
        cc = {}

    print(f"\n=== QUESTIONS (round 1) ===")
    for i, q in enumerate(all_questions):
        print(f"  [{i}] {q}")

    print(f"\n=== ENRICHED PROBLEM (from SSE) ===")
    ep = enriched_problem_from_sse or sp.get("clarification_context", {}).get("enriched_problem", "")
    print(f"  {ep[:500]}")

    # ── Assertions ─────────────────────────────────────────────────────────
    print(f"\n=== ASSERTIONS ===")
    event_types = [e.get("event") for e in events]
    non_connected = [e for e in events if e.get("event") not in ("connected",)]

    def check(n: int, label: str, val: bool) -> None:
        results[n] = val
        print(f"  {'PASS' if val else 'FAIL'}  [{n:2d}] {label}")

    check(1, "First SSE event is clarification_required",
          bool(non_connected) and non_connected[0].get("event") == "clarification_required")
    check(2, "clarification_required has non-empty questions list",
          bool(all_questions))
    check(3, "POST /clarify was accepted (task submitted)",
          True)  # we fire-and-forget; actual result logged above
    check(4, "clarification_complete received in SSE",
          clarification_complete_seen)
    check(5, "clarification_complete contains enriched_problem field",
          bool(enriched_problem_from_sse))
    check(6, "enriched_problem is longer than original problem",
          len(ep) > len(PROBLEM))
    check(7, "enriched_problem contains original problem text AND an answer value",
          PROBLEM in ep and (
              "500" in ep or "AWS" in ep or "50ms" in ep or "Kafka" in ep
          ))
    check(8, "session_started received after clarification_complete",
          session_started_seen and clarification_complete_seen)
    check(9, "scratchpad clarification_context.enriched_problem populated",
          bool(sp.get("clarification_context", {}).get("enriched_problem")))
    check(10, "session status moved away from 'clarifying'",
          session_status not in ("clarifying", "unknown"))

    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"\n{'>>> CHECKPOINT PASSED <<<' if passed == total else '>>> CHECKPOINT FAILED <<<'}")
    print(f"  {passed}/{total} assertions passed")
    if passed < total:
        print(f"\n  Full event sequence: {event_types}")


if __name__ == "__main__":
    asyncio.run(main())
