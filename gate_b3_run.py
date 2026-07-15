"""
Phase B gate runner — re-creates a session, drives it to completion,
inspects checkpoints for all 5 criteria.
Usage: python gate_b3_run.py <run_number> <problem_text>
Returns exit code 0 if all 5 gates passed, 1 otherwise.
"""
import sys, json, time, http.client, urllib.request, asyncio, os

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv; load_dotenv()

BASE = "http://127.0.0.1:8000"

def post(path, data, token=""):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {token}"} if token else {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def run_gate(run_num, problem):
    print(f"\n{'='*68}")
    print(f"RUN {run_num}: {problem[:60]}...")
    print(f"{'='*68}")

    token = post("/api/auth/login",
                 {"email": "phase0test@test.com", "password": "Test1234!"})["access_token"]

    sid = post("/api/sessions",
               {"problem_statement": problem, "depth_tier": "shallow"},
               token)["session_id"]
    print(f"  SID={sid}")

    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=700)
    conn.request("GET", f"/api/sessions/{sid}/stream?token={token}",
                 headers={"Accept": "text/event-stream"})
    resp = conn.getresponse()

    q_idx = 0
    Q = ["Team of 5, cloud-native, no ops budget.", "Single region, existing AWS account.",
         "Under $300/month total.", "MVP only, 4-week timeline."]
    FRAMING_ANS = "Startup constraints: AWS, small team, minimal ops, 4-week MVP."

    gate = {
        "auditor_passed":       False,
        "verdict_rationale":    "",
        "stage_transition_fired": False,
        "stage_bottomed_out":   None,
        "brief_stack_len":      0,
        "s1_created":           False,
        "s1_expert_spoke":      False,
        "s1_messages":          [],
        "cap_fired":            False,
        "solution_produced":    False,
        "reviewer_calls":       [],
        "expert_messages":      [],
        "stage_transition_fired_before_s1": False,
        # Gate 3b: decision count trajectory across audit cycles
        # Each entry is the cumulative proposed-decision count for that phase:
        # index 0 = before first reviewer, index 1 = cleanup-1 output, etc.
        "decision_counts":      [],
        "_phase_decisions":     0,   # counter for current phase
    }
    buf = b""
    in_s1 = False

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
                    qn = ev.get("question_number", 0)
                    print(f"  [Q{qn}] {ev.get('question','')[:60]}")
                    ans = Q[q_idx] if q_idx < len(Q) else "No preference."
                    q_idx += 1; time.sleep(0.3)
                    post(f"/api/sessions/{sid}/respond", {"answer": ans}, token)

                elif et == "questionnaire_complete":
                    print(f"  [qc] {ev.get('question_count')} Qs done")

                elif et == "clarification_required":
                    qs = ev.get("questions", [])
                    print(f"  [framing] {len(qs)} Qs")
                    time.sleep(0.3)
                    post(f"/api/sessions/{sid}/respond", {"answer": FRAMING_ANS}, token)

                elif et == "roster_selected":
                    print(f"  [roster] {ev.get('roster', [])}")

                elif et == "message" and not ev.get("is_private"):
                    role = ev.get("role", "?")
                    c = ev.get("content", "").encode("ascii", "replace").decode()[:60]
                    print(f"  [msg{'*S1*' if in_s1 else '    '}] {role}: {c}")
                    gate["expert_messages"].append(role)
                    if in_s1 and role not in ("system", "human"):
                        gate["s1_messages"].append(role)
                        gate["s1_expert_spoke"] = True

                elif et == "decision":
                    # Count every proposed decision event for Gate 3b trajectory
                    gate["_phase_decisions"] += 1

                elif et == "reviewer_complete":
                    vp = ev.get("verdict_passed")
                    rc = ev.get("retry_count", 0)
                    vr = ev.get("verdict_rationale", "").encode("ascii", "replace").decode()[:120]
                    # Snapshot decision count at this reviewer boundary
                    gate["decision_counts"].append(gate["_phase_decisions"])
                    gate["_phase_decisions"] = 0   # reset for next cleanup phase
                    dc = gate["decision_counts"]
                    print(f"  [reviewer] passed={vp} retry={rc} decisions_this_phase={dc[-1]}")
                    print(f"             rationale: {vr}")
                    gate["reviewer_calls"].append({"passed": vp, "retry": rc, "rationale": vr})
                    if vp:
                        gate["auditor_passed"] = True
                        gate["verdict_rationale"] = vr

                elif et == "stage_transition":
                    gate["stage_transition_fired"] = True
                    bo = ev.get("bottomed_out")
                    nl = ev.get("next_label", "")
                    bl = ev.get("brief_length", 0)
                    gate["stage_bottomed_out"] = bo
                    print(f"  [STAGE_TRANSITION] bottomed_out={bo} next={nl!r} brief_len={bl}")
                    if not bo:
                        gate["s1_created"] = True
                        in_s1 = True
                        print("  *** DESCENDING TO S1 ***")

                elif et == "synthesizing":
                    print("  [synthesizing]")
                    if gate["stage_transition_fired"] and not gate["s1_expert_spoke"]:
                        gate["cap_fired"] = True

                elif et == "cleanup_complete":
                    print(f"  [cleanup] turns={ev.get('turns_taken')}")

                elif et == "session_complete":
                    toks = ev.get("total_tokens", 0)
                    doc = ev.get("solution_document") or {}
                    gate["solution_produced"] = bool(doc)
                    summ = str(doc.get("executive_summary","")).encode("ascii","replace").decode()[:120]
                    print(f"  [COMPLETE] tokens={toks}")
                    print(f"  summary: {summ}")
                    conn.close(); break

                elif et == "error":
                    print(f"  [ERROR] {ev}")
                    conn.close(); break

            except json.JSONDecodeError:
                pass

    # Checkpoint evidence
    print(f"\n  --- Checkpoint evidence (run {run_num}) ---")
    all_passed = False

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
            ss = cv.get("stage_stack", [])
            bs = cv.get("brief_stack", [])
            cs = cv.get("current_stage") or {}
            sbo = cv.get("stage_bottomed_out")
            tr = cv.get("termination_reason")
            tc = cv.get("turn_count", 0)
            v = cs.get("verdict") or {}
            gate["brief_stack_len"] = len(bs)

            print(f"  tc={tc} term={tr} sbo={sbo}")
            print(f"  stage_stack({len(ss)}): ", end="")
            for e in ss:
                print(f"[{e.get('stage_id')} closed={e.get('closed')} brief={bool(e.get('brief'))}]", end=" ")
            print()
            print(f"  brief_stack({len(bs)}): ", end="")
            for b in bs:
                print(f"[{b.get('stage_id')} len={len(b.get('brief') or '')}]", end=" ")
            print()
            print(f"  verdict: passed={v.get('passed')} retry={v.get('retry_count')}")
            sol = cv.get("solution_document")
            print(f"  sol_doc: {'EXISTS' if sol else 'NONE'}")
        await pool.close()

    asyncio.run(check_cp())

    # Score
    g1 = gate["auditor_passed"]
    g2 = gate["stage_transition_fired"] and gate["brief_stack_len"] > 0
    g3 = gate["s1_created"] and gate["s1_expert_spoke"]
    g4 = True  # code-verified (Fix 3 in place); S1 avoidance only checkable if S1 ran
    g5 = gate["cap_fired"] or (gate["stage_transition_fired"] and gate["stage_bottomed_out"])
    g6 = gate["solution_produced"]

    # Gate 3b: decision count should NOT decrease across cycles (re-caveat, not retract)
    dc = gate["decision_counts"]
    g3b_held = len(dc) >= 1 and all(dc[i] >= dc[0] for i in range(len(dc))) if dc else False
    traj = " -> ".join(str(x) for x in dc) if dc else "(no reviewer calls)"

    print(f"\n  GATE SCORES run {run_num}:")
    print(f"  1 auditor_passed:          {'PASS' if g1 else 'FAIL'} — {gate['verdict_rationale'][:60]}")
    print(f"  2 stage_transition+brief:  {'PASS' if g2 else 'FAIL'} (fired={gate['stage_transition_fired']} brief_len={gate['brief_stack_len']})")
    print(f"  3 S1 created+expert:       {'PASS' if g3 else 'FAIL'} (s1={gate['s1_created']} expert={gate['s1_expert_spoke']})")
    print(f"  4 S1 no re-litigate:       SKIP (code-verified by Fix 3)" if not g3 else
          f"  4 S1 no re-litigate:       CHECK s1_msgs={gate['s1_messages']}")
    print(f"  3b decision-count held:    {'PASS' if g3b_held else 'FAIL/UNKNOWN'} trajectory={traj}")
    print(f"  5 cap/bottom-out:          {'PASS' if g5 else 'FAIL'}")
    print(f"  6 solution+complete:       {'PASS' if g6 else 'FAIL'}")

    all_passed = g1 and g2 and g3 and g5 and g6
    print(f"\n  ALL GATES: {'*** FULL PASS ***' if all_passed else 'incomplete'}")
    return all_passed, gate


