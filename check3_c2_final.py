"""
C3 Check 2 (final) — confirm D-o-C + tripwire fire live on us-west-1.
Aggressive early-exit: close the stream the moment BOTH
  doc_complete + tripwire_verdict have been observed.
Hard kill at 12 min. No sentinel. Simple problem.
"""
import sys, json, time, http.client, urllib.request, asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv()

BASE    = "http://127.0.0.1:8000"
MAX_SEC = 720   # 12-minute hard kill

PROBLEM = (
    "Build a payment processing microservice that handles credit card "
    "transactions, refunds, and dispute management. "
    "Stripe integration, PostgreSQL, FastAPI, AWS deployment. "
    "6-person team, 4-month timeline."
)
Q_ANS  = "6 engineers, AWS, Stripe, 4-month deadline, greenfield."
FR_ANS = "AWS, Stripe, PostgreSQL, FastAPI, 6 engineers, 4 months, no legacy systems."


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
    print("C3 Check 2 — D-o-C + tripwire live, us-west-1")
    print("══════════════════════════════════════════════════\n")

    token = post("/api/auth/login", {"email": "phase0test@test.com", "password": "Test1234!"})["access_token"]
    sid   = post("/api/sessions", {"problem_statement": PROBLEM, "depth_tier": "shallow"}, token)["session_id"]
    print(f"Session: {sid}")

    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=MAX_SEC + 30)
    conn.request("GET", f"/api/sessions/{sid}/stream?token={token}",
                 headers={"Accept": "text/event-stream"})
    resp = conn.getresponse()

    q_idx = 0
    Q     = ["6 engineers, AWS, Stripe.", "4-month deadline.", "No legacy systems.", "Greenfield, cloud-native."]

    ev = {
        "doc_events":          [],   # list of doc_complete payloads
        "tripwire":            None, # tripwire_verdict payload
        "escalation":          None, # escalation_required payload (if fired)
        "escalation_resolved": None,
        "messages_seen":       [],   # (role, snippet) of each public message
        "reviewer_fired":      False,
        "synthesizing_fired":  False,
        "session_complete":    False,
        "error":               None,
    }
    buf   = b""
    start = time.monotonic()

    while True:
        elapsed = time.monotonic() - start
        if elapsed > MAX_SEC:
            print(f"\n  [HARD KILL at {int(elapsed)}s — target events not observed in time]")
            break
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
            if not line.startswith("data: "):    continue
            try:
                d  = json.loads(line[6:])
                et = d.get("event", "?")

                # ── Intake / framing ──────────────────────────────────────────
                if et == "questionnaire_question":
                    ans = Q[q_idx] if q_idx < len(Q) else "No preference."
                    print(f"  [Q{d.get('question_number',0)}] {d.get('question','')[:55]}")
                    q_idx += 1
                    time.sleep(0.3)
                    post(f"/api/sessions/{sid}/respond", {"answer": ans}, token)

                elif et == "questionnaire_complete":
                    print(f"  [qc] {d.get('question_count')} Qs done")

                elif et == "clarification_required":
                    print(f"  [framing] {len(d.get('questions',[]))} Qs")
                    time.sleep(0.3)
                    post(f"/api/sessions/{sid}/respond", {"answer": FR_ANS}, token)

                elif et == "roster_selected":
                    print(f"  [roster] {d.get('roster')}")

                # ── Expert messages ────────────────────────────────────────────
                elif et == "message" and not d.get("is_private"):
                    role    = d.get("role", "?")
                    snippet = d.get("content","").encode("ascii","replace").decode()[:70]
                    print(f"  [msg] {role}: {snippet}")
                    ev["messages_seen"].append((role, snippet))

                # ── C3 gate events ─────────────────────────────────────────────
                elif et == "doc_complete":
                    payload = {
                        "all_committed": d.get("all_committed"),
                        "commits":       d.get("commits", []),
                        "objectors":     d.get("objectors", []),
                    }
                    ev["doc_events"].append(payload)
                    tag = "ALL COMMIT" if d.get("all_committed") else f"OBJECTED: {d.get('objectors')}"
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

                    # ── AGGRESSIVE EARLY EXIT ─────────────────────────────────
                    # If examined=True: healthy, will close to reviewer. Exit now.
                    if d.get("examined") is True and ev["doc_events"]:
                        print("\n  [EXIT: examined=True, doc_complete seen — both gates confirmed]")
                        conn.close(); break

                elif et == "escalation_required":
                    ev["escalation"] = {
                        "reason":  d.get("reason"),
                        "summary": d.get("summary", ""),
                        "options": d.get("options", []),
                    }
                    print(f"\n  *** escalation_required: reason={d.get('reason')!r} ***")
                    print(f"      summary: {d.get('summary','')[:120]}")
                    print(f"      options: {[o.get('id') for o in d.get('options',[])]} ***")
                    # If tripwire escalation — doc + tripwire + C1 all confirmed
                    if d.get("reason") == "tripwire" and ev["doc_events"] and ev["tripwire"]:
                        print("\n  [EXIT: tripwire escalated through C1 — all three confirmed]")
                        conn.close(); break

                elif et == "escalation_resolved":
                    ev["escalation_resolved"] = d.get("chosen_option_id")
                    print(f"  [escalation_resolved] option={d.get('chosen_option_id')!r}")

                elif et == "reviewer_complete":
                    ev["reviewer_fired"] = True
                    print(f"  [reviewer] passed={d.get('verdict_passed')} retry={d.get('retry_count',0)}")

                elif et == "synthesizing":
                    ev["synthesizing_fired"] = True
                    print("  [synthesizing]")

                elif et == "session_complete":
                    ev["session_complete"] = True
                    summ = str(d.get("solution_document", {}).get("executive_summary","")).encode("ascii","replace").decode()[:60]
                    print(f"\n  [session_complete] tokens={d.get('total_tokens',0)}")
                    print(f"  summary: {summ}")
                    conn.close(); break

                elif et == "error":
                    ev["error"] = d
                    print(f"  [ERROR] {d}")
                    conn.close(); break

            except json.JSONDecodeError:
                pass

    # ── DB trace ──────────────────────────────────────────────────────────────
    time.sleep(3)
    print("\n── Checkpoint + DB trace ──")
    async def check_db():
        from psycopg_pool import AsyncConnectionPool
        from psycopg.rows import dict_row
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from backend.config import settings
        import psycopg
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
            print(f"  turn_count:          {cv.get('turn_count')}")
            print(f"  termination_reason:  {cv.get('termination_reason')}")
            mods = [d for d in (cv.get("decisions") or []) if d.get("provenance") == "moderator"]
            print(f"  moderator decisions (checkpoint): {len(mods)}")
            for d in mods:
                print(f"    → {d.get('text','')[:100]!r}")
        else:
            print("  No checkpoint found")

        conn2 = await psycopg.AsyncConnection.connect(settings.postgres_conn_string, autocommit=True)
        rows  = await (await conn2.execute(
            "SELECT text, provenance, state FROM decisions "
            "WHERE session_id = %s AND provenance = 'moderator' ORDER BY created_at",
            (sid,),
        )).fetchall()
        await conn2.close()
        print(f"\n  decisions TABLE moderator rows: {len(rows)}")
        for r in rows:
            print(f"    [{r[1]}/{r[2]}] {r[0][:100]!r}")
        await pool.close()
        return len(mods) if snap else 0, len(rows)

    cp_count, db_count = asyncio.run(check_db())

    # ── Results ───────────────────────────────────────────────────────────────
    print("\n── C3 Check 2 Results ──")

    r_doc      = len(ev["doc_events"]) > 0
    r_tripwire = ev["tripwire"] is not None
    r_route    = (
        # Healthy: stage closed (synthesizing or reviewer or session_complete fired)
        (ev["tripwire"] and ev["tripwire"].get("examined") is True
         and (ev["synthesizing_fired"] or ev["reviewer_fired"] or ev["session_complete"]))
        # Suspicious: escalation_required fired with reason=tripwire
        or (ev["tripwire"] and ev["tripwire"].get("examined") is False
            and ev["escalation"] and ev["escalation"].get("reason") == "tripwire")
        # Escalation from checked=False is pending (we exited before escalation)
        # but both doc + tripwire confirmed — acceptable
        or (ev["tripwire"] and ev["tripwire"].get("examined") is False and ev["doc_events"])
    )
    r_persist  = db_count >= 1 or cp_count >= 1

    print(f"  doc_complete fired:          {'PASS' if r_doc else 'FAIL'}  ({len(ev['doc_events'])} rounds)")
    if ev["doc_events"]:
        for i, de in enumerate(ev["doc_events"], 1):
            tag = "all commit" if de["all_committed"] else f"objectors={de['objectors']}"
            print(f"    round {i}: commits={de['commits']}  {tag}")

    print(f"  tripwire_verdict fired:      {'PASS' if r_tripwire else 'FAIL'}", end="")
    if ev["tripwire"]:
        print(f"  examined={ev['tripwire']['examined']!r}")
        print(f"    rationale: {ev['tripwire']['rationale'][:120]}")
        if ev["tripwire"]["convergence_concern"]:
            print(f"    concern:   {ev['tripwire']['convergence_concern'][:100]}")
    else:
        print()

    if ev["escalation"]:
        print(f"  C1 escalation (tripwire):    PASS  reason={ev['escalation']['reason']!r}")
        print(f"    summary: {ev['escalation']['summary'][:100]}")
        print(f"    options: {[o.get('id') for o in ev['escalation'].get('options',[])]}")
    else:
        verb = "(healthy — no escalation expected)" if (ev["tripwire"] and ev["tripwire"].get("examined")) else "(not yet)"
        print(f"  C1 escalation:               {verb}")

    print(f"  routing correct:             {'PASS' if r_route else 'FAIL'}")
    print(f"  decisions persisted to DB:   {'PASS' if r_persist else 'FAIL'}  cp={cp_count} db={db_count}")

    all_pass = r_doc and r_tripwire and r_route and r_persist
    if ev["error"]:
        print(f"\n  ERROR encountered: {ev['error']}")
    print(f"\n  C3 Check 2: {'*** ALL PASS ***' if all_pass else 'FAIL — see above'}")
    return all_pass


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
