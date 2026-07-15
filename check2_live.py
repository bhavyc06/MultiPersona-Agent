"""
Check 2: live seat via [[TEST_BATON:security]] on a fintech problem.
Confirms: domain_nominated SSE → gate → expert_recruited SSE (no pause)
          → recruited expert speaks → seat in decision ledger → no double-persist.
"""
import sys, json, time, http.client, urllib.request, asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv()

BASE = "http://127.0.0.1:8000"

PROBLEM = (
    "[[TEST_BATON:security]] "
    "Build a fintech payments app handling credit cards and bank transfers. "
    "PCI DSS compliance required. 50k transactions/day, sub-200ms p99 latency. "
    "AWS, 8-person engineering team, 6-month roadmap."
)
Q_ANS  = "8 engineers, AWS, cloud-native, 6-month deadline."
FR_ANS = "AWS preferred, PCI DSS mandatory, 50k txns/day, sub-200ms, 8 engineers, greenfield."


def post(path, data, token=""):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {token}"} if token else {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def run():
    print("\n══════════════════════════════════════════════════")
    print("Check 2 — live seat via TEST_BATON:security")
    print("══════════════════════════════════════════════════\n")

    token = post("/api/auth/login", {"email": "phase0test@test.com", "password": "Test1234!"})["access_token"]
    sid   = post("/api/sessions", {"problem_statement": PROBLEM, "depth_tier": "shallow"}, token)["session_id"]
    print(f"Session: {sid}")

    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=700)
    conn.request("GET", f"/api/sessions/{sid}/stream?token={token}",
                 headers={"Accept": "text/event-stream"})
    resp = conn.getresponse()

    q_idx = 0
    Q = ["8 engineers, AWS experience.", "Cloud-native, 6-month roadmap.",
         "PCI DSS mandatory.", "Greenfield — no legacy systems."]

    ev = {
        "domain_nominated_fired": False,
        "nominated_domain": None,
        "nominated_by": None,
        "gate_band": None,
        "expert_recruited_fired": False,
        "recruited_role": None,
        "recruited_score": None,
        "escalation_fired": False,   # should be FALSE for confident
        "recruited_spoke": False,
        "recruited_msg_snippet": "",
        "decision_events": [],       # list of {id, text, provenance} from SSE
        "solution_produced": False,
        "messages": [],
    }
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
                d = json.loads(line[6:])
                et = d.get("event", "?")

                if et == "questionnaire_question":
                    ans = Q[q_idx] if q_idx < len(Q) else "No preference."
                    print(f"  [Q{d.get('question_number',0)}] {d.get('question','')[:50]}")
                    q_idx += 1; time.sleep(0.3)
                    post(f"/api/sessions/{sid}/respond", {"answer": ans}, token)

                elif et == "questionnaire_complete":
                    print(f"  [qc] {d.get('question_count')} Qs done")

                elif et == "clarification_required":
                    print(f"  [framing] {len(d.get('questions',[]))} Qs")
                    time.sleep(0.3)
                    post(f"/api/sessions/{sid}/respond", {"answer": FR_ANS}, token)

                elif et == "roster_selected":
                    print(f"  [roster] {d.get('roster')}")

                elif et == "domain_nominated":
                    ev["domain_nominated_fired"] = True
                    ev["nominated_domain"]       = d.get("domain")
                    ev["nominated_by"]           = d.get("role")
                    print(f"\n  *** domain_nominated: role={d.get('role')!r} domain={d.get('domain')!r} ***")

                elif et == "expert_recruited":
                    ev["expert_recruited_fired"] = True
                    ev["recruited_role"]         = d.get("role")
                    ev["recruited_score"]        = d.get("score")
                    ev["gate_band"]              = "confident"  # fired → confident (no escalation)
                    print(
                        f"  *** expert_recruited: {d.get('display_name')} ({d.get('role')})"
                        f"  domain={d.get('domain')!r} score={d.get('score',0):.2f} ***"
                    )

                elif et == "escalation_required":
                    ev["escalation_fired"] = True
                    ev["gate_band"]        = "borderline"
                    print(f"  *** ESCALATION (borderline): {d.get('summary','')[:60]} ***")
                    # Auto-choose "seat" to let session proceed
                    time.sleep(0.5)
                    post(f"/api/sessions/{sid}/respond", {"answer": "seat"}, token)

                elif et == "decision":
                    ev["decision_events"].append({
                        "id":        d.get("id"),
                        "text":      d.get("text","")[:80],
                        "provenance": d.get("provenance"),
                        "state":      d.get("state"),
                    })

                elif et == "message" and not d.get("is_private"):
                    role = d.get("role","?")
                    c    = d.get("content","").encode("ascii","replace").decode()[:60]
                    tag  = " [RECRUITED]" if ev["recruited_role"] and role == ev["recruited_role"] else "          "
                    print(f"  [msg{tag}] {role}: {c}")
                    ev["messages"].append({"role": role, "content": d.get("content","")})
                    if ev["recruited_role"] and role == ev["recruited_role"]:
                        ev["recruited_spoke"] = True
                        ev["recruited_msg_snippet"] = d.get("content","")[:200]
                        print("  [EARLY EXIT: recruited expert spoke — closing stream for seat trace]")
                        conn.close(); break

                elif et == "reviewer_complete":
                    print(f"  [reviewer] passed={d.get('verdict_passed')} retry={d.get('retry_count',0)}")

                elif et == "cleanup_complete":
                    print(f"  [cleanup] turns={d.get('turns_taken')}")

                elif et == "synthesizing":
                    print("  [synthesizing]")

                elif et == "session_complete":
                    doc = d.get("solution_document") or {}
                    ev["solution_produced"] = bool(doc)
                    summ = str(doc.get("executive_summary","")).encode("ascii","replace").decode()[:80]
                    print(f"\n  [COMPLETE] tokens={d.get('total_tokens',0)}")
                    print(f"  summary: {summ}")
                    conn.close(); break

                elif et == "error":
                    print(f"  [ERROR] {d}"); conn.close(); break

            except json.JSONDecodeError:
                pass

    # ── Checkpoint trace (for double-persist check) ───────────────────────────
    # Brief pause so the server's fire-and-forget create_task DB writes settle.
    time.sleep(3)
    print("\n── Checkpoint + DB trace ──")
    async def check_cp():
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from backend.config import settings
        import psycopg

        pool = AsyncConnectionPool(
            conninfo=settings.postgres_conn_string, min_size=1, max_size=2,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            open=False,
        )
        await pool.open()
        cp = AsyncPostgresSaver(conn=pool)

        snap = await cp.aget({"configurable": {"thread_id": sid}})
        cp_decisions = []
        if snap:
            cv = snap.get("channel_values", {})
            print(f"  roster:              {cv.get('roster')}")
            print(f"  last_nomination:     {cv.get('last_nomination')}")
            cp_decs = [d for d in cv.get("decisions",[]) if d.get("provenance")=="moderator"]
            cp_decisions = cp_decs
            print(f"  checkpoint moderator_decisions: {len(cp_decs)}")
            for d in cp_decs:
                print(f"    → {d.get('text','')[:90]!r}")
            cps = [p for p in (cv.get("custom_personas") or []) if p.get("role","").endswith("_specialist")]
            print(f"  recruited_personas:  {[p['role'] for p in cps]}")

        # Also query decisions table directly (separate from checkpoint)
        conn = await psycopg.AsyncConnection.connect(settings.postgres_conn_string, autocommit=True)
        rows = await (await conn.execute(
            "SELECT id, text, provenance, state FROM decisions "
            "WHERE session_id = %s AND provenance = 'moderator' ORDER BY created_at",
            (sid,),
        )).fetchall()
        await conn.close()
        print(f"\n  decisions TABLE moderator rows: {len(rows)}")
        for r in rows:
            print(f"    [{r[2]}/{r[3]}] {r[1][:80]!r}")

        double_persist = (len(cp_decisions) != len(rows)) if rows else False
        print(f"\n  Double-persist check: checkpoint={len(cp_decisions)} DB_table={len(rows)}")
        if double_persist:
            print("  *** DOUBLE-PERSIST DETECTED — count mismatch ***")
        else:
            print("  No double-persist detected (counts match)")

        sol = snap.get("channel_values",{}).get("solution_document") if snap else None
        print(f"  sol_doc:             {'EXISTS' if sol else 'NONE'}")

        await pool.close()
        return double_persist, len(rows)

    double_persist, db_row_count = asyncio.run(check_cp())

    # ── Gate check on recruited expert message ─────────────────────────────────
    guardrails_ok = False
    if ev["recruited_spoke"] and ev["recruited_msg_snippet"]:
        snippet = ev["recruited_msg_snippet"].lower()
        # Domain-locked expert should have security-domain content (not generic)
        # and should use best-guess or OWNER-AUTHORITY language
        domain_ok    = "security" in snippet or "pci" in snippet or "encrypt" in snippet or "compliance" in snippet
        guardrails_ok = domain_ok  # minimal check: speaks about its domain
        print(f"\n  Recruited expert message check:")
        print(f"  snippet (200 chars): {ev['recruited_msg_snippet'][:200]!r}")
        print(f"  domain_content_ok: {domain_ok}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n── Check 2 Results ──")
    r1 = ev["domain_nominated_fired"]
    r2 = ev["expert_recruited_fired"] and not ev["escalation_fired"]  # confident → no pause
    r3 = ev["recruited_role"] and ev["recruited_role"].endswith("_specialist")
    r4 = ev["recruited_spoke"]
    r5 = db_row_count >= 1  # seat logged in decisions table
    r6 = not double_persist
    r7 = ev["solution_produced"]

    print(f"  domain_nominated fired:          {'PASS' if r1 else 'FAIL'}  by={ev['nominated_by']!r} domain={ev['nominated_domain']!r}")
    print(f"  expert_recruited, NO escalation: {'PASS' if r2 else 'FAIL'}  band=confident (escalation_fired={ev['escalation_fired']})")
    print(f"  _specialist role in roster:      {'PASS' if r3 else 'FAIL'}  role={ev['recruited_role']!r}")
    print(f"  recruited expert spoke:          {'PASS' if r4 else 'FAIL'}")
    print(f"  seat in decisions DB table:      {'PASS' if r5 else 'FAIL'}  rows={db_row_count}")
    print(f"  no double-persist:               {'PASS' if r6 else 'FAIL'}")
    print(f"  solution produced:               {'PASS' if r7 else 'FAIL'}")

    all_pass = all([r1, r2, r3, r4, r5, r6, r7])
    print(f"\n  Check 2 result: {'*** ALL PASS ***' if all_pass else 'FAIL — see above'}")
    return all_pass


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
