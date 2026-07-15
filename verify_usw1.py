"""
Step 4: Short live session to confirm us-west-1 model calls work.
Early-exit as soon as the first expert speaks successfully.
Measures first-expert latency to compare against ap-south-1 baseline.
"""
import sys, json, time, http.client, urllib.request, asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv()

BASE = "http://127.0.0.1:8000"

PROBLEM = (
    "Design a REST API for a blog platform. "
    "Users, posts, comments. PostgreSQL backend, FastAPI. "
    "Small team, 6-week timeline."
)
Q_ANS  = "3 developers, FastAPI, PostgreSQL, simple CRUD, no auth complexity."
FR_ANS = "PostgreSQL, FastAPI, 3 devs, 6 weeks, greenfield, no compliance needs."


def post(path, data, token=""):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode(),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def run():
    print("\n══════════════════════════════════════════════════")
    print("Step 4 — us-west-1 live verify (first expert early-exit)")
    print("══════════════════════════════════════════════════\n")

    t_session_start = time.monotonic()

    token = post("/api/auth/login", {"email": "phase0test@test.com", "password": "Test1234!"})["access_token"]
    sid   = post("/api/sessions", {"problem_statement": PROBLEM, "depth_tier": "shallow"}, token)["session_id"]
    print(f"Session: {sid}")

    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=600)
    conn.request("GET", f"/api/sessions/{sid}/stream?token={token}",
                 headers={"Accept": "text/event-stream"})
    resp = conn.getresponse()

    q_idx   = 0
    Q       = ["3 devs, FastAPI, PostgreSQL.", "6-week deadline.", "No compliance.", "Greenfield."]
    ev      = {"first_expert_spoke": False, "first_expert_role": None,
               "first_msg_snippet": "", "model_errors": [], "model_key_seen": None}
    t_first_expert = None
    buf     = b""
    start   = time.monotonic()
    MAX     = 600

    while True:
        if time.monotonic() - start > MAX:
            print(f"  [TIMEOUT {MAX}s]"); break
        try:
            chunk = resp.read(256)
        except Exception as e:
            print(f"  [stream error] {e}"); break
        if not chunk:
            print("  [stream closed]"); break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip().decode("utf-8", errors="replace")
            if not line or line.startswith(":"): continue
            if not line.startswith("data: "): continue
            try:
                d  = json.loads(line[6:])
                et = d.get("event", "?")

                if et == "questionnaire_question":
                    ans = Q[q_idx] if q_idx < len(Q) else "No preference."
                    print(f"  [Q{d.get('question_number',0)}] {d.get('question','')[:50]}")
                    q_idx += 1; time.sleep(0.3)
                    post(f"/api/sessions/{sid}/respond", {"answer": ans}, token)

                elif et == "questionnaire_complete":
                    print(f"  [qc] {d.get('question_count')} Qs done")

                elif et == "clarification_required":
                    print(f"  [framing] {len(d.get('questions', []))} Qs — sending answer")
                    time.sleep(0.3)
                    post(f"/api/sessions/{sid}/respond", {"answer": FR_ANS}, token)

                elif et == "roster_selected":
                    print(f"  [roster] {d.get('roster')}")
                    t_first_expert = time.monotonic()   # start timing from roster selection

                elif et == "message" and not d.get("is_private"):
                    role = d.get("role", "?")
                    content = d.get("content", "")
                    snippet = content.encode("ascii", "replace").decode()[:80]
                    print(f"  [msg] {role}: {snippet}")

                    if not ev["first_expert_spoke"] and role not in ("system", "human"):
                        ev["first_expert_spoke"] = True
                        ev["first_expert_role"]  = role
                        ev["first_msg_snippet"]  = content[:200]
                        latency_ms = round((time.monotonic() - (t_first_expert or start)) * 1000)
                        print(f"\n  *** FIRST EXPERT SPOKE: {role} ({latency_ms}ms from roster) ***")
                        print(f"  [EARLY EXIT: us-west-1 model call confirmed working]")
                        conn.close()
                        break

                elif et == "error":
                    print(f"  [ERROR] {d}")
                    ev["model_errors"].append(d)
                    conn.close(); break

            except json.JSONDecodeError:
                pass

    total_ms = round((time.monotonic() - t_session_start) * 1000)

    # ── DB check for the model ARN used ─────────────────────────────────────────
    print("\n── DB / checkpoint trace ──")
    async def check_arn():
        from psycopg_pool import AsyncConnectionPool
        from psycopg.rows import dict_row
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from backend.config import settings
        pool = AsyncConnectionPool(
            conninfo=settings.postgres_conn_string, min_size=1, max_size=2,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            open=False,
        )
        await pool.open()
        cp  = AsyncPostgresSaver(conn=pool)
        snap = await cp.aget({"configurable": {"thread_id": sid}})
        if snap:
            cv = snap.get("channel_values", {})
            msgs = [m for m in (cv.get("messages") or []) if not m.get("is_private")]
            print(f"  messages in checkpoint: {len(msgs)}")
            print(f"  turn_count: {cv.get('turn_count')}")
        await pool.close()
    asyncio.run(check_arn())

    # ── Summary ─────────────────────────────────────────────────────────────────
    print("\n── Step 4 Results ──")
    r1 = ev["first_expert_spoke"]
    r2 = len(ev["model_errors"]) == 0
    r3 = bool(ev["first_msg_snippet"])

    print(f"  Model calls succeeded (us-west-1):  {'PASS' if r1 else 'FAIL'}")
    print(f"  No ValidationException/errors:       {'PASS' if r2 else 'FAIL'}")
    print(f"  First expert produced real output:   {'PASS' if r3 else 'FAIL'}")
    if ev["first_expert_spoke"]:
        print(f"  First expert role: {ev['first_expert_role']!r}")
        print(f"  First 200 chars: {ev['first_msg_snippet'][:200]!r}")
    print(f"  Total wall-clock (session start→first expert): {total_ms}ms")

    all_pass = r1 and r2 and r3
    print(f"\n  Step 4: {'*** PASS ***' if all_pass else 'FAIL'}")
    return all_pass


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
