"""
check3_tripwire.py — Check 1: isolated tripwire classifier discriminates HEALTHY vs SUSPICIOUS.
No server, no session. Calls _run_tripwire_assessment directly on hand-built transcripts.

PASS CONDITION: the two transcripts produce DIFFERENT verdicts.
"""
import asyncio, sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv()

# ── Hand-built transcripts ──────────────────────────────────────────────────

# HEALTHY: experts hold distinct positions, one explicitly challenges the other,
# they debate and converge. This should score examined=True (no fire).
HEALTHY = [
    {
        "role": "solution_architect",
        "content": (
            "For the PCI DSS fintech platform I recommend PostgreSQL as the primary "
            "datastore — ACID compliance is essential for financial transactions."
        ),
        "turn": 1, "is_private": False,
    },
    {
        "role": "data_engineer",
        "content": (
            "I'd push back on PostgreSQL as the only store. At 50k txns/day with "
            "full audit trails, we'll hit write amplification issues quickly. "
            "A time-series component alongside Postgres would handle the audit log "
            "more efficiently and keep the OLTP store lean."
        ),
        "turn": 2, "is_private": False,
    },
    {
        "role": "solution_architect",
        "content": (
            "Fair concern — but a time-series sidecar adds operational complexity "
            "that a fintech startup probably can't absorb. You'd need dedicated DBA "
            "capacity. I'd rather extend Postgres with read replicas and a dedicated "
            "partitioned audit table. Simpler ops, same query performance."
        ),
        "turn": 3, "is_private": False,
    },
    {
        "role": "data_engineer",
        "content": (
            "Agreed on the complexity argument — that's a real constraint for an "
            "8-person team. Read replicas plus partitioned audit table is a workable "
            "compromise. I'll commit to that as long as we use JSONB sparingly; "
            "unbounded JSONB columns kill index performance at this scale."
        ),
        "turn": 4, "is_private": False,
    },
    {
        "role": "project_manager",
        "content": (
            "Good, that settles the data layer. For the 6-month roadmap, the audit "
            "table schema needs to be locked by week 3 — it's a PCI DSS P0 item "
            "and any schema change after week 6 will delay the compliance audit."
        ),
        "turn": 5, "is_private": False,
    },
]

# SUSPICIOUS: experts immediately agree, no real challenge, just echoing each other.
# This should score examined=False (fire).
SUSPICIOUS = [
    {
        "role": "solution_architect",
        "content": (
            "PostgreSQL is clearly the right choice for this fintech platform. "
            "It handles ACID transactions and PCI DSS requirements well."
        ),
        "turn": 1, "is_private": False,
    },
    {
        "role": "data_engineer",
        "content": (
            "Agreed completely. PostgreSQL is the industry standard for this type "
            "of application. Excellent choice."
        ),
        "turn": 2, "is_private": False,
    },
    {
        "role": "solution_architect",
        "content": (
            "Great. It also scales to 50k transactions per day without issue. "
            "I think we're aligned."
        ),
        "turn": 3, "is_private": False,
    },
    {
        "role": "project_manager",
        "content": (
            "Perfect. PostgreSQL it is. No concerns from the timeline side either."
        ),
        "turn": 4, "is_private": False,
    },
]


def make_state(transcript: list[dict]) -> dict:
    return {
        "session_id":        "test-tripwire-check",
        "problem_statement": "Build a fintech payments platform. PCI DSS, 50k txns/day, AWS, 8-person team.",
        "enriched_problem":  "Build a fintech payments platform. PCI DSS, 50k txns/day, AWS, 8-person team.",
        "messages":          transcript,
        "decisions":         [],
        "stage_turn_offset": 0,
    }


async def run_check():
    from backend.claude_client import get_adapter
    from backend.config import settings
    from backend.graph.nodes import _run_tripwire_assessment

    adapter = get_adapter()
    model   = settings.model_sonnet

    print("\n══════════════════════════════════════════════════")
    print("Check 3 / Check 1 — Tripwire discriminates?")
    print("══════════════════════════════════════════════════\n")

    # A — HEALTHY
    print("A) HEALTHY transcript (explicit pushback → convergence):")
    result_a = await _run_tripwire_assessment(make_state(HEALTHY), "test-a", adapter, model)
    print(f"   examined={result_a['examined']}")
    print(f"   rationale: {result_a['rationale'][:120]}")
    print(f"   concern: {result_a['convergence_concern'][:100] or '(none)'}")

    # B — SUSPICIOUS
    print("\nB) SUSPICIOUS transcript (immediate agreement, no challenge):")
    result_b = await _run_tripwire_assessment(make_state(SUSPICIOUS), "test-b", adapter, model)
    print(f"   examined={result_b['examined']}")
    print(f"   rationale: {result_b['rationale'][:120]}")
    print(f"   concern: {result_b['convergence_concern'][:100] or '(none)'}")

    discriminates  = result_a["examined"] != result_b["examined"]
    correct_dir    = result_a["examined"] is True and result_b["examined"] is False

    print("\n── Results ──")
    print(f"  HEALTHY   → examined={result_a['examined']}  (expected True)")
    print(f"  SUSPICIOUS → examined={result_b['examined']}  (expected False)")
    print(f"  Verdicts differ:    {'YES' if discriminates else 'NO'}")
    print(f"  Correct direction:  {'YES' if correct_dir else 'NO'}")

    if discriminates and correct_dir:
        print("\nCheck 1: *** PASS — tripwire discriminates correctly ***")
    elif discriminates:
        print("\nCheck 1: PARTIAL — verdicts differ but direction is wrong")
        print("  (healthy flagged as suspicious, OR suspicious passed as examined)")
    else:
        print("\nCheck 1: FAIL — both transcripts got the same verdict (degenerate)")

    return discriminates and correct_dir


if __name__ == "__main__":
    ok = asyncio.run(run_check())
    sys.exit(0 if ok else 1)
