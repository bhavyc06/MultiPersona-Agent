#!/usr/bin/env python
"""
Phase 2 checkpoint — Real expert nodes + SSE stream.
Tests 3 and 5 use httpx async to keep ONE SSE stream open
(avoiding the multi-stream queue race condition).
Run: python -m tests.checkpoint_phase2
"""
import asyncio
import json
import sys
import time
import urllib.request

import httpx

BASE = "http://localhost:8000"
# Each test gets a unique user to avoid the 5-sessions/hour rate limit
_TS = int(time.time())
EMAIL   = f"p2t1_{_TS}@example.com"   # Tests 1-2 (no session creation)
EMAIL_3 = f"p2t3_{_TS}@example.com"   # Test 3
EMAIL_4 = f"p2t4_{_TS}@example.com"   # Test 4
EMAIL_5 = f"p2t5_{_TS}@example.com"   # Test 5
PASSWORD = "Phase2Test!"

_ANSWERS_P2 = {
    1: {"0": "10k students, 500 requests/sec peak",
        "1": "AWS, existing Postgres DB, prefer managed services",
        "2": "Real-time tracking, sub-1s check-in latency"},
    2: {"0": "Mobile app + web dashboard",
        "1": "RFID cards or facial recognition",
        "2": "Must integrate with existing SIS"},
    3: {"0": "Privacy compliance: FERPA required",
        "1": "2 engineers, 3-month timeline, $10k/month infra",
        "2": "REST API + WebSocket for live dashboard"},
}


def _http(method, path, body=None, token=None, timeout=15):
    url = BASE + path
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _get_token():
    _, r = _http("POST", "/api/auth/login", {"email": EMAIL, "password": PASSWORD})
    if "access_token" not in r:
        _http("POST", "/api/auth/register", {"email": EMAIL, "password": PASSWORD})
        _, r = _http("POST", "/api/auth/login", {"email": EMAIL, "password": PASSWORD})
    return r["access_token"]


async def _post_respond(client: httpx.AsyncClient, session_id: str,
                        answer: str, headers: dict) -> None:
    """Post an answer to /respond; called as a fire-and-forget task."""
    await asyncio.sleep(1)
    try:
        r = await client.post(f"/api/sessions/{session_id}/respond",
                              json={"answer": answer}, headers=headers)
        print(f"  [/respond] {r.status_code}")
    except Exception as exc:
        print(f"  [/respond ERROR] {exc}")


async def _run_session_async(problem: str, answers_map: dict,
                              max_seconds: int = 600,
                              override_creds: tuple | None = None) -> list[dict]:
    """
    Single-stream async SSE reader.
    Keeps ONE connection open for the entire session.
    When clarification_required arrives, fires /respond as an asyncio task.
    Returns all events collected including session_complete.
    """
    if override_creds:
        email, password = override_creds
        _, r = _http("POST", "/api/auth/login", {"email": email, "password": password})
        token = r["access_token"]
    else:
        token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}

    # Create session
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        r = await client.post("/api/sessions",
                              json={"problem_statement": problem}, headers=headers)
        r.raise_for_status()
        session_id = r.json()["session_id"]
        print(f"  session_id: {session_id}")

        events: list[dict] = []
        clarify_rounds = 0
        start = time.monotonic()

        async with client.stream(
            "GET", f"/api/sessions/{session_id}/stream",
            headers=headers, timeout=max_seconds + 10,
        ) as stream:
            async for line in stream.aiter_lines():
                if time.monotonic() - start > max_seconds:
                    print(f"  [timeout at {time.monotonic()-start:.0f}s]")
                    break
                if not line.startswith("data:"):
                    continue
                try:
                    evt = json.loads(line[6:])
                except Exception:
                    continue

                etype = evt.get("event", "?")
                events.append(evt)
                print(f"  [{time.monotonic()-start:5.1f}s] {etype}")

                if etype == "clarification_required":
                    clarify_rounds += 1
                    answers = answers_map.get(clarify_rounds,
                                              {"0": "Standard best-practice approach"})
                    combined = "\n\n".join(f"Q{k}: {v}" for k, v in answers.items())
                    asyncio.create_task(
                        _post_respond(client, session_id, combined, headers)
                    )

                if etype in ("session_complete", "error"):
                    break

    return events


