import json
import re

from backend.claude_client import get_adapter
from backend.config import settings

_SYSTEM = """You are a technical problem complexity classifier for a consulting team.

Classify the problem into exactly one tier:
- simple: 2-3 specialists can address it in a single phase. Well-understood domain, standard patterns, no novel integrations.
- standard: Needs 2-3 phases and 4-6 specialists. Multiple systems, but established patterns apply.
- complex: Requires all 4 phases and the full 8-specialist team. Novel architecture, multiple risky integrations, or high uncertainty.

Respond with valid JSON only — no markdown, no explanation, no extra text:
{"complexity": "simple|standard|complex", "reasoning": "one sentence"}"""


async def classify_problem(problem: str) -> dict:
    adapter = get_adapter()
    response = await adapter.complete(
        system_prompt=_SYSTEM,
        user_prompt=f"Classify this technical problem:\n\n{problem}",
        model=settings.model_haiku,
        max_tokens=500,
    )

    text = response.text.strip()
    # Strip markdown code fences if the model wraps the JSON
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)

    try:
        result = json.loads(text)
        if result.get("complexity") not in ("simple", "standard", "complex"):
            result["complexity"] = "standard"
        return result
    except json.JSONDecodeError:
        return {
            "complexity": "standard",
            "reasoning": "Classification failed to produce valid JSON; defaulting to standard.",
        }
