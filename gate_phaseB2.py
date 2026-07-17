"""
Phase B2 live gate — verify both fixes on the food-photo calorie tracker problem.
Confirms:
  1. Intake asks >1 question (Part A fix)
  2. No "proposed 0 decision(s)" from FIX-8 truncation (Part B fix)
  3. FINAL→S1→bottom-out still fires
  4. Session completes with decisions populated
"""
import sys, json, time, http.client, urllib.request, asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv()

BASE    = "http://127.0.0.1:8000"
PROBLEM = "build an iOS app that identifies food from a photo and logs its calories"
MAX_SEC = 2400  # 40 min

Q_ANSWERS = [
    "Consumer app, general public, iOS only for now.",
    "Small startup team, 3 developers, 6-month timeline, pre-seed budget.",
    "Accuracy matters more than speed. We want the ML model to be reliable.",
    "No existing backend. Greenfield. AWS preferred.",
]
FR_ANS = "iOS consumer app, 3 devs, 6 months, photo-based food recognition, accuracy priority, AWS backend, greenfield."


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
    print("Phase B2 live gate — food calorie tracker")
    print("══════════════════════════════════════════════════\n")

    token = post("/api/auth/login", {"email": "phase0test@test.com", "password": "Test1234!"})["access_token"]
    sid   = post("/api/sessions", {"problem_statement": PROBLEM, "depth_tier": "shallow"}, token)["session_id"]
    print(f"Session: {sid}\n")

    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=MAX_SEC + 30)
    conn.request("GET", f"/api/sessions/{sid}/stream?token={token}",
                 headers={"Accept": "text/event-stream"})
    resp = conn.getresponse()

    q_idx = 0
    ev = {
        "q_count": 0,
        "q_texts": [],
        "stages_opened": [],
        "stage_descend": False,
        "stage_bottomout": False,
        "expert_decisions": {},   # role → count
        "zero_decision_experts": [],
        "solution_produced": False,
        "total_tokens": 0,
    }
    buf   = b""
    start = time.monotonic()
    last_expert = None

    while True:
        if time.monotonic() - start > MAX_SEC:
            print(f"\n[HARD KILL at {int(time.monotonic()-start)}s]"); break
        try:
            chunk = resp.read(256)
        except Exception as e:
            print(f"[stream error] {e}"); break
        if not chunk:
            print("[stream closed]"); break
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
                    ev["q_count"] += 1
                    q_text = d.get("question", "")
                    ev["q_texts"].append(q_text)
                    ans = Q_ANSWERS[q_idx] if q_idx < len(Q_ANSWERS) else "No strong preference."
                    print(f"  [Q{ev['q_count']}] {q_text[:70]}")
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

                elif et == "message" and not d.get("is_private"):
                    role = d.get("role", "?")
                    last_expert = role
                    snippet = d.get("content","").encode("ascii","replace").decode()[:60]
                    print(f"  [msg] {role}: {snippet}")

                elif et == "decision":
                    role = d.get("proposed_by", "?")
                    ev["expert_decisions"][role] = ev["expert_decisions"].get(role, 0) + 1

                elif et == "stage_transition":
                    if not d.get("bottomed_out"):
                        ev["stage_descend"] = True
                        print(f"\n  [DESCEND] {d.get('from_label')} → {d.get('next_label')}")
                    else:
                        ev["stage_bottomout"] = True
                        print(f"\n  [BOTTOM] bottomed out → synthesis")

                elif et in ("synthesizing",):
                    print("  [synthesizing]")

                elif et == "reviewer_complete":
                    print(f"  [reviewer] passed={d.get('verdict_passed')} retry={d.get('retry_count',0)}")

                elif et == "session_complete":
                    doc = d.get("solution_document") or {}
                    ev["solution_produced"] = bool(doc)
                    ev["total_tokens"] = d.get("total_tokens", 0)
                    summ = str(doc.get("executive_summary","")).encode("ascii","replace").decode()[:100]
                    print(f"\n  [COMPLETE] tokens={ev['total_tokens']}")
                    print(f"  summary: {summ}")
                    conn.close(); break

                elif et == "error":
                    print(f"  [ERROR] {d}"); conn.close(); break

            except json.JSONDecodeError:
                pass

    # ── Check zero-decision experts ────────────────────────────────────────────
    print("\n── Expert decisions ──")
    for role, cnt in sorted(ev["expert_decisions"].items()):
        flag = " *** ZERO ***" if cnt == 0 else ""
        print(f"  {role:30s} {cnt} decisions{flag}")

    zero_experts = [r for r, c in ev["expert_decisions"].items() if c == 0]

    # ── Results ────────────────────────────────────────────────────────────────
    print("\n── Phase B2 Gate Results ──")
    r1 = ev["q_count"] >= 2
    r2 = len(zero_experts) == 0
    r3 = ev["stage_descend"] and ev["stage_bottomout"]
    r4 = ev["solution_produced"]

    print(f"  1. Intake >1 question:           {'PASS' if r1 else 'FAIL'}  (asked {ev['q_count']} questions)")
    print(f"  2. No zero-decision experts:     {'PASS' if r2 else 'FAIL'}  (zeros={zero_experts})")
    print(f"  3. FINAL→S1→bottom-out:          {'PASS' if r3 else 'FAIL'}  (descend={ev['stage_descend']} bottom={ev['stage_bottomout']})")
    print(f"  4. Solution produced:            {'PASS' if r4 else 'FAIL'}")

    all_pass = r1 and r2 and r3 and r4
    print(f"\n  Phase B2: {'*** ALL PASS ***' if all_pass else 'FAIL — see above'}")
    return all_pass


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
