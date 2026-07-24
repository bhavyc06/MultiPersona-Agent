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


# ── V5-C: pre-run setup recommendation ──────────────────────────────────────
# Extends the existing Haiku classifier to recommend, for the pre-run setup
# popup, a depth tier AND a per-seat analysis level for each seated expert.
# One lightweight Haiku call. The recommendation is advisory — the user can
# override every value in the setup popup before the run starts.
#
# Tiers  : shallow | standard | deep   (see config.TIER_CONFIG)
# Levels : L1 | L2 | L3                (see config.LEVEL_BUNDLES)

_VALID_TIERS = ("shallow", "standard", "deep")
_VALID_LEVELS = ("L1", "L2", "L3")

_SETUP_SYSTEM = """You are a consulting engagement planner. Given a technical problem and
the roster of expert roles that will work it, recommend how much analytical depth the
engagement needs.

Recommend TWO things:
1. A depth tier for the whole engagement:
   - shallow : simple, well-understood problem; standard patterns; quick pass.
   - standard: multiple systems or moderate uncertainty; established patterns apply.
   - deep    : novel architecture, risky integrations, or high uncertainty.
2. A per-seat analysis level for EACH role in the roster:
   - L1 : surface pass — quick, low-stakes lane for this problem.
   - L2 : moderate depth — a normally-important contributor here.
   - L3 : maximum depth + must-challenge — the crux of THIS problem lives in this role.

Give exactly ONE role L3 only if it is genuinely the crux. Most roles are L1 or L2 on
simple problems. Keep each reason to a single short clause.

Respond with valid JSON only — no markdown, no prose outside the object:
{
  "recommended_tier": "shallow|standard|deep",
  "tier_reason": "one short clause",
  "per_seat_levels": {"role_name": "L1|L2|L3", ...},
  "seat_reasons": {"role_name": "one short clause", ...}
}"""


def _coerce_setup(result: dict, roster: list[str]) -> dict:
    """Validate + normalise a raw setup recommendation against the roster.
    Guarantees every roster role gets a valid level, and the tier is valid."""
    tier = result.get("recommended_tier")
    if tier not in _VALID_TIERS:
        tier = "standard"

    raw_levels = result.get("per_seat_levels") or {}
    raw_reasons = result.get("seat_reasons") or {}
    # Default per-tier level for any role the model omitted or mis-labelled.
    _tier_default = {"shallow": "L1", "standard": "L2", "deep": "L3"}[tier]

    per_seat_levels: dict[str, str] = {}
    seat_reasons: dict[str, str] = {}
    for role in roster:
        lvl = raw_levels.get(role)
        if lvl not in _VALID_LEVELS:
            lvl = _tier_default
        per_seat_levels[role] = lvl
        seat_reasons[role] = str(raw_reasons.get(role) or f"default {lvl} for {tier} tier")

    return {
        "recommended_tier": tier,
        "tier_reason": str(result.get("tier_reason") or f"defaulted to {tier}"),
        "per_seat_levels": per_seat_levels,
        "seat_reasons": seat_reasons,
    }


async def recommend_setup(
    problem: str,
    roster: list[str],
    qa_context: str = "",
) -> dict:
    """One Haiku call → recommended depth tier + per-seat level for each seated
    expert, each with a one-line reason. Fails safe to a tier-default mapping so
    it never blocks the setup popup.

    Returns:
        {
          "recommended_tier": "shallow|standard|deep",
          "tier_reason": str,
          "per_seat_levels": {role: "L1|L2|L3"},
          "seat_reasons": {role: str},
        }
    """
    roster = list(roster or [])
    user_prompt = (
        f"Problem:\n{problem}\n\n"
        + (f"Intake context:\n{qa_context}\n\n" if qa_context else "")
        + "Roster (recommend a level for each):\n"
        + "\n".join(f"- {r}" for r in roster)
    )
    try:
        adapter = get_adapter()
        response = await adapter.complete(
            system_prompt=_SETUP_SYSTEM,
            user_prompt=user_prompt,
            model=settings.model_haiku,
            max_tokens=500,
        )
        text = response.text.strip()
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        result = json.loads(text)
        return _coerce_setup(result, roster)
    except Exception:
        # Fail safe — return a sensible standard-tier default for the whole roster.
        return _coerce_setup({}, roster)
