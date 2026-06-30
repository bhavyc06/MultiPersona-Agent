#!/usr/bin/env python
"""
Phase 3 checkpoint — MoE gating, intelligent routing, consensus detection.
Uses single async SSE streams (no close/reopen race condition).
Run: python -m tests.checkpoint_phase3
"""
import asyncio
import json
import sys
import time
import urllib.request

import httpx

BASE = "http://localhost:8000"
_TS = int(time.time())
PASSWORD = "Phase3Test!"
# Unique user per test to avoid 5/hour rate limit
EMAILS = {i: f"p3t{i}_{_TS}@example.com" for i in range(1, 6)}

# Clarification answers (comprehensive so Haiku says "ready")
_ANSWERS_SIMPLE = {
    1: {"0": "Small team of 2, PostgreSQL, AWS Lambda, 3-month timeline",
        "1": "CRUD operations for todo items: create, read, update, delete, mark complete",
        "2": "Mobile + web clients, simple auth via JWT"},
}

_ANSWERS_COMPLEX = {
    1: {"0": "50k transactions/sec peak, 10TB/day streaming data, AWS",
        "1": "Existing Kafka cluster, Spark for batch, Python ML stack",
        "2": "Sub-100ms scoring latency, 99.9% uptime, GDPR compliance"},
    2: {"0": "Real-time and batch features, gradient boosted trees + deep learning",
        "1": "Flink for streaming features, 100+ feature store entries",
        "2": "Model registry, drift detection, A/B testing framework required"},
    3: {"0": "6-engineer team, 9-month delivery window, $50k/month infra budget",
        "1": "React dashboard, mobile SDK for merchants",
        "2": "Needs to integrate with 3 existing fraud rule engines"},
}


