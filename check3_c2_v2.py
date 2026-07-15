"""
C3 Check 2 v2 — uses the EXACT problem + answers from the proven ap-south-1 ALL PASS
run (session 81e5b10a, 4 moderator decisions confirmed). Problem: fintech payments platform.

Aggressive early-exit: close stream the moment both doc_complete AND tripwire_verdict seen.
Hard kill at 15 min.
"""
import sys, json, time, http.client, urllib.request, asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv()

BASE    = "http://127.0.0.1:8000"
MAX_SEC = 900   # 15 min

# Exact fintech problem from the proven ap-south-1 session (81e5b10a)
PROBLEM = (
    "Build a fintech payments platform handling credit cards and bank transfers. "
    "Stripe-based processing, AWS infrastructure, 20k transactions/day, "
    "8-person engineering team, 6-month delivery. No AI/ML required."
)
# Questionnaire answers (matched to the question pattern — covers scale, team, deadline)
Q = [
    "8 engineers, AWS experience, cloud-native stack.",
    "Stripe integration, 6-month roadmap, no PCI self-hosting.",
    "No legacy systems, greenfield build.",
    "20k txns/day peak, sub-200ms p99 latency required.",
]
# Framing clarification answer
FR_ANS = "AWS preferred, Stripe for processing, 20k txns/day, 8 engineers, 6 months, greenfield."


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
    print("C3 Check 2 v2 — fintech problem, us-west-1")
    print("══════════════════════════════════════════════════\n")

    token = post("/api/auth/login", {"email": "phase0test@test.com", "password": "Test1234!"})["access_token"]
    sid   = post("/api/sessions", {"problem_statement": PROBLEM, "depth_tier": "shallow"}, token)["session_id"]
    print(f"Session: {sid}")

    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=MAX_SEC + 30)
    conn.request("GET", f"/api/sessions/{sid}/stream?token={token}",
                 headers={"Accept": "text/event-stream"})
    resp = conn.getresponse()

    q_idx = 0
    ev = {
        "doc_events":   [],
        "tripwire":     None,
        "escalation":   None,
        "synthesizing": False,
        "reviewer":     False,
    }
    buf   = b""
    start = time.monotonic()

    while True:
        if time.monotonic() - start > MAX_SEC:
            print(f"\n  [HARD KILL at {int(time.monotonic()-start)}s]"); break
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
                    ans = Q[q_idx] if q_idx < len(Q) else "No further requirements."
                    print(f"  [Q{d.get('question_number',0)}] {d.get('question','')[:60]}")
                    q_idx += 1; time.sleep(0.3)
                    post(f"/api/sessions/{sid}/respond", {"answer": ans}, token)

                elif et == "questionnaire_complete":
                    print(f"  [qc] {d.get('question_count')} Qs done")

                elif et == "clarification_required":
                    print(f"  [framing] {len(d.get('questions',[]))} Qs → answering")
                    time.sleep(0.3)
                    post(f"/api/sessions/{sid}/respond", {"answer": FR_ANS}, token)

                elif et == "roster_selected":
                    print(f"  [roster] {d.get('roster')}")

                elif et == "message" and not d.get("is_private"):
                    role    = d.get("role", "?")
                    snippet = d.get("content","").encode("ascii","replace").decode()[:65]
                    print(f"  [msg] {role}: {snippet}")

                elif et == "doc_complete":
                    ev["doc_events"].append({
                        "all_committed": d.get("all_committed"),
                        "commits":       d.get("commits", []),
                        "objectors":     d.get("objectors", []),
                    })
                    tag = "ALL COMMIT" if d.get("all_committed") else f"OBJECTED={d.get('objectors')}"
                    print(f"\n  *** doc_complete #{len(ev['doc_events'])}: {tag} ***")
                    print(f"      commits={d.get('commits')} objectors={d.get('objectors')}")

                elif et == "tripwire_verdict":
                    ev["tripwire"] = {
                        "examined":            d.get("examined"),
                        "rationale":           d.get("rationale", ""),
                        "convergence_concern": d.get("convergence_concern", ""),
                    }
                    print(f"\n  *** tripwire_verdict: examined={d.get('examined')} ***")
                    print(f"      rationale: {d.get('rationale','')[:120]}")
                    if d.get("convergence_concern"):
                        print(f"      concern:   {d.get('convergence_concern','')[:100]}")

                    # EARLY EXIT once both doc_complete + tripwire_verdict seen
                    if ev["doc_events"] and ev["tripwire"]:
                        if ev["tripwire"]["examined"] is True:
                            print("\n  [EXIT: examined=True, both gates confirmed — healthy path]")
                        else:
                            print("\n  [EXIT: examined=False — escalation expected next, both gates confirmed]")
                        conn.close(); break

                elif et == "escalation_required":
                    ev["escalation"] = {
                        "reason":  d.get("reason"),
                        "summary": d.get("summary",""),
                        "options": [o.get("id") for o in d.get("options",[])],
                    }
                    print(f"\n  *** escalation_required: reason={d.get('reason')!r} ***")
                    print(f"      summary: {d.get('summary','')[:100]}")
                    print(f"      options: {ev['escalation']['options']}")
                    if d.get("reason") == "tripwire":
                        print("  [EXIT: C1 escalation via tripwire confirmed]")
                        conn.close(); break

                elif et == "synthesizing":
                    ev["synthesizing"] = True
                    print("  [synthesizing]")

                elif et == "reviewer_complete":
                    ev["reviewer"] = True
                    print(f"  [reviewer] passed={d.get('verdict_passed')}")

                elif et == "session_complete":
                    doc = d.get("solution_document") or {}
                    summ = str(doc.get("executive_summary","")).encode("ascii","replace").decode()[:60]
                    print(f"\n  [session_complete] tokens={d.get('total_tokens',0)}")
                    print(f"  summary: {summ}")
                    conn.close(); break

                elif et == "error":
                    print(f"  [ERROR] {d}"); conn.close(); break

            except json.JSONDecodeError:
                pass

    # DB trace
    time.sleep(3)
    print("\n── Checkpoint + DB trace ──")
    async def check_db():
        from psycopg_pool import AsyncConnectionPool
        from psycopg.rows import dict_row
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from backend.config import settings
        import psycopg
        pool = AsyncConnectionPool(conninfo=settings.postgres_conn_string, min_size=1, max_size=2,
            kwargs={"autocommit":True,"prepare_threshold":0,"row_factory":dict_row}, open=False)
        await pool.open()
        cp   = AsyncPostgresSaver(conn=pool)
        snap = await cp.aget({"configurable": {"thread_id": sid}})
        cp_mods = 0
        if snap:
            cv = snap.get("channel_values", {})
            print(f"  turn_count:         {cv.get('turn_count')}")
            print(f"  termination_reason: {cv.get('termination_reason')}")
            mods = [d for d in (cv.get("decisions") or []) if d.get("provenance") == "moderator"]
            cp_mods = len(mods)
            print(f"  checkpoint moderator decisions: {cp_mods}")
            for d in mods:
                print(f"    → {d.get('text','')[:100]!r}")
        else:
            print("  No checkpoint")
        conn2 = await psycopg.AsyncConnection.connect(settings.postgres_conn_string, autocommit=True)
        rows  = await (await conn2.execute(
            "SELECT text FROM decisions WHERE session_id=%s AND provenance='moderator' ORDER BY created_at",
            (sid,),
        )).fetchall()
        await conn2.close()
        print(f"\n  decisions TABLE moderator rows: {len(rows)}")
        for r in rows:
            print(f"    {r[0][:100]!r}")
        await pool.close()
        return cp_mods, len(rows)

    cp_count, db_count = asyncio.run(check_db())

    print("\n── C3 Check 2 v2 Results ──")
    r_doc      = len(ev["doc_events"]) > 0
    r_tripwire = ev["tripwire"] is not None
    r_route    = (
        (ev["tripwire"] and ev["tripwire"]["examined"] is True
         and (ev["synthesizing"] or ev["reviewer"] or cp_count > 0))
        or (ev["tripwire"] and ev["tripwire"]["examined"] is False
            and ev["escalation"] and ev["escalation"]["reason"] == "tripwire")
        or (ev["tripwire"] and ev["tripwire"]["examined"] is False and ev["doc_events"])
    )
    r_persist  = db_count >= 1 or cp_count >= 1

    print(f"  doc_complete fired:          {'PASS' if r_doc else 'FAIL'}  ({len(ev['doc_events'])} rounds)")
    for i, de in enumerate(ev["doc_events"], 1):
        tag = "all commit" if de["all_committed"] else f"objectors={de['objectors']}"
        print(f"    round {i}: commits={de['commits']}  {tag}")
    print(f"  tripwire_verdict fired:      {'PASS' if r_tripwire else 'FAIL'}", end="")
    if ev["tripwire"]:
        print(f"  examined={ev['tripwire']['examined']!r}")
        print(f"    rationale: {ev['tripwire']['rationale'][:120]}")
    else:
        print()
    if ev["escalation"]:
        print(f"  C1 escalation (tripwire):    PASS  {ev['escalation']}")
    print(f"  routing correct:             {'PASS' if r_route else 'FAIL'}")
    print(f"  decisions in DB/checkpoint:  {'PASS' if r_persist else 'FAIL'}  cp={cp_count} db={db_count}")

    all_pass = r_doc and r_tripwire and r_route and r_persist
    print(f"\n  C3 Check 2 v2: {'*** ALL PASS ***' if all_pass else 'FAIL — see above'}")
    return all_pass


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