# ── Tests ──────────────────────────────────────────────────────────────────────

def test1_expert_node_returns_valid_update():
    print("\n[TEST 1] Expert node returns valid state update (real Claude call)")
    try:
        async def run():
            from backend.graph.state import INITIAL_STATE
            from backend.graph.nodes import ai_architect_node
            state = {
                **INITIAL_STATE,
                "session_id": "test-expert-1",
                "user_id":    "user-test",
                "problem_statement": "Build a real-time attendance system",
                "enriched_problem":  "Build a real-time attendance system for a school with 10k students",
                "turn_count": 1,
            }
            result = await asyncio.wait_for(ai_architect_node(state), timeout=90)
            assert "messages" in result
            assert len(result["messages"]) > 0
            msg = result["messages"][0]
            assert msg["role"] == "ai_architect"
            assert msg["content"]
            assert not msg.get("is_private")
            print(f"  ai_architect said: {msg['content'][:120]}...")
            print(f"  proposed_decisions: {len(result.get('decisions', []))}")
            return True
        return asyncio.run(run())
    except Exception as exc:
        print(f"  FAIL: {exc}")
        return False


def test2_synthesis_returns_document():
    print("\n[TEST 2] Synthesis node returns solution document (real Claude Opus call)")
    try:
        async def run():
            from backend.graph.state import INITIAL_STATE
            from backend.graph.nodes import synthesis_node
            state = {
                **INITIAL_STATE,
                "session_id": "test-synth-2",
                "user_id":    "user-test",
                "problem_statement": "Build attendance system",
                "enriched_problem":  "Build a real-time school attendance system",
                "messages": [
                    {"role": "ai_architect", "content": "Use Redis for real-time tracking with RFID.", "turn": 1, "is_private": False},
                    {"role": "solution_architect", "content": "Event-driven with Kafka + microservices.", "turn": 2, "is_private": False},
                ],
                "decisions": [
                    {"id": "d1", "text": "Use Redis for sub-second presence tracking",
                     "proposed_by": "ai_architect", "state": "locked",
                     "provenance": "converged", "supersedes_id": None},
                ],
                "turn_count": 2,
                "termination_reason": "ceiling",
            }
            result = await asyncio.wait_for(synthesis_node(state), timeout=150)
            doc = result.get("solution_document")
            assert doc is not None
            assert isinstance(doc, dict)
            assert "executive_summary" in doc
            assert doc["executive_summary"]
            assert "empty agent_outputs" not in str(doc)
            print(f"  executive_summary: {doc['executive_summary'][:200]}...")
            return True
        return asyncio.run(run())
    except Exception as exc:
        print(f"  FAIL: {exc}")
        return False


def test3_sse_events_fire():
    """Single async SSE stream — no close/reopen race condition."""
    print("\n[TEST 3] SSE events fire during graph run (single stream, up to 10 min)")
    try:
        _http("POST", "/api/auth/register", {"email": EMAIL_3, "password": PASSWORD})
        answers = {1: {"0": "Small team, PostgreSQL, AWS, REST API, 3-month timeline"}}
        events = asyncio.run(
            _run_session_async("Design a simple task manager API", answers,
                               max_seconds=600,
                               override_creds=(EMAIL_3, PASSWORD))
        )
        etypes = [e.get("event") for e in events]
        print(f"  all event types: {etypes}")

        has_message  = "message" in etypes or "session_started" in etypes
        has_complete = "session_complete" in etypes

        assert has_complete, f"session_complete not received. Got: {etypes}"
        assert has_message,  f"no message events. Got: {etypes}"
        print(f"  has message events: {has_message}")
        print(f"  has session_complete: {has_complete}")
        return True
    except Exception as exc:
        print(f"  FAIL: {exc}")
        return False


