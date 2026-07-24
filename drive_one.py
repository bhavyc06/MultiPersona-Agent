"""
Drive a single session to completion, answering one question at a time.
Waits for each question to appear in the SSE stream before responding.
Never fires concurrent /respond calls.

Usage: python drive_one.py <session_id> <token>
"""
import sys, json, time, http.client, urllib.request, asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE    = "http://127.0.0.1:8000"
SID     = sys.argv[1]
TOKEN   = sys.argv[2]
MAX_SEC = 2400

ANSWER  = (
    "Small team, 2 devs, 3-month timeline. "
    "React frontend, FastAPI backend, PostgreSQL. "
    "Public users, no mobile needed, modest scale."
)

def post(path, data):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TOKEN}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=MAX_SEC + 30)
conn.request(
    "GET", f"/api/sessions/{SID}/stream?token={TOKEN}",
    headers={"Accept": "text/event-stream"},
)
resp = conn.getresponse()

buf = b""
start = time.monotonic()
solution = None
questions_pending = False
answered = 0

while True:
    elapsed = int(time.monotonic() - start)
    if elapsed > MAX_SEC:
        print(f"\n[TIMEOUT at {elapsed}s]")
        break

    try:
        chunk = resp.read(512)
    except Exception as e:
        print(f"[stream error] {e}")
        break
    if not chunk:
        print("[stream closed]")
        break

    buf += chunk
    while b"\n\n" in buf:
        raw, buf = buf.split(b"\n\n", 1)
        lines = raw.decode("utf-8", errors="replace").strip().splitlines()
        evt, data_str = "message", ""
        for ln in lines:
            if ln.startswith("event:"): evt = ln[6:].strip()
            elif ln.startswith("data:"): data_str = ln[5:].strip()
        if not data_str:
            continue

        try:
            payload = json.loads(data_str)
        except Exception:
            payload = {}

        # The SSE emitter puts event type inside the JSON as "event": "..."
        # not as a bare SSE `event:` line.
        ptype = payload.get("event", evt)

        # ── Questions (questionnaire or framing/clarification) ──────────────
        if ptype in ("questionnaire_question", "clarification_required", "framing_question"):
            q    = payload.get("question") or str(payload.get("questions", "?"))
            qnum = payload.get("question_number", payload.get("round", answered + 1))
            print(f"\n[{elapsed}s] Q{qnum}: {q[:100]}", flush=True)
            # Wait a moment to let the checkpoint commit before answering
            time.sleep(2)
            answered += 1
            try:
                res = post(f"/api/sessions/{SID}/respond", {"answer": ANSWER})
                print(f"  → responded ({res.get('status','?')})", flush=True)
            except urllib.error.HTTPError as e:
                body = e.read().decode()
                print(f"  → respond HTTP {e.code}: {body[:200]}", flush=True)
            except Exception as e:
                print(f"  → respond failed: {e}", flush=True)

        elif ptype in ("questionnaire_complete", "clarification_complete"):
            print(f"[{elapsed}s] {ptype}", flush=True)

        elif ptype == "agent_thinking":
            print(f"[{elapsed}s] ▶ {payload.get('agent','?')} thinking...", flush=True)

        elif ptype == "message" and not payload.get("is_private"):
            role    = payload.get("role", "?")
            content = payload.get("content", "")
            turn    = payload.get("turn", "?")
            if role not in ("system",):
                print(f"[{elapsed}s] [{role} turn={turn}] ({len(content)} chars): {content[:120]}", flush=True)

        elif ptype == "decision" and payload.get("state") == "locked":
            print(f"[{elapsed}s] LOCKED: {payload.get('text','')[:80]}", flush=True)

        elif ptype == "session_complete":
            solution = payload.get("solution_document")
            total_t  = payload.get("total_tokens", 0)
            print(f"\n[{elapsed}s] SESSION COMPLETE (tokens={total_t:,})", flush=True)
            break

        elif ptype == "error":
            print(f"[{elapsed}s] ERROR: {payload}", flush=True)

    if solution is not None:
        break

print("\n" + "=" * 60)
if solution:
    es = solution.get("executive_summary", "")
    kd = solution.get("key_decisions", [])
    print(f"\nEXECUTIVE SUMMARY ({len(es)} chars):\n{es[:600]}")
    print(f"\nKEY DECISIONS ({len(kd)}):")
    for i, d in enumerate(kd[:5], 1):
        print(f"  [{i}] {d[:110]}")
    if len(kd) > 5:
        print(f"  ... and {len(kd)-5} more")
    bad = "could not be generated"
    print(f"\n'could not be generated' present: {bad in es}")
else:
    print("No solution from stream — will check file/DB externally.")
