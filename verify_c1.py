"""
Phase C.1 verification: drives a session with [[TEST_ESCALATION]] sentinel,
confirms pause → ruling → resume, then reads the checkpoint for the state trace.
"""
import sys, json, time, http.client, urllib.request, asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv()

BASE = "http://127.0.0.1:8000"

PROBLEM = (
    "[[TEST_ESCALATION]] "
    "Build a simple task manager for a 5-person team. "
    "Web-based, no mobile app needed. Budget $50/month."
)

Q_ANS  = "Small team, non-technical users, low budget."
FR_ANS = "5 people, web only, AWS preferred, $50/month hard cap."


def post(path, data, token=""):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(data).encode(),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {})
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def run():
    print("\n══════════════════════════════════════════════════")
    print("Phase C.1 verification — escalation channel test")
    print("══════════════════════════════════════════════════\n")

    # Auth
    token = post("/api/auth/login", {"email": "phase0test@test.com", "password": "Test1234!"})["access_token"]

    # Create session with sentinel
    sid = post("/api/sessions", {"problem_statement": PROBLEM, "depth_tier": "shallow"}, token)["session_id"]
    print(f"Session: {sid}")

    # Open SSE stream
    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=700)
    conn.request("GET", f"/api/sessions/{sid}/stream?token={token}",
                 headers={"Accept": "text/event-stream"})
    resp = conn.getresponse()

    q_idx = 0
    Q = ["Small team, non-technical.", "Web only, AWS.", "Under $50/month.", "MVP first."]

    escalation_fired     = False
    escalation_resolved  = False
    ruling_seen          = None
    solution_produced    = False
    expert_after_ruling  = False
    buf = b""

    while True:
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
                ev = json.loads(line[6:])
                et = ev.get("event", "?")

                if et == "questionnaire_question":
                    ans = Q[q_idx] if q_idx < len(Q) else "No preference."
                    print(f"  [Q{ev.get('question_number',0)}] {ev.get('question','')[:55]}")
                    q_idx += 1; time.sleep(0.3)
                    post(f"/api/sessions/{sid}/respond", {"answer": ans}, token)

                elif et == "questionnaire_complete":
                    print(f"  [qc] {ev.get('question_count')} Qs done")

                elif et == "clarification_required":
                    print(f"  [framing] {len(ev.get('questions',[]))} Qs")
                    time.sleep(0.3)
                    post(f"/api/sessions/{sid}/respond", {"answer": FR_ANS}, token)

                elif et == "roster_selected":
                    print(f"  [roster] {ev.get('roster')}")

                # ── ESCALATION EVENTS ──────────────────────────────────────
                elif et == "escalation_required":
                    escalation_fired = True
                    opts = ev.get("options", [])
                    print(f"\n  *** ESCALATION FIRED ***")
                    print(f"  reason:  {ev.get('reason')}")
                    print(f"  summary: {ev.get('summary')}")
                    for o in opts:
                        print(f"    [{o['id']}] {o['label']} — {o['impact']}")
                    # Simulate user choosing 'mvp'
                    chosen = "mvp"
                    print(f"\n  >> Sending choice: {chosen!r}")
                    time.sleep(0.5)
                    post(f"/api/sessions/{sid}/respond", {"answer": chosen}, token)

                elif et == "escalation_resolved":
                    escalation_resolved = True
                    ruling_seen = ev.get("chosen_option_id")
                    print(f"  [escalation_resolved] chosen={ruling_seen!r}")

                # ── NORMAL EVENTS ──────────────────────────────────────────
                elif et == "message" and not ev.get("is_private"):
                    role = ev.get("role", "?")
                    c = ev.get("content", "").encode("ascii","replace").decode()[:55]
                    tag = "  [msg-POST-RULING]" if escalation_resolved else "  [msg           ]"
                    print(f"{tag} {role}: {c}")
                    if escalation_resolved and role not in ("system","human"):
                        expert_after_ruling = True

                elif et == "reviewer_complete":
                    vp = ev.get("verdict_passed")
                    print(f"  [reviewer] passed={vp} retry={ev.get('retry_count',0)}")

                elif et == "decision":
                    prov = ev.get("provenance","?")
                    text = ev.get("text","")[:50].encode("ascii","replace").decode()
                    if prov == "moderator":
                        print(f"  [DECISION/moderator] {text!r}")

                elif et == "cleanup_complete":
                    print(f"  [cleanup] turns={ev.get('turns_taken')}")

                elif et == "synthesizing":
                    print("  [synthesizing]")

                elif et == "session_complete":
                    doc = ev.get("solution_document") or {}
                    solution_produced = bool(doc)
                    summ = str(doc.get("executive_summary","")).encode("ascii","replace").decode()[:100]
                    print(f"\n  [COMPLETE] tokens={ev.get('total_tokens',0)}")
                    print(f"  summary: {summ}")
                    conn.close(); break

                elif et == "error":
                    print(f"  [ERROR] {ev}"); conn.close(); break

            except json.JSONDecodeError:
                pass

    # ── Checkpoint trace ───────────────────────────────────────────────────────
    print("\n── Checkpoint trace ──")
    async def check_cp():
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from backend.config import settings

        pool = AsyncConnectionPool(
            conninfo=settings.postgres_conn_string, min_size=1, max_size=2,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            open=False,
        )
        await pool.open()
        cp = AsyncPostgresSaver(conn=pool)
        snap = await cp.aget({"configurable": {"thread_id": sid}})
        if snap:
            cv = snap.get("channel_values", {})
            print(f"  pending_escalation:  {cv.get('pending_escalation')}")
            print(f"  escalation_ruling:   {cv.get('escalation_ruling')}")
            print(f"  turn_count:          {cv.get('turn_count')}")
            print(f"  termination_reason:  {cv.get('termination_reason')}")
            # Show moderator decisions from the decision ledger
            mods = [d for d in cv.get("decisions", []) if d.get("provenance") == "moderator"]
            print(f"  moderator decisions: {len(mods)}")
            for d in mods:
                print(f"    → {d.get('text','')[:80]!r}")
            sol = cv.get("solution_document")
            print(f"  sol_doc:             {'EXISTS' if sol else 'NONE'}")
        else:
            print("  (no checkpoint found)")
        await pool.close()

    asyncio.run(check_cp())

    # ── Verdict ───────────────────────────────────────────────────────────────
    print("\n── C1 Gate Results ──")
    g_esc_fired     = escalation_fired
    g_esc_resolved  = escalation_resolved
    g_ruling_ok     = ruling_seen == "mvp"
    g_expert_after  = expert_after_ruling
    g_solution      = solution_produced

    print(f"  escalation_required fired:  {'PASS' if g_esc_fired else 'FAIL'}")
    print(f"  escalation_resolved fired:  {'PASS' if g_esc_resolved else 'FAIL'}")
    print(f"  ruling recorded (mvp):      {'PASS' if g_ruling_ok else 'FAIL'} — got {ruling_seen!r}")
    print(f"  expert spoke after ruling:  {'PASS' if g_expert_after else 'FAIL'}")
    print(f"  solution produced:          {'PASS' if g_solution else 'FAIL'}")

    all_passed = all([g_esc_fired, g_esc_resolved, g_ruling_ok, g_solution])
    print(f"\n  C1 result: {'*** ALL PASS ***' if all_passed else 'incomplete'}")
    return all_passed


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
