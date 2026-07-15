"""
Phase C.2 isolated relevance gate test.
Calls _run_relevance_gate with 3 hand-built orphan nominations and
prints band + score for each. No live session needed.
Usage: python verify_c2_gate.py
"""
import asyncio, sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv()

PROBLEM = (
    "Build a GDPR-compliant customer data platform for an e-commerce company "
    "handling 5 million EU customers. Real-time event streaming, PII encryption, "
    "audit logs, data subject rights (DSAR). AWS infrastructure, 12-person eng team."
)

# Three nominations: one clearly relevant, one borderline, one clearly irrelevant
NOMINATIONS = [
    ("data_privacy_legal",   "EXPECT: confident (GDPR is central to this problem)"),
    ("devops_sre",           "EXPECT: borderline (useful but not the core gap here)"),
    ("interior_design",      "EXPECT: irrelevant (unrelated to engineering problem)"),
]

async def run():
    from backend.claude_client import get_adapter
    from backend.config import settings
    from backend.graph.nodes import _run_relevance_gate

    adapter = get_adapter()
    model   = settings.model_sonnet

    print(f"\nRelevance Gate Test")
    print(f"Problem: {PROBLEM[:80]}...\n")
    print(f"Thresholds: confident>={settings.recruitment_confident_threshold}  "
          f"borderline>={settings.recruitment_borderline_threshold}\n")
    print(f"{'DOMAIN':<26} {'SCORE':>6}  {'BAND':<12}  REASONING")
    print("-" * 90)

    all_ok = True
    for domain, expectation in NOMINATIONS:
        result = await _run_relevance_gate(
            "test-session", domain, PROBLEM, [], adapter, model,
        )
        band    = result["band"]
        score   = result["score"]
        reason  = result["reasoning"][:55]

        # Simple sanity check against expectation keyword
        expected_band = expectation.split("(")[0].lower().strip().split()[-1]
        ok = band == expected_band
        if not ok:
            all_ok = False

        flag = "OK" if ok else "UNEXPECTED"
        print(f"  {domain:<24} {score:>6.2f}  {band:<12}  {reason!r}  [{flag}]")

    print()
    print(f"  Expected bands satisfied: {'YES — all 3 correct' if all_ok else 'NO — check results'}")
    return all_ok


if __name__ == "__main__":
    ok = asyncio.run(run())
    sys.exit(0 if ok else 1)
