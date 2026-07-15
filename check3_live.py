"""
check3_live.py — Check 2: confirm D-o-C + tripwire mechanisms run in a live session.

Confirms from SSE + checkpoint:
  - doc_complete fired (each expert committed or objected; round logged to trail)
  - tripwire_verdict fired with a verdict
  - If tripwire fired: escalation_required via C1 with probe/accept options, ruling routed
  - If tripwire passed: stage closed normally to reviewer

Either outcome is fine — we're confirming the mechanism runs and routes, not forcing a verdict.
Early-exit once tripwire_verdict or escalation_required observed. Kill at ~15 min.
"""
import sys, json, time, http.client, urllib.request, asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv()

BASE = "http://127.0.0.1:8000"

PROBLEM = (
    "Build a fintech payments platform handling credit cards and bank transfers. "
    "Stripe-based processing, AWS infrastructure, 20k transactions/day, "
    "8-person engineering team, 6-month delivery. No AI/ML required."
)
Q_ANS   = "8 engineers, AWS, cloud-native stack, 6-month deadline, no PCI self-hosting."
FR_ANS  = "AWS preferred, Stripe for processing, 20k txns/day, 8 engineers, greenfield."


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
    print("Check 3 / Check 2 — D-o-C + tripwire live run")
    print("══════════════════════════════════════════════════\n")

    token = post("/api/auth/login", {"email": "phase0test@test.com", "password": "Test1234!"})["access_token"]
    sid   = post("/api/sessions", {"problem_statement": PROBLEM, "depth_tier": "shallow"}, token)["session_id"]
    print(f"Session: {sid}")

    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=900)
    conn.request("GET", f"/api/sessions/{sid}/stream?token={token}",
                 headers={"Accept": "text/event-stream"})
    resp = conn.getresponse()

    q_idx = 0
    Q = ["3 developers, FastAPI, PostgreSQL.", "8-week deadline.", "No compliance requirements.", "Greenfield."]

    ev = {
        "doc_fired":            False,
        "doc_commits":          [],
        "doc_objectors":        [],
        "tripwire_fired":       False,
        "tripwire_examined":    None,
        "tripwire_rationale":   "",
        "escalation_fired":     False,
        "escalation_reason":    "",
        "escalation_resolved":  False,
        "reviewer_fired":       False,
        "solution_produced":    False,
        "messages":             [],
    }
    buf = b""

    start_t = time.time()
    MAX_SECS = 1800  # 30 min hard ceiling (D-o-C adds extra API calls)

    while True:
        if time.time() - start_t > MAX_SECS:
            print(f"  [TIMEOUT {MAX_SECS}s reached — stopping]")
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
                    print(f"  [framing] {len(d.get('questions', []))} Qs")
                    time.sleep(0.3)
                    post(f"/api/sessions/{sid}/respond", {"answer": FR_ANS}, token)

                elif et == "roster_selected":
                    print(f"  [roster] {d.get('roster')}")

                elif et == "message" and not d.get("is_private"):
                    role = d.get("role", "?")
                    c    = d.get("content", "").encode("ascii", "replace").decode()[:60]
                    print(f"  [msg] {role}: {c}")
                    ev["messages"].append({"role": role, "content": d.get("content", "")})

                elif et == "doc_complete":
                    ev["doc_fired"]    = True
                    ev["doc_commits"]  = d.get("commits", [])
                    ev["doc_objectors"] = d.get("objectors", [])
                    print(
                        f"\n  *** doc_complete: all_committed={d.get('all_committed')} "
                        f"commits={d.get('commits')} objectors={d.get('objectors')} ***"
                    )

                elif et == "tripwire_verdict":
                    ev["tripwire_fired"]    = True
                    ev["tripwire_examined"] = d.get("examined")
                    ev["tripwire_rationale"] = d.get("rationale", "")
                    print(
                        f"\n  *** tripwire_verdict: examined={d.get('examined')} — "
                        f"{d.get('rationale','')[:80]} ***"
                    )
                    if d.get("examined"):
                        # Healthy consensus — C3 gate closed normally; capture and exit
                        print("  [EARLY EXIT: tripwire fired healthy verdict — capturing trace]")
                        conn.close(); break

                elif et == "escalation_required":
                    ev["escalation_fired"]  = True
                    ev["escalation_reason"] = d.get("reason", "")
                    print(
                        f"\n  *** escalation_required: reason={d.get('reason')!r} "
                        f"summary={d.get('summary','')[:60]} ***"
                    )
                    if d.get("reason") == "tripwire":
                        # Auto-choose "probe" to confirm routing works
                        time.sleep(0.5)
                        post(f"/api/sessions/{sid}/respond", {"answer": "probe"}, token)
                        print("  [auto-responded: probe]")
                        print("  [EARLY EXIT: tripwire escalation captured — closing stream]")
                        conn.close(); break

                elif et == "escalation_resolved":
                    ev["escalation_resolved"] = True
                    print(f"  [escalation_resolved] option={d.get('chosen_option_id')!r}")

                elif et == "reviewer_complete":
                    ev["reviewer_fired"] = True
                    print(f"  [reviewer] passed={d.get('verdict_passed')} retry={d.get('retry_count',0)}")

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

    # ── DB trace ──────────────────────────────────────────────────────────────
    time.sleep(3)
    print("\n── Checkpoint + DB trace ──")
    async def check_cp():
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
        cp = AsyncPostgresSaver(conn=pool)
        snap = await cp.aget({"configurable": {"thread_id": sid}})
        if snap:
            cv = snap.get("channel_values", {})
            print(f"  turn_count:           {cv.get('turn_count')}")
            print(f"  termination_reason:   {cv.get('termination_reason')}")
            mods = [d for d in (cv.get("decisions") or []) if d.get("provenance") == "moderator"]
            print(f"  moderator decisions:  {len(mods)}")
            for d in mods:
                print(f"    → {d.get('text','')[:100]!r}")
        else:
            print("  No checkpoint found")

        conn2 = await psycopg.AsyncConnection.connect(settings.postgres_conn_string, autocommit=True)
        rows  = await (await conn2.execute(
            "SELECT text, provenance FROM decisions WHERE session_id = %s AND provenance = 'moderator' ORDER BY created_at",
            (sid,),
        )).fetchall()
        await conn2.close()
        print(f"\n  decisions TABLE moderator rows: {len(rows)}")
        for r in rows:
            print(f"    [{r[1]}] {r[0][:100]!r}")
        await pool.close()

    asyncio.run(check_cp())

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n── Check 3 / Check 2 Results ──")
    r1 = ev["doc_fired"]
    r2 = ev["tripwire_fired"]
    r3 = (
        # Either: tripwire healthy → no escalation (normal close)
        (ev["tripwire_examined"] is True and not ev["escalation_fired"])
        # Or: tripwire suspicious → escalation fired with reason=tripwire
        or (ev["tripwire_examined"] is False and ev["escalation_fired"] and ev["escalation_reason"] == "tripwire")
    )

    print(f"  doc_complete fired:              {'PASS' if r1 else 'FAIL'}  commits={ev['doc_commits']} objectors={ev['doc_objectors']}")
    print(f"  tripwire_verdict fired:          {'PASS' if r2 else 'FAIL'}  examined={ev['tripwire_examined']!r}")
    print(f"  routing correct for verdict:     {'PASS' if r3 else 'FAIL'}  escalation_fired={ev['escalation_fired']} reason={ev['escalation_reason']!r}")

    all_pass = all([r1, r2, r3])
    print(f"\n  Check 2 result: {'*** ALL PASS ***' if all_pass else 'FAIL — see above'}")
    return all_pass


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