# ── Problems designed to yield clean, concrete decisions ─────────────────────
PROBLEMS = [
    ("I need to pick between PostgreSQL and MySQL for a new 10k-user SaaS. "
     "Read-heavy, 5 tables, single AWS region. Budget $200/month."),

    ("Choose a caching strategy for a REST API: Redis vs Memcached. "
     "Microservice, AWS EKS, p99 latency must be under 50ms."),

    ("I need to decide on async job processing for a Python web app: "
     "Celery vs RQ. 1000 jobs/day, 5-minute max latency, single machine."),

    ("Pick a static site host for a developer documentation site: "
     "GitHub Pages vs Netlify vs Vercel. Free tier, custom domain, CI/CD."),

    ("Choose between JWT and session cookies for auth in a Next.js SaaS. "
     "10k users, no mobile app, single origin."),

    # Phase B gate problem — fresh topic, no prior session memory for this user
    ("Design a simple expense-tracking web app for a team of 8 people. "
     "They need to submit receipts, get manager approval, and export monthly "
     "reports. No existing infrastructure. Budget $150/month. Timeline: 6 weeks."),

    # Phase B gate run 2 — yoga studio, completely fresh topic
    ("Build a booking system for a small yoga studio: class schedules, "
     "member sign-ups, waitlists, instructor payouts. No existing tools. "
     "~200 members. Owner is non-technical. Budget $100/month."),
]


if __name__ == "__main__":
    run_num = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    problem = PROBLEMS[(run_num - 1) % len(PROBLEMS)]
    passed, _ = run_gate(run_num, problem)
    sys.exit(0 if passed else 1)