def test4_respond_endpoint_works():
    print("\n[TEST 4] /respond endpoint exists and accepts POST")
    try:
        _http("POST", "/api/auth/register", {"email": EMAIL_4, "password": PASSWORD})
        _, tr = _http("POST", "/api/auth/login", {"email": EMAIL_4, "password": PASSWORD})
        token = tr["access_token"]
        status, r = _http("POST", "/api/sessions",
                          {"problem_statement": "Build a todo app"}, token=token)
        assert status == 201
        session_id = r["session_id"]
        print(f"  session_id: {session_id}")

        # Collect until clarification_required
        url = f"{BASE}/api/sessions/{session_id}/stream?token={token}"
        req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
        has_clarify = False
        start = time.time()
        with urllib.request.urlopen(req, timeout=100) as resp:
            for line in resp:
                if time.time() - start > 90:
                    break
                line = line.decode().strip()
                if line.startswith("data:"):
                    try:
                        evt = json.loads(line[5:])
                        etype = evt.get("event", "?")
                        print(f"  [{time.time()-start:4.1f}s] {etype}")
                        if etype == "clarification_required":
                            has_clarify = True
                            break
                    except Exception:
                        pass

        assert has_clarify, "clarification_required not received"
        status, r = _http("POST", f"/api/sessions/{session_id}/respond",
                          {"answer": "React, Node.js, PostgreSQL"}, token=token)
        print(f"  /respond HTTP {status}: {r}")
        assert status == 200
        assert r.get("status") == "resumed"
        return True
    except Exception as exc:
        print(f"  FAIL: {exc}")
        return False


def test5_full_session_end_to_end():
    """Full session with single async SSE stream — uses a dedicated user to avoid rate limits."""
    print("\n[TEST 5] Full session end-to-end (single stream, up to 10 min)")
    try:
        _http("POST", "/api/auth/register", {"email": EMAIL_5, "password": PASSWORD})
        events = asyncio.run(
            _run_session_async(
                "Build a real time attendance system for a school",
                _ANSWERS_P2,
                max_seconds=600,
                override_creds=(EMAIL_5, PASSWORD),
            )
        )
        etypes = [e.get("event") for e in events]
        print(f"  event sequence: {etypes}")

        assert "session_complete" in etypes, f"session_complete not received. Got: {etypes}"
        complete_evt = next(e for e in events if e.get("event") == "session_complete")
        doc = complete_evt.get("solution_document")
        assert doc is not None
        assert isinstance(doc, dict)
        assert doc.get("executive_summary")
        assert "empty agent_outputs" not in str(doc)

        print(f"\n  === SOLUTION DOCUMENT (executive_summary) ===")
        print(f"  {doc['executive_summary'][:400]}")
        return True
    except Exception as exc:
        print(f"  FAIL: {exc}")
        import traceback; traceback.print_exc()
        return False


def main():
    print("=" * 60)
    print("Phase 2 Checkpoint — Real Expert Nodes + SSE Stream")
    print("=" * 60)

    results = {
        "Test 1 — Expert node state update":  test1_expert_node_returns_valid_update(),
        "Test 2 — Synthesis returns document": test2_synthesis_returns_document(),
        "Test 3 — SSE events fire":            test3_sse_events_fire(),
        "Test 4 — /respond endpoint":          test4_respond_endpoint_works(),
        "Test 5 — Full session end-to-end":    test5_full_session_end_to_end(),
    }

    print("\n" + "=" * 60)
    passed = 0
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if ok:
            passed += 1

    total = len(results)
    print(f"\n{'>>> CHECKPOINT PASSED <<<' if passed == total else '>>> CHECKPOINT FAILED <<<'}")
    print(f"  {passed}/{total} tests passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
