from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Claude API
    anthropic_api_key: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://user:pass@localhost:5432/consulting_sim"

    @property
    def postgres_conn_string(self) -> str:
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    redis_url: str = "redis://localhost:6379/0"
    chroma_persist_dir: str = "./data/chroma"

    # Auth
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # Session limits
    session_max_turns: int = 12
    session_timeout_seconds: int = 600  # raised from 240 — questionnaire stage adds mandatory pre-framing time
    session_token_budget: int = 150000

    # ── V5-B THE CLOCK: wall-clock time governor ──────────────────────────────
    # The real per-tier budgets live in TIER_CONFIG (600 / 1200 / 1800s). This
    # switch overrides ALL tier budgets with a single value so the wrap can be
    # exercised in ~2 min instead of 10 during a demo/test.
    # TEMP: set to e.g. 120 to test the wrap fast; MUST be None for the real
    # demo (real budgets 600/1200/1800 from TIER_CONFIG).
    clock_demo_override_seconds: int | None = None  # RESET to None (V5-C) — real budgets 600/1200/1800 from TIER_CONFIG
    synthesis_transcript_window: int = 30  # FIX-10: max messages fed to synthesis_node

    # Model IDs — APAC cross-region inference profile ARNs (ap-south-1)
    # These are the canonical IDs; claude_client._resolve_model passes ARNs through directly.
    model_opus:   str = "arn:aws:bedrock:ap-south-1:654654399581:application-inference-profile/xz6f6fgbpcmy"
    model_sonnet: str = "arn:aws:bedrock:ap-south-1:654654399581:application-inference-profile/tvbo89xo0vxp"
    model_haiku:  str = "arn:aws:bedrock:ap-south-1:654654399581:application-inference-profile/mokx0bgyqra7"

    # Uppercase aliases for compatibility (e.g. direct Bedrock verify scripts)
    @property
    def MODEL_OPUS(self) -> str:
        return self.model_opus

    @property
    def MODEL_SONNET(self) -> str:
        return self.model_sonnet

    @property
    def MODEL_HAIKU(self) -> str:
        return self.model_haiku

    # Observability
    logfire_token: str = ""
    environment: str = "development"

    # Memory encryption
    memory_encryption_key: str = ""

    # Clarification loop
    clarification_max_rounds: int = 3
    clarification_answer_timeout_seconds: int = 300

    # TASK-2.2: reverse-engineered questionnaire caps
    questionnaire_max_questions_shallow: int = 4
    questionnaire_max_questions_deep: int = 8
    questionnaire_max_contradiction_branches_deep: int = 3  # research 6.4 cap
    # Minimum questions before the stop classifier is even consulted.
    # Prevents Haiku from returning "enough" after a single sparse Q&A.
    questionnaire_min_questions_shallow: int = 2
    questionnaire_min_questions_deep: int = 3

    # PHASE-A: §7 cap-set — token ledger promoted to first-class; stage/audit
    # caps defined here, enforced in Phase B. Session token budget already exists (Fix #8).
    rounds_per_stage_shallow: int = 3      # expert turns per stage, shallow tier
    rounds_per_stage_deep: int = 6         # expert turns per stage, deep tier
    max_experts_per_stage: int = 5         # seats active in a single stage
    # max_stages_cap is the ACTIVE working limit (starts at 1, raised incrementally toward
    # max_stages_soft_cap). max_stages_soft_cap is the eventual product ceiling (B.3).
    # B.1: cap=1 means the full run is a single Stage FINAL — no descent, no loop.
    # B.3: raise cap toward max_stages_soft_cap as the descent loop is introduced.
    max_stages_cap: int = 2                # PHASE-B.3: raised from 1 — descent now exercised for real. Toward max_stages_soft_cap (6) as later phases prove this out.
    max_stages_soft_cap: int = 6           # eventual product ceiling; enforced in B.3
    max_audit_retries_per_stage: int = 2   # enforced in Phase B

    # FIX-DOC: hard iteration cap on the Disagree-or-Commit loop per stage.
    # On cap-hit the stage force-closes; unresolved objections become "flagged for owner" items.
    doc_round_cap_shallow: int = 3   # D-o-C rounds before force-close, shallow tier
    doc_round_cap_deep: int = 5      # D-o-C rounds before force-close, deep tier

    # PHASE-C.2: relevance gate thresholds for autonomous expert recruitment
    # score >= confident  → seat immediately, no user approval needed
    # score >= borderline (< confident) → escalate through C1 channel ("seat?" / "skip?")
    # score < borderline  → clearly irrelevant, silently ignore the nomination
    recruitment_confident_threshold: float = 0.70
    recruitment_borderline_threshold: float = 0.40
    max_seated_experts: int = 5   # PRD §7: hard cap on concurrently seated experts

    # Bedrock client socket timeout (seconds); applies to both read and connect.
    bedrock_read_timeout_seconds: int = 60

    # Adapter selection: True → ClaudeAdapter (CLI subprocess), False → ApiClaudeAdapter (SDK)
    use_cli: bool = True

    # Demo narration trace — emits human-readable step-by-step log lines to the
    # demo_trace logger (no timestamp/module clutter) and as SSE "trace" events.
    # Set False in production to silence without ripping out the calls.
    demo_trace: bool = True


settings = Settings()

