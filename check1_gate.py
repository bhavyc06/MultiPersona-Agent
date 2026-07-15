"""
Check 1: isolated relevance gate test.
Calls _run_relevance_gate directly for 3 orphan nominations
against a fintech payments problem.
Expected: distinct bands across the three (relevant ≠ irrelevant ≠ borderline).
"""
import asyncio, sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv()

PROBLEM = (
    "Build a fintech payments app handling credit cards and bank transfers. "
    "PCI DSS compliance required. 50k transactions/day, sub-200ms p99 latency. "
    "AWS infrastructure, 8-person team, 6-month roadmap."
)

NOMINATIONS = [
    ("security",                 "EXPECT confident  — PCI DSS makes security an obvious gap"),
    ("underwater_basket_weaving","EXPECT irrelevant — absurd, unrelated to fintech"),
    ("devops",                   "EXPECT borderline — useful but not core for early MVP"),
]


async def run():
    from backend.claude_client import get_adapter
    from backend.config import settings
    from backend.graph.nodes import _run_relevance_gate

    adapter = get_adapter()
    model   = settings.model_sonnet

    print(f"\nCheck 1 — Relevance Gate (fintech payments problem)")
    print(f"Confident threshold >= {settings.recruitment_confident_threshold}")
    print(f"Borderline threshold >= {settings.recruitment_borderline_threshold}")
    print(f"Problem: {PROBLEM[:80]}...\n")
    print(f"{'DOMAIN':<30} {'SCORE':>6}  {'BAND':<12}  REASONING")
    print("-" * 95)

    bands_seen = set()
    results = []
    for domain, expectation in NOMINATIONS:
        r = await _run_relevance_gate(
            "check1", domain, PROBLEM, [],  # empty brief_stack
            adapter, model,
        )
        bands_seen.add(r["band"])
        results.append((domain, r["band"], r["score"], r["reasoning"]))
        print(f"  {domain:<28} {r['score']:>6.2f}  {r['band']:<12}  {r['reasoning'][:55]!r}")
        print(f"  {'':28}       {'':12}  ({expectation})")
        print()

    calibrated = len(bands_seen) >= 2  # at minimum two different bands
    print(f"Bands seen: {sorted(bands_seen)}")
    print(f"Gate calibration: {'PASS — at least 2 distinct bands' if calibrated else 'FAIL — all nominations land in the same band (degenerate)'}")
    return calibrated, results


if __name__ == "__main__":
    ok, results = asyncio.run(run())
    sys.exit(0 if ok else 1)
