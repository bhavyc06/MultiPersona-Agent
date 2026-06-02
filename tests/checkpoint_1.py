#!/usr/bin/env python
"""
Phase 1 checkpoint: submit the canonical problem, collect SSE events through
Phase 1 (Frame), then dump the scratchpad and decision log.

Usage: python -m tests.checkpoint_1
"""
import asyncio
import json
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8000"
PROBLEM = "Build a real-time ML feature store"
EMAIL = "checkpoint@example.com"
PASSWORD = "Checkpoint1!"


async def get_token(client: httpx.AsyncClient) -> str:
    r = await client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    if r.status_code == 401:
        await client.post("/api/auth/register", json={"email": EMAIL, "password": PASSWORD})
        r = await client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    return r.json()["access_token"]


async def collect_events(
    client: httpx.AsyncClient,
    session_id: str,
    headers: dict,
    max_seconds: int = 240,
) -> list[dict]:
    events: list[dict] = []
    start = time.monotonic()

    async with client.stream(
        "GET",
        f"/api/sessions/{session_id}/stream",
        headers=headers,
        timeout=max_seconds + 10,
    ) as stream:
        async for line in stream.aiter_lines():
            elapsed = time.monotonic() - start
            if elapsed > max_seconds:
                print(f"  [timeout at {elapsed:.0f}s]")
                break

            if not line.startswith("data: "):
                continue

            try:
                evt = json.loads(line[6:])
            except json.JSONDecodeError:
                continue

            events.append(evt)
            etype = evt.get("event", "?")
            print(f"  [{elapsed:5.1f}s] {etype:20s}  {_summary(evt)}")

            if etype in ("session_complete", "error"):
                print("  [terminal event — stream done]")
                break

            # For the checkpoint we stop reading after Phase 1 barrier fires
            if etype == "phase_complete" and evt.get("phase") == 1:
                print("  [Phase 1 barrier — stopping stream read for checkpoint]")
                break

    return events


def _summary(evt: dict) -> str:
    e = dict(evt)
    e.pop("event", None)
    e.pop("solution_document", None)
    s = str(e)
    return s[:100]


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        # ── 1. Auth ──────────────────────────────────────────────────────────
        print("=== STEP 1: Auth ===")
        token = await get_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        print(f"  Authenticated OK")

        # ── 2. Create session ────────────────────────────────────────────────
        print(f"\n=== STEP 2: Create session ===")
        r = await client.post(
            "/api/sessions",
            json={"problem_statement": PROBLEM},
            headers=headers,
        )
        r.raise_for_status()
        data = r.json()
        session_id = data["session_id"]
        print(f"  session_id : {session_id}")
        print(f"  status     : {data['status']}")

        # ── 3. SSE event stream ──────────────────────────────────────────────
        print(f"\n=== STEP 3: SSE event stream (waiting for Phase 1 barrier) ===")
        events = await collect_events(client, session_id, headers, max_seconds=240)

        # ── 4. Scratchpad dump ───────────────────────────────────────────────
        print(f"\n=== STEP 4: Scratchpad ===")
        sp_path = Path(f"data/sessions/{session_id}/scratchpad.json")

        # Give the barrier write a moment to complete
        await asyncio.sleep(1)

        if not sp_path.exists():
            print(f"  ERROR: scratchpad not found at {sp_path}")
            return

        sp = json.loads(sp_path.read_text())

        print(f"  complexity         : {sp['complexity']}")
        print(f"  agent_outputs keys : {list(sp['agent_outputs'].keys())}")
        print(f"  decision_log count : {len(sp['decision_log'])}")

        # ── 5. Decision log ──────────────────────────────────────────────────
        print(f"\n=== STEP 5: Decision log ===")
        if sp["decision_log"]:
            for entry in sp["decision_log"]:
                print(
                    f"  [{entry['locked_by']} / phase {entry['phase']}] "
                    f"{entry['decision'][:80]}"
                )
        else:
            print("  (empty — barrier not yet reached or no decisions locked)")

        # ── 6. One raw agent output ──────────────────────────────────────────
        print(f"\n=== STEP 6: Raw agent output (ai_architect) ===")
        if "ai_architect" in sp["agent_outputs"]:
            print(json.dumps(sp["agent_outputs"]["ai_architect"], indent=2))
        else:
            print("  (not yet in scratchpad)")

        # ── 7. Event sequence assertion ──────────────────────────────────────
        print(f"\n=== STEP 7: Event sequence check ===")
        etypes = [e.get("event") for e in events]
        print(f"  Full sequence : {etypes}")
        checks = [
            ("session_started in events", "session_started" in etypes),
            ("phase_start in events", "phase_start" in etypes),
            ("agent_start in events", "agent_start" in etypes),
            ("token in events", "token" in etypes),
            ("agent_end in events", "agent_end" in etypes),
            ("ai_architect output exists", "ai_architect" in sp["agent_outputs"]),
            ("solution_architect output exists", "solution_architect" in sp["agent_outputs"]),
            ("decision_log has >=1 entry", len(sp["decision_log"]) >= 1),
        ]
        for label, result in checks:
            print(f"  {'PASS' if result else 'FAIL'} {label}")

        # ── 8. Token estimate ────────────────────────────────────────────────
        print(f"\n=== STEP 8: Token estimate ===")
        chars = len(sp_path.read_text())
        print(f"  Scratchpad chars : {chars}")
        print(f"  Estimated tokens : ~{chars // 4}  (scratchpad only; prompt tokens not counted)")
        print(f"  Total events     : {len(events)}")

        all_passed = all(r for _, r in checks)
        print(f"\n{'>>> CHECKPOINT PASSED <<<' if all_passed else '>>> CHECKPOINT FAILED <<<'}")


if __name__ == "__main__":
    asyncio.run(main())
