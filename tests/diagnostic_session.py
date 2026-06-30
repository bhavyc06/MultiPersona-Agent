"""Quick diagnostic: run a single session and verify session_complete + locked_decisions."""
import asyncio
import json
import sys
import time
import urllib.request

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE = "http://localhost:8000"
_TS = int(time.time())
EMAIL = f"diag_{_TS}@example.com"
PASSWORD = "DiagTest1!"


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


async def run_diagnostic():
    _post("/api/auth/register", {"email": EMAIL, "password": PASSWORD})
    _, r = _post("/api/auth/login", {"email": EMAIL, "password": PASSWORD})
    token = r["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        r = await client.post(
            "/api/sessions",
            json={"problem_statement": "Build a simple REST API for a todo list app"},
            headers=headers,
        )
        r.raise_for_status()
        session_id = r.json()["session_id"]
        print(f"session_id: {session_id}", flush=True)

        events = []
        clarify_rounds = 0
        start = time.monotonic()

        async with client.stream(
            "GET",
            f"/api/sessions/{session_id}/stream",
            headers=headers,
            timeout=1810,
        ) as stream:
            async for line in stream.aiter_lines():
                elapsed = time.monotonic() - start
                if elapsed > 1800:
                    print(f"[TIMEOUT at {elapsed:.0f}s]", flush=True)
                    break
                if not line.startswith("data:"):
                    continue
                try:
                    evt = json.loads(line[6:])
                except Exception:
                    continue

                etype = evt.get("event", "?")
                extra = ""
                if etype == "decision":
                    extra = f" state={evt.get('state')} text={str(evt.get('text',''))[:50]}"
                elif etype == "session_complete":
                    locked = evt.get("locked_decisions", [])
                    extra = f" locked={len(locked)} doc_keys={list((evt.get('solution_document') or {}).keys())}"
                print(f"  [{elapsed:5.1f}s] {etype}{extra}", flush=True)
                events.append(evt)

                if etype == "clarification_required":
                    clarify_rounds += 1
                    answers = {
                        "0": "5k users, AWS, Python FastAPI, PostgreSQL, 3-month timeline",
                        "1": "CRUD todo items, JWT auth, REST API",
                        "2": "Team of 2, $200/month infra budget",
                    }
                    combined = "\n\n".join(f"Q{k}: {v}" for k, v in answers.items())

                    async def _respond():
                        await asyncio.sleep(1)
                        resp = await client.post(
                            f"/api/sessions/{session_id}/respond",
                            json={"answer": combined},
                            headers=headers,
                        )
                        print(f"  [/respond] {resp.status_code}", flush=True)

                    asyncio.create_task(_respond())

                if etype in ("session_complete", "error"):
                    break

    has_complete = any(e.get("event") == "session_complete" for e in events)
    locked = next(
        (e.get("locked_decisions", []) for e in events if e.get("event") == "session_complete"),
        [],
    )
    doc = next(
        (e.get("solution_document", {}) for e in events if e.get("event") == "session_complete"),
        {},
    )

    print(f"\n=== DIAGNOSTIC RESULTS ===")
    print(f"Total events received: {len(events)}")
    print(f"has session_complete: {has_complete}")
    print(f"locked_decisions count: {len(locked)}")
    for d in locked[:5]:
        print(f"  [{d.get('provenance','?')}] {str(d.get('text',''))[:80]}")
    if doc:
        key_decisions = doc.get("key_decisions", [])
        print(f"key_decisions in doc: {len(key_decisions)}")
        for kd in key_decisions[:3]:
            print(f"  - {str(kd)[:80]}")
    print("=" * 26)
    return has_complete, locked


if __name__ == "__main__":
    ok, locked = asyncio.run(run_diagnostic())
    sys.exit(0 if ok and len(locked) >= 1 else 1)