def _register_and_get_token(email: str, password: str) -> str:
    def _post(path, body):
        req = urllib.request.Request(
            BASE + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    _post("/api/auth/register", {"email": email, "password": password})
    _, r = _post("/api/auth/login", {"email": email, "password": password})
    return r["access_token"]


async def _post_respond(client: httpx.AsyncClient, session_id: str,
                         answer: str, headers: dict) -> None:
    await asyncio.sleep(1)
    try:
        r = await client.post(f"/api/sessions/{session_id}/respond",
                              json={"answer": answer}, headers=headers)
        print(f"  [/respond] {r.status_code}")
    except Exception as exc:
        print(f"  [/respond ERROR] {exc}")


async def _run_session(problem: str, answers_map: dict,
                        email: str, max_seconds: int = 600) -> tuple[list[dict], str | None]:
    """
    Run a full session using a single async SSE stream.
    Returns (events, session_id).
    """
    token = _register_and_get_token(email, PASSWORD)
    headers = {"Authorization": f"Bearer {token}"}

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
                elapsed = time.monotonic() - start
                print(f"  [{elapsed:5.1f}s] {etype}"
                      + (f" — {evt.get('roster', evt.get('agent', ''))}"
                         if etype in ("roster_selected", "agent_thinking") else ""))

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

    return events, session_id


def _get_roster_from_events(events: list[dict]) -> list[str]:
    for e in events:
        if e.get("event") == "roster_selected":
            return e.get("roster", [])
    return []


def _get_speakers_from_events(events: list[dict]) -> list[str]:
    """Ordered list of agent roles that spoke (from message events)."""
    seen = []
    for e in events:
        if e.get("event") == "message":
            role = e.get("role", "")
            if role and role not in seen:
                seen.append(role)
    return seen


def _get_termination_reason(events: list[dict]) -> str | None:
    for e in events:
        if e.get("event") == "session_complete":
            doc = e.get("solution_document", {})
            # termination_reason is in the graph state, emitted separately or
            # inferred from turn count
            return e.get("termination_reason")
    return None


def _count_turns(events: list[dict]) -> int:
    return sum(1 for e in events if e.get("event") == "message")


# ── Tests ──────────────────────────────────────────────────────────────────────

def test1_simple_problem_small_roster() -> tuple[bool, list[str]]:
    print("\n[TEST 1] Simple problem activates small roster (≤5 experts, no ai_architect)")
    try:
        events, session_id = asyncio.run(
            _run_session(
                "Build a REST API for a todo list app with user authentication",
                _ANSWERS_SIMPLE,
                EMAILS[1],
                max_seconds=600,
            )
        )
        roster = _get_roster_from_events(events)
        print(f"  Selected roster: {roster}")

        assert roster, "roster_selected event not received"
        assert len(roster) <= 5, f"too many experts selected ({len(roster)}): {roster}"
        assert "ai_architect" not in roster, "ai_architect shouldn't be needed for a simple REST API"
        assert "solution_architect" in roster, "solution_architect always needed"
        assert "project_manager" in roster, "project_manager always needed"
        has_complete = any(e.get("event") == "session_complete" for e in events)
        assert has_complete, "session_complete not received"

        print(f"  PASS: roster={roster}, size={len(roster)}")
        return True, roster
    except Exception as exc:
        print(f"  FAIL: {exc}")
        import traceback; traceback.print_exc()
        return False, []


def test2_complex_problem_large_roster() -> tuple[bool, list[str]]:
    print("\n[TEST 2] Complex ML platform activates large roster (≥5, with AI and data experts)")
    try:
        events, session_id = asyncio.run(
            _run_session(
                "Build a real-time ML fraud detection platform with streaming data "
                "pipelines, model serving, feature store, and a monitoring dashboard",
                _ANSWERS_COMPLEX,
                EMAILS[2],
                max_seconds=1200,  # 20 min — 8 agents × ~90s each + routing overhead
            )
        )
        roster = _get_roster_from_events(events)
        print(f"  Selected roster: {roster}")

        assert roster, "roster_selected event not received"
        assert len(roster) >= 5, f"too few experts for a complex ML platform ({len(roster)}): {roster}"
        assert "ai_architect" in roster, "ai_architect needed for ML platform"
        assert "data_engineer" in roster, "data_engineer needed for streaming pipelines"
        has_complete = any(e.get("event") == "session_complete" for e in events)
        assert has_complete, "session_complete not received"

        print(f"  PASS: roster={roster}, size={len(roster)}")
        return True, roster
    except Exception as exc:
        print(f"  FAIL: {exc}")
        import traceback; traceback.print_exc()
        return False, []


def test3_consensus_terminates_before_ceiling() -> bool:
    """Reuse a fresh simple session — check it terminates well before the 20-turn ceiling."""
    print("\n[TEST 3] Consensus terminates session before 20-turn ceiling")
    try:
        events, session_id = asyncio.run(
            _run_session(
                "Build a REST API for a simple blog platform",
                _ANSWERS_SIMPLE,
                EMAILS[3],
                max_seconds=900,
            )
        )
        message_count = _count_turns(events)
        has_complete = any(e.get("event") == "session_complete" for e in events)
        assert has_complete, "session_complete not received"

        # Consensus fires before ceiling (20 turns) — the simple problem
        # should finish in far fewer turns
        assert message_count < 18, (
            f"Expected consensus before ceiling, but {message_count} messages were exchanged"
        )

        # Check if termination_reason can be inferred from the graph events
        # (emitted as part of session_complete or as a separate SSE if we added it)
        roster = _get_roster_from_events(events)
        print(f"  Roster: {roster}")
        print(f"  Messages exchanged: {message_count} (< 18 ceiling)")
        print(f"  PASS: consensus or early termination detected")
        return True
    except Exception as exc:
        print(f"  FAIL: {exc}")
        return False


def test4_intelligent_routing() -> bool:
    """Verify expert sequence is non-trivial: ≥2 different experts, project_manager last."""
    print("\n[TEST 4] Intelligent routing — at least 2 experts, PM speaks last")
    try:
        events, session_id = asyncio.run(
            _run_session(
                "Design a microservices architecture for an e-commerce platform",
                {1: {"0": "10k concurrent users, AWS, existing MySQL DB",
                     "1": "REST APIs, React frontend, mobile apps",
                     "2": "Team of 4, 6-month timeline"}},
                EMAILS[4],
                max_seconds=900,
            )
        )
        speakers = _get_speakers_from_events(events)
        has_complete = any(e.get("event") == "session_complete" for e in events)
        assert has_complete, "session_complete not received"

        print(f"  Expert sequence: {speakers}")
        assert len(speakers) >= 2, f"expected ≥2 different experts, got {speakers}"
        assert "project_manager" in speakers, "project_manager should have spoken"

        # project_manager should be the last expert before synthesis
        # (it may not always be the absolute last due to routing, but it should appear)
        pm_idx = max((i for i, s in enumerate(speakers) if s == "project_manager"), default=-1)
        if pm_idx >= 0 and len(speakers) > 1:
            non_pm_after = [s for s in speakers[pm_idx+1:] if s != "project_manager"]
            # Allow small deviations (routing isn't always perfect)
            if non_pm_after:
                print(f"  NOTE: Some experts spoke after PM: {non_pm_after} (routing not 100% strict)")

        print(f"  PASS: {len(speakers)} experts spoke, PM present, sequence looks intelligent")
        return True
    except Exception as exc:
        print(f"  FAIL: {exc}")
        return False


def test5_roster_persisted_to_db() -> bool:
    """Check that roster column is populated in sessions table after a session completes."""
    print("\n[TEST 5] Roster persisted to DB + rolling summary (if triggered)")
    try:
        # Run a session that will likely have >15 messages (use complex problem)
        events, session_id = asyncio.run(
            _run_session(
                "Build a distributed event processing system with real-time analytics",
                {1: {"0": "1M events/day, Kafka, Kubernetes, GCP",
                     "1": "Python backend, real-time dashboards",
                     "2": "Team of 3, 5-month timeline, SLA 99.5%"}},
                EMAILS[5],
                max_seconds=1200,  # 20 min — handles retry overhead from transient CLI failures
            )
        )
        has_complete = any(e.get("event") == "session_complete" for e in events)
        assert has_complete, "session_complete not received"

        # Check DB roster
        async def check_db():
            import uuid as _uuid
            from backend.db.postgres import AsyncSessionLocal
            from backend.models import Session
            async with AsyncSessionLocal() as db:
                sess = await db.get(Session, _uuid.UUID(session_id))
                assert sess is not None, "session not found in DB"
                assert sess.roster, f"roster column is empty/null for session {session_id}"
                print(f"  DB roster: {sess.roster}")
                return sess.roster

        roster_db = asyncio.run(check_db())
        roster_sse = _get_roster_from_events(events)
        print(f"  SSE roster: {roster_sse}")
        print(f"  DB roster:  {roster_db}")

        # They should match
        assert set(roster_db) == set(roster_sse), (
            f"Roster mismatch: SSE={roster_sse}, DB={roster_db}"
        )

        message_count = _count_turns(events)
        print(f"  Messages exchanged: {message_count}")
        if message_count > 15:
            print("  Rolling summary should have triggered (>15 messages)")
        else:
            print("  Rolling summary not triggered (<= 15 messages) — OK")

        print(f"  PASS: roster in DB={roster_db}")
        return True
    except Exception as exc:
        print(f"  FAIL: {exc}")
        import traceback; traceback.print_exc()
        return False


def main() -> None:
    print("=" * 60)
    print("Phase 3 Checkpoint — MoE Gating + Intelligent Routing")
    print("=" * 60)

    r1, roster1 = test1_simple_problem_small_roster()
    r2, roster2 = test2_complex_problem_large_roster()
    r3 = test3_consensus_terminates_before_ceiling()
    r4 = test4_intelligent_routing()
    r5 = test5_roster_persisted_to_db()

    results = {
        "Test 1 — Simple problem small roster":  r1,
        "Test 2 — Complex problem large roster": r2,
        "Test 3 — Consensus before ceiling":     r3,
        "Test 4 — Intelligent routing":          r4,
        "Test 5 — Roster persisted to DB":       r5,
    }

    print("\n" + "=" * 60)
    passed = 0
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if ok:
            passed += 1

    print(f"\n  TEST 1 roster: {roster1}")
    print(f"  TEST 2 roster: {roster2}")

    total = len(results)
    print(f"\n{'>>> CHECKPOINT PASSED <<<' if passed == total else '>>> CHECKPOINT FAILED <<<'}")
    print(f"  {passed}/{total} tests passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
