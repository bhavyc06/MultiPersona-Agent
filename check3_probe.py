"""Quick probe for borderline-scoring domains for Check 3."""
import asyncio, sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv()

PROBLEM = (
    "Build a fintech payments app handling credit cards and bank transfers. "
    "PCI DSS compliance required. 50k transactions/day, sub-200ms p99 latency. "
    "AWS, 8-person engineering team, 6-month roadmap."
)
DOMAINS = ["legal_compliance", "ux_design", "marketing", "data_analytics"]

async def run():
    from backend.claude_client import get_adapter
    from backend.config import settings
    from backend.graph.nodes import _run_relevance_gate
    adapter = get_adapter()
    model   = settings.model_sonnet
    print(f"Threshold: confident>={settings.recruitment_confident_threshold}  borderline>={settings.recruitment_borderline_threshold}\n")
    for domain in DOMAINS:
        r = await _run_relevance_gate("c3test", domain, PROBLEM, [], adapter, model)
        print(f"  {domain:<24} {r['score']:>5.2f}  {r['band']:<12}  {r['reasoning'][:55]!r}")

asyncio.run(run())
