#!/usr/bin/env python
"""
Phase 4 automated checkpoint — export endpoint.

Assertions:
  1. GET /api/sessions/{id}/export?format=md returns 200 after session completes
  2. Content-Type contains "text"
  3. Response body is non-empty

The test submits a session, answers clarification, waits for session_complete,
then hits the export endpoint.

Usage: python -m tests.checkpoint_4
"""
import asyncio
import json
import time

import httpx

BASE = "http://localhost:8000"
PROBLEM = "Build a simple REST API for user management"
EMAIL = "cp4@example.com"
PASSWORD = "Checkpoint4!"

_ANSWERS = {
    1: {"0": "CRUD endpoints for users: create, read, update, delete",
        "1": "JWT authentication, role-based access control",
        "2": "PostgreSQL, FastAPI, Python",
        "3": "Small team, 100k users at scale"},
    2: {"0": "OpenAPI spec required, versioning via URL prefix",
        "1": "Containerised with Docker, deploy on AWS ECS",
        "2": "Standard REST conventions, JSON responses",
        "3": "2 engineers, 6-week delivery"},
    3: {"0": "Rate limiting per user, audit logging",
        "1": "Email verification on signup",
        "2": "Health check endpoints required",
        "3": "Tests required: unit + integration"},
}


async def get_token(client: httpx.AsyncClient) -> str:
    r = await client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    if r.status_code == 401:
        await client.post("/api/auth/register", json={"email": EMAIL, "password": PASSWORD})
        r = await client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    return r.json()["access_token"]


async def _submit(client, session_id, answers, headers, rnd):
    await asyncio.sleep(1)
    r = await client.post(
        f"/api/sessions/{session_id}/clarify",
        json={"answers": answers}, headers=headers,
    )
    print(f"  [clarify round {rnd}] {r.status_code}")


async def run_to_complete(client: httpx.AsyncClient, headers: dict) -> str:
    r = await client.post("/api/sessions",
                          json={"problem_statement": PROBLEM}, headers=headers)
    r.raise_for_status()
    session_id = r.json()["session_id"]
    print(f"  session_id: {session_id}")

    start = time.monotonic()
    async with client.stream("GET", f"/api/sessions/{session_id}/stream",
                             headers=headers, timeout=700) as stream:
        async for line in stream.aiter_lines():
            if time.monotonic() - start > 660:
                print("  [timeout]")
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
                rnd = evt.get("round", 1)
                answers = _ANSWERS.get(rnd, {str(i): "Standard approach" for i in range(4)})
                asyncio.create_task(_submit(client, session_id, answers, headers, rnd))

            elif etype == "session_complete":
                print("  [session_complete]")
                break
            elif etype == "error":
                break

    return session_id


async def main():
    results: dict[int, bool] = {}

    def check(n, label, val):
        results[n] = val
        print(f"  {'PASS' if val else 'FAIL'}  [{n}] {label}")

    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        print("=== AUTH ===")
        token = await get_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        print("  Authenticated")

        print("\n=== RUNNING SESSION (waiting for session_complete) ===")
        session_id = await run_to_complete(client, headers)

        # Give server a moment to write solution.json
        await asyncio.sleep(3)

        print(f"\n=== EXPORT ENDPOINT ===")
        r = await client.get(
            f"/api/sessions/{session_id}/export",
            params={"format": "md"},
            headers=headers,
        )
        print(f"  Status: {r.status_code}")
        print(f"  Content-Type: {r.headers.get('content-type', '?')}")
        print(f"  Body length: {len(r.text)} chars")
        if r.status_code == 200:
            print(f"  Body preview: {r.text[:200]!r}")

    print("\n=== ASSERTIONS ===")
    check(1, "GET /export returns 200", r.status_code == 200)
    check(2, "Content-Type contains 'text'", "text" in r.headers.get("content-type", ""))
    check(3, "Response body is non-empty", len(r.text) > 10)

    passed = sum(1 for v in results.values() if v)
    print(f"\n{'>>> CHECKPOINT PASSED <<<' if passed == len(results) else '>>> CHECKPOINT FAILED <<<'}")
    print(f"  {passed}/{len(results)} assertions passed")


if __name__ == "__main__":
    asyncio.run(main())
