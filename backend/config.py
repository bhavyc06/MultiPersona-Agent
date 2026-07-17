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

    # Adapter selection: True → ClaudeAdapter (CLI subprocess), False → ApiClaudeAdapter (SDK)
    use_cli: bool = True

    # Demo narration trace — emits human-readable step-by-step log lines to the
    # demo_trace logger (no timestamp/module clutter) and as SSE "trace" events.
    # Set False in production to silence without ripping out the calls.
    demo_trace: bool = True


settings = Settings()
