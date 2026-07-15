"""
Phase C.2 live session test.
Problem: GDPR customer data platform — chosen to produce organic domain nominations
(SA/DE will likely nominate security or legal). Falls back to [[TEST_BATON:security]]
sentinel if no organic nomination fires.
Usage: python verify_c2_live.py
"""
import sys, json, time, http.client, urllib.request, asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv()

BASE = "http://127.0.0.1:8000"

# GDPR problem designed to produce organic nominations.
# [[TEST_BATON:security]] acts as a sentinel: if no expert nominates organically
# on turn 0, supervisor injects last_nomination="security" at first dispatch.
# (This sentinel is distinct from [[TEST_ESCALATION]] — it is removed once organic
# nominations are reliably produced by the GDPR problem.)
PROBLEM = (
    "[[TEST_BATON:security]] "   # belt-and-suspenders: injects nomination if organic one doesn't fire
    "Build a GDPR-compliant customer data platform for an EU e-commerce company. "
    "5 million customer records. Need: real-time event streaming, PII encryption "
    "at rest + in transit, audit logs, data subject access requests, right-to-erasure. "
    "AWS infrastructure. No existing data platform. Budget: $8k/month."
)

Q_ANS  = "12-person eng team, cloud-native, AWS experience, 18-month roadmap."
FR_ANS = "AWS preferred, 12 engineers, GDPR compliance mandatory, $8k/month hard cap, greenfield."


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
    print("Phase C.2 live session — baton-pass recruitment test")
    print("══════════════════════════════════════════════════\n")

    token = post("/api/auth/login", {"email": "phase0test@test.com", "password": "Test1234!"})["access_token"]
    sid   = post("/api/sessions", {"problem_statement": PROBLEM, "depth_tier": "shallow"}, token)["session_id"]
    print(f"Session: {sid}")

    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=700)
    conn.request("GET", f"/api/sessions/{sid}/stream?token={token}",
                 headers={"Accept": "text/event-stream"})
    resp = conn.getresponse()

    q_idx = 0
    Q = ["12 engineers, AWS expertise.", "Cloud-native, 18-month roadmap.",
         "$8k/month hard cap.", "Greenfield — no existing platform."]

    gate = {
        "nomination_fired":   False,
        "nomination_domain":  None,
        "gate_band":          None,
        "recruited":          False,
        "recruited_role":     None,
        "recruited_spoke":    False,
        "escalation_fired":   False,
        "escalation_domain":  None,
        "solution_produced":  False,
        "expert_messages":    [],
        "decisions_logged":   [],
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

                elif et == "domain_nominated":
                    gate["nomination_fired"]  = True
                    gate["nomination_domain"] = ev.get("domain")
                    print(f"\n  *** BATON-PASS: {ev.get('role')!r} nominated domain={ev.get('domain')!r} ***")

                elif et == "expert_recruited":
                    gate["recruited"]      = True
                    gate["recruited_role"] = ev.get("role")
                    gate["gate_band"]      = ev.get("band") or "confident"
                    print(
                        f"  *** RECRUITED: {ev.get('display_name')} ({ev.get('role')}) "
                        f"domain={ev.get('domain')!r} score={ev.get('score',0):.2f} ***"
                    )

                elif et == "escalation_required":
                    gate["escalation_fired"]  = True
                    gate["escalation_domain"] = gate["nomination_domain"]
                    gate["gate_band"]         = "borderline"
                    print(f"  *** BORDERLINE ESCALATION: {ev.get('summary','')[:60]} ***")
                    time.sleep(0.5)
                    post(f"/api/sessions/{sid}/respond", {"answer": "seat"}, token)

                elif et == "escalation_resolved":
                    gate["recruited"] = True  # will be updated by expert_recruited
                    print(f"  [escalation_resolved] chosen={ev.get('chosen_option_id')!r}")

                elif et == "message" and not ev.get("is_private"):
                    role = ev.get("role", "?")
                    c = ev.get("content", "").encode("ascii","replace").decode()[:55]
                    tag = " [RECRUITED]" if (gate["recruited"] and role == gate["recruited_role"]) else "          "
                    print(f"  [msg{tag}] {role}: {c}")
                    gate["expert_messages"].append(role)
                    if gate["recruited"] and role == gate["recruited_role"]:
                        gate["recruited_spoke"] = True

                elif et == "decision":
                    if ev.get("provenance") == "moderator":
                        t = ev.get("text","")[:70].encode("ascii","replace").decode()
                        gate["decisions_logged"].append(ev.get("text",""))
                        print(f"  [DECISION/moderator] {t!r}")

                elif et == "reviewer_complete":
                    print(f"  [reviewer] passed={ev.get('verdict_passed')} retry={ev.get('retry_count',0)}")

                elif et == "cleanup_complete":
                    print(f"  [cleanup] turns={ev.get('turns_taken')}")

                elif et == "synthesizing":
                    print("  [synthesizing]")

                elif et == "session_complete":
                    doc = ev.get("solution_document") or {}
                    gate["solution_produced"] = bool(doc)
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
        cp   = AsyncPostgresSaver(conn=pool)
        snap = await cp.aget({"configurable": {"thread_id": sid}})
        if snap:
            cv = snap.get("channel_values", {})
            print(f"  last_nomination:            {cv.get('last_nomination')}")
            print(f"  recruitment_pending_domain: {cv.get('recruitment_pending_domain')}")
            print(f"  roster:                     {cv.get('roster')}")
            mods = [d for d in cv.get("decisions", []) if d.get("provenance") == "moderator"]
            print(f"  moderator decisions:        {len(mods)}")
            for d in mods:
                print(f"    → {d.get('text','')[:90]!r}")
            cps = cv.get("custom_personas", [])
            recruited = [p for p in cps if p.get("role","").endswith("_specialist")]
            print(f"  recruited personas:         {[p['role'] for p in recruited]}")
            sol = cv.get("solution_document")
            print(f"  sol_doc:                    {'EXISTS' if sol else 'NONE'}")
        else:
            print("  (no checkpoint found)")
        await pool.close()

    asyncio.run(check_cp())

    # ── Gate results ──────────────────────────────────────────────────────────
    print("\n── C2 Gate Results ──")
    g1 = gate["nomination_fired"]
    g2 = gate["recruited"] or gate["escalation_fired"]
    g3 = gate["gate_band"] is not None
    g4 = (gate["recruited"] and (gate["gate_band"] == "confident" or gate["escalation_fired"]))
    g5 = gate["recruited_spoke"] or gate["escalation_fired"]
    g6 = len(gate["decisions_logged"]) > 0
    g7 = gate["solution_produced"]

    print(f"  nomination_fired:      {'PASS' if g1 else 'FAIL'}  domain={gate['nomination_domain']!r}")
    print(f"  gate ran + banded:     {'PASS' if g3 else 'FAIL'}  band={gate['gate_band']!r}")
    print(f"  recruit/escalation:    {'PASS' if g4 else 'FAIL'}  recruited={gate['recruited']}  role={gate['recruited_role']!r}")
    print(f"  recruited expert spoke:{'PASS' if g5 else 'FAIL/NA'}")
    print(f"  seat logged to ledger: {'PASS' if g6 else 'FAIL'}  entries={len(gate['decisions_logged'])}")
    print(f"  solution produced:     {'PASS' if g7 else 'FAIL'}")

    all_passed = g1 and g3 and g7
    print(f"\n  C2 result: {'*** CORE PASS ***' if all_passed else 'incomplete'}")
    return all_passed, gate


if __name__ == "__main__":
    ok, _ = run()
    sys.exit(0 if ok else 1)