# ── V5-A: Three-tier session config (PRD §3.1 / §4.2) ────────────────────────
# budget_seconds  : wall-clock ceiling for the full session (enforcement in V5-B)
# soft_ratio      : fraction of budget at which supervisor steers toward synthesis
# hard_ratio      : fraction of budget at which synthesis is forced unconditionally
# reserve_seconds : seconds kept in reserve for reviewer + cleanup + synthesis
# rounds_cap      : max expert turns per stage
# default_level_profile : the L-level bundle used for expert calls in this tier
TIER_CONFIG: dict[str, dict] = {
    "shallow": {
        "budget_seconds":        600,
        "soft_ratio":            0.60,
        "hard_ratio":            0.85,
        "reserve_seconds":       90,
        "rounds_cap":            3,
        "default_level_profile": "L1",
    },
    "standard": {
        "budget_seconds":        1200,
        "soft_ratio":            0.60,
        "hard_ratio":            0.85,
        "reserve_seconds":       180,
        "rounds_cap":            4,
        "default_level_profile": "L2",
    },
    "deep": {
        "budget_seconds":        1800,
        "soft_ratio":            0.60,
        "hard_ratio":            0.85,
        "reserve_seconds":       270,
        "rounds_cap":            6,
        "default_level_profile": "L3",
    },
}

# ── V5-A: Level bundles L1 / L2 / L3 (PRD §2.2) ─────────────────────────────
# model           : which model tier drives expert calls at this level
# thinking_budget : extended-thinking token budget (0 = off; wired to adapter in V5-B Part 2)
# max_output_tokens: per-turn token ceiling for expert responses
# turns_per_stage : max expert turns this level contributes per stage (enforcement in V5-B)
# prompt_fragment : key describing the analysis-depth instruction injected per turn (V5-B)
# pushback_posture: challenge intensity instruction keyword used by supervisor / expert prompts
LEVEL_BUNDLES: dict[str, dict] = {
    "L1": {
        "model":              "sonnet",   # L1+L2 both Sonnet; difference is thinking budget + output cap
        "thinking_budget":    0,
        "max_output_tokens":  700,  # raised 450→700 in OPEN-3 fix: JSON envelope + full-depth message needs headroom; still < L2 (800).
        "turns_per_stage":    1,
        "prompt_fragment":    "surface",
        "pushback_posture":   "minimal",
    },
    "L2": {
        "model":              "sonnet",
        "thinking_budget":    3000,
        "max_output_tokens":  800,
        "turns_per_stage":    2,
        "prompt_fragment":    "3-4 levels",
        "pushback_posture":   "moderate",
    },
    "L3": {
        "model":              "opus",
        "thinking_budget":    8000,
        "max_output_tokens":  1200,
        "turns_per_stage":    3,
        "prompt_fragment":    "6-8 levels + must-challenge",
        "pushback_posture":   "strong",
    },
}

# ── Cost estimation: per-million-token USD list prices ───────────────────────
# CONFIRMED 2026-07-24 against platform.claude.com/docs/en/about-claude/pricing
# for the 4.5-tier models this app uses (Opus 4.5 / Sonnet 4.5 / Haiku 4.5).
# NOTE: these are base GLOBAL list prices. The backend calls Bedrock *regional*
# inference profiles, which carry a ~10% premium — not applied here; the Cost
# panel is a development estimate (and CLI token counts omit prompt-cache savings
# that lower real production cost). Re-verify if the models in use change.
MODEL_PRICING: dict[str, dict[str, float]] = {
    "opus":   {"input_per_mtok": 5.0, "output_per_mtok": 25.0},   # Claude Opus 4.5
    "sonnet": {"input_per_mtok": 3.0, "output_per_mtok": 15.0},   # Claude Sonnet 4.5
    "haiku":  {"input_per_mtok": 1.0, "output_per_mtok": 5.0},    # Claude Haiku 4.5
}

# Map any model identifier (Bedrock inference-profile ARN or bare model id) to a
# pricing tier. Explicit ARNs cover current (ap-south-1) + legacy (us-west-1)
# session data; the substring fallback catches bare ids like "claude-opus-4-5".
_MODEL_TIER_BY_ID: dict[str, str] = {
    settings.model_opus:   "opus",
    settings.model_sonnet: "sonnet",
    settings.model_haiku:  "haiku",
    # us-west-1 inference profiles (present in older session records)
    "arn:aws:bedrock:us-west-1:654654399581:application-inference-profile/ejpjsea13wpw": "opus",
    "arn:aws:bedrock:us-west-1:654654399581:application-inference-profile/wxs8vfomtgt9": "sonnet",
    "arn:aws:bedrock:us-west-1:654654399581:application-inference-profile/drf1d6igxbea": "haiku",
}


def model_pricing_tier(model_id: str | None) -> str | None:
    """Resolve a model id/ARN to a pricing tier ('opus'|'sonnet'|'haiku'), or None."""
    if not model_id:
        return None
    if model_id in _MODEL_TIER_BY_ID:
        return _MODEL_TIER_BY_ID[model_id]
    m = model_id.lower()
    if "opus" in m:
        return "opus"
    if "sonnet" in m:
        return "sonnet"
    if "haiku" in m:
        return "haiku"
    return None


def cost_for_tokens(model_id: str | None, input_tokens: int, output_tokens: int) -> float:
    """USD cost for a call: (input/1e6 * in_price) + (output/1e6 * out_price).
    Returns 0.0 for an unknown model (never guesses a tier)."""
    tier = model_pricing_tier(model_id)
    if tier is None:
        return 0.0
    p = MODEL_PRICING[tier]
    return (input_tokens / 1_000_000.0) * p["input_per_mtok"] \
        + (output_tokens / 1_000_000.0) * p["output_per_mtok"]
