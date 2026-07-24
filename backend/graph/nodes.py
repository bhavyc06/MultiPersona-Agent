"""
backend/graph/nodes.py — Phase 3: MoE gating, intelligent routing,
consensus detection, rolling summarisation.
"""
import asyncio
import json
import logging
import re
import uuid as uuid_module
from pathlib import Path

from backend.claude_client import get_adapter
from backend.config import LEVEL_BUNDLES, TIER_CONFIG, cost_for_tokens, settings
from backend.demo_trace import dtrace
from backend.graph.contradiction import detect_contradiction
from backend.graph.state import ChatState
from backend.sse.emitter import (
    ESCALATION_REQUIRED,
    HUMAN_INPUT_RECEIVED,
    HUMAN_INPUT_REQUIRED,
    PAUSE_ARMED,
    SESSION_COMPLETE,
    SETUP_APPLIED,
    SETUP_REQUIRED,
    emit,
    emit_message,
    emit_session_status,
)

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

ALL_EXPERTS = [
    "ai_architect",
    "solution_architect",
    "data_engineer",
    "data_scientist",
    "ai_engineer",
    "solution_engineer",
    "ui_builder",
    "project_manager",
]

DEFAULT_ROSTER = [
    "solution_architect",
    "solution_engineer",
    "project_manager",
]

# PHASE-A: static domain-tag mapping used to seed expert_registry and filter
# transcript context in _build_expert_context. Each value is the set of lanes
# this persona owns. Used by domain-scoped context assembly (Step 2).
EXPERT_DOMAIN_TAGS: dict[str, list[str]] = {
    "data_engineer":      ["data_pipeline", "ingestion", "storage", "schemas"],
    "data_scientist":     ["analysis", "modeling", "experimentation", "evaluation"],
    "solution_engineer":  ["implementation", "integration", "build_mechanics"],
    "solution_architect": ["system_design", "architecture", "patterns", "scalability"],
    "ai_architect":       ["ai_strategy", "model_selection", "mlops", "ai_governance"],
    "ai_engineer":        ["llm_integration", "inference", "rag", "agent_build"],
    "ui_builder":         ["frontend", "ui", "ux", "mockups"],
    "project_manager":    ["timeline", "sequencing", "risk", "scope"],
}

# ── Phase 8: per-session side-channel flags checked by supervisor_node ────────
# Keyed by session_id (str). Set by /pause and /finalize endpoints.
# supervisor_node checks at entry — works whether graph is running or paused.
_pause_requests: set[str] = set()
_finalize_requests: set[str] = set()
# _steer_pending mirrors ask_human_node's _ask_human_questions pattern:
# tracks sessions between the first run (pause flag consumed, interrupt raises)
# and the second run (LangGraph replay, interrupt returns the steering text).
_steer_pending: dict[str, bool] = {}
# _escalation_pending: same two-phase pattern — set in Phase 1 (escalation armed),
# cleared in Phase 2 (after interrupt returns the user's choice).
_escalation_pending: dict[str, bool] = {}
# PHASE-C.3: _doc_started and _tripwire_probe_count removed — now in graph state
# (doc_committed_this_stage: bool, tripwire_probe_count: int) so they survive
# the interrupt/replay cycle and supervisor re-entries without cross-session risk.
# Tracks sessions whose roster has been announced to the frontend via SSE.
# Prevents double-emission when both roster_selection_node AND supervisor_node
# could fire roster_selected (roster_selection_node sets the flag; supervisor_node
# fires only when the roster was pre-set and roster_selection_node was skipped).
_roster_announced: set[str] = set()

# ── V5-C: pre-run setup popup (bench approval) two-phase interrupt state ───────
# Same pattern as _framing_questions / _escalation_pending: roster_selection_node
# runs an LLM roster call + a Haiku setup-recommendation call, then interrupt()s
# for the user's approval. LangGraph replays the node from the top on resume, so
# the roster + recommendation are cached here on the first run and reused on the
# second (post-resume) run — the LLM calls fire exactly once per session.
#   _setup_pending : sessions armed and awaiting the user's setup approval.
#   _setup_cache   : {session_id: {"roster": [...], "recommendation": {...}}}
_setup_pending: set[str] = set()
_setup_cache: dict[str, dict] = {}

# ── Per-session cost / token accumulator ──────────────────────────────────────
# Populated by _record_usage() after every adapter.complete() call.
# Keyed by session_id; cleaned up by synthesis_node after SESSION_COMPLETE emit.
_session_cost: dict[str, dict] = {}

# ── Per-session output token budget accumulator (FIX-8) ───────────────────────
# Tracks total output tokens per session. Checked by supervisor_node before
# dispatching the next expert. Cleaned up by _persist_status in sessions.py
# when session reaches COMPLETED or FAILED.
# FIX-8: deep fix (native max_tokens) deferred to Bedrock migration in claude_client.py
_session_token_totals: dict[str, int] = {}


# ── V5-B THE CLOCK: wall-clock time governor state ────────────────────────────
# All keyed by session_id. Module-level (not ChatState) for the same reason the
# token ledger above is: these are updated OUTSIDE node returns (the pause ledger
# is driven from _run_graph/_resume_graph in sessions.py) and single-process,
# in-memory tracking matches the existing ledger's assumptions.
#
# _session_clock_start  : timestamp of the FIRST expert turn. This is the CLOCK's
#                         zero — NOT session creation. Intake/questionnaire/framing
#                         time does not count. Supersedes the creation-time
#                         session_start_time (FIX-5) for time governance.
# _session_paused_total : accumulated seconds the graph spent paused for user input
#                         (escalation rulings, mid-session ask_human) AFTER the clock
#                         started. Subtracted from elapsed so HITL waits are free.
# _session_pause_started: timestamp the current pause began (absent = graph running).
# _session_soft_nudged  : sessions that already fired the one-time soft nudge.
# _clock_nudge_pending  : sessions whose NEXT expert turn should receive the
#                         time-pressure instruction (consumed once by _run_expert).
_session_clock_start:   dict[str, float] = {}
_session_paused_total:  dict[str, float] = {}
_session_pause_started: dict[str, float] = {}
_session_soft_nudged:   set[str] = set()
_clock_nudge_pending:   set[str] = set()

# Termination reasons that mean "the session physically must stop now" — no new
# stages, no re-audit budget. time_wrap joins the pre-existing hard resource stops.
_CLOCK_HARD_STOPS = {"time_wrap", "timeout", "budget_exceeded"}


def _clock_mark_first_expert_turn(session_id: str) -> None:
    """Start the CLOCK at the first expert turn (idempotent per session)."""
    import time as _t
    if session_id not in _session_clock_start:
        _session_clock_start[session_id] = _t.time()
        # Discard any pauses accumulated BEFORE the clock started (questionnaire /
        # framing waits) — they are irrelevant and would otherwise undercount elapsed.
        _session_paused_total[session_id] = 0.0
        _session_pause_started.pop(session_id, None)
        logger.info(
            "[CLOCK] session_start_time set at first expert turn for %s", session_id
        )


def _clock_pause_begin(session_id: str) -> None:
    """Mark the graph as paused for user input (called when interrupt() fires)."""
    import time as _t
    _session_pause_started[session_id] = _t.time()


def _clock_pause_end(session_id: str) -> None:
    """Close an open pause and add its duration to the ledger (called on resume)."""
    import time as _t
    started = _session_pause_started.pop(session_id, None)
    if started is not None:
        paused = max(0.0, _t.time() - started)
        _session_paused_total[session_id] = (
            _session_paused_total.get(session_id, 0.0) + paused
        )
        logger.info(
            "[CLOCK] pause ledger: +%.0fs (total paused=%.0fs) for %s",
            paused, _session_paused_total[session_id], session_id,
        )


def _elapsed_seconds(state: ChatState) -> float:
    """Active wall-clock seconds since the first expert turn, minus paused time."""
    import time as _t
    session_id = state["session_id"]
    start = _session_clock_start.get(session_id)
    if start is None:
        return 0.0
    paused = _session_paused_total.get(session_id, 0.0)
    # Defensive: if a pause is somehow open right now, count it too.
    if session_id in _session_pause_started:
        paused += max(0.0, _t.time() - _session_pause_started[session_id])
    return max(0.0, _t.time() - start - paused)


def _clock_budget(state: ChatState) -> tuple[float, float, float, float]:
    """Return (budget_seconds, soft_ratio, hard_ratio, reserve_seconds) for the tier.

    The demo override (config.clock_demo_override_seconds) replaces the budget only —
    ratios/reserve still come from TIER_CONFIG.
    """
    tier = state.get("depth_tier", "shallow")
    cfg = TIER_CONFIG.get(tier, TIER_CONFIG["shallow"])
    budget = float(cfg["budget_seconds"])
    if settings.clock_demo_override_seconds is not None:
        budget = float(settings.clock_demo_override_seconds)
    return budget, float(cfg["soft_ratio"]), float(cfg["hard_ratio"]), float(cfg["reserve_seconds"])


def clock_backstop_seconds(depth_tier: str) -> int:
    """Hard asyncio kill-timeout for _run_graph/_resume_graph, scaled to the tier
    budget (+ reserve + grace) so standard/deep sessions aren't killed before they
    naturally wrap. Honors the demo override."""
    cfg = TIER_CONFIG.get(depth_tier, TIER_CONFIG["shallow"])
    budget = (settings.clock_demo_override_seconds
              if settings.clock_demo_override_seconds is not None
              else cfg["budget_seconds"])
    return int(budget) + int(cfg["reserve_seconds"]) + 30


def _clock_cleanup(session_id: str) -> None:
    """Drop all per-session CLOCK state (called at session end)."""
    _session_clock_start.pop(session_id, None)
    _session_paused_total.pop(session_id, None)
    _session_pause_started.pop(session_id, None)
    _session_soft_nudged.discard(session_id)
    _clock_nudge_pending.discard(session_id)


def _record_usage(session_id: str, response, role: str = "") -> None:
    """Accumulate token + cost data from a ClaudeResponse into _session_cost."""
    acc = _session_cost.setdefault(session_id, {
        "total_cost_usd":        0.0,
        "input_tokens":          0,
        "output_tokens":         0,
        "cache_creation_tokens": 0,
        "cache_read_tokens":     0,
        "total_duration_ms":     0,
        "by_model":              {},
    })
    _in  = getattr(response, "input_tokens",  0)
    _out = getattr(response, "output_tokens", 0)
    model_key = getattr(response, "model", None) or "unknown"

    # COST FIX: the CLI/Bedrock path never populated response.cost_usd (→ $0.0000).
    # Compute real cost from the (real) token counts × the per-model price table.
    # Prefer an adapter-reported cost if one is ever provided; else price the tokens.
    _resp_cost = getattr(response, "cost_usd", 0.0) or 0.0
    _call_cost = _resp_cost if _resp_cost > 0 else cost_for_tokens(model_key, _in, _out)

    acc["total_cost_usd"]        += _call_cost
    acc["input_tokens"]          += _in
    acc["output_tokens"]         += _out
    acc["cache_creation_tokens"] += getattr(response, "cache_creation_tokens",  0)
    acc["cache_read_tokens"]     += getattr(response, "cache_read_tokens",      0)
    acc["total_duration_ms"]     += getattr(response, "duration_ms",            0)

    if model_key not in acc["by_model"]:
        acc["by_model"][model_key] = {
            "cost_usd":     0.0,
            "input_tokens":  0,
            "output_tokens": 0,
            "calls":         0,
        }
    bm = acc["by_model"][model_key]
    bm["cost_usd"]     += _call_cost
    bm["input_tokens"]  += _in
    bm["output_tokens"] += _out
    bm["calls"]         += 1

_AGENT_MD_DIR = Path(".claude/agents")

_FRAMING_SYSTEM = (
    "You are a consulting intake specialist. Generate 2-4 specific, "
    "actionable clarifying questions for the given technical problem. "
    "Each question should uncover information that would materially change "
    "the recommended solution. Return JSON only: "
    '{"questions": ["question 1", "question 2", ...]}'
)

# PHASE-B.2 / F5: Stage FINAL goal-pin.
# Detects "solution in disguise" — a stated goal that is actually a
# precursor to a bigger unstated objective. Surfacing to the user is
# Phase C's escalation channel; for now: detected + logged + reflected
# in stage label.
_GOAL_PIN_SYSTEM = """
You are checking whether the user's stated goal is itself a genuine end goal,
or a precursor to a bigger goal they haven't stated (a "solution in disguise").
Example: "I want a Postgres database" is usually a precursor to a real goal like
"I want to track customer orders reliably."

Given the problem statement / brief, answer: is this a complete, standalone goal,
or does it imply a larger unstated objective the user has not articulated?

Return ONLY valid JSON:
{"is_solution_in_disguise": true|false, "implied_larger_goal": "..." or null}
""".strip()

_SYNTHESIS_SYSTEM = (
    "You are the lead consulting architect. Synthesize the expert discussion "
    "into a comprehensive solution document. Be concrete and specific — "
    "reference the actual technologies and decisions from the conversation.\n\n"
    "Return ONLY a valid JSON object with this schema:\n"
    '{"executive_summary": "...", "recommended_architecture": "...", '
    '"key_decisions": ["..."], "implementation_phases": ["..."], '
    '"risks": ["..."], "open_items": ["..."]}'
)

# Turn ceiling raised for group chat (consensus will usually fire earlier)
_TURN_CEILING = 20

# ── Cleanup decision rules (Fix E/F) ──────────────────────────────────────────
# Injected into every cleanup targeted_prompt so the decision-format rules
# travel into user_prompt_override turns, where _build_expert_context is skipped.
# This ensures OWNER-AUTHORITY flagging and proposed_decisions requirements
# are present on the user-prompt side, not just in the system-prompt persona.
_CLEANUP_DECISION_RULES = """
OUTPUT RULES (mandatory — apply these even in a correction turn):
- Respond with ONLY valid JSON: {"message": "...", "reasoning": "...", "proposed_decisions": [...], "open_questions": [...], "needs_human_input": false}
- proposed_decisions REQUIRED: you MUST end this turn with AT LEAST the same decisions you held before, now corrected. Fewer decisions than before is a FAIL.
- FABRICATED CONFIDENCE fix: do NOT remove the decision. Remove the false precision instead. Example — "Lambda costs $40/month (no evidence)" becomes "Use AWS Lambda for compute (best-guess — actual cost requires traffic profiling)". The technology choice stays; the unsupported number goes.
- OWNER-AUTHORITY fix: do NOT remove the decision. Add the [OWNER-AUTHORITY] prefix. Example — "[OWNER-AUTHORITY] Recommend Auth0 over Cognito (best-guess) — requires client budget approval".
- Retracting a decision to escape a finding WILL fail the next audit with "no decisions locked". Keep every decision; correct its framing.
""".strip()


# ── PHASE-C.2: Baton-pass / recruitment helpers ───────────────────────────────

# Domain-lock + best-guess preamble injected into every recruited persona.
# Mirrors the requirements already in the .md persona files but enforces them
# programmatically so they survive any future prompt edits.
_RECRUITED_PERSONA_GUARDRAILS = (
    "DOMAIN LOCK: you are authorised to advise ONLY within your specific domain. "
    "Do not venture beyond it — defer to the appropriate specialist for all else.\n\n"
    "BEST-GUESS FLAGGING (mandatory): if you assert a specific number, deadline, "
    "vendor cost, or technology choice without direct evidence from the problem "
    "brief, you MUST append '(best-guess)' to the claim. Never present an "
    "unsubstantiated figure as settled fact.\n\n"
    "OWNER-AUTHORITY FLAGGING (mandatory): if a decision requires client "
    "sign-off (budget, legal, vendor contract), prefix it with [OWNER-AUTHORITY]."
)


async def _run_relevance_gate(
    session_id: str,
    nominated_domain: str,
    enriched_problem: str,
    brief_stack: list[dict],
    adapter,
    model: str,
) -> dict:
    """
    Score how relevant a nominated domain is to the current stage problem.
    Returns {"band": "confident"|"borderline"|"irrelevant", "score": float, "reasoning": str}
    Fails safe to "irrelevant" on any error.
    """
    brief_text = "\n\n".join(
        f"[{b.get('stage_id')} — {b.get('label')}]: {b.get('brief','')[:200]}"
        for b in brief_stack
    ) if brief_stack else "(no prior stage briefs)"

    prompt = (
        f"You are evaluating whether a domain expert should join a consulting council.\n\n"
        f"Problem being solved:\n{enriched_problem[:400]}\n\n"
        f"Prior stage context:\n{brief_text[:300]}\n\n"
        f"Nominated domain: '{nominated_domain}'\n\n"
        "Score 0.0–1.0: how relevant is THIS domain to the specific problem above? "
        "Would a specialist in ONLY this domain have concrete advice not already "
        "covered by a general technical council?\n"
        f"  >= {settings.recruitment_confident_threshold}: CONFIDENT — obvious specialist gap\n"
        f"  >= {settings.recruitment_borderline_threshold}: BORDERLINE — real but uncertain connection\n"
        f"  <  {settings.recruitment_borderline_threshold}: IRRELEVANT — tangential or unrelated\n\n"
        'Return ONLY valid JSON: {"score": 0.0, "reasoning": "one concise sentence"}'
    )

    try:
        resp = await adapter.complete(
            system_prompt="You are a consulting team composition analyst. Return only valid JSON.",
            user_prompt=prompt,
            model=model,
            max_tokens=120,
        )
        _record_usage(session_id, resp, "relevance_gate")
        data = _parse_json_safe(resp.text, {"score": 0.0, "reasoning": "parse error"})
        score = float(max(0.0, min(1.0, data.get("score", 0.0))))

        if score >= settings.recruitment_confident_threshold:
            band = "confident"
        elif score >= settings.recruitment_borderline_threshold:
            band = "borderline"
        else:
            band = "irrelevant"

        logger.info(
            "[%s] relevance gate: domain=%r score=%.2f band=%s — %s",
            session_id, nominated_domain, score, band,
            data.get("reasoning", "")[:60],
        )
        return {"band": band, "score": score, "reasoning": data.get("reasoning", "")}
    except Exception as exc:
        logger.warning("[%s] relevance gate failed — treating as irrelevant: %s", session_id, exc)
        return {"band": "irrelevant", "score": 0.0, "reasoning": f"gate error: {exc}"}


async def _generate_recruited_persona(
    domain: str,
    session_id: str,
    enriched_problem: str,
    adapter,
    model: str,
) -> dict:
    """
    Generate a domain-locked, guardrail-injected persona for a recruited expert.
    Returns {role, display_name, system_prompt, emoji, color}.
    """
    display_name = domain.replace("_", " ").title() + " Specialist"
    role = domain.lower().replace(" ", "_").replace("-", "_") + "_specialist"

    system_prompt = (
        f"You are the {display_name} in a multi-agent consulting team. "
        f"Your domain is STRICTLY limited to {domain} topics.\n\n"
        f"{_RECRUITED_PERSONA_GUARDRAILS}\n\n"
        "You are participating in a live expert group chat. Read what others have "
        "said, build on their points where relevant to your domain, and challenge "
        "proposals where you see a domain-specific problem.\n\n"
        "You MUST respond with ONLY valid JSON:\n"
        '{"message": "...", "reasoning": "...", "proposed_decisions": [...], '
        '"open_questions": [...], "needs_human_input": false, "next_domain": null}'
    )

    # Haiku call for emoji + colour (cheap, non-critical)
    try:
        meta_resp = await adapter.complete(
            system_prompt='Return ONLY valid JSON: {"emoji": "single emoji", "color": "pastel hex"}',
            user_prompt=(
                f"Persona: {display_name}. "
                "Avoid these colors: #fce7f3 #dbeafe #dcfce7 #fef3c7 #ede9fe #ffedd5 #cffafe #fef9c3"
            ),
            model=settings.model_haiku,
            max_tokens=50,
        )
        _record_usage(session_id, meta_resp, "recruitment_meta")
        meta = _parse_json_safe(meta_resp.text, {"emoji": "🔍", "color": "#e2e8f0"})
    except Exception:
        meta = {"emoji": "🔍", "color": "#e2e8f0"}

    return {
        "role":          role,
        "display_name":  display_name,
        "system_prompt": system_prompt,
        "emoji":         meta.get("emoji", "🔍"),
        "color":         meta.get("color", "#e2e8f0"),
    }


async def _seat_expert(
    domain: str,
    gate_score: float,
    state: ChatState,
    session_id: str,
    adapter,
    model: str,
) -> tuple[dict, str]:
    """
    PHASE-C.2: seat a new expert for `domain`, enforcing the expert cap.
    Returns (state_delta_dict, new_role).
    state_delta includes: roster, custom_personas, expert_registry, decisions.
    Logs the seat (and any retire) to the decision trail.
    """
    registry = list(state.get("expert_registry") or [])
    roster   = list(state.get("roster") or [])
    personas = list(state.get("custom_personas") or [])

    decisions_to_log: list[dict] = []

    # ── Cap enforcement: retire one idle expert if we're at the limit ─────────
    seated_count = sum(
        1 for r in registry if r.get("seated", True) and r["role"] in roster
    )
    if seated_count >= settings.max_seated_experts:
        stage_start = state.get("stage_turn_offset", 0)
        pub = [m for m in state.get("messages", []) if not m.get("is_private")]
        stage_speakers = {m["role"] for m in pub if m.get("turn", 0) >= stage_start}
        # Idle = has spoken in current stage, is NOT project_manager
        idle_role = next(
            (r for r in roster
             if r != "project_manager"
             and r in stage_speakers),
            None,
        )
        if idle_role:
            roster = [r for r in roster if r != idle_role]
            registry = [
                ({**r, "seated": False} if r["role"] == idle_role else r)
                for r in registry
            ]
            import uuid as _uuid_retire
            retire_dec = {
                "id":            str(_uuid_retire.uuid4()),
                "text":          (
                    f"[MODERATOR RETIREMENT] {idle_role} retired to make room "
                    f"for {domain}_specialist (expert cap={settings.max_seated_experts})"
                ),
                "proposed_by":   "moderator",
                "state":         "locked",
                "provenance":    "moderator",
                "supersedes_id": None,
            }
            decisions_to_log.append(retire_dec)
            asyncio.create_task(_persist_decisions_db(session_id, [retire_dec]))
            await emit(session_id, "expert_retired", {
                "role":   idle_role,
                "reason": f"cap enforcement — seating {domain} specialist",
            })
            logger.info("[%s] retired %r to enforce expert cap", session_id, idle_role)

    # ── Generate domain-locked persona ────────────────────────────────────────
    new_persona = await _generate_recruited_persona(
        domain, session_id,
        state.get("enriched_problem") or state.get("problem_statement", ""),
        adapter, model,
    )
    new_role = new_persona["role"]

    # Splice into roster before project_manager
    pm_in_roster     = "project_manager" in roster
    roster_without_pm = [r for r in roster if r != "project_manager"]
    if new_role not in roster_without_pm:
        roster_without_pm.append(new_role)
    new_roster = roster_without_pm + (["project_manager"] if pm_in_roster else [])

    # Level a recruited seat runs at = the current tier's default profile.
    _recruited_level = TIER_CONFIG.get(
        state.get("depth_tier", "shallow"), TIER_CONFIG["shallow"]
    )["default_level_profile"]

    # Extend expert_registry (dedup by role)
    if not any(r["role"] == new_role for r in registry):
        registry = registry + [{
            "role":        new_role,
            "domain_tags": [domain],
            "seated":      True,
            "provenance":  "recruited",
            "level":       _recruited_level,
        }]

    # Merge custom_personas (dedup by role)
    merged_personas = [p for p in personas if p["role"] != new_role]
    merged_personas.append(new_persona)

    # Log the seat to the decision trail
    import uuid as _uuid_seat
    seat_dec = {
        "id":            str(_uuid_seat.uuid4()),
        "text":          (
            f"[MODERATOR SEAT] Recruited {new_persona['display_name']} ({new_role}) "
            f"for domain '{domain}' (relevance_score={gate_score:.2f}). "
            "Domain-lock and best-guess guardrails enforced in persona prompt."
        ),
        "proposed_by":   "moderator",
        "state":         "locked",
        "provenance":    "moderator",
        "supersedes_id": None,
    }
    decisions_to_log.append(seat_dec)
    asyncio.create_task(_persist_decisions_db(session_id, [seat_dec]))
    await emit(session_id, "expert_recruited", {
        "role":         new_role,
        "display_name": new_persona["display_name"],
        "domain":       domain,
        "score":        gate_score,
        "emoji":        new_persona["emoji"],
        "color":        new_persona["color"],
        # V5-D: fields the persona-library save needs. Recruited experts only —
        # core-8 never emit this event, so a save affordance keyed off it is
        # structurally limited to recruited specialists.
        "provenance":         "recruited",
        "default_level":      _recruited_level,
        "domain_lock_prompt": new_persona["system_prompt"],
    })
    logger.info(
        "[%s] seated %r (%s) for domain=%r score=%.2f",
        session_id, new_role, new_persona["display_name"], domain, gate_score,
    )
    dtrace(session_id,
        f"[RECRUIT]   ✓ Seated {new_persona['display_name']} ({new_role}) "
        f"for domain \"{domain}\" (score={gate_score:.2f}) — autonomous"
    )

    state_delta = {
        "roster":          new_roster,
        "expert_registry": registry,
        "custom_personas": merged_personas,
        "decisions":       decisions_to_log,
    }
    return state_delta, new_role


# ── PHASE-C.3: Disagree-or-Commit + Tripwire helpers ─────────────────────────

async def _run_doc_round(
    state: "ChatState",
    session_id: str,
    roster: list[str],
    adapter,
) -> tuple[bool, list[str], list[dict]]:
    """
    Disagree-or-Commit round. Each seated expert is asked once:
    COMMIT (no remaining objection) or OBJECT: <specific reason>.
    A substantive objection (len >= 20) re-opens deliberation.

    Returns (all_committed: bool, objector_roles: list[str], doc_decisions: list[dict]).
    Uses Haiku (bounded decision, not multi-step reasoning).
    """
    import uuid as _uuid_doc
    stage_start = state.get("stage_turn_offset", 0)
    stage_msgs = [
        m for m in state.get("messages", [])
        if not m.get("is_private") and m.get("turn", 0) >= stage_start
    ]
    locked_decs = [d for d in state.get("decisions", []) if d.get("state") == "locked"]

    context = (
        f"Problem: {(state.get('enriched_problem') or state.get('problem_statement', ''))[:300]}\n\n"
        "Stage discussion:\n"
        + "\n".join(f"- {m['role']}: {m['content'][:200]}" for m in stage_msgs[-10:])
        + "\n\nLocked decisions so far:\n"
        + ("\n".join(f"- {d['text'][:150]}" for d in locked_decs[:5]) or "(none yet)")
    )

    objectors: list[str] = []
    commits: list[str] = []

    for role in roster:
        prompt = (
            f"{context}\n\n"
            f"You are the {role.replace('_', ' ').title()}. "
            "The council appears to have reached consensus. "
            "Before this stage closes, you must EXPLICITLY state:\n\n"
            "  COMMIT — I have no remaining substantive objection.\n"
            "  OBJECT: <specific reason> — I raise a substantive new concern that materially changes the advice.\n\n"
            "Minor preferences or stylistic disagreements are NOT substantive. "
            "A substantive objection must name a specific technical risk, conflict, or missing "
            "constraint that would change the recommendation.\n\n"
            'Return ONLY valid JSON: {"stance": "commit"|"object", "reason": "..."}'
        )
        try:
            resp = await adapter.complete(
                system_prompt=(
                    "You are an expert in a consulting council making an explicit commit/object "
                    "declaration. Return ONLY valid JSON."
                ),
                user_prompt=prompt,
                model=settings.model_haiku,
                max_tokens=150,
            )
            _record_usage(session_id, resp, f"doc_{role}")
            data = _parse_json_safe(resp.text, {"stance": "commit", "reason": ""})
            stance = str(data.get("stance", "commit")).strip().lower()
            reason = str(data.get("reason", "")).strip()
            if stance.startswith("object") and len(reason) >= 20:
                objectors.append(role)
                logger.info("[%s] D-o-C: %s OBJECTED — %s", session_id, role, reason[:80])
            else:
                commits.append(role)
                logger.info("[%s] D-o-C: %s committed", session_id, role)
        except Exception as exc:
            logger.warning("[%s] D-o-C call for %s failed — treating as commit: %s", session_id, role, exc)
            commits.append(role)

    all_committed = len(objectors) == 0
    summary = (
        f"COMMITS: {commits}" if all_committed
        else f"COMMITS: {commits} | OBJECTS: {objectors}"
    )
    doc_dec = {
        "id":            str(_uuid_doc.uuid4()),
        "text":          f"[DISAGREE-OR-COMMIT ROUND] {summary}",
        "proposed_by":   "moderator",
        "state":         "locked",
        "provenance":    "moderator",
        "category":      "procedure_log",
        "supersedes_id": None,
    }
    asyncio.create_task(_persist_decisions_db(session_id, [doc_dec]))
    await emit(session_id, "doc_complete", {
        "commits":       commits,
        "objectors":     objectors,
        "all_committed": all_committed,
    })
    return all_committed, objectors, [doc_dec]


async def _run_tripwire_assessment(
    state: "ChatState",
    session_id: str,
    adapter,
    model: str,
) -> dict:
    """
    Tripwire classifier. Assesses whether genuine challenge occurred in the current
    stage's discussion — keyed on SPACE EXPLORED, not time-to-agree.

    Returns {"examined": bool, "rationale": str, "convergence_concern": str}.
    Fails safe to examined=True (healthy) so fast legitimate consensus is not blocked.
    """
    stage_start = state.get("stage_turn_offset", 0)
    stage_msgs = [
        m for m in state.get("messages", [])
        if not m.get("is_private") and m.get("turn", 0) >= stage_start
    ]

    if len(stage_msgs) < 2:
        return {"examined": True, "rationale": "too few messages to assess", "convergence_concern": ""}

    locked_decs = [d for d in state.get("decisions", []) if d.get("state") == "locked"]
    transcript  = "\n".join(f"[{m['role']}]: {m['content'][:300]}" for m in stage_msgs)
    dec_text    = "\n".join(f"- {d['text'][:120]}" for d in locked_decs[:8]) or "(none)"

    prompt = (
        "You are the agreement-bias tripwire. Detect UNEXAMINED consensus — when a "
        "council converged WITHOUT genuine challenge.\n\n"
        "Key criteria (key on SPACE EXPLORED, not speed):\n"
        "- examined=True (HEALTHY): experts held distinct initial positions, someone challenged "
        "  or questioned a claim, there was actual pushback or debate, OR the problem is simple "
        "  and quick agreement is appropriate.\n"
        "- examined=False (SUSPICIOUS): experts immediately agreed, no real critique occurred, "
        "  they echoed the same position without independent analysis, OR agreement happened "
        "  before the option space was explored.\n\n"
        "IMPORTANT: fast agreement is NOT automatically suspicious. A simple question with an "
        "obvious answer should reach consensus quickly. Suspicious means NO ONE raised an "
        "alternative approach, risk, or challenge at any point.\n\n"
        f"Problem: {(state.get('enriched_problem') or state.get('problem_statement', ''))[:300]}\n\n"
        f"Stage discussion:\n{transcript}\n\n"
        f"Locked decisions:\n{dec_text}\n\n"
        "Was there genuine challenge? Did experts hold distinct positions and engage with each "
        "other's claims?\n\n"
        'Return ONLY valid JSON: {"examined": true|false, "rationale": "one sentence", '
        '"convergence_concern": "if suspicious: specific concern; if healthy: empty string"}'
    )

    try:
        resp = await adapter.complete(
            system_prompt=(
                "You are an agreement-bias detector for consulting councils. "
                "Return ONLY valid JSON."
            ),
            user_prompt=prompt,
            model=model,
            max_tokens=200,
        )
        _record_usage(session_id, resp, "tripwire")
        data = _parse_json_safe(resp.text, {"examined": True, "rationale": "parse error", "convergence_concern": ""})
        result = {
            "examined":            bool(data.get("examined", True)),
            "rationale":           str(data.get("rationale", "")),
            "convergence_concern": str(data.get("convergence_concern", "")),
        }
        logger.info(
            "[%s] tripwire: examined=%s — %s",
            session_id, result["examined"], result["rationale"][:80],
        )
        return result
    except Exception as exc:
        logger.warning("[%s] tripwire failed — treating as examined (healthy): %s", session_id, exc)
        return {"examined": True, "rationale": f"error: {exc}", "convergence_concern": ""}


# ── PHASE-C.3: shared D-o-C + Tripwire gate ──────────────────────────────────

async def _run_c3_gate(
    state: "ChatState",
    session_id: str,
    summary_update: dict,
) -> "dict | None":
    """
    Single gate that guards every path reaching _make_synthesis_locks().
    Called from next_speaker=='synthesis' AND the ask_human fallback.
    Never from _check_consensus (that path uses 'converged' provenance and
    is structurally separate — see below).

    Returns:
      - A state-delta dict if the gate intercepted (D-o-C objection re-opens
        deliberation, OR tripwire fired → pending_escalation). Caller must
        return this dict immediately instead of closing.
      - None if the gate passed cleanly. Caller proceeds to _make_synthesis_locks.

    State fields consumed / written (all in graph state, not module-level dicts):
      doc_committed_this_stage: bool  — True once a D-o-C all-commit occurred
      tripwire_probe_count: int       — increments on each tripwire escalation
    Both are cleared by stage_transition_node on descent.
    """
    stage_start   = state.get("stage_turn_offset", 0)
    stage_msgs    = [
        m for m in state.get("messages", [])
        if not m.get("is_private") and m.get("turn", 0) >= stage_start
    ]
    enough        = len(stage_msgs) >= 2
    already_done  = bool(state.get("doc_committed_this_stage", False))
    probe_count   = int(state.get("tripwire_probe_count", 0))
    probe_cap     = settings.max_audit_retries_per_stage
    probe_forced  = probe_count >= probe_cap
    extra: list[dict] = []

    if not enough:
        # Too few stage messages — skip gate, close normally
        logger.info("[%s] C3 gate: not enough stage messages (%d) — skipping", session_id, len(stage_msgs))
        return None

    if already_done:
        # D-o-C committed this stage and tripwire already ran — skip to close
        logger.info("[%s] C3 gate: doc_committed_this_stage=True — skipping to close", session_id)
        return None

    if probe_forced:
        logger.info(
            "[%s] C3 gate: probe cap (%d/%d) hit — force-closing",
            session_id, probe_count, probe_cap,
        )
        return None

    # ── a) Disagree-or-Commit round ─────────────────────────────────────────
    # FIX-DOC: track iteration count; cap at doc_round_cap_shallow/deep to prevent
    # infinite spiral when two experts hold contradictory locked decisions.
    doc_round_count = int(state.get("doc_round_count_this_stage", 0))
    _depth = state.get("depth_tier", "shallow")
    _doc_cap = settings.doc_round_cap_deep if _depth == "deep" else settings.doc_round_cap_shallow

    roster = list(state.get("roster") or DEFAULT_ROSTER)
    dtrace(session_id,
        f"[D-O-C]     ▶ Disagree-or-commit round {doc_round_count + 1}/{_doc_cap} "
        f"({len(roster)} experts)...")
    committed, objectors, doc_decs = await _run_doc_round(
        state, session_id, roster, get_adapter(),
    )
    extra.extend(doc_decs)
    new_doc_count = doc_round_count + 1
    dtrace(session_id, f"[D-O-C]     ✓ commits={[r for r in roster if r not in objectors]}  objectors={objectors}")

    if not committed:
        if new_doc_count >= _doc_cap:
            # Cap hit — force-close; do NOT re-open deliberation, do NOT escalate to user.
            # Record the unresolved disagreement as a flagged open item in the decision trail.
            import uuid as _uuid_unres
            unres_dec = {
                "id":            str(_uuid_unres.uuid4()),
                "text":          (
                    f"[UNRESOLVED] Disagreement not resolved after {new_doc_count} D-o-C rounds "
                    f"(objecting roles: {objectors}). Flagged for owner review."
                ),
                "proposed_by":   "moderator",
                "state":         "locked",
                "provenance":    "moderator",
                "supersedes_id": None,
            }
            asyncio.create_task(_persist_decisions_db(session_id, [unres_dec]))
            dtrace(session_id,
                f"[D-O-C]     ⚠ Cap hit ({new_doc_count}/{_doc_cap}) — "
                f"force-closing; unresolved disagreement flagged for owner")
            logger.warning(
                "[%s] D-o-C cap (%d/%d) — forcing stage close, objectors=%s",
                session_id, new_doc_count, _doc_cap, objectors,
            )
            return {
                "__c3_extra__":              extra + [unres_dec],
                "doc_committed_this_stage":  True,
                "doc_round_count_this_stage": new_doc_count,
            }

        logger.info("[%s] C3 gate: D-o-C objection by %s — re-opening", session_id, objectors)
        next_spk = (
            objectors[0] if objectors and objectors[0] in roster
            else roster[0]
        )
        return {
            **summary_update,
            **({"decisions": extra} if extra else {}),
            "current_speaker":             next_spk,
            "doc_round_count_this_stage":  new_doc_count,
        }

    # ── b) All committed → mark done, run tripwire ─────────────────────────
    dtrace(session_id, "[TRIPWIRE]  ▶ Assessing whether genuine challenge occurred...")
    import uuid as _uuid_tw_g
    tw = await _run_tripwire_assessment(state, session_id, get_adapter(), settings.model_sonnet)
    tw_dec = {
        "id":            str(_uuid_tw_g.uuid4()),
        "text":          f"[TRIPWIRE VERDICT] examined={tw['examined']} — {tw['rationale'][:150]}",
        "proposed_by":   "moderator",
        "state":         "locked",
        "provenance":    "moderator",
        "category":      "procedure_log",
        "supersedes_id": None,
    }
    asyncio.create_task(_persist_decisions_db(session_id, [tw_dec]))
    await emit(session_id, "tripwire_verdict", {
        "examined":            tw["examined"],
        "rationale":           tw["rationale"],
        "convergence_concern": tw["convergence_concern"],
    })
    extra.append(tw_dec)

    # ── c) Suspicious → escalate via C1 ───────────────────────────────────
    if not tw["examined"]:
        new_probe_count = probe_count + 1
        tw_esc = {
            "reason":  "tripwire",
            "summary": (
                f"Council agreed with little challenge: "
                f"{tw['convergence_concern'][:120]}. "
                f"(Probe {new_probe_count}/{probe_cap})"
            ),
            "options": [
                {
                    "id":     "probe",
                    "label":  "Send back for genuine challenge",
                    "impact": "Experts re-examine assumptions and surface real objections",
                },
                {
                    "id":     "accept",
                    "label":  "Accept consensus as-is",
                    "impact": "Close the stage; all experts have committed",
                },
            ],
        }
        logger.info("[%s] C3 gate: tripwire fired (probe %d/%d) — escalating via C1", session_id, new_probe_count, probe_cap)
        dtrace(session_id, f"[TRIPWIRE]  ✓ Verdict: examined=False — \"{tw['rationale'][:80]}\"  ⏸ escalating to user")
        return {
            **summary_update,
            **({"decisions": extra} if extra else {}),
            # Reset doc_committed so D-o-C re-runs after deliberation reopens
            "doc_committed_this_stage": False,
            "tripwire_probe_count":     new_probe_count,
            "pending_escalation":       tw_esc,
        }

    # ── d) Healthy — return extra decisions + doc_committed flag; caller closes ─
    logger.info("[%s] C3 gate: healthy — proceeding to close", session_id)
    dtrace(session_id, f"[TRIPWIRE]  ✓ Verdict: examined=True — \"{tw['rationale'][:80]}\"")
    return {
        "__c3_extra__":            extra,   # sentinel key; caller extracts this
        "doc_committed_this_stage": True,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_persona(role: str) -> str:
    path = _AGENT_MD_DIR / f"{role}.md"
    if path.exists():
        return path.read_text()
    return (
        f"You are the {role.replace('_', ' ').title()} "
        f"in a multi-agent consulting group chat with other specialists. "
        f"Read what others have said, build on their points, and challenge "
        f"proposals where you see a problem.\n\n"
        f"Respond with ONLY valid JSON: "
        f'{{"message": "...", "reasoning": "...", '
        f'"proposed_decisions": [], "open_questions": []}}'
    )


def _get_seat_tags(state: ChatState, role: str) -> set[str]:
    """Look up domain_tags for role from expert_registry. Returns empty set if not found."""
    for seat in state.get("expert_registry", []):
        if seat.get("role") == role:
            return set(seat.get("domain_tags", []))
    return set()


def _tier_default_level(state: ChatState) -> str:
    """Return the default level profile for the current depth_tier."""
    tier = state.get("depth_tier", "shallow")
    return TIER_CONFIG.get(tier, TIER_CONFIG["shallow"])["default_level_profile"]


def _get_seat_level(state: ChatState, role: str) -> str:
    """Look up the level (L1/L2/L3) for role from expert_registry.
    Falls back to the tier's default_level_profile if not set."""
    for seat in state.get("expert_registry", []):
        if seat.get("role") == role:
            return seat.get("level") or _tier_default_level(state)
    return _tier_default_level(state)


def _build_expert_context(state: ChatState, role: str) -> str:
    # PHASE-A: domain-scoped context — expert sees its lane's messages + all
    # locked decisions, not the full transcript. Filtered by domain_tags from
    # expert_registry. (Brief-stack integration comes in Phase B.)
    session_id = state.get("session_id", "?")
    problem = state.get("enriched_problem") or state["problem_statement"]
    lines: list[str] = []

    # PHASE-C.4a: Owner rulings — challengeable-if-irrelevant. Injected BEFORE background summaries.
    # These are decisions the owner locked in prior sessions on a similar problem.
    # Scoped by 0.82 similarity (same lineage guard as memory_context) — unrelated sessions excluded.
    owner_rulings_context = state.get("owner_rulings_context", [])
    if owner_rulings_context:
        lines.append("## Prior Owner Decisions (from your past sessions on a similar problem)")
        lines.append(
            "These are decisions the owner locked in a prior session. "
            "If this session's problem is genuinely the same or a direct continuation, "
            "honor them as strong prior constraints and build on them. "
            "BUT if any listed ruling is clearly irrelevant to the CURRENT problem, "
            "say so explicitly and do NOT apply it — a prior ruling from a different "
            "project is not binding here. Do not silently carry forward a ruling that "
            "does not fit this problem."
        )
        lines.append("")
        for ruling in owner_rulings_context:
            lines.append(ruling)
        lines.append("")

    memory_context = state.get("memory_context", [])
    if memory_context:
        lines.append("## Prior Session Context — BACKGROUND ONLY")
        lines.append(
            "The following are decisions from an earlier project by this user, as background. "
            "They are NOT binding and may not apply. "
            "Treat them as challengeable context. "
            "Only if a past decision is DIRECTLY applicable to the current problem may you choose "
            "to raise it — in your own words, noting it came from prior context. "
            "Do not re-propose past decisions simply because you agree."
        )
        lines.append("")
        for m in memory_context:
            lines.append(f"- {m}")
        lines.append("")

    # PHASE-B.3: prior-stage briefs prepended before current-stage context.
    # This is what lets descended-stage experts build on closed stages.
    brief_stack = state.get("brief_stack", [])
    if brief_stack:
        lines.append("## Prior Stage Summaries (resolved precursor layers)")
        for entry in brief_stack:
            lines.append(f"### {entry.get('label', entry.get('stage_id', '?'))}")
            lines.append(entry.get("brief", "(no brief)"))
            lines.append("")

    lines.append(f"## Problem Statement\n{problem}\n")

    if state.get("rolling_summary"):
        lines += ["## Prior Discussion Summary", state["rolling_summary"], ""]

    pub = [m for m in state.get("messages", []) if not m.get("is_private", False)]

    # ── Domain-scoped transcript filtering ────────────────────────────────────
    my_tags = _get_seat_tags(state, role)
    if my_tags and pub:
        # Keep: own prior messages + messages from domain-adjacent experts.
        # A message is domain-adjacent if the sender's tags overlap ours.
        filtered = [
            m for m in pub
            if m.get("role") == role                          # own messages
            or (_get_seat_tags(state, m.get("role", "")) & my_tags)  # domain overlap
        ]
        # Fallback: if no relevant messages yet (first speaker or isolated domain),
        # include last 3 public messages so the expert isn't starved.
        context_msgs = filtered if filtered else pub[-3:]
        context_msgs = context_msgs[-10:]  # hard cap regardless
    else:
        # No registry / no tags: safe fallback to existing full-context behavior
        context_msgs = pub[-10:]

    logger.info(
        "[%s] %s context: %d domain-relevant messages (of %d total public)",
        session_id, role, len(context_msgs), len(pub),
    )

    if context_msgs:
        lines.append("## Recent Expert Discussion")
        for m in context_msgs:
            lines.append(f"**{m['role']} (turn {m.get('turn', 0)})**: {m['content']}")
        lines.append("")

    # Locked decisions are NEVER filtered — every expert sees all shared ground truth
    locked = [d for d in state.get("decisions", []) if d.get("state") == "locked"]
    if locked:
        lines.append("## Locked Decisions (do NOT re-open)")
        for d in locked:
            lines.append(f"- {d['text']}")
        lines.append("")

    if state.get("rag_chunks"):
        lines.append("## Relevant Reference Material")
        for chunk in state["rag_chunks"][:3]:
            lines.append(
                f"[{chunk.get('source', 'KB')}]: "
                f"{chunk.get('content', '')[:300]}"
            )
        lines.append("")

    # V5-A: analysis-depth instruction keyed to this seat's level bundle
    _ctx_level    = _get_seat_level(state, role)
    _ctx_fragment = LEVEL_BUNDLES.get(_ctx_level, LEVEL_BUNDLES["L1"])["prompt_fragment"]
    _depth_instruction = {
        "surface": (
            "State the 2-3 headline considerations in your lane. "
            "Flag risks; don't explore them deeply. Be brief."
        ),
        "3-4 levels": (
            "Reason 3-4 implication levels deep. "
            "Explore the top risk before committing."
        ),
        "6-8 levels + must-challenge": (
            "Reason 6-8 implication levels. "
            "Challenge at least one prior claim. "
            "Before approving, state what would have to be true for you to be satisfied, "
            "and confirm it is."
        ),
    }.get(_ctx_fragment, "Be specific and actionable.")

    lines.append(
        f"As the {role.replace('_', ' ').title()}, respond with ONLY valid JSON — "
        "no prose, no markdown fences, no text before or after the JSON object:\n"
        '{"message": "Your complete expert analysis as a single prose string. '
        f"{_depth_instruction} "
        "Build on or challenge what others have said. "
        'Write at full depth and richness — do NOT shorten it to fit the JSON envelope.", '
        '"reasoning": "Your private chain-of-thought — what you considered and why.", '
        '"proposed_decisions": ["concrete actionable decision string 1", "decision string 2"], '
        '"open_questions": ["specific question directed at a named expert"], '
        '"needs_human_input": false, "next_domain": null}'
    )
    return "\n".join(lines)


def _parse_expert_response(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)

    # ── Path 1: full JSON parse ───────────────────────────────────────────────
    try:
        data = json.loads(text)
        msg = str(data.get("message", "") or "").strip() or text[:800]
        # json.loads already converts \n → real newlines; explicit replace is a no-op
        # but guards against double-escaped strings from some models.
        msg = msg.replace("\\n", "\n")
        # next_domain: normalise to lowercase snake_case or None
        _nd = data.get("next_domain")
        _next_domain = (
            str(_nd).strip().lower().replace(" ", "_").replace("-", "_")
            if _nd and str(_nd).strip() not in ("null", "none", "")
            else None
        )
        return {
            "message":            msg,
            "reasoning":          str(data.get("reasoning", "")),
            "proposed_decisions": list(data.get("proposed_decisions", [])),
            "open_questions":     list(data.get("open_questions", [])),
            "needs_human_input":  bool(data.get("needs_human_input", False)),
            "next_domain":        _next_domain,
        }
    except json.JSONDecodeError:
        pass

    # ── Path 2: regex extraction (handles FIX-8 mid-JSON truncation) ─────────
    # FIX-8 may cut valid JSON at 6 000 chars, leaving {"message":"...(truncated)
    # json.loads then fails and we previously returned raw text with the envelope.
    msg_match = re.search(r'"message"\s*:\s*"((?:[^"\\]|\\.)*)', text)
    if msg_match:
        raw_fragment = msg_match.group(1)
        try:
            # Decode JSON string escapes by re-parsing as a JSON string literal
            msg = json.loads('"' + raw_fragment + '"')
        except json.JSONDecodeError:
            msg = raw_fragment.replace("\\n", "\n").replace('\\"', '"')
        return {
            "message":            msg,
            "reasoning":          "",
            "proposed_decisions": [],
            "open_questions":     [],
            "needs_human_input":  False,
            "next_domain":        None,
        }

    # ── Path 3: plain-text fallback ───────────────────────────────────────────
    return {
        "message":            text[:1000].replace("\\n", "\n"),
        "reasoning":          "",
        "proposed_decisions": [],
        "open_questions":     [],
        "needs_human_input":  False,
        "next_domain":        None,
    }


def _parse_json_safe(text: str, fallback: dict) -> dict:
    text = text.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return fallback


async def _persist_message(
    session_id: str,
    role: str,
    content: str,
    is_private: bool,
    turn: int,
    tokens_used: int = 0,
) -> None:
    try:
        import uuid as _uuid
        from backend.db.postgres import AsyncSessionLocal
        from backend.models import AgentMessage
        async with AsyncSessionLocal() as db:
            msg = AgentMessage(
                session_id=_uuid.UUID(session_id),
                agent_role=role,
                phase=turn,
                content=content,
                is_private=is_private,
                tokens_used=tokens_used,
            )
            db.add(msg)
            await db.commit()
    except Exception as exc:
        logger.warning(f"[{session_id}] agent_messages insert failed: {exc}")


# ── Consensus detection ────────────────────────────────────────────────────────

def _check_consensus(state: ChatState) -> bool:
    """
    Returns True when the group can synthesise now.
    Conditions (all must be true):
      1. Every expert in the selected roster has spoken at least once
         IN THE CURRENT STAGE (turn >= stage_turn_offset — PHASE-B.3 fix to
         prevent Stage S1 from immediately inheriting Stage FINAL's speakers).
      2. No EFFECTIVE (non-superseded) decisions remain in "proposed"
         or "challenged" state.
    """
    roster = state.get("roster") or DEFAULT_ROSTER
    # PHASE-B.3: only count messages from the current stage's turn window
    stage_start = state.get("stage_turn_offset", 0)
    speakers = {
        m["role"]
        for m in state.get("messages", [])
        if not m.get("is_private")
        and m["role"] in roster
        and m.get("turn", 0) >= stage_start
    }
    all_spoke = all(r in speakers for r in roster)

    # Only look at live (non-superseded) decisions
    effective = _get_effective_decisions(state.get("decisions", []))
    no_pending = not any(
        d.get("state") in ("proposed", "challenged")
        for d in effective
    )
    return all_spoke and no_pending


# ── Intelligent supervisor routing ────────────────────────────────────────────

async def _supervisor_route(state: ChatState) -> str:
    """
    Decide who speaks next using a Sonnet call.
    Returns an expert role name, "synthesis", or "ask_human".
    Falls back to the next unheard roster member on error.
    """
    roster = state.get("roster") or DEFAULT_ROSTER
    # Scope to current stage only — stage_turn_offset is set to turn_count
    # at the moment of descent, so S1 sees only messages produced after FINAL.
    # Without this filter, S1 inherits FINAL's speakers and routes to
    # "synthesis" immediately with remaining=[].
    stage_start = state.get("stage_turn_offset", 0)
    pub = [
        m for m in state.get("messages", [])
        if not m.get("is_private") and m.get("turn", 0) >= stage_start
    ]
    last_msgs = pub[-5:]

    # Include custom personas in the effective roster for routing decisions
    custom_personas = state.get("custom_personas", [])
    custom_roles = [p["role"] for p in custom_personas]
    effective_roster = roster + [r for r in custom_roles if r not in roster]

    speakers_so_far = list(dict.fromkeys(
        m["role"] for m in pub if m["role"] in effective_roster
    ))
    remaining = [r for r in effective_roster if r not in speakers_so_far]

    proposed = [d["text"] for d in state.get("decisions", []) if d.get("state") == "proposed"]
    locked_count = sum(1 for d in state.get("decisions", []) if d.get("state") == "locked")

    # Build custom persona description block for the routing LLM
    custom_desc = ""
    if custom_personas:
        custom_desc = "\n\nCustom expert personas (may also be selected as next speaker):\n" + "\n".join([
            f"- {p['role']} ({p['display_name']}): {p['system_prompt'][:120]}..."
            for p in custom_personas
        ])

    prompt = (
        f"You are facilitating an expert consulting group chat.\n\n"
        f"Problem: {(state.get('enriched_problem') or state['problem_statement'])[:300]}\n\n"
        f"Expert roster: {roster}\n"
        f"Already spoken: {speakers_so_far}\n"
        f"Remaining to speak: {remaining}\n\n"
        f"Last messages:\n"
        + "\n".join(f"- {m['role']}: {m['content'][:150]}" for m in last_msgs)
        + f"\n\nProposed decisions (not locked): {proposed[:5]}\n"
        f"Locked decisions: {locked_count}\n"
        f"Open questions: {state.get('open_questions', [])[-3:]}\n"
        f"Turn count: {state['turn_count']}"
        + custom_desc
        + "\n\nRules:\n"
        "- project_manager speaks last, after all technical experts\n"
        "- If an expert raised a specific question another expert should answer, route there\n"
        "- If all roster members have spoken and the problem is well covered, return \"synthesis\"\n"
        "- Custom personas may be selected at any point when their expertise is relevant\n"
        "- If a specific human question arises, return \"ask_human\"\n\n"
        'Respond with ONLY valid JSON: {"next": "expert_role_or_synthesis_or_ask_human", "reason": "one sentence"}'
    )

    adapter = get_adapter()
    try:
        response = await adapter.complete(
            system_prompt="You are a meeting facilitator.",
            user_prompt=prompt,
            model=settings.model_sonnet,
            max_tokens=200,
        )
        _record_usage(state["session_id"], response, "routing")
        data = _parse_json_safe(response.text, {"next": "synthesis"})
        next_speaker = data.get("next", "synthesis")
        reason = data.get("reason", "")
        logger.info(
            f"[{state['session_id']}] supervisor → {next_speaker}: {reason}"
        )
        return next_speaker
    except Exception as exc:
        logger.warning(f"[{state['session_id']}] supervisor routing failed: {exc}")
        # Fallback: next unheard expert, or synthesis
        for r in roster:
            if r not in speakers_so_far:
                return r
        return "synthesis"


# ── Rolling summarisation (Option B — summary only, no message replacement) ───

async def _maybe_summarize(state: ChatState, session_id: str) -> dict:
    """
    If public message count > 15, summarise oldest 10 into rolling_summary.
    Returns {"rolling_summary": "..."} or {} if no action taken.
    Uses Haiku (cheap). Does NOT modify messages (append-only constraint).
    """
    pub = [m for m in state.get("messages", []) if not m.get("is_private")]
    if len(pub) <= 15:
        return {}

    to_summarize = pub[:10]
    text = "\n".join(
        f"{m['role']}: {m['content'][:300]}" for m in to_summarize
    )
    adapter = get_adapter()
    try:
        resp = await adapter.complete(
            system_prompt=(
                "Summarize this expert discussion in 2-3 sentences. "
                "Focus on decisions made and key recommendations. Plain text only."
            ),
            user_prompt=text,
            model=settings.model_haiku,
            max_tokens=200,
        )
        _record_usage(session_id, resp, "summary")
        existing = state.get("rolling_summary", "")
        new_summary = (
            f"{existing}\n{resp.text}".strip() if existing else resp.text
        )
        logger.info(f"[{session_id}] rolled up {len(to_summarize)} messages into summary")
        return {"rolling_summary": new_summary}
    except Exception as exc:
        logger.warning(f"[{session_id}] rolling summary failed: {exc}")
        return {}


# ── Roster selection node ─────────────────────────────────────────────────────

# ── V5-C: setup-popup helpers ─────────────────────────────────────────────────

def _tier_default_level(tier: str) -> str:
    """The default L-level for a tier (shallow→L1, standard→L2, deep→L3)."""
    return TIER_CONFIG.get(tier, TIER_CONFIG["standard"])["default_level_profile"]


def _build_setup_payload(roster: list[str], recommendation: dict, brief: str = "") -> dict:
    """Assemble the full structured payload the pre-run setup popup will render:
    recommended tier + reason, per-seat recommended level + reason, and the
    available override options (tiers, levels)."""
    rec_tier = recommendation.get("recommended_tier", "standard")
    rec_levels = recommendation.get("per_seat_levels", {})
    seat_reasons = recommendation.get("seat_reasons", {})

    seats = []
    for role in roster:
        lvl = rec_levels.get(role) or _tier_default_level(rec_tier)
        seats.append({
            "role":               role,
            "recommended_level":  lvl,
            "reason":             seat_reasons.get(role, ""),
        })

    return {
        "brief":            brief,
        "recommended_tier": rec_tier,
        "tier_reason":      recommendation.get("tier_reason", ""),
        "roster":           [s["role"] for s in seats],
        "seats":            seats,
        # Override options the frontend renders as dropdowns.
        "options": {
            "tiers":  list(TIER_CONFIG.keys()),      # shallow / standard / deep
            "levels": list(LEVEL_BUNDLES.keys()),    # L1 / L2 / L3
        },
        # Per-tier wall-clock budgets (seconds) — the popup ties the tier selector
        # to the clock (shallow 600 / standard 1200 / deep 1800 → 10/20/30 min).
        "tier_budgets": {t: TIER_CONFIG[t]["budget_seconds"] for t in TIER_CONFIG},
        # The response contract the popup (Part 2) sends back via /respond.
        # Omitting a field means "accept the recommendation for it".
        "response_shape": {
            "type":   "setup",
            "tier":   "<one of options.tiers — omit to accept recommended>",
            "levels": {"<role>": "<one of options.levels> — omit any role to keep its recommended level"},
        },
    }


def _resolve_setup_choice(raw, recommendation: dict, roster: list[str]) -> dict:
    """Turn the user's approval payload (from interrupt resume) into a final,
    validated choice. Accepts a JSON string, a dict, or a bare accept string.
    Any field the user omits falls back to the recommendation.

    Returns {"tier", "tier_source", "levels", "levels_source"} where *_source is
    "user_override" or "recommended" (for the audit trail + [SETUP] log line)."""
    valid_tiers = set(TIER_CONFIG.keys())
    valid_levels = set(LEVEL_BUNDLES.keys())

    rec_tier = recommendation.get("recommended_tier", "standard")
    if rec_tier not in valid_tiers:
        rec_tier = "standard"
    rec_levels = recommendation.get("per_seat_levels", {})

    # Normalise the resume value into a dict.
    override = raw
    if isinstance(raw, str):
        s = raw.strip()
        try:
            override = json.loads(s) if s else {}
        except (json.JSONDecodeError, ValueError):
            override = {}
    if not isinstance(override, dict):
        override = {}

    # Tier
    ov_tier = override.get("tier")
    if ov_tier in valid_tiers:
        tier, tier_source = ov_tier, "user_override"
    else:
        tier, tier_source = rec_tier, "recommended"

    # Per-seat levels — recommendation is the base; valid overrides win.
    ov_levels = override.get("levels") or {}
    levels: dict[str, str] = {}
    any_level_override = False
    for role in roster:
        base = rec_levels.get(role)
        if base not in valid_levels:
            base = _tier_default_level(tier)
        v = ov_levels.get(role)
        if v in valid_levels:
            levels[role] = v
            if v != base:
                any_level_override = True
        else:
            levels[role] = base
    levels_source = "user_override" if any_level_override else "recommended"

    return {
        "tier":          tier,
        "tier_source":   tier_source,
        "levels":        levels,
        "levels_source": levels_source,
    }


async def roster_selection_node(state: ChatState) -> dict:
    """
    MoE gating: select which experts this problem genuinely needs, then pause at
    the pre-run SETUP popup (bench approval) so the user can review / override the
    recommended depth tier + per-seat analysis levels before the run starts.

    Two-phase interrupt (mirrors framing_node / escalation): the Sonnet roster
    call + the Haiku setup-recommendation call fire ONCE on the first run and are
    cached in _setup_cache; LangGraph replays the node on resume, at which point
    interrupt() returns the user's approval and the overrides are applied.
    """
    session_id = state["session_id"]
    adapter = get_adapter()

    # ── Phase 1 — first run only: pick roster, recommend setup, arm the popup ──
    if session_id not in _setup_pending:
        prompt = (
            "You are selecting the expert team for a consulting engagement.\n\n"
            f"Problem: {state['enriched_problem']}\n\n"
            "Available experts:\n"
            "- ai_architect: AI/ML strategy, model selection, MLOps\n"
            "- solution_architect: System design, components, patterns\n"
            "- data_engineer: Pipelines, ingestion, storage, schemas\n"
            "- data_scientist: Statistics, modeling, experimentation\n"
            "- ai_engineer: LLM integration, RAG, inference pipelines\n"
            "- solution_engineer: Build feasibility, implementation\n"
            "- ui_builder: Frontend/backend proposals, UI mockups\n"
            "- project_manager: Timeline, sequencing, risk, scope\n\n"
            "Select ONLY the experts genuinely needed. "
            "A simple CRUD API needs 3-4 experts. A full ML platform needs 6-8.\n\n"
            "Rules:\n"
            "- Always include project_manager (speaks last)\n"
            "- Always include solution_architect for any system design\n"
            "- Include data experts only if data pipelines are central\n"
            "- Include AI experts only if AI/ML is required\n"
            "- Minimum 3 experts, maximum 8\n\n"
            'Respond with ONLY valid JSON: {"roster": ["expert_role_1", "expert_role_2", ...]}'
        )

        roster: list[str] = []
        try:
            response = await adapter.complete(
                system_prompt="You are a consulting team selector.",
                user_prompt=prompt,
                model=settings.model_sonnet,
                max_tokens=300,
            )
            _record_usage(session_id, response, "roster")
            data = _parse_json_safe(response.text, {"roster": []})
            raw = [r for r in data.get("roster", []) if r in ALL_EXPERTS]

            # Enforce: always end with project_manager
            if "project_manager" in raw:
                raw.remove("project_manager")
            raw.append("project_manager")

            # Enforce minimum
            roster = raw if len(raw) >= 3 else ["solution_architect", "solution_engineer", "project_manager"]
        except Exception as exc:
            logger.warning(f"[{session_id}] roster_selection failed: {exc}")
            roster = ["solution_architect", "solution_engineer", "project_manager"]

        logger.info(f"[{session_id}] roster selected: {roster}")

        # Persist roster to DB sessions table
        try:
            import uuid as _uuid
            from backend.db.postgres import AsyncSessionLocal
            from backend.models import Session
            async with AsyncSessionLocal() as db:
                sess = await db.get(Session, _uuid.UUID(session_id))
                if sess:
                    sess.roster = roster
                    await db.commit()
        except Exception as exc:
            logger.warning(f"[{session_id}] roster DB persist failed: {exc}")

        _roster_announced.add(session_id)   # guard supervisor_node from double-emitting
        await emit_session_status(session_id, "roster_selected", roster=roster)
        _stage_id = (state.get("current_stage") or {}).get("stage_id", "FINAL")
        _stage_lbl = (state.get("current_stage") or {}).get("label", "Final Goal")
        dtrace(session_id, f"[STAGE]     ▶ ══ STAGE {_stage_id} ({_stage_lbl}) opened  |  depth={state.get('depth_tier','shallow')} ══")
        dtrace(session_id, f"[ROSTER]    ▶ Selected experts: {roster}")

        # V5-C: recommend tier + per-seat levels over the seated roster (one Haiku call).
        try:
            from backend.orchestrator.classifier import recommend_setup
            _qa_ctx = "\n".join(
                f"Q: {qa.get('question','')} A: {qa.get('answer','')}"
                for qa in (state.get("questionnaire_qa") or [])
            )[:1500]
            recommendation = await recommend_setup(state["enriched_problem"], roster, _qa_ctx)
        except Exception as exc:
            logger.warning(f"[{session_id}] setup recommendation failed: {exc}")
            from backend.orchestrator.classifier import _coerce_setup
            recommendation = _coerce_setup({}, roster)

        _setup_cache[session_id] = {"roster": roster, "recommendation": recommendation}
        _setup_pending.add(session_id)

        _brief = (state.get("enriched_problem") or state.get("problem_brief")
                  or state.get("problem_statement") or "")[:280]
        _payload = _build_setup_payload(roster, recommendation, _brief)
        await emit(session_id, SETUP_REQUIRED, _payload)
        dtrace(
            session_id,
            f"[SETUP]     ⏸ Bench approval — recommend tier={recommendation.get('recommended_tier')} "
            f"| levels={recommendation.get('per_seat_levels')}"
        )

    # ── Phase 2 — both runs: interrupt() raises on run 1, returns approval on run 2 ──
    _cached = _setup_cache.get(session_id, {})
    roster = _cached.get("roster") or list(state.get("roster") or DEFAULT_ROSTER)
    recommendation = _cached.get("recommendation") or {}

    _brief2 = (state.get("enriched_problem") or state.get("problem_brief")
               or state.get("problem_statement") or "")[:280]
    from langgraph.types import interrupt
    raw_approval = interrupt({"type": "setup", **_build_setup_payload(roster, recommendation, _brief2)})

    # ── Everything below runs only on the SECOND (post-resume) pass ──
    _setup_pending.discard(session_id)
    _setup_cache.pop(session_id, None)

    choice = _resolve_setup_choice(raw_approval, recommendation, roster)
    tier = choice["tier"]
    levels = choice["levels"]

    # Apply per-seat levels to the expert_registry (preserve non-roster seats).
    registry = [dict(s) for s in (state.get("expert_registry") or [])]
    for seat in registry:
        role = seat.get("role")
        if role in levels:
            seat["level"] = levels[role]

    applied = {
        "tier":          tier,
        "levels":        levels,
        "tier_source":   choice["tier_source"],
        "levels_source": choice["levels_source"],
    }

    # Audit log — recommendation vs. applied, with per-source annotation.
    _tier_note = "user override" if choice["tier_source"] == "user_override" else "recommended"
    _lvl_note = "user override" if choice["levels_source"] == "user_override" else "recommended"
    _seat_str = ", ".join(f"{r}={levels[r]}" for r in roster)
    _setup_log = f"[SETUP] tier={tier} ({_tier_note}) | {_seat_str} ({_lvl_note})"
    logger.info(f"[{session_id}] {_setup_log}")
    dtrace(session_id, f"[SETUP]     ✓ tier={tier} ({_tier_note}) | {_seat_str} ({_lvl_note})")
    await emit(session_id, SETUP_APPLIED, applied)

    return {
        "roster":                roster,
        "depth_tier":            tier,
        "expert_registry":       registry,
        "setup_recommendation":  recommendation,
        "setup_applied":         applied,
    }


# ── Supervisor node ───────────────────────────────────────────────────────────

async def supervisor_node(state: ChatState) -> dict:
    """
    Intelligent router. Phase 3 implementation:
    1. Consensus detection — terminate cleanly when experts agree.
    2. Hard ceiling at _TURN_CEILING turns.
    3. LLM-based routing via _supervisor_route.
    4. Rolling summary update.
    Phase 5 additions: delegate-to-supervisor arbitration branch,
    human-directed question detection.
    """
    session_id = state["session_id"]
    turn = state["turn_count"]

    roster = state.get("roster") or DEFAULT_ROSTER
    logger.info(
        f"[ROUTE] [{session_id}] supervisor_node entry: "
        f"turn={turn}, "
        f"current_speaker={state.get('current_speaker')!r}, "
        f"awaiting_human={state.get('awaiting_human')}, "
        f"messages={len(state.get('messages', []))}, "
        f"roster={roster}"
    )

    # ── Phase 5: arbitration branch signals ───────────────────────────────────
    human_input = state.get("human_input") or ""
    if human_input == "[DELEGATE_TO_SUPERVISOR]":
        challenged = [
            d for d in state.get("decisions", [])
            if d.get("state") == "challenged"
        ]
        if challenged:
            import uuid as _uuid_arb
            locks = [
                {
                    "id":            str(_uuid_arb.uuid4()),
                    "text":          d["text"],
                    "proposed_by":   d["proposed_by"],
                    "state":         "locked",
                    "provenance":    "orchestrator",
                    "supersedes_id": d["id"],
                }
                for d in challenged
            ]
            asyncio.create_task(_persist_decisions_db(session_id, locks))
            logger.info(
                f"[{session_id}] delegate branch: locking "
                f"{len(locks)} challenged decisions"
            )
            next_spk = await _supervisor_route(state)
            return {
                "decisions":     locks,
                "human_input":   None,
                "current_speaker": next_spk,
            }

    # ── Phase 7: user-triggered finalize ─────────────────────────────────────
    if human_input == "[USER_FINALIZE]":
        proposed = [
            d for d in state.get("decisions", [])
            if d.get("state") == "proposed"
        ]
        locks: list[dict] = []
        if proposed:
            import uuid as _uuid_fin
            locks = [
                {
                    "id":            str(_uuid_fin.uuid4()),
                    "text":          d["text"],
                    "proposed_by":   d["proposed_by"],
                    "state":         "locked",
                    "provenance":    "human",
                    "supersedes_id": d["id"],
                }
                for d in proposed
            ]
            asyncio.create_task(_persist_decisions_db(session_id, locks))
        logger.info(f"[{session_id}] [USER_FINALIZE] — routing to synthesis")
        await emit_session_status(session_id, "synthesizing")
        return {
            **({"decisions": locks} if locks else {}),
            "human_input":        None,
            "termination_reason": "user_finalize",
            "current_speaker":    None,
        }

    # ── Phase 8: flag-based finalize (works on running graph, no double-stream) ──
    if session_id in _finalize_requests:
        _finalize_requests.discard(session_id)
        proposed = [
            d for d in state.get("decisions", [])
            if d.get("state") == "proposed"
        ]
        fin_locks: list[dict] = []
        if proposed:
            import uuid as _uuid_fin2
            fin_locks = [
                {
                    "id":            str(_uuid_fin2.uuid4()),
                    "text":          d["text"],
                    "proposed_by":   d["proposed_by"],
                    "state":         "locked",
                    "provenance":    "human",
                    "supersedes_id": d["id"],
                }
                for d in proposed
            ]
            asyncio.create_task(_persist_decisions_db(session_id, fin_locks))
        logger.info(f"[{session_id}] _finalize_requests — routing to synthesis")
        await emit_session_status(session_id, "synthesizing")
        return {
            **({"decisions": fin_locks} if fin_locks else {}),
            "human_input":        None,
            "termination_reason": "user_finalize",
            "current_speaker":    None,
        }

    # ── Phase 8: user-initiated pause + steer (two-phase, mirrors ask_human_node)
    #
    # LangGraph re-runs the node from the top on resume, so interrupt() cannot
    # be called in a simple if/else — the flag check would fail on the second run.
    # Pattern: Phase 1 fires on the first run (consumes flag, emits SSE, marks
    # pending), Phase 2 fires on BOTH runs (interrupt raises on run 1, returns
    # the steering text on run 2). Only code AFTER interrupt() executes on run 2.
    _steer_prompt = "What direction should the team take next?"

    # Phase 1 — first run only: consume flag, notify frontend, mark pending
    if session_id in _pause_requests and session_id not in _steer_pending:
        _pause_requests.discard(session_id)
        _steer_pending[session_id] = True
        await emit(session_id, PAUSE_ARMED, {"prompt": _steer_prompt})
        logger.info(f"[{session_id}] user pause — pausing for steering input")

    # Phase 2 — both runs: interrupt() raises on run 1, returns text on run 2
    if session_id in _steer_pending:
        from langgraph.types import interrupt
        steering_text = str(interrupt({"type": "steering", "prompt": _steer_prompt}))

        # Everything below only executes on the SECOND run (after resume)
        _steer_pending.pop(session_id, None)

        msg = {
            "role":       "human",
            "content":    f"[Steered] {steering_text}",
            "turn":       turn,
            "is_private": False,
        }
        await emit_message(session_id, "human", msg["content"], turn, is_private=False)
        asyncio.create_task(
            _persist_message(session_id, "human", msg["content"], False, turn)
        )

        updated_problem = (
            (state.get("enriched_problem") or state["problem_statement"])
            + f"\n\n--- MID-SESSION USER DIRECTIVE ---\n{steering_text}\n"
            + "(All experts must incorporate this directive going forward.)"
        )

        next_spk = await _supervisor_route(state)
        return {
            "messages":         [msg],
            "enriched_problem": updated_problem,
            "human_input":      None,
            "current_speaker":  next_spk,
        }

    # ── Phase C.1: Moderator escalation (two-phase interrupt, mirrors pause+steer) ──
    # pending_escalation is set by real triggers (C2/C3) or the synthetic test hook.
    # When set, the graph pauses so the user can choose a fork; the ruling lands in
    # the decision ledger and escalation_ruling state before deliberation resumes.

    _esc = state.get("pending_escalation")

    # ── [TEST-ONLY] Synthetic trigger — fires ONCE on turn 0 when sentinel is present.
    # Remove / replace when C2/C3 add real triggers (recruitment fork, owner-authority).
    if (
        _esc is None
        and session_id not in _escalation_pending
        and state.get("roster")                    # framing + roster selection done
        and state.get("turn_count", 0) == 0        # before any expert speaks
        and "[[TEST_ESCALATION]]" in (state.get("problem_statement") or "")
    ):
        _esc = {
            "reason":  "test_fork",
            "summary": "Synthetic escalation test: choose the project scope",
            "options": [
                {"id": "mvp",  "label": "MVP scope",  "impact": "4-week build, core features only"},
                {"id": "full", "label": "Full scope", "impact": "12-week build, complete feature set"},
            ],
        }
    # ── end test-only block ───────────────────────────────────────────────────────────

    # Phase 1 — first run only: arm escalation, emit SSE.
    # Store the payload dict (not just True) so Phase 2 can access it after resume.
    if _esc and session_id not in _escalation_pending:
        _escalation_pending[session_id] = _esc
        await emit(session_id, ESCALATION_REQUIRED, {
            "reason":  _esc["reason"],
            "summary": _esc["summary"],
            "options": _esc["options"],
        })
        logger.info(f"[{session_id}] escalation armed: {_esc['reason']}")
        dtrace(session_id,
            f"[ESCALATE]  ⏸ Escalation to user: \"{_esc['summary'][:80]}\""
            f"  options={[o['id'] for o in _esc['options']]}"
        )

    # Phase 2 — both runs: interrupt() raises on run 1, returns chosen option on run 2
    if session_id in _escalation_pending:
        # Retrieve the cached payload (set in Phase 1) — available on both runs.
        _esc_cached = _escalation_pending[session_id] if isinstance(_escalation_pending.get(session_id), dict) else (_esc or {})
        from langgraph.types import interrupt as _esc_interrupt
        chosen_raw = _esc_interrupt({
            "type":    "escalation",
            "reason":  _esc_cached.get("reason", ""),
            "summary": _esc_cached.get("summary", ""),
            "options": _esc_cached.get("options", []),
        })

        # Everything below only executes on the SECOND run (after resume)
        _escalation_pending.pop(session_id, None)
        ruling = {"chosen_option_id": str(chosen_raw).strip(), "note": ""}
        dtrace(session_id, f"[ESCALATE]  ✓ User ruling: \"{ruling['chosen_option_id']}\" → resuming")

        import uuid as _uuid_esc
        ruling_dec = {
            "id":            str(_uuid_esc.uuid4()),
            "text":          (
                f"[MODERATOR RULING] {_esc_cached.get('summary', '(escalation)')}: "
                f"chosen option '{ruling['chosen_option_id']}'"
            ),
            "proposed_by":   "human",
            "state":         "locked",
            "provenance":    "moderator",
            "category":      "procedure_log",  # V5-B: keep [MODERATOR RULING] out of Key Decisions (same as D-o-C/tripwire); still persisted to trail/DB
            "supersedes_id": None,
        }
        asyncio.create_task(_persist_decisions_db(session_id, [ruling_dec]))
        await emit(session_id, "escalation_resolved", {
            "chosen_option_id": ruling["chosen_option_id"],
        })
        logger.info(
            f"[{session_id}] escalation resolved → '{ruling['chosen_option_id']}'"
        )

        # ── PHASE-C.2: Recruitment fork — handle seat/skip ruling immediately ──
        # If this escalation was raised by the baton-pass gate (reason=recruitment_fork),
        # act on the user's choice here rather than routing to a random expert first.
        _recruit_domain = state.get("recruitment_pending_domain")
        if _esc_cached.get("reason") == "recruitment_fork" and _recruit_domain:
            if ruling["chosen_option_id"] == "seat":
                _tier = state.get("depth_tier", "shallow")
                _m = settings.model_opus if _tier == "deep" else settings.model_sonnet
                _delta, _new_role = await _seat_expert(
                    _recruit_domain, 0.55,   # borderline mid-point score
                    state, session_id, adapter, _m,
                )
                logger.info(
                    "[%s] borderline recruitment escalation resolved → seating %r",
                    session_id, _new_role,
                )
                return {
                    **_delta,
                    "decisions":                 [ruling_dec] + _delta.get("decisions", []),
                    "pending_escalation":         None,
                    "escalation_ruling":          None,
                    "recruitment_pending_domain": None,
                    "last_nomination":            None,
                    "current_speaker":            _new_role,
                }
            else:  # "skip"
                logger.info("[%s] borderline recruitment escalation resolved → skip", session_id)
                next_spk = await _supervisor_route(state)
                return {
                    "decisions":                 [ruling_dec],
                    "pending_escalation":         None,
                    "escalation_ruling":          None,
                    "recruitment_pending_domain": None,
                    "last_nomination":            None,
                    "current_speaker":            next_spk,
                }

        # ── PHASE-C.3: Tripwire fork ──────────────────────────────────────────
        if _esc_cached.get("reason") == "tripwire":
            if ruling["chosen_option_id"] == "probe":
                logger.info("[%s] tripwire probe → re-opening deliberation", session_id)
                _tw_next = await _supervisor_route(state)
                return {
                    "decisions":                [ruling_dec],
                    "pending_escalation":       None,
                    "escalation_ruling":        ruling,
                    # Reset so D-o-C re-runs when consensus is reached again
                    "doc_committed_this_stage": False,
                    "current_speaker":          _tw_next,
                }
            else:  # "accept"
                logger.info("[%s] tripwire accept → closing stage", session_id)
                import uuid as _uuid_tw_acc
                _tw_proposed = [d for d in state.get("decisions", []) if d.get("state") == "proposed"]
                _tw_locks = [
                    {
                        "id":            str(_uuid_tw_acc.uuid4()),
                        "text":          d["text"],
                        "proposed_by":   d["proposed_by"],
                        "state":         "locked",
                        "provenance":    "converged",
                        "supersedes_id": d["id"],
                    }
                    for d in _tw_proposed
                ]
                if _tw_locks:
                    asyncio.create_task(_persist_decisions_db(session_id, _tw_locks))
                await emit_session_status(session_id, "synthesizing")
                return {
                    "decisions":          [ruling_dec] + _tw_locks,
                    "pending_escalation": None,
                    "escalation_ruling":  ruling,
                    "termination_reason": "consensus",
                    "current_speaker":    None,
                }

        # Route back into normal supervisor flow with the ruling available in state
        next_spk = await _supervisor_route(state)
        return {
            "decisions":          [ruling_dec],
            "pending_escalation": None,
            "escalation_ruling":  ruling,
            "current_speaker":    next_spk,
        }

    # Framing or roster_selection needed — handled by route_from_supervisor
    if not state.get("enriched_problem") or not state.get("roster"):
        return {}

    # Announce the roster to the frontend if roster_selection_node was skipped
    # (i.e., a pre-set roster was provided — manual mode or pre-session custom personas).
    # roster_selection_node sets _roster_announced before emitting; if the session
    # arrives here without going through roster_selection_node, we emit once now.
    # Custom persona definitions are included so the frontend can register emoji/color.
    if session_id not in _roster_announced:
        _roster_announced.add(session_id)
        await emit_session_status(
            session_id,
            "roster_selected",
            roster=list(state.get("roster", [])),
            custom_personas=state.get("custom_personas", []),
        )

    # Rolling summarisation (only updates rolling_summary, not messages)
    summary_update = await _maybe_summarize(state, session_id)

    # ── V5-B THE CLOCK: wall-clock time governor ──────────────────────────────
    # Supersedes the FIX-5 fixed session_timeout_seconds check. Tier-aware budgets
    # (TIER_CONFIG: 600/1200/1800s, or the demo override) measured from the first
    # expert turn, minus HITL pause time. Two gates:
    #   Step 2 — soft nudge at soft_ratio × budget (once): next expert gets asked
    #            to converge. Session keeps running.
    #   Step 3 — hard converge at hard_ratio × budget: stop seating new experts,
    #            stop recruitment, route to close (→ reviewer → synthesis).
    # Placed BEFORE baton-pass / recruitment so the wrap preempts new seating.
    # The clock only runs once an expert has spoken (guard below), so framing /
    # questionnaire time never trips it. The auditor is NEVER skipped: setting
    # termination_reason routes through route_from_supervisor branch 3 → reviewer.
    if _session_clock_start.get(session_id) is not None:
        _elapsed = _elapsed_seconds(state)
        _budget, _soft_r, _hard_r, _reserve = _clock_budget(state)

        # Step 2 — soft nudge (fire once per session)
        if _elapsed >= _soft_r * _budget and session_id not in _session_soft_nudged:
            _session_soft_nudged.add(session_id)
            _clock_nudge_pending.add(session_id)
            logger.info(
                "[CLOCK] soft nudge fired at %.0fs / %.0fs (soft_ratio=%.2f)",
                _elapsed, _budget, _soft_r,
            )
            dtrace(session_id,
                f"[CLOCK]     ⏱ Soft nudge at {_elapsed:.0f}s/{_budget:.0f}s"
                f" — next expert asked to converge")

        # Step 3 — hard converge + auto-wrap
        if _elapsed >= _hard_r * _budget:
            logger.warning(
                "[CLOCK] hard converge at %.0fs — wrapping (budget=%.0fs, hard_ratio=%.2f)",
                _elapsed, _budget, _hard_r,
            )
            dtrace(session_id,
                f"[CLOCK]     ⏱ HARD CONVERGE at {_elapsed:.0f}s/{_budget:.0f}s"
                f" — wrapping: closing current stage via auditor → synthesis")
            await emit(session_id, "phase_event", {
                "event":           "time_wrap",
                "elapsed_seconds": round(_elapsed),
                "budget_seconds":  round(_budget),
            })
            import uuid as _uuid_wrap
            wrap_locks = [
                {
                    "id":            str(_uuid_wrap.uuid4()),
                    "text":          d["text"],
                    "proposed_by":   d["proposed_by"],
                    "state":         "locked",
                    "provenance":    "time_wrap",
                    "supersedes_id": d["id"],
                }
                for d in state.get("decisions", [])
                if d.get("state") == "proposed"
            ]
            if wrap_locks:
                asyncio.create_task(_persist_decisions_db(session_id, wrap_locks))
            await emit_session_status(session_id, "synthesizing")
            return {
                **summary_update,
                **({"decisions": wrap_locks} if wrap_locks else {}),
                "termination_reason": "time_wrap",
                "current_speaker":    None,
            }

    # ── Phase C.2: Baton-pass / expert recruitment ───────────────────────────
    # Fires when the last expert passed a next_domain baton.
    # Only runs when framing + roster selection are done and no active escalation.

    # ── [TEST-ONLY] Synthetic baton trigger — fires on turn 1 when sentinel present ──
    # Format: "[[TEST_BATON:domain]]" in problem_statement.
    # Injects last_nomination=domain if no organic nomination came from the experts.
    # Remove / replace when the GDPR-class problems reliably produce organic nominations.
    import re as _re
    _tb_match = _re.search(r"\[\[TEST_BATON:([a-z_]+)\]\]", state.get("problem_statement") or "")
    if (
        _tb_match
        and state.get("turn_count", 0) == 1          # after first expert speaks
        and not state.get("last_nomination")          # no organic nomination yet
        and state.get("roster")
    ):
        _synthetic_domain = _tb_match.group(1)
        logger.info("[%s] TEST_BATON: injecting synthetic nomination=%r", session_id, _synthetic_domain)
        await emit(session_id, "domain_nominated", {"role": "sentinel", "domain": _synthetic_domain})
        # Treat as if expert nominated this domain (state shadow for rest of this turn)
        state = {**state, "last_nomination": _synthetic_domain}
    # ── end test-only block ───────────────────────────────────────────────────────────

    _baton = state.get("last_nomination")
    if (
        _baton
        and state.get("enriched_problem")
        and state.get("roster")
        and not state.get("pending_escalation")
    ):
        _bp_roster   = state.get("roster") or []
        _bp_registry = state.get("expert_registry") or []
        _bp_tier     = state.get("depth_tier", "shallow")
        _bp_model    = settings.model_opus if _bp_tier == "deep" else settings.model_sonnet

        # 1. Already seated? Route directly — no gate needed.
        _existing = next(
            (r["role"] for r in _bp_registry
             if r.get("seated", True)
             and _baton in (r.get("domain_tags") or [])
             and r["role"] in _bp_roster),
            None,
        )
        if _existing:
            logger.info(
                "[%s] baton-pass: domain=%r already seated as %r — routing directly",
                session_id, _baton, _existing,
            )
            return {
                **summary_update,
                "last_nomination": None,
                "current_speaker": _existing,
            }

        # 2. Orphan nomination — run relevance gate.
        dtrace(session_id, f"[BATON]     ▶ Orphan nomination \"{_baton}\" → running relevance gate...")
        _bp_adapter = get_adapter()
        _gate = await _run_relevance_gate(
            session_id, _baton,
            state.get("enriched_problem") or state.get("problem_statement", ""),
            list(state.get("brief_stack", [])),
            _bp_adapter, _bp_model,
        )
        dtrace(session_id,
            f"[BATON]     ✓ Relevance gate: score={_gate['score']:.2f} → {_gate['band']}"
            + (f"  ({_gate['reasoning'][:60]})" if _gate.get("reasoning") else "")
        )

        if _gate["band"] == "irrelevant":
            logger.info(
                "[%s] baton-pass: domain=%r irrelevant (score=%.2f) — ignoring",
                session_id, _baton, _gate["score"],
            )
            # Fall through to normal routing with nomination cleared

        elif _gate["band"] == "confident":
            _delta, _new_role = await _seat_expert(
                _baton, _gate["score"], state, session_id, _bp_adapter, _bp_model,
            )
            return {
                **summary_update,
                **_delta,
                "last_nomination": None,
                "current_speaker": _new_role,
            }

        elif _gate["band"] == "borderline":
            _label = _baton.replace("_", " ").title()
            _esc_payload = {
                "reason":  "recruitment_fork",
                "summary": (
                    f"Seat a {_label} specialist? "
                    f"(relevance score: {_gate['score']:.2f}) — {_gate['reasoning']}"
                ),
                "options": [
                    {
                        "id":     "seat",
                        "label":  f"Seat {_label} specialist",
                        "impact": f"A {_baton} expert joins the council for this stage",
                    },
                    {
                        "id":     "skip",
                        "label":  "Skip — continue without",
                        "impact": f"The {_baton} domain will not get a dedicated expert",
                    },
                ],
            }
            logger.info(
                "[%s] baton-pass: domain=%r borderline (score=%.2f) — escalating",
                session_id, _baton, _gate["score"],
            )
            dtrace(session_id, f"[RECRUIT]   ⏸ \"{_baton}\" borderline (score={_gate['score']:.2f}) — escalated to user")
            return {
                **summary_update,
                "last_nomination":            None,
                "recruitment_pending_domain": _baton,
                "pending_escalation":         _esc_payload,
            }

        # If irrelevant or gate error: clear nomination and fall through
        # (summary_update already computed; return includes cleared last_nomination)
        if _gate["band"] == "irrelevant":
            # Cannot early-return here because we need the baton cleared even on
            # fall-through; set current_speaker via normal routing below and
            # include last_nomination: None in the final return instead.
            state = {**state, "last_nomination": None}  # shadow for rest of turn

    # ── Phase 4: Contradiction detection ──────────────────────────────────────
    # Skip when fewer than 2 different experts have spoken (can't contradict
    # yourself) or on the first turn (nothing proposed by others yet).
    pub_speakers = {
        m["role"] for m in state.get("messages", [])
        if not m.get("is_private")
        and m["role"] in (state.get("roster") or DEFAULT_ROSTER)
    }
    if (state["turn_count"] > 1
            and len(pub_speakers) >= 2
            and state.get("decisions")
            and _session_contradiction_count.get(
                session_id, 0) < 6):
        pub = [m for m in state.get("messages", []) if not m.get("is_private")]
        last_speaker = pub[-1]["role"] if pub else None

        if last_speaker:
            # Effective (non-superseded) decisions only, to avoid
            # re-triggering a contradiction already being debated.
            effective_all = _get_effective_decisions(state.get("decisions", []))

            # Decisions proposed by the last speaker (live ones only)
            new_proposed = [
                d["text"] for d in effective_all
                if d.get("state") == "proposed"
                and d.get("proposed_by") == last_speaker
            ]
            # Prior effective decisions from OTHER experts
            prior_effective = [
                d for d in effective_all
                if d.get("proposed_by") != last_speaker
                and d.get("state") in ("proposed", "locked")
            ]

            if new_proposed and prior_effective:
                conflict = await detect_contradiction(
                    new_proposed,
                    prior_effective,
                    state.get("enriched_problem", ""),
                    session_id,
                )

                if conflict:
                    # Increment session total
                    _session_contradiction_count[session_id] = \
                        _session_contradiction_count.get(
                            session_id, 0) + 1

                    conflict_id = conflict["conflicts_with_id"]
                    rounds_used = _challenge_rounds.get(conflict_id, 0)

                    if rounds_used < 2:
                        # Route back to original proposer for debate
                        rounds_used += 1
                        _challenge_rounds[conflict_id] = rounds_used
                        original_proposer = conflict["conflicts_with_by"]

                        await emit(session_id, "contradiction", {
                            "conflict":           conflict,
                            "round":              rounds_used,
                            "challenged_by":      last_speaker,
                            "original_proposer":  original_proposer,
                        })

                        # Mark the challenged decision (new superseding entry)
                        challenged_entry = next(
                            (d for d in state["decisions"] if d["id"] == conflict_id),
                            None,
                        )
                        new_challenged = []
                        if challenged_entry:
                            import uuid as _uuid_c
                            new_challenged = [{
                                **challenged_entry,
                                "id":            str(_uuid_c.uuid4()),
                                "state":         "challenged",
                                "supersedes_id": conflict_id,
                            }]

                        asyncio.create_task(_persist_challenge_round(
                            conflict_id, session_id,
                            last_speaker, rounds_used, "pending",
                        ))

                        logger.info(
                            f"[{session_id}] contradiction — routing to "
                            f"{original_proposer} (round {rounds_used}/2): "
                            f"{conflict['summary']}"
                        )
                        return {
                            **summary_update,
                            **({"decisions": new_challenged} if new_challenged else {}),
                            "current_speaker": original_proposer,
                        }

                    else:
                        # 2 rounds exhausted — supervisor arbitrates
                        logger.info(
                            f"[{session_id}] deadlock after 2 rounds — "
                            f"supervisor locking decision"
                        )
                        await emit(session_id, "arbitration", {
                            "conflict":    conflict,
                            "resolution":  "supervisor_decided",
                            "note": (
                                "Locked by supervisor after 2 debate rounds. "
                                "Phase 5 will add full human arbitration UI."
                            ),
                        })
                        locked = _lock_decision(
                            state["decisions"], conflict_id, "orchestrator"
                        )
                        asyncio.create_task(_persist_challenge_round(
                            conflict_id, session_id,
                            "supervisor", 3, "orchestrator_decided",
                        ))
                        return {
                            **summary_update,
                            **({"decisions": locked} if locked else {}),
                            "current_speaker": await _supervisor_route(state),
                        }
    elif (_session_contradiction_count.get(
            session_id, 0) >= 6
          and state["turn_count"] > 1):
        logger.info(
            f"[{session_id}] contradiction cap (6) reached "
            f"— skipping detection, routing normally"
        )

    # ── Phase 5: human-directed question detection ────────────────────────────
    # Only pause for human input when an expert explicitly sets needs_human_input=true
    # in their JSON output. Keyword-scanning ordinary discussion text is removed
    # because terms like "user", "requirement", "budget" appear in every expert
    # message and caused false-positive hangs.
    _pub_for_human_check = [
        m for m in state.get("messages", []) if not m.get("is_private")
    ]
    _last_msg = _pub_for_human_check[-1] if _pub_for_human_check else {}
    logger.info(
        f"[ROUTE] [{session_id}] human-signal check: "
        f"last_speaker={_last_msg.get('role')!r}, "
        f"needs_human_input={_last_msg.get('needs_human_input', False)}"
    )
    if _last_msg.get("needs_human_input"):
        _unresolved = [
            q for q in state.get("open_questions", [])
            if not q.startswith("[RESOLVED]")
        ]
        logger.info(
            f"[ROUTE] [{session_id}] explicit needs_human_input from "
            f"{_last_msg.get('role')!r} — routing ask_human, "
            f"unresolved_qs={len(_unresolved)}"
        )
        return {
            **summary_update,
            "awaiting_human": True,
            "current_speaker": None,
        }

    # ── Consensus check ────────────────────────────────────────────────────────
    if _check_consensus(state):
        # PHASE-C.3: run shared gate before closing. _check_consensus fires when
        # no_pending=True (all decisions already locked) — rare in practice, but
        # guarded for completeness. Uses "converged" provenance unlike the
        # supervisor-synthesis paths.
        _cc_gate = await _run_c3_gate(state, session_id, summary_update)
        if _cc_gate is not None and "__c3_extra__" not in _cc_gate:
            return _cc_gate  # D-o-C objection or tripwire escalation
        _cc_extra = _cc_gate["__c3_extra__"] if _cc_gate else []
        _cc_state  = {"doc_committed_this_stage": True} if _cc_gate else {}

        logger.info(f"[{session_id}] consensus reached — locking proposals + synthesising")

        import uuid as _uuid_lock
        all_proposed = [
            d for d in state.get("decisions", [])
            if d.get("state") == "proposed"
        ]
        decisions_to_lock = [
            {
                "id":            str(_uuid_lock.uuid4()),
                "text":          d["text"],
                "proposed_by":   d["proposed_by"],
                "state":         "locked",
                "provenance":    "converged",
                "supersedes_id": d["id"],
            }
            for d in all_proposed
        ]
        logger.info(
            f"[{session_id}] consensus: all_proposed={len(all_proposed)}, "
            f"decisions_to_lock={len(decisions_to_lock)}"
        )
        _all_close_decs = _cc_extra + decisions_to_lock
        if _all_close_decs:
            asyncio.create_task(_persist_decisions_db(session_id, _all_close_decs))

        await emit_session_status(session_id, "synthesizing")
        return {
            **summary_update,
            **_cc_state,
            **({"decisions": _all_close_decs} if _all_close_decs else {}),
            "termination_reason": "consensus",
            "current_speaker":    None,
        }

    # FIX-8: session-level token budget guard — force synthesis when budget exceeded
    if _session_token_totals.get(session_id, 0) >= settings.session_token_budget:
        logger.warning(
            f"[{session_id}] token budget exceeded "
            f"({_session_token_totals.get(session_id, 0)} >= {settings.session_token_budget})"
        )
        import uuid as _uuid_budget
        budget_locks = [
            {
                "id":            str(_uuid_budget.uuid4()),
                "text":          d["text"],
                "proposed_by":   d["proposed_by"],
                "state":         "locked",
                "provenance":    "budget_ceiling",
                "supersedes_id": d["id"],
            }
            for d in state.get("decisions", [])
            if d.get("state") == "proposed"
        ]
        if budget_locks:
            asyncio.create_task(_persist_decisions_db(session_id, budget_locks))
        await emit_session_status(session_id, "synthesizing")
        return {
            **summary_update,
            **({"decisions": budget_locks} if budget_locks else {}),
            "termination_reason": "budget_exceeded",
            "current_speaker": None,
        }

    # Hard ceiling — lock any remaining proposed decisions before synthesis
    if turn >= _TURN_CEILING or state.get("solution_document"):
        logger.warning(f"[{session_id}] turn ceiling hit ({turn})")
        import uuid as _uuid_ceil
        ceiling_locks = [
            {
                "id":            str(_uuid_ceil.uuid4()),
                "text":          d["text"],
                "proposed_by":   d["proposed_by"],
                "state":         "locked",
                "provenance":    "ceiling",
                "supersedes_id": d["id"],
            }
            for d in state.get("decisions", [])
            if d.get("state") == "proposed"
        ]
        if ceiling_locks:
            asyncio.create_task(_persist_decisions_db(session_id, ceiling_locks))

        await emit_session_status(session_id, "synthesizing")
        return {
            **summary_update,
            **({"decisions": ceiling_locks} if ceiling_locks else {}),
            "termination_reason": "ceiling",
            "current_speaker": None,
        }

    # ── Helper: lock all remaining proposed decisions before synthesis ────────────
    def _make_synthesis_locks(provenance: str) -> list[dict]:
        import uuid as _uuid_s
        proposed = [d for d in state.get("decisions", []) if d.get("state") == "proposed"]
        locked = [
            {
                "id":            str(_uuid_s.uuid4()),
                "text":          d["text"],
                "proposed_by":   d["proposed_by"],
                "state":         "locked",
                "provenance":    provenance,
                "supersedes_id": d["id"],
            }
            for d in proposed
        ]
        if locked:
            asyncio.create_task(_persist_decisions_db(session_id, locked))
        return locked

    # ── Per-stage expert-turn cap (rounds_per_stage setting — was in config but never wired) ──
    _stage_turns = state.get("turn_count", 0) - state.get("stage_turn_offset", 0)
    _depth_tier  = state.get("depth_tier", "shallow")
    _stage_cap   = (settings.rounds_per_stage_deep if _depth_tier == "deep"
                    else settings.rounds_per_stage_shallow)
    if _stage_turns >= _stage_cap:
        logger.warning(
            "[%s] per-stage round cap (%d/%d) — forcing synthesis",
            session_id, _stage_turns, _stage_cap,
        )
        dtrace(session_id,
            f"[CAP]       ⚠ Stage cap: {_stage_turns}/{_stage_cap} expert turns — routing to synthesis")
        locks = _make_synthesis_locks("ceiling")
        await emit_session_status(session_id, "synthesizing")
        return {
            **summary_update,
            **({"decisions": locks} if locks else {}),
            "termination_reason": "ceiling",
            "current_speaker":    None,
        }

    # Intelligent routing
    next_speaker = await _supervisor_route(state)
    logger.info(
        f"[ROUTE] [{session_id}] _supervisor_route returned: next_speaker={next_speaker!r}"
    )

    if next_speaker == "synthesis":
        # PHASE-C.3: primary trigger — Sonnet routing says synthesis.
        _syn_gate = await _run_c3_gate(state, session_id, summary_update)
        if _syn_gate is not None and "__c3_extra__" not in _syn_gate:
            return _syn_gate  # D-o-C objection or tripwire escalation
        _syn_extra = _syn_gate["__c3_extra__"] if _syn_gate else []
        _syn_state  = {"doc_committed_this_stage": True} if _syn_gate else {}

        locks = _make_synthesis_locks("consensus_by_supervisor")
        logger.info(f"[{session_id}] supervisor→synthesis: locking {len(locks)} proposed decisions")
        await emit_session_status(session_id, "synthesizing")
        return {
            **summary_update,
            **_syn_state,
            **({"decisions": _syn_extra + locks} if (_syn_extra or locks) else {}),
            "termination_reason": "consensus_by_supervisor",
            "current_speaker":    None,
        }

    if next_speaker in ("ask_human", "human_input"):
        # Phase 5 will implement human mid-session pausing; for now continue
        # by picking the next unheard expert (stage-scoped so S1 starts fresh)
        roster = state.get("roster") or DEFAULT_ROSTER
        _ah_stage_start = state.get("stage_turn_offset", 0)
        pub = [m for m in state.get("messages", []) if not m.get("is_private") and m.get("turn", 0) >= _ah_stage_start]
        heard = {m["role"] for m in pub if m["role"] in roster}
        fallback = next((r for r in roster if r not in heard), "synthesis")
        if fallback == "synthesis":
            # PHASE-C.3: guard this path too — it was the ungated path in ed83867d.
            _ah_gate = await _run_c3_gate(state, session_id, summary_update)
            if _ah_gate is not None and "__c3_extra__" not in _ah_gate:
                return _ah_gate  # D-o-C objection or tripwire escalation
            _ah_extra = _ah_gate["__c3_extra__"] if _ah_gate else []
            _ah_state  = {"doc_committed_this_stage": True} if _ah_gate else {}

            locks = _make_synthesis_locks("consensus_by_supervisor")
            await emit_session_status(session_id, "synthesizing")
            return {
                **summary_update,
                **_ah_state,
                **({"decisions": _ah_extra + locks} if (_ah_extra or locks) else {}),
                "termination_reason": "consensus_by_supervisor",
                "current_speaker":    None,
            }
        next_speaker = fallback

    # Validate the returned speaker is in the roster or is a custom persona
    roster = state.get("roster") or DEFAULT_ROSTER
    _custom_roles = [p["role"] for p in state.get("custom_personas", [])]
    if next_speaker not in ALL_EXPERTS and next_speaker not in _custom_roles:
        # Unexpected response — fall back to first unheard (stage-scoped)
        _inv_stage_start = state.get("stage_turn_offset", 0)
        pub = [m for m in state.get("messages", []) if not m.get("is_private") and m.get("turn", 0) >= _inv_stage_start]
        heard = {m["role"] for m in pub if m["role"] in roster}
        next_speaker = next((r for r in roster if r not in heard), "synthesis")
        if next_speaker == "synthesis":
            locks = _make_synthesis_locks("ceiling")
            await emit_session_status(session_id, "synthesizing")
            return {
                **summary_update,
                **({"decisions": locks} if locks else {}),
                "termination_reason": "ceiling",
                "current_speaker": None,
            }

    await emit_session_status(session_id, "agent_thinking", agent=next_speaker)
    return {
        **summary_update,
        "current_speaker":  next_speaker,
        "last_nomination":  None,   # clear any unconsumed baton on normal routing
    }


# ── Phase 4: per-session challenge round counters ─────────────────────────────
# Maps decision_id → number of debate rounds consumed (max 2).
_challenge_rounds: dict[str, int] = {}

# Total contradiction rounds fired per session.
# Cap at 6 to prevent runaway loops on ambiguous problems.
_session_contradiction_count: dict[str, int] = {}


# ── Phase 4 helpers ───────────────────────────────────────────────────────────

async def _persist_decisions_db(session_id: str, decisions: list[dict]) -> None:
    """
    Upsert a list of decision dicts into the decisions table.
    Uses INSERT ... ON CONFLICT DO UPDATE so re-runs are idempotent.
    Fire-and-forget — non-fatal on error.
    """
    if not decisions:
        return
    try:
        import uuid as _uuid
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from backend.db.postgres import AsyncSessionLocal
        from backend.models import Decision as DecisionModel
        async with AsyncSessionLocal() as db:
            for d in decisions:
                stmt = pg_insert(DecisionModel).values(
                    id=_uuid.UUID(d["id"]),
                    session_id=_uuid.UUID(session_id),
                    text=d["text"],
                    proposed_by=d.get("proposed_by", "unknown"),
                    state=d.get("state", "proposed"),
                    provenance=d.get("provenance"),
                    supersedes_id=(
                        _uuid.UUID(d["supersedes_id"])
                        if d.get("supersedes_id") else None
                    ),
                ).on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "state":      d.get("state", "proposed"),
                        "provenance": d.get("provenance"),
                    },
                )
                await db.execute(stmt)
            await db.commit()
    except Exception as exc:
        logger.warning(f"[{session_id}] decisions DB upsert failed: {exc}")


async def _persist_challenge_round(
    decision_id: str,
    session_id: str,
    challenger: str,
    round_number: int,
    outcome: str,
) -> None:
    """Write a ChallengeRound row to the DB (fire-and-forget)."""
    try:
        import uuid as _uuid
        from backend.db.postgres import AsyncSessionLocal
        from backend.models import ChallengeRound
        async with AsyncSessionLocal() as db:
            cr = ChallengeRound(
                decision_id=_uuid.UUID(decision_id),
                challenger=challenger,
                round_number=round_number,
                outcome=outcome,
            )
            db.add(cr)
            await db.commit()
    except Exception as exc:
        logger.warning(f"[{session_id}] ChallengeRound persist failed: {exc}")


def _lock_decision(decisions: list[dict], decision_id: str, provenance: str) -> list[dict]:
    """
    Return a new superseding entry with state='locked'.
    The original stays in the append-only list; the new entry points
    back via supersedes_id.
    """
    target = next((d for d in decisions if d["id"] == decision_id), None)
    if not target:
        return []
    import uuid as _uuid
    return [{
        "id":            str(_uuid.uuid4()),
        "text":          target["text"],
        "proposed_by":   target["proposed_by"],
        "state":         "locked",
        "provenance":    provenance,
        "supersedes_id": decision_id,
    }]


def _get_effective_decisions(decisions: list[dict]) -> list[dict]:
    """
    Return only the 'live' decisions — those whose id does not appear
    as the supersedes_id of any other entry.
    Handles the append-only invariant: each state change adds a new
    superseding entry; we exclude the entries being superseded.
    """
    superseded_ids = {d["supersedes_id"] for d in decisions if d.get("supersedes_id")}
    return [d for d in decisions if d["id"] not in superseded_ids]


# ── Questionnaire infrastructure (TASK-2.2) ──────────────────────────────────

_questionnaire_current: dict[str, dict] = {}
# Per-session cache — same pattern as _framing_questions.
# Stores the question being asked during a live interrupt() cycle.

_QUESTIONNAIRE_SYSTEM = """
You are conducting a reverse-engineered intake. The user has stated an end goal.
Your job is to work BACKWARD from that goal: identify the immediate precursor
decision that must be resolved to reach it, and ask ONE question about that
precursor.

Do not ask the user to design architecture or make expert-level technical
decisions. Ask for CONSTRAINTS and PREFERENCES instead: budget, timeline, risk
appetite, existing systems, team size, hard requirements. The council will make
the technical decisions later — your job is only to surface what the council
needs to know to do that.

Given the end goal and everything answered so far, ask the single most important
next precursor question. Funnel from general to specific — do not jump to fine
technical detail early.

Return ONLY valid JSON:
{"question": "...", "reasoning": "why this is the next precursor"}
""".strip()

# TASK-2.2 / research 6.1: stop decision is a SEPARATE call from question
# generation — models under-ask by default and this gets worse with retrieved
# context. Never merge this into the question generation prompt.
_STOP_CLASSIFIER_SYSTEM = """
You are judging whether an intake questionnaire has gathered enough information
to brief a consulting team, NOT whether you personally could answer the question.
Given the end goal and the Q&A so far, answer only: does the team have enough
context to begin, at the requested depth level?

Depth level "shallow" means: enough to establish direction at a strategic level.
Depth level "deep" means: enough to reach concrete technical precursors, not
just strategic ones.

Also flag if any answer contradicts or significantly changes an earlier answer —
this is a contradiction cycle, not an error.

Return ONLY valid JSON:
{"enough": true|false, "reason": "...", "contradiction_found": false}
""".strip()


async def _questionnaire_should_stop(
    problem_statement: str,
    questionnaire_qa: list[dict],
    depth_tier: str,
    question_count: int,
    session_id: str,
) -> tuple[bool, bool]:
    """
    Returns (should_stop: bool, contradiction_found: bool).
    Hard cap always wins — classifier can only stop early, never extend past it.
    Minimum floor prevents stopping before the intake has any real breadth.
    Fails toward stopping (shorter questionnaires) on any error.
    """
    cap = (
        settings.questionnaire_max_questions_deep
        if depth_tier == "deep"
        else settings.questionnaire_max_questions_shallow
    )
    if question_count >= cap:
        return True, False

    # Minimum floor: don't let the classifier stop before we have genuine breadth.
    # Haiku aggressively returns "enough" on a single Q&A; the floor prevents that.
    min_floor = settings.questionnaire_min_questions_deep if depth_tier == "deep" else settings.questionnaire_min_questions_shallow
    if question_count < min_floor:
        logger.info(
            "[%s] questionnaire: floor not reached (%d/%d) — skipping stop classifier",
            session_id, question_count, min_floor,
        )
        return False, False

    adapter = get_adapter()
    qa_lines = "\n".join(
        f"Q: {qa.get('question', '')}\nA: {qa.get('answer', '')}"
        for qa in questionnaire_qa
    )
    try:
        resp = await adapter.complete(
            system_prompt=_STOP_CLASSIFIER_SYSTEM,
            user_prompt=(
                f"Depth level: {depth_tier}\n\n"
                f"End goal: {problem_statement}\n\n"
                f"Q&A so far:\n{qa_lines}"
            ),
            model=settings.model_haiku,
            max_tokens=150,
        )
        _record_usage(session_id, resp, "questionnaire_stop")
        data = _parse_json_safe(resp.text, {"enough": True, "reason": "parse_error", "contradiction_found": False})
        return bool(data.get("enough", True)), bool(data.get("contradiction_found", False))
    except Exception as exc:
        logger.warning(f"[{session_id}] questionnaire stop classifier failed — stopping: {exc}")
        return True, False  # fail toward stopping


async def _compact_questionnaire(
    problem_statement: str,
    questionnaire_qa: list[dict],
    session_id: str,
) -> str:
    """
    TASK-2.2 / research 6.3: council NEVER sees raw questionnaire_qa —
    only the compacted brief. Prevents lost-in-multi-turn degradation on
    long deep-mode questionnaires.
    """
    adapter = get_adapter()
    qa_text = "\n".join(
        f"Q: {qa.get('question', '')}\nA: {qa.get('answer', '')}"
        for qa in questionnaire_qa
    )
    try:
        resp = await adapter.complete(
            system_prompt=(
                "Compact this intake Q&A into a structured problem brief the "
                "council will use as their starting context. Preserve every "
                "concrete constraint and preference stated. Do not editorialize "
                "or add assumptions. Note any questions the user skipped."
            ),
            user_prompt=f"End goal: {problem_statement}\n\nQ&A:\n{qa_text}",
            model=settings.model_haiku,
            max_tokens=600,
        )
        _record_usage(session_id, resp, "questionnaire_compact")
        return resp.text.strip()
    except Exception as exc:
        logger.warning(f"[{session_id}] questionnaire compaction failed — using fallback: {exc}")
        lines = [f"Goal: {problem_statement}", ""]
        for qa in questionnaire_qa:
            a = qa.get("answer", "")
            lines.append(f"- {qa.get('question', '')}: {a}")
        return "\n".join(lines)


async def questionnaire_node(state: ChatState) -> dict:
    """
    TASK-2.2: reverse-engineered intake. Runs BEFORE framing.
    Each call asks ONE precursor question via interrupt(), loops via
    route_from_questionnaire until the stop classifier (or hard cap) fires,
    then compacts Q&A → problem_brief and sets questionnaire_done=True.
    """
    from langgraph.types import interrupt

    session_id  = state["session_id"]
    depth_tier  = state.get("depth_tier", "shallow")
    q_count     = state.get("questionnaire_question_count", 0)
    prior_qa: list[dict] = state.get("questionnaire_qa", [])
    prior_branches: list[dict] = state.get("contradiction_branches", [])

    cap = (
        settings.questionnaire_max_questions_deep
        if depth_tier == "deep"
        else settings.questionnaire_max_questions_shallow
    )

    # Early exit if already done (safety guard for unexpected re-entry)
    if state.get("questionnaire_done"):
        return {}

    _tier_model = settings.model_opus if depth_tier == "deep" else settings.model_sonnet
    adapter = get_adapter()

    # ── Generate question (first-run only — skipped on LangGraph resume replay) ──
    if session_id not in _questionnaire_current:
        problem = state["problem_statement"]
        context = f"End goal: {problem}"
        if prior_qa:
            context += "\n\nQ&A so far:\n" + "\n".join(
                f"Q: {qa['question']}\nA: {qa['answer']}" for qa in prior_qa
            )
        try:
            q_resp = await adapter.complete(
                system_prompt=_QUESTIONNAIRE_SYSTEM,
                user_prompt=context,
                model=_tier_model,
                max_tokens=300,
            )
            _record_usage(session_id, q_resp, "questionnaire_gen")
            q_data = _parse_json_safe(q_resp.text, {"question": None, "reasoning": ""})
            question = q_data.get("question") or "What are the key constraints for this project?"
        except Exception as exc:
            logger.warning(f"[{session_id}] questionnaire question generation failed: {exc}")
            question = "What are the key constraints for this project?"

        new_count = q_count + 1
        _questionnaire_current[session_id] = {"question": question, "count": new_count}

        dtrace(session_id, f"[INTAKE]    ▶ Q{new_count}/{cap}: \"{question[:80]}\"")
        await emit(session_id, "questionnaire_question", {
            "question":       question,
            "question_number": new_count,
            "max_questions":  cap,
            "can_skip":       True,
        })
        logger.info(f"[{session_id}] questionnaire: Q{new_count}/{cap}: {question[:60]!r}")

    # ── Pause for user answer ──
    current  = _questionnaire_current[session_id]
    raw_answer = interrupt({
        "question":        current["question"],
        "type":            "questionnaire",
        "question_number": current["count"],
        "can_skip":        True,
    })

    # ── Post-resume: process answer ──
    question = current["question"]
    count    = current["count"]
    _questionnaire_current.pop(session_id, None)

    answer_text = str(raw_answer).strip()
    if answer_text.lower() in ("[skip]", "skip", "[skipped]", "s", ""):
        answer_text = "[SKIPPED]"
    dtrace(session_id, f"[INTAKE]    ✓ Answer received: \"{answer_text[:80]}\"")

    new_qa_entry = {"question": question, "answer": answer_text}
    full_qa = prior_qa + [new_qa_entry]

    # ── Stop classifier (separate call — research 6.1) ──
    problem = state["problem_statement"]
    should_stop, contradiction_found = await _questionnaire_should_stop(
        problem, full_qa, depth_tier, count, session_id
    )

    # ── TASK-2.2 / research 6.4: contradiction cycle tracking ──
    new_branches: list[dict] = []
    if contradiction_found:
        uncapped = sum(1 for b in prior_branches if not b.get("capped", False))
        if depth_tier == "deep":
            cap_branches = settings.questionnaire_max_contradiction_branches_deep
            capped = uncapped >= cap_branches
            new_branches = [{"branch": f"Q{count}: {question[:60]}", "cycles_applied": 1, "capped": capped}]
            if capped:
                logger.info(f"[{session_id}] questionnaire: deep branch cap hit ({uncapped}/{cap_branches}) — global cycle only")
        else:  # shallow: global cap of 2
            shallow_global_cap = 2
            capped = uncapped >= shallow_global_cap
            new_branches = [{"branch": f"Q{count}: {question[:60]}", "cycles_applied": 1, "capped": capped}]
            if capped:
                should_stop = True  # shallow global cap hit → force stop
                logger.info(f"[{session_id}] questionnaire: shallow global contradiction cap hit — forcing stop")

    if should_stop:
        # ── Compact Q&A → problem_brief (research 6.3) ──
        brief = await _compact_questionnaire(problem, full_qa, session_id)
        await emit(session_id, "questionnaire_complete", {
            "question_count": count,
            "brief_length":   len(brief),
            "depth_tier":     depth_tier,
        })
        logger.info(f"[{session_id}] questionnaire done: {count} questions, brief={len(brief)} chars")
        delta: dict = {
            "questionnaire_qa":             [new_qa_entry],
            "questionnaire_question_count": count,
            "questionnaire_done":           True,
            "problem_brief":                brief,
        }
        if new_branches:
            delta["contradiction_branches"] = new_branches
        return delta
    else:
        logger.info(f"[{session_id}] questionnaire continuing: {count} asked, cap={cap}")
        delta = {
            "questionnaire_qa":             [new_qa_entry],
            "questionnaire_question_count": count,
        }
        if new_branches:
            delta["contradiction_branches"] = new_branches
        return delta


# ── Framing questions cache ───────────────────────────────────────────────────
_framing_questions: dict[str, list[str]] = {}


# ── Framing node ─────────────────────────────────────────────────────────────

async def framing_node(state: ChatState) -> dict:
    from langgraph.types import interrupt

    session_id = state["session_id"]
    # TASK-2.2 / Step 7: consume problem_brief if produced by questionnaire;
    # fall back to raw problem_statement for sessions that skipped questionnaire.
    problem = state.get("problem_brief") or state["problem_statement"]
    adapter = get_adapter()

    if session_id not in _framing_questions:
        logger.info(f"[{session_id}] framing: generating clarifying questions")
        try:
            q_resp = await adapter.complete(
                system_prompt=_FRAMING_SYSTEM,
                user_prompt=f"Technical problem: {problem}",
                model=settings.model_sonnet,
                max_tokens=500,
            )
            _record_usage(session_id, q_resp, "framing")
            q_data = _parse_json_safe(q_resp.text, {"questions": []})
            questions: list[str] = q_data.get("questions", [])
            if not questions:
                questions = [
                    "What is the expected scale (users, transactions/sec, data volume)?",
                    "What is the primary tech stack and cloud provider?",
                    "What are the key constraints (budget, timeline, existing systems)?",
                ]
        except Exception as exc:
            logger.warning(f"[{session_id}] framing question generation failed: {exc}")
            questions = [
                "What is the expected scale?",
                "What is the existing infrastructure?",
                "What are the key constraints?",
            ]

        _framing_questions[session_id] = questions
        await emit_session_status(session_id, "clarification_required", questions=questions)
        logger.info(f"[{session_id}] framing: waiting for user answers")
    else:
        questions = _framing_questions[session_id]
        logger.info(f"[{session_id}] framing: resuming with cached questions")

    answer = interrupt({"questions": questions, "type": "clarification"})

    enriched = (
        f"Original Problem: {problem}\n\n"
        f"Clarifications Provided:\n{answer}"
    )

    rag_chunks: list[dict] = []
    try:
        from backend.tools.search_kb import search_knowledge_base
        rag_chunks = await search_knowledge_base(enriched[:400], top_k=5)
    except Exception as exc:
        logger.warning(f"[{session_id}] framing RAG failed: {exc}")

    _framing_questions.pop(session_id, None)

    await emit_session_status(session_id, "clarification_complete", enriched_problem=enriched[:200])

    # PHASE-B.2 / F5: Stage FINAL goal-pin — detect "solution in disguise"
    dtrace(session_id, "[GOAL-PIN]  ▶ Checking if stated goal is a solution-in-disguise...")
    _goal_check = await _run_goal_pin(session_id, adapter, enriched)
    _cs = state.get("current_stage") or {}
    _label = _cs.get("label", "Final Goal")
    if _goal_check.get("is_solution_in_disguise"):
        _implied = (_goal_check.get("implied_larger_goal") or "")[:60]
        dtrace(session_id, f"[GOAL-PIN]  ⚠ Solution-in-disguise — implied larger goal: \"{_implied}\"")
        _label = "Final Goal (possible precursor detected)"
        logger.warning(
            "[%s] goal-pin: possible solution-in-disguise — implied larger goal: %s",
            session_id, _goal_check.get("implied_larger_goal"),
        )
    _cs_with_goal = {**_cs, "goal_check": _goal_check, "label": _label}
    if not _goal_check.get("is_solution_in_disguise"):
        dtrace(session_id, f"[GOAL-PIN]  ✓ Goal pinned: \"{_label}\"  (laddered up: no)")

    return {
        "enriched_problem": enriched,
        "awaiting_human":   False,
        "rag_chunks":       rag_chunks,
        "current_stage":    _cs_with_goal,
    }


async def _run_goal_pin(session_id: str, adapter, enriched_problem: str) -> dict:
    """
    PHASE-B.2 / F5: F5 laddering check for Stage FINAL.
    Uses Sonnet (judgment call, not Haiku).
    Fails safe to is_solution_in_disguise=False so it never blocks a session.
    """
    try:
        resp = await adapter.complete(
            system_prompt=_GOAL_PIN_SYSTEM,
            user_prompt=f"Problem statement / brief:\n{enriched_problem[:800]}",
            model=settings.model_sonnet,
            max_tokens=200,
        )
        _record_usage(session_id, resp, "goal_pin")
        result = _parse_json_safe(resp.text, {"is_solution_in_disguise": False, "implied_larger_goal": None})
        return {
            "is_solution_in_disguise": bool(result.get("is_solution_in_disguise", False)),
            "implied_larger_goal":     result.get("implied_larger_goal"),
        }
    except Exception as exc:
        logger.warning(f"[{session_id}] goal_pin failed — skipping: {exc}")
        return {"is_solution_in_disguise": False, "implied_larger_goal": None}


# ── V5-E: 3-panel summary generation ──────────────────────────────────────────
# One expert turn renders at three depths: a 1-line gist (middle chat), a short
# paragraph (right stenographer, collapsed), and the full text (left reasoning /
# stenographer expanded). chat_line + steno_summary are two small Haiku calls;
# both fall back to a truncation of the full text so a turn is NEVER blocked (E13).

def _chat_line_fallback(text: str) -> str:
    """First sentence, capped ~140 chars — used if the Haiku 1-liner fails."""
    text = " ".join((text or "").split())
    if not text:
        return "(no summary)"
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return (first[:140].rstrip() + "…") if len(first) > 140 else first


def _steno_fallback(text: str) -> str:
    """First ~320 chars — used if the Haiku paragraph summary fails."""
    text = " ".join((text or "").split())
    return (text[:320].rstrip() + "…") if len(text) > 320 else (text or "(no summary)")


async def _summarize_turn(session_id: str, text: str) -> tuple[str, str]:
    """Produce (chat_line, steno_summary) for an expert turn via two small,
    concurrent Haiku calls. Each independently falls back to a truncation of
    `text` on error/empty — this coroutine never raises."""
    adapter = get_adapter()
    src = (text or "")[:4000]

    async def _one(system: str, max_tokens: int, fallback: str, tag: str) -> str:
        try:
            resp = await adapter.complete(
                system_prompt=system,
                user_prompt=src,
                model=settings.model_haiku,
                max_tokens=max_tokens,
            )
            _record_usage(session_id, resp, tag)
            out = (resp.text or "").strip()
            out = re.sub(r"^```[a-z]*\n?", "", out)
            out = re.sub(r"\n?```$", "", out).strip()
            return out or fallback
        except Exception as exc:
            logger.warning("[%s] %s summary failed — using truncation: %s", session_id, tag, exc)
            return fallback

    chat_line, steno_summary = await asyncio.gather(
        _one(
            "Summarize, in ONE sentence of at most 20 words, the single most important "
            "point this expert made. Plain text only — no preamble, no quotes.",
            60, _chat_line_fallback(text), "panel_chat_line",
        ),
        _one(
            "Summarize what this expert argued and concluded in 2-4 short sentences "
            "(one tight paragraph). Plain text only — no preamble, no headings.",
            220, _steno_fallback(text), "panel_steno",
        ),
    )
    return chat_line, steno_summary


# ── Expert node ───────────────────────────────────────────────────────────────

async def _run_expert(
    state: ChatState,
    role: str,
    system_prompt_override: str | None = None,
    user_prompt_override: str | None = None,
) -> dict:
    session_id = state["session_id"]
    turn = state["turn_count"]
    adapter = get_adapter()

    # V5-B THE CLOCK: the wall-clock zero is the first expert turn, not session
    # creation — intake/questionnaire/framing time does not count. Idempotent.
    _clock_mark_first_expert_turn(session_id)

    logger.info(f"[{session_id}] {role} speaking (turn {turn})")
    dtrace(session_id, f"[EXPERT]    ▶ {role} speaking (turn {turn})...")

    # Use override when provided (custom personas) — otherwise load from .md file
    persona = system_prompt_override if system_prompt_override else _load_persona(role)
    context = user_prompt_override if user_prompt_override else _build_expert_context(state, role)

    # FIX-4C: per-expert KB grounding — was framing-only
    # Skip for targeted cleanup prompts (user_prompt_override already focused).
    if not user_prompt_override:
        try:
            from backend.tools.search_kb import search_knowledge_base as _search_kb
            _kb_problem = state.get("enriched_problem") or state.get("problem_statement", "")
            _kb_query = f"{role.replace('_', ' ')} {_kb_problem[:200]}"
            _kb_chunks = await _search_kb(query=_kb_query, top_k=3)
            if _kb_chunks:
                _kb_text = "\n\n".join(
                    f"[{c.get('source', 'KB')}]: {c.get('content', '')[:300]}"
                    for c in _kb_chunks
                )
                context = f"Relevant knowledge:\n{_kb_text}\n\n{context}"
        except Exception as _kb_exc:
            logger.warning(f"[{session_id}] {role} per-expert KB search failed: {_kb_exc}")

    # V5-B THE CLOCK — Step 2: one-time soft nudge. When the supervisor fired the
    # nudge, the NEXT real expert turn (not cleanup corrections) gets a terse
    # time-pressure instruction. Consumed once. Invisible to the user except that
    # the answer comes back shorter and more convergent.
    if not user_prompt_override and session_id in _clock_nudge_pending:
        _clock_nudge_pending.discard(session_id)
        context = (
            "[TIME PRESSURE] The session is past the soft point of its time budget. "
            "Be concise and move toward converging on your lane's position — state "
            "your recommendation and key decisions directly and avoid re-opening "
            "settled points.\n\n"
        ) + context

    # V5-A: model + output cap driven by the seat's level bundle.
    # Reviewer/auditor are NOT expert calls and are NOT governed by this path.
    _seat_level  = _get_seat_level(state, role)
    _bundle      = LEVEL_BUNDLES.get(_seat_level, LEVEL_BUNDLES["L1"])
    _bundle_model_name = _bundle["model"]   # "sonnet" | "opus"
    _expert_model = (
        settings.model_opus   if _bundle_model_name == "opus"
        else settings.model_sonnet                              # L1 and L2 both Sonnet
    )
    _expert_max_tokens = _bundle["max_output_tokens"]
    _thinking_budget   = _bundle.get("thinking_budget", 0)
    # NOTE (V5-A STOP): extended thinking is intentionally NOT wired to the Bedrock
    # Converse call here. The correct additionalModelRequestFields key for thinking on
    # cross-region inference profiles (ARN-based, Claude claude-sonnet-4-5/claude-opus-4-5) has not been
    # confirmed against a live call. Passing the wrong key silently no-ops. See V5-B.
    dtrace(session_id,
        f"[EXPERT]    level={_seat_level} model={_bundle_model_name} "
        f"max_tokens={_expert_max_tokens} thinking_budget={_thinking_budget}(unwired)"
    )

    _expert_tokens = 0
    try:
        response = await adapter.complete(
            system_prompt=persona,
            user_prompt=context,
            model=_expert_model,
            max_tokens=_expert_max_tokens,
        )
        _record_usage(session_id, response, role)
        _expert_tokens = response.input_tokens + response.output_tokens

        # FIX-8 / PHASE-A: token ledger promoted to first-class; stage/audit
        # caps defined in config, enforced in Phase B.
        _session_token_totals[session_id] = (
            _session_token_totals.get(session_id, 0) + _expert_tokens
        )
        logger.info(
            "[%s] token ledger: %s used %d tokens this turn | session total=%d / budget=%d",
            session_id, role, _expert_tokens,
            _session_token_totals[session_id], settings.session_token_budget,
        )

        # FIX-8: app-level output truncation guard. Bedrock enforces max_tokens natively
        # (now 3000), so this path fires only on genuinely oversized edge cases.
        # Threshold updated to match the new token budget.
        raw_text = response.text
        node_max_chars = 3000 * 4  # 3000 tokens × ~4 chars/token
        if len(raw_text) > node_max_chars:
            _clean = re.sub(r"^```[a-z]*\n?", "", raw_text.strip())
            _clean = re.sub(r"\n?```$", "", _clean).strip()
            try:
                json.loads(_clean)
                # Valid JSON despite length — leave intact to avoid corruption
            except json.JSONDecodeError:
                raw_text = raw_text[:node_max_chars]
                logger.warning("FIX-8: response truncated to %d chars for %s", node_max_chars, role)

        parsed = _parse_expert_response(raw_text)
    except Exception as exc:
        _err_type = type(exc).__name__
        logger.warning(
            f"[{session_id}] [EXPERT] ✗ {role} call failed ({_err_type}) — unavailable this turn"
        )
        # Emit SSE events so the frontend can show a styled system bubble.
        asyncio.create_task(emit(session_id, "expert_error", {
            "role": role,
            "reason": "service timeout",
        }))
        await emit_message(
            session_id, "system",
            f"[{role.replace('_', ' ').title()} was unavailable this turn (service timeout).]",
            turn, is_private=False,
        )
        # Return WITHOUT adding to state.messages — a missing voice is NOT a vote.
        # Excluded from _check_consensus (speakers set) and the tripwire transcript.
        return {
            "messages":        [],
            "decisions":       [],
            "open_questions":  [],
            "current_speaker": None,
            "turn_count":      turn + 1,
            "last_nomination": None,
        }

    message = parsed["message"]
    reasoning = parsed["reasoning"]
    proposed = parsed["proposed_decisions"]
    open_qs = parsed["open_questions"]
    needs_human_input = parsed["needs_human_input"]
    next_domain = parsed.get("next_domain")  # PHASE-C.2: baton-pass nomination

    # Guard: CLI returned empty result — skip turn rather than emit empty bubble
    if not message.strip():
        logger.warning(
            f"[{session_id}] {role} returned EMPTY message at turn {turn} "
            f"(CLI empty result) — skipping turn"
        )
        await emit_message(
            session_id, "system",
            f"[{role.replace('_', ' ').title()} could not respond this turn — skipping]",
            turn, is_private=False,
        )
        return {
            "messages":        [],
            "decisions":       [],
            "open_questions":  [],
            "current_speaker": None,
            "turn_count":      turn + 1,
            "last_nomination": None,
        }

    # V5-E: emit the turn at three depths. Send immediately with truncation
    # fallbacks so nothing blocks; a background task upgrades chat_line +
    # steno_summary with the Haiku versions via a follow-up `turn_summary` event.
    await emit_message(
        session_id, role, message, turn, is_private=False,
        extra={
            "chat_line":     _chat_line_fallback(message),
            "steno_summary": _steno_fallback(message),
            "full_text":     message,
        },
    )

    async def _upgrade_summaries(_role=role, _turn=turn, _text=message):
        _cl, _ss = await _summarize_turn(session_id, _text)
        await emit(session_id, "turn_summary", {
            "role": _role, "turn": _turn,
            "chat_line": _cl, "steno_summary": _ss,
        })
    asyncio.create_task(_upgrade_summaries())

    asyncio.create_task(_persist_message(session_id, role, message, False, turn, _expert_tokens))
    if reasoning:
        asyncio.create_task(_persist_message(session_id, role, reasoning, True, turn))

    pub_msg = {
        "role": role,
        "content": message,
        "turn": turn,
        "is_private": False,
        "needs_human_input": needs_human_input,
    }
    priv_msg_list = (
        [{"role": role, "content": reasoning, "turn": turn, "is_private": True}]
        if reasoning else []
    )

    new_decisions = [
        {
            "id": str(uuid_module.uuid4()),
            "text": d,
            "proposed_by": role,
            "state": "proposed",
            "provenance": None,
            "supersedes_id": None,
        }
        for d in proposed
        if d.strip()
    ]

    for dec in new_decisions:
        asyncio.create_task(emit(session_id, "decision", dec))

    # Persist proposed decisions to DB so challenge_rounds FK is satisfiable
    if new_decisions:
        asyncio.create_task(_persist_decisions_db(session_id, new_decisions))

    dtrace(session_id,
        f"[EXPERT]    ✓ {role} proposed {len(new_decisions)} decision(s)"
        + (f"; nominated domain: {next_domain}" if next_domain else "")
    )
    if next_domain:
        logger.info("[%s] %s nominated next_domain=%r", session_id, role, next_domain)
        await emit(session_id, "domain_nominated", {"role": role, "domain": next_domain})

    return {
        "messages":        [pub_msg] + priv_msg_list,
        "decisions":       new_decisions,
        "open_questions":  open_qs,
        "current_speaker": None,
        "turn_count":      turn + 1,
        "last_nomination": next_domain,  # PHASE-C.2: carry baton to supervisor
    }


def make_expert_node(role: str):
    async def node(state: ChatState) -> dict:
        return await _run_expert(state, role)
    node.__name__ = role
    return node


# ── Phase 8 Slice 6: Generic custom persona node ──────────────────────────────

async def custom_persona_node(state: ChatState) -> dict:
    """
    Single graph node that serves ALL custom personas.
    Reads the current_speaker role name, looks up its definition in
    state["custom_personas"], and calls _run_expert with the custom
    system_prompt. This avoids adding new graph nodes at runtime —
    the LangGraph topology is fixed; only state changes at runtime.
    """
    session_id = state["session_id"]
    role = state.get("current_speaker", "custom_persona")
    persona_defs = state.get("custom_personas", [])
    persona = next((p for p in persona_defs if p["role"] == role), None)

    if not persona:
        logger.warning(
            f"[{session_id}] custom persona '{role}' not found in state — skipping turn"
        )
        return {"turn_count": state.get("turn_count", 0) + 1}

    return await _run_expert(
        state,
        role=persona["role"],
        system_prompt_override=persona["system_prompt"],
    )


ai_architect_node       = make_expert_node("ai_architect")
solution_architect_node = make_expert_node("solution_architect")
data_engineer_node      = make_expert_node("data_engineer")
data_scientist_node     = make_expert_node("data_scientist")
ai_engineer_node        = make_expert_node("ai_engineer")
solution_engineer_node  = make_expert_node("solution_engineer")


async def project_manager_node(state: ChatState) -> dict:
    # FIX-4A: deterministic timeline call — was never invoked
    result = await _run_expert(state, "project_manager")
    session_id = state["session_id"]

    # Derive timeline inputs from the PM's response
    pm_text = ""
    for msg in result.get("messages", []):
        if msg.get("role") == "project_manager" and not msg.get("is_private"):
            pm_text = msg.get("content", "")
            break
    pm_lower = pm_text.lower()
    complexity = "complex" if "complex" in pm_lower else "simple" if "simple" in pm_lower else "standard"
    features_count = max(1, len(result.get("decisions", [])) or 3)
    scope = {"complexity": complexity, "team_size": 3, "features_count": features_count}

    try:
        from backend.tools.estimate_timeline import estimate_timeline
        timeline = await estimate_timeline(scope)
        await emit(session_id, "tool_result", {
            "agent": "project_manager",
            "tool": "estimate_timeline",
            "result": timeline,
        })
        tool_msg = {
            "role":       "project_manager",
            "content":    f"[TIMELINE ESTIMATE]\n{json.dumps(timeline, indent=2)}",
            "turn":       state.get("turn_count", 0),
            "is_private": True,
        }
        result = {**result, "messages": result.get("messages", []) + [tool_msg]}
        logger.info(f"[{session_id}] estimate_timeline fired: total_weeks={timeline.get('total_weeks')}")
    except Exception as exc:
        logger.error(f"[{session_id}] estimate_timeline failed: {exc}")

    return result


async def ui_builder_node(state: ChatState) -> dict:
    # FIX-4B: deterministic mockup call — was never invoked
    result = await _run_expert(state, "ui_builder")
    session_id = state["session_id"]

    # Derive mockup spec from the UI Builder's response
    ub_text = ""
    for msg in result.get("messages", []):
        if msg.get("role") == "ui_builder" and not msg.get("is_private"):
            ub_text = msg.get("content", "")
            break
    component_description = (ub_text[:300].strip() if ub_text else
                             "Dashboard interface for the proposed solution")
    spec = {
        "session_id":            session_id,
        "component_description": component_description,
        "tech_stack":            "React, TypeScript",
        "color_scheme":          "professional",
    }

    try:
        from backend.tools.generate_mockup import generate_ui_mockup
        mockup = await generate_ui_mockup(spec)
        artifact_ref  = mockup.get("artifact_ref", "")
        preview_html  = mockup.get("preview_html", "")

        # Persist to UiMockup table
        try:
            import uuid as _uuid_m
            from datetime import datetime as _dt
            from backend.db.postgres import AsyncSessionLocal
            from backend.models import UiMockup
            async with AsyncSessionLocal() as db:
                db.add(UiMockup(
                    session_id=_uuid_m.UUID(session_id),
                    artifact_ref=artifact_ref,
                    created_at=_dt.utcnow(),
                ))
                await db.commit()
        except Exception as _db_exc:
            logger.warning(f"[{session_id}] UiMockup DB persist failed: {_db_exc}")

        await emit(session_id, "tool_result", {
            "agent":      "ui_builder",
            "tool":       "generate_ui_mockup",
            "result":     {"html": preview_html, "artifact_ref": artifact_ref, "exportable": True},
        })
        tool_msg = {
            "role":       "ui_builder",
            "content":    f"[UI MOCKUP GENERATED] artifact_ref={artifact_ref}",
            "turn":       state.get("turn_count", 0),
            "is_private": True,
        }
        result = {**result, "messages": result.get("messages", []) + [tool_msg]}
        logger.info(f"[{session_id}] generate_ui_mockup fired: artifact_ref={artifact_ref}")
    except Exception as exc:
        logger.error(f"[{session_id}] generate_ui_mockup failed: {exc}")

    return result


# ── Independent reviewer node ────────────────────────────────────────────────

_REVIEWER_WINDOW = 40  # messages fed to reviewer (wider than synthesis window)

_REVIEWER_SYSTEM = """
You are an independent auditor for a consulting council. You were not part of the
discussion. Your job is two-part: (1) flag issues, (2) deliver a pass/fail verdict.

WHAT TO FLAG (findings):
- FABRICATED CONFIDENCE: an expert asserted a specific number, deadline, or
  technology as decided fact when no evidence or reasoning was given.
- OWNER-AUTHORITY CALLS: a decision that legitimately requires the client/owner
  (budget approval, legal sign-off, org policy) was made by the council without
  flagging that it needs external confirmation.
- UNFLAGGED BEST-GUESSES: an expert used "probably", "should be fine", "typically"
  or similar hedging language for a load-bearing claim but presented it as settled.
- GENUINE GAPS OR CONFLICTS: important questions left unanswered, or two experts
  contradicting each other on a locked decision without resolution.

List up to 6 findings. For each: severity (high/medium/low), a one-sentence
description naming the agent(s) involved and quoting or closely paraphrasing the
claim, and agents_affected listing the role names of every expert whose output
the finding concerns (e.g. ["solution_architect", "data_engineer"]).

VERDICT:
After listing findings, decide: are the locked decisions a DEFENSIBLE DIRECTIONAL
STARTING POINT that a client could act on, despite remaining gaps?

- PASS if: the conclusions are concrete enough to move to the next precursor layer.
  Known gaps are fine as long as they are flagged (not hidden). High-severity
  findings about fabricated confidence or unresolved blocking contradictions must
  be absent or addressed.
- FAIL if: a locked decision rests on fabricated confidence, a blocking
  contradiction was never resolved, or a critical owner-authority call was made
  without flagging it. "Actionable with caveats" is a PASS, not a fail.

Return ONLY valid JSON:
{
  "passed": true|false,
  "verdict_rationale": "one sentence explaining the pass or fail decision",
  "findings": [
    {"severity": "high|medium|low", "description": "...", "agents_affected": ["role_name"]}
  ]
}
""".strip()


async def reviewer_node(state: ChatState) -> dict:
    session_id = state["session_id"]
    adapter = get_adapter()

    logger.info(f"[{session_id}] reviewer starting")
    _rev_stage_id = (state.get("current_stage") or {}).get("stage_id", "?")
    dtrace(session_id, f"[AUDITOR]   ▶ Stage {_rev_stage_id} under review...")
    await emit(session_id, "agent_start", {"agent_role": "reviewer", "phase": "review"})

    problem = state.get("enriched_problem") or state["problem_statement"]
    all_pub = [m for m in state.get("messages", []) if not m.get("is_private", False)]
    pub = all_pub[-_REVIEWER_WINDOW:]

    conversation = "\n".join(
        f"**{m['role']} (turn {m.get('turn', 0)})**: {m['content']}"
        for m in pub
    ) or "(no expert discussion recorded)"

    locked = [d for d in state.get("decisions", []) if d.get("state") == "locked"]
    decisions_text = "\n".join(
        f"- [{d.get('provenance', '?')}] {d.get('proposed_by', '?')}: {d['text']}"
        for d in locked
    ) or "(none locked)"

    reviewer_prompt = (
        f"Problem: {problem}\n\n"
        f"Expert Discussion:\n{conversation}\n\n"
        f"Locked Decisions:\n{decisions_text}\n\n"
        "Produce your independent review findings as JSON."
    )

    findings: list[dict] = []
    overall_assessment = ""
    _auditor_passed = False   # fail-safe default: broken audit retries rather than falsely closing
    _verdict_rationale = ""
    try:
        # FIX-P0.2: reviewer upgraded to Opus — catching gaps needs more capability
        # than generating prose (this is the one call where the Opus premium is justified)
        resp = await adapter.complete(
            system_prompt=_REVIEWER_SYSTEM,
            user_prompt=reviewer_prompt,
            model=settings.model_opus,
            max_tokens=1500,
        )
        _record_usage(session_id, resp, "reviewer")
        parsed = _parse_json_safe(resp.text, {"passed": False, "verdict_rationale": "", "findings": []})
        findings = parsed.get("findings", [])[:6]  # hard cap at 6
        # PHASE-B.2 / Fix 1b: auditor self-declares passed — no longer derived from
        # severity counts. Fail-safe: missing or unparseable "passed" defaults to False
        # so a broken audit retries rather than falsely closing the stage.
        _auditor_passed = bool(parsed.get("passed", False))
        _verdict_rationale = str(parsed.get("verdict_rationale", ""))
        # Legacy overall_assessment for any callers that still read it
        overall_assessment = _verdict_rationale or parsed.get("overall_assessment", "")
        logger.info(
            "[%s] reviewer: %d findings, auditor passed=%s — '%s'",
            session_id, len(findings), _auditor_passed, _verdict_rationale[:80],
        )
    except Exception as exc:
        logger.warning(f"[{session_id}] reviewer failed — skipping: {exc}")

    # PHASE-B.2: auditor writes a stage-keyed verdict. This is what the structural
    # invariant checks before allowing a stage to close.
    _cs = state.get("current_stage") or {}
    _prev_verdict = _cs.get("verdict")
    _prev_retry   = _prev_verdict.get("retry_count", 0) if _prev_verdict else -1
    _verdict = {
        "stage_id":        _cs.get("stage_id", "FINAL"),
        "passed":          _auditor_passed,
        "verdict_rationale": _verdict_rationale,
        "findings":        findings,
        "retry_count":     _prev_retry + 1,   # 0 on first pass, 1 on re-audit, etc.
    }
    _cs_with_verdict = {**_cs, "verdict": _verdict}
    logger.info(
        "[%s] reviewer verdict: passed=%s retry_count=%d",
        session_id, _verdict["passed"], _verdict["retry_count"],
    )
    _high_ct = sum(1 for f in findings if f.get("severity") == "high")
    _med_ct  = sum(1 for f in findings if f.get("severity") == "medium")
    dtrace(session_id,
        f"[AUDITOR]   {'✓' if _auditor_passed else '✗'} Verdict: passed={_auditor_passed}"
        f" (retry {_verdict['retry_count']}/{settings.max_audit_retries_per_stage})"
        f" — \"{_verdict_rationale[:80]}\""
    )
    if not _auditor_passed and (_high_ct or _med_ct):
        dtrace(session_id, f"[AUDITOR]   ✗ Findings: {_high_ct} high, {_med_ct} med")

    await emit(session_id, "reviewer_complete", {
        "findings":            findings,
        "overall_assessment":  overall_assessment,
        "verdict_rationale":   _verdict_rationale,
        "finding_count":       len(findings),
        "verdict_passed":      _verdict["passed"],
        "retry_count":         _verdict["retry_count"],
    })
    await emit(session_id, "agent_end", {"agent_role": "reviewer", "decisions_locked": []})

    return {
        "reviewer_findings": findings,
        "reviewer_done":     True,
        "current_stage":     _cs_with_verdict,
    }


# ── Cleanup round node ────────────────────────────────────────────────────────

async def cleanup_round_node(state: ChatState) -> dict:
    session_id  = state["session_id"]
    findings    = state.get("reviewer_findings", [])

    # Only high-severity findings trigger cleanup turns
    high = [f for f in findings if f.get("severity") == "high"]

    # Collect unique affected agents in finding order, cap at 3 turns
    seen: list[str] = []
    for f in high:
        for agent in f.get("agents_affected", []):
            if agent not in seen:
                seen.append(agent)
    cleanup_agents = seen[:3]
    if cleanup_agents:
        dtrace(session_id, f"[CLEANUP]   ▶ Routing findings back to: {cleanup_agents}")

    all_messages:  list[dict] = []
    all_decisions: list[dict] = []

    for agent in cleanup_agents:
        agent_findings = [f for f in high if agent in f.get("agents_affected", [])]
        finding_descs  = "\n".join(f"- {f['description']}" for f in agent_findings)
        targeted_prompt = (
            f"The independent reviewer flagged the following issue(s) in your analysis:\n"
            f"{finding_descs}\n\n"
            "CORRECTION RULES:\n"
            "1. Do NOT retract or remove any decision. Retracting leaves the council with "
            "nothing to lock and will fail the next audit.\n"
            "2. For FABRICATED CONFIDENCE: re-state the decision with explicit uncertainty. "
            "Drop the unsupported number; keep the technology choice flagged as best-guess. "
            "Example — 'Lambda costs $40/month' becomes "
            "'Use AWS Lambda for compute (best-guess — actual cost requires traffic profiling)'.\n"
            "3. For OWNER-AUTHORITY: add the [OWNER-AUTHORITY] prefix instead of removing the "
            "decision. Example — '[OWNER-AUTHORITY] Recommend Auth0 over Cognito (best-guess) "
            "— requires client budget approval'.\n"
            "4. You must end this turn with AT LEAST the same number of decisions, now corrected.\n\n"
            f"{_CLEANUP_DECISION_RULES}"
        )
        try:
            cleanup_result = await _run_expert(
                state,
                role=agent,
                user_prompt_override=targeted_prompt,
            )
            all_messages.extend(cleanup_result.get("messages", []))
            all_decisions.extend(cleanup_result.get("decisions", []))
        except Exception as exc:
            logger.error(f"[{session_id}] cleanup turn for {agent} failed: {exc}")

    await emit(session_id, "cleanup_complete", {
        "turns_taken":       len(cleanup_agents),
        "agents_addressed":  cleanup_agents,
    })

    # PHASE-B.2 / Step 3: if the verdict's retry_count has hit the cap, flag for
    # route_from_cleanup so it routes to synthesis rather than back to reviewer.
    # This guarantees the loop is airtight — never more than max_audit_retries_per_stage.
    _cs_verdict = (state.get("current_stage") or {}).get("verdict") or {}
    _retry_count = _cs_verdict.get("retry_count", 0)
    _exhausted   = _retry_count >= settings.max_audit_retries_per_stage

    result: dict = {
        "messages":            all_messages,
        "decisions":           all_decisions,
        "cleanup_round_done":  True,
        "turn_count":          state.get("turn_count", 0),  # don't increment — infrastructure turns
    }
    if _exhausted:
        logger.warning(
            "[%s] audit retry cap hit (retry_count=%d >= max=%d) — escalating to synthesis",
            session_id, _retry_count, settings.max_audit_retries_per_stage,
        )
        result["termination_reason"] = "audit_retries_exhausted"
    return result


# ── Stage transition infrastructure (PHASE-B.3) ──────────────────────────────


async def _compact_stage(
    session_id: str,
    adapter,
    stage: dict,
    pub_messages: list[dict],
    locked_decisions: list[dict],
) -> str:
    """
    Summarize a just-closed (passing) stage into a compact brief for the next stage.
    Uses Haiku (summarization task, not analysis). Fails safe to a concat of
    locked decisions rather than blocking progress.
    """
    locked_text = "\n".join(
        f"- {d.get('text', '')}" for d in locked_decisions
    ) or "(none)"
    msg_text = "\n".join(
        f"{m.get('role','?')} (turn {m.get('turn',0)}): {m.get('content','')[:200]}"
        for m in pub_messages[-15:]
    ) or "(no discussion)"
    try:
        resp = await adapter.complete(
            system_prompt=(
                "Summarize this stage's discussion into a compact brief for the next "
                "stage of deliberation. Preserve concrete decisions and constraints. "
                "Do not editorialize."
            ),
            user_prompt=(
                f"Stage: {stage.get('label','?')}\n\n"
                f"Discussion:\n{msg_text}\n\n"
                f"Locked decisions:\n{locked_text}"
            ),
            model=settings.model_haiku,
            max_tokens=500,
        )
        _record_usage(session_id, resp, "stage_compact")
        return resp.text.strip()
    except Exception as exc:
        logger.warning(f"[{session_id}] _compact_stage failed — falling back to decisions: {exc}")
        return f"Stage '{stage.get('label','?')}' locked decisions:\n{locked_text}"


async def _check_precursor(
    session_id: str,
    adapter,
    enriched_problem: str,
    brief_stack: list[dict],
    depth_tier: str,
    stage_stack_len: int,
    just_closed_brief: str = "",
) -> dict:
    """
    PHASE-B.3: stop classifier — decide whether to descend to a new precursor stage
    or bottom out to synthesis. CAP CHECK FIRST (mirrors questionnaire classifier design).

    Returns {"bottomed_out": bool, "next_label": str|None, "next_focus": str|None}
    Fails safe to bottomed_out=True (fail toward finishing, not runaway descent).

    KNOWN LIMIT: this classifier has no reliable self-bottoming behaviour — in isolated
    testing it returned descend on 8/8 inputs including vacuous ones. Safe at cap=2
    (the cap forces bottom-out after one descent). BEFORE raising max_stages_cap above 2,
    retune this prompt to genuinely detect atomic/bottom conclusions, or the staircase
    will descend to the cap every time regardless of problem depth.
    """
    # Cap always wins — if adding one more stage would hit the cap, skip the classifier
    if stage_stack_len + 1 >= settings.max_stages_cap:
        logger.info(
            "[%s] precursor check: cap hit (%d+1 >= %d) — forcing bottom-out",
            session_id, stage_stack_len, settings.max_stages_cap,
        )
        return {"bottomed_out": True, "next_label": None, "next_focus": None, "reason": "cap"}

    _tier_model = settings.model_opus if depth_tier == "deep" else settings.model_sonnet
    briefs_text = "\n\n".join(
        f"[{e['stage_id']} — {e['label']}]: {e['brief']}"
        for e in brief_stack
    ) or "(no prior stages)"

    # Fix 3: include the just-closed stage's brief so the classifier knows what was
    # decided — previously this was blind to stage conclusions, causing S1 to re-litigate
    # Stage FINAL's locked decisions.
    closed_brief_section = (
        f"\nThe stage you are descending FROM concluded:\n{just_closed_brief}\n"
        "Do not re-open these decisions; identify the PRECURSOR that must be solved "
        "before them.\n"
    ) if just_closed_brief else ""

    _PRECURSOR_SYSTEM = """
Given the Final Goal and the stages resolved so far (see the brief stack),
determine whether the stage that just closed still implies an unresolved PRECURSOR —
a deeper layer of decisions that must be made before this stage's conclusions are
actionable. If yes, name it concisely (a short label) and describe its focus in one
sentence. If the stage's conclusions are already actionable/concrete with nothing
further to resolve, say so.

Return ONLY valid JSON:
{"bottomed_out": true|false, "next_label": "..." or null, "next_focus": "..." or null}
""".strip()

    try:
        resp = await adapter.complete(
            system_prompt=_PRECURSOR_SYSTEM,
            user_prompt=(
                f"Final Goal: {enriched_problem[:400]}\n\n"
                f"{closed_brief_section}"
                f"Prior stage briefs:\n{briefs_text}"
            ),
            model=_tier_model,
            max_tokens=200,
        )
        _record_usage(session_id, resp, "precursor_check")
        result = _parse_json_safe(
            resp.text,
            {"bottomed_out": True, "next_label": None, "next_focus": None},
        )
        return {
            "bottomed_out":  bool(result.get("bottomed_out", True)),
            "next_label":    result.get("next_label"),
            "next_focus":    result.get("next_focus"),
        }
    except Exception as exc:
        logger.warning(f"[{session_id}] _check_precursor failed — defaulting to bottom-out: {exc}")
        return {"bottomed_out": True, "next_label": None, "next_focus": None}


async def stage_transition_node(state: ChatState) -> dict:
    """
    PHASE-B.3: runs when a stage passes its audit.
    1. Compacts the passed stage → brief_stack entry.
    2. Runs the precursor stop-classifier.
    3. If bottom-out: signals routing to synthesis. Does NOT touch stage_stack
       or current_stage — B.1's synthesis_node closure handles the final append.
    4. If descend: closes+appends OLD current_stage (with brief), creates NEW
       current_stage, resets per-stage flags so the new stage runs fully.
    """
    session_id  = state["session_id"]
    adapter     = get_adapter()
    depth_tier  = state.get("depth_tier", "shallow")
    current_stage = state.get("current_stage") or {}
    stage_stack   = state.get("stage_stack", [])

    # Collect this stage's public messages and locked decisions for compaction
    stage_start = state.get("stage_turn_offset", 0)
    pub_all     = [m for m in state.get("messages", []) if not m.get("is_private")]
    stage_msgs  = [m for m in pub_all if m.get("turn", 0) >= stage_start]
    locked      = [d for d in state.get("decisions", []) if d.get("state") == "locked"]

    # OPEN-3B: lock any proposed decisions that survived to this passing verdict.
    # First-pass: proposed list is empty (supervisor already locked before routing to reviewer) → no-op.
    # Retry-pass: cleanup turns added proposals; supervisor's lock window closed before they existed.
    # stage_transition_node only runs when _stage_can_close=True (verdict.passed=True),
    # so this lock is always gated on a passing auditor verdict — the invariant holds.
    import uuid as _uuid_st
    _proposed_to_lock = [
        d for d in state.get("decisions", [])
        if d.get("state") == "proposed" and d.get("text", "").strip()
    ]
    _stage_locks = [
        {
            "id":            str(_uuid_st.uuid4()),
            "text":          d["text"],
            "proposed_by":   d["proposed_by"],
            "state":         "locked",
            "provenance":    "audit_pass",
            "supersedes_id": d["id"],
        }
        for d in _proposed_to_lock
    ]
    if _stage_locks:
        asyncio.create_task(_persist_decisions_db(session_id, _stage_locks))
        logger.info(
            "[%s] stage_transition: locking %d proposed decisions on passing verdict (audit_pass)",
            session_id, len(_stage_locks),
        )
        dtrace(session_id,
            f"[STAGE-LOCK] ▶ Locking {len(_stage_locks)} proposed decisions on passing audit verdict"
        )
        locked = locked + _stage_locks  # extend for _compact_stage so brief reflects full locked set

    brief = await _compact_stage(session_id, adapter, current_stage, stage_msgs, locked)

    # V5-B THE CLOCK: at a hard stop (time_wrap / timeout / budget) the session
    # must close — do NOT open a new precursor stage even if this stage's audit
    # passed. This also fixes the latent case where the precursor classifier
    # (which descends on nearly every input) would descend under a resource stop.
    if state.get("termination_reason") in _CLOCK_HARD_STOPS:
        logger.info(
            "[%s] stage_transition: hard stop (%s) — forcing bottom-out, no descent",
            session_id, state.get("termination_reason"),
        )
        precursor = {"bottomed_out": True, "next_label": None, "next_focus": None}
    else:
        precursor = await _check_precursor(
            session_id, adapter,
            state.get("enriched_problem") or state.get("problem_statement", ""),
            list(state.get("brief_stack", [])),
            depth_tier,
            len(stage_stack),
            just_closed_brief=brief,   # Fix 3: classifier now sees what FINAL decided
        )

    bottomed_out  = precursor["bottomed_out"]
    next_label    = precursor.get("next_label")
    next_focus    = precursor.get("next_focus")

    await emit(session_id, "stage_transition", {
        "from_stage":   current_stage.get("stage_id", "?"),
        "from_label":   current_stage.get("label", "?"),
        "bottomed_out": bottomed_out,
        "next_label":   next_label,
        "brief_length": len(brief),
    })

    if bottomed_out:
        # Bottom-out: push brief to brief_stack; do NOT close or append current_stage
        # (synthesis_node's B.1 closure logic handles that unchanged).
        logger.info("[%s] stage_transition: bottom-out → synthesis", session_id)
        dtrace(session_id, "[BOTTOM]    ▶ Staircase bottomed out → final synthesis")
        return {
            "brief_stack":        [{"stage_id": current_stage.get("stage_id","?"),
                                    "label": current_stage.get("label","?"),
                                    "brief": brief}],
            "stage_bottomed_out": True,
            **({"decisions": _stage_locks} if _stage_locks else {}),
        }
    else:
        # Descend: close OLD stage (with brief), push to stage_stack,
        # create NEW current_stage, reset per-stage gating flags.
        _closed_old = {**current_stage, "brief": brief, "closed": True}
        new_stage_id  = f"S{len(stage_stack) + 1}"  # "S1" for first descent
        _new_stage = {
            "stage_id": new_stage_id,
            "label":    next_label or f"Precursor {new_stage_id}",
            "brief":    None,
            "verdict":  None,
            "closed":   False,
        }
        logger.info(
            "[%s] stage_transition: descending to %s (%s)",
            session_id, new_stage_id, _new_stage["label"],
        )
        _new_brief_depth = len(state.get("brief_stack", [])) + 1
        dtrace(session_id,
            f"[DESCEND]   ▶ Stage {current_stage.get('stage_id','?')} closed"
            f" → compacting brief → descending to next precursor"
        )
        dtrace(session_id,
            f"[DESCEND]   ✓ New stage {new_stage_id} ({_new_stage['label']})"
            f" | brief_stack depth={_new_brief_depth}"
        )
        dtrace(session_id,
            f"[STAGE]     ▶ ══ STAGE {new_stage_id} ({_new_stage['label']}) opened"
            f"  |  depth={depth_tier} ══"
        )
        return {
            "brief_stack":         [{"stage_id": _closed_old["stage_id"],
                                     "label": _closed_old["label"],
                                     "brief": brief}],
            "stage_stack":         [_closed_old],   # appended via Annotated[add] reducer
            "current_stage":       _new_stage,
            "stage_bottomed_out":  False,
            **({"decisions": _stage_locks} if _stage_locks else {}),
            # Reset per-stage flags so the new stage's review chain runs fully
            "reviewer_done":             False,
            "cleanup_round_done":        False,
            # PHASE-C.3: reset D-o-C + tripwire state so the new stage runs fresh
            "doc_committed_this_stage":  False,
            "tripwire_probe_count":      0,
            "doc_round_count_this_stage": 0,   # FIX-DOC: clear loop counter for new stage
            # On descent, reset termination_reason so supervisor dispatches S1 experts
            # rather than being short-circuited by the prior stage's stop signal.
            # consensus/consensus_by_supervisor/user_finalize are stage-LOCAL — they mean
            # "Stage FINAL reached consensus", not "the whole session must stop". Keeping
            # them causes route_from_supervisor's branch 3 to route to reviewer immediately,
            # skipping expert dispatch entirely for S1.
            # Only hard resource limits (timeout, budget, time_wrap) are session-wide
            # and should persist. (In practice the hard-stop guard above forces
            # bottom-out, so this descent branch is not reached under a hard stop —
            # kept consistent for defence in depth.)
            "termination_reason": (
                state.get("termination_reason")
                if state.get("termination_reason") in _CLOCK_HARD_STOPS
                else None
            ),
            "current_speaker":     None,
            "stage_turn_offset":   state.get("turn_count", 0),  # consensus counts from here
        }


# ── Synthesis helpers ─────────────────────────────────────────────────────────

def _dedup_decisions(decisions: list[dict]) -> list[dict]:
    """Collapse near-duplicate decisions at render time. Never mutates the live ledger."""
    import re as _re

    def _mk(text: str) -> str:
        t = text.lower()
        t = _re.sub(r'^\[owner-authority\]\s*', '', t)
        t = _re.sub(r'\(best-guess[^)]*\)', '', t)
        t = _re.sub(r'\([^)]*\$[^)]*\)', '', t)
        t = _re.sub(r'\s+', ' ', t).strip()
        return t

    groups: dict[str, list[dict]] = {}
    for d in decisions:
        key = _mk(d.get("text", ""))
        groups.setdefault(key, []).append(d)

    result: list[dict] = []
    for group in groups.values():
        best = max(group, key=lambda d: len(d.get("text", "")))
        result.append(best)
    return result


def _extract_themes(decisions: list[dict]) -> str:
    """Return a short phrase of top themes from the first few decisions."""
    samples = [
        d.get("text", "")[:80].split(".")[0].strip()
        for d in decisions[:3]
        if d.get("text")
    ]
    return "; ".join(samples)


# ── Synthesis node ────────────────────────────────────────────────────────────

async def synthesis_node(state: ChatState) -> dict:
    session_id = state["session_id"]
    adapter = get_adapter()

    logger.info(f"[{session_id}] synthesis starting")

    problem = state.get("enriched_problem") or state["problem_statement"]

    # FIX-10: was feeding full un-truncated transcript — quality risk on long sessions
    all_pub = [m for m in state.get("messages", []) if not m.get("is_private", False)]
    window = settings.synthesis_transcript_window
    dropped = all_pub[:-window] if len(all_pub) > window else []
    pub = all_pub[-window:]

    # Build opening context block — rolling_summary SUBSTITUTES for the dropped tail
    # rather than stacking on top of it (avoids double-counting the same content).
    rolling_summary = state.get("rolling_summary", "")
    dropped_summary = ""
    if dropped:
        if rolling_summary:
            # Use existing rolling summary as the stand-in for dropped messages
            dropped_summary = rolling_summary
        else:
            # No rolling summary exists — create one from the dropped tail (cheap Haiku call)
            dropped_text = "\n".join(
                f"{m['role']} (turn {m.get('turn', 0)}): {m['content'][:200]}"
                for m in dropped
            )
            try:
                _summ_resp = await adapter.complete(
                    system_prompt=(
                        "Summarize the key technical decisions and discussion points "
                        "from these expert conversation excerpts in 2-3 paragraphs."
                    ),
                    user_prompt=dropped_text,
                    model=settings.model_haiku,
                    max_tokens=500,
                )
                _record_usage(session_id, _summ_resp, "synthesis_summary")
                dropped_summary = _summ_resp.text
            except Exception as _summ_exc:
                logger.warning(f"[{session_id}] dropped-message summary failed: {_summ_exc}")
                dropped_summary = f"[{len(dropped)} earlier messages not shown]"

    # Collect locked decisions — iterate in reverse so the latest entry
    # per text wins; dedup by text to avoid counting superseded+new pairs.
    all_decisions = state.get("decisions", [])
    locked_states = [d.get("state") for d in all_decisions]
    logger.info(
        f"[{session_id}] synthesis entry: "
        f"{len(all_decisions)} decisions, states={locked_states}"
    )
    seen_texts: set[str] = set()
    locked: list[dict] = []
    for d in reversed(all_decisions):
        text = d.get("text", "")
        if d.get("state") == "locked" and d.get("category") != "procedure_log" and text not in seen_texts:
            seen_texts.add(text)
            locked.append(d)
    logger.info(f"[{session_id}] synthesis: locked decisions found={len(locked)}")
    _syn_stages = len(state.get("stage_stack", [])) + 1
    dtrace(session_id,
        f"[SYNTH]     ▶ Stitching {len(locked)} locked decisions"
        f" across {_syn_stages} stage(s) into deliverable..."
    )

    # Fallback: if no locked entries found, lock all proposed entries right
    # here in synthesis (handles the case where locking happened in the same
    # turn as synthesis routing)
    if not locked:
        import uuid as _uuid_syn
        logger.warning(
            f"[{session_id}] synthesis: no locked decisions "
            f"found, locking all proposed as fallback"
        )
        proposed_all = [d for d in all_decisions if d.get("state") == "proposed"]
        locked = [
            {
                "id":            str(_uuid_syn.uuid4()),
                "text":          d["text"],
                "proposed_by":   d["proposed_by"],
                "state":         "locked",
                "provenance":    "converged",
                "supersedes_id": d["id"],
            }
            for d in proposed_all
        ]
        if locked:
            asyncio.create_task(_persist_decisions_db(session_id, locked))

    # Dedup for render only — does not touch the live ledger or DB writes
    render_locked = _dedup_decisions(locked)
    if len(render_locked) < len(locked):
        logger.info(
            f"[{session_id}] synthesis dedup: {len(locked)} → {len(render_locked)} decisions"
        )

    # Build windowed conversation — prepend summary block if messages were dropped
    conv_parts = []
    if dropped_summary:
        conv_parts.append(f"[Summary of earlier exchanges]: {dropped_summary}")
    conv_parts.extend(
        f"**{m['role']} (turn {m.get('turn', 0)})**: {m['content']}"
        for m in pub
    )
    conversation = "\n".join(conv_parts) or "(no expert discussion recorded)"

    decisions_text = "\n".join(
        f"- [{d.get('provenance', '?')}] {d.get('proposed_by', '?')}: {d['text']}"
        for d in render_locked
    ) or "(none locked)"

    synthesis_user = (
        f"Problem: {problem}\n\n"
        f"Expert Discussion:\n{conversation}\n\n"
        f"Locked Decisions ({len(render_locked)} total):\n{decisions_text}\n\n"
        "Synthesize into a comprehensive solution document. "
        "Include ALL locked decisions verbatim in the key_decisions list."
    )

    # Part E: give synthesis explicit awareness of reviewer findings and cleanup
    if state.get("reviewer_findings"):
        findings_text = "\n".join(
            f"- [{f.get('gap_type', 'finding').upper()}] {f.get('description', '')}"
            for f in state["reviewer_findings"]
        )
        synthesis_user += f"\n\nReviewer findings addressed in cleanup:\n{findings_text}"

    # Part C (FIX-5) / V5-B: when synthesis is forced by the clock (timeout or the
    # V5-B time_wrap), flag the incomplete coverage so the doc is honest about it.
    if state.get("termination_reason") in ("timeout", "time_wrap"):
        synthesis_preamble = (
            "Note: this session reached its time budget before all workstreams "
            "were fully closed. Synthesise the best possible solution from what "
            "was actually decided. Clearly note any workstreams or stages that "
            "were not fully closed due to the time budget — do NOT present "
            "unfinished or un-audited work as complete."
        )
    else:
        synthesis_preamble = ""
    effective_synthesis_system = (
        f"{synthesis_preamble}\n\n{_SYNTHESIS_SYSTEM}" if synthesis_preamble
        else _SYNTHESIS_SYSTEM
    )

    # Level 1: normal structured-output call
    doc = None
    try:
        resp = await adapter.complete(
            system_prompt=effective_synthesis_system,
            user_prompt=synthesis_user,
            model=settings.model_opus,
            max_tokens=8000,
        )
        _record_usage(session_id, resp, "synthesis")
        _parsed = _parse_json_safe(resp.text, None)
        if _parsed and isinstance(_parsed, dict):
            doc = _parsed
        else:
            logger.warning(
                f"[{session_id}] [SYNTH] Level 1 parse failed "
                f"(non-JSON response) → Level 2"
            )
    except Exception as _l1_exc:
        logger.warning(
            f"[{session_id}] [SYNTH] Level 1 failed "
            f"({type(_l1_exc).__name__}) → Level 2"
        )

    if doc is None:
        # Level 2: single plain-prose call — no JSON schema, no parsing
        _fallback_summary = ""
        try:
            _fb_resp = await adapter.complete(
                system_prompt=(
                    "You are the lead consulting architect. "
                    "Write a 3-4 sentence executive summary of the technical solution "
                    "based on the locked decisions listed. "
                    "Return plain prose only — no JSON, no bullet points, no headers."
                ),
                user_prompt=(
                    f"Problem: {problem}\n\n"
                    f"Locked decisions ({len(render_locked)}):\n{decisions_text}"
                ),
                model=settings.model_opus,
                max_tokens=3000,
            )
            _record_usage(session_id, _fb_resp, "synthesis_fallback")
            _fallback_summary = _fb_resp.text.strip()
            logger.info(f"[{session_id}] [SYNTH] Level 2 succeeded")
        except Exception as _l2_exc:
            logger.warning(
                f"[{session_id}] [SYNTH] Level 2 failed "
                f"({type(_l2_exc).__name__}) → Level 3"
            )

        # Level 3: deterministic — no model call, cannot fail
        if not _fallback_summary:
            _themes = _extract_themes(render_locked)
            _n = len(render_locked)
            _fallback_summary = (
                f"This session produced {_n} decision{'s' if _n != 1 else ''}"
                + (f" covering {_themes}" if _themes else "")
                + ". See the full list below."
            )
            logger.info(f"[{session_id}] [SYNTH] Level 3 fired — deterministic string, no model call")

        doc = {
            "executive_summary": _fallback_summary,
            "recommended_architecture": "See key decisions below.",
            "key_decisions": [d.get("text", "") for d in render_locked[:20]],
            "implementation_phases": [],
            "risks": [],
            "open_items": [],
        }

    # ── V5-B THE CLOCK — Step 4 / E9: wrap accounting on the deliverable ──────
    # When the clock wrapped the session, prepend an honest banner and — if the
    # current stage did NOT pass its audit — attach the auditor's findings as
    # visible open items. Never present a failed/un-audited stage as closed/green.
    if state.get("termination_reason") in _CLOCK_HARD_STOPS:
        _cs_now       = state.get("current_stage") or {}
        _cs_verdict   = _cs_now.get("verdict") or {}
        _stage_passed = _cs_verdict.get("passed") is True
        _stages_total  = len(state.get("stage_stack", [])) + 1
        _stages_closed = len(state.get("stage_stack", [])) + (1 if _stage_passed else 0)
        _wrap_elapsed  = _elapsed_seconds(state)
        _banner = (
            f"⏱ Wrapped at time budget ({round(_wrap_elapsed)}s) — "
            f"{_stages_closed} of {_stages_total} stage(s) closed."
        )
        doc["executive_summary"] = f"{_banner}\n\n{doc.get('executive_summary', '')}".strip()
        if not _stage_passed:
            _open = list(doc.get("open_items") or [])
            _open.append(
                f"[UNCLOSED STAGE {_cs_now.get('stage_id', '?')}] Shipped without a "
                f"passing audit verdict at time-wrap — treat the items below as open."
            )
            _wrap_findings = _cs_verdict.get("findings") or state.get("reviewer_findings") or []
            for _f in _wrap_findings[:6]:
                _sev  = str(_f.get("severity", "?")).upper()
                _desc = _f.get("description") or _f.get("title") or _f.get("gap_type") or "audit finding"
                _open.append(f"[AUDIT {_sev}] {_desc}")
            doc["open_items"] = _open
        logger.info(
            "[%s] time-wrap deliverable: %s (stage_passed=%s, open_items=%d)",
            session_id, _banner, _stage_passed, len(doc.get("open_items") or []),
        )
        dtrace(session_id,
            f"[CLOCK]     ⏱ Deliverable: {_stages_closed}/{_stages_total} stage(s) closed"
            + ("" if _stage_passed else " — current stage NOT closed (audit findings attached as open items)"))

    import json as _json
    sol_path = Path(f"data/sessions/{session_id}/solution.json")
    sol_path.parent.mkdir(parents=True, exist_ok=True)
    sol_path.write_text(_json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    try:
        import uuid as _uuid
        from sqlalchemy import select as _sd_select
        from backend.db.postgres import AsyncSessionLocal
        from backend.models import SolutionDocument
        async with AsyncSessionLocal() as db:
            # Idempotent: skip insert if a row already exists (guards double-synthesis)
            existing = await db.execute(
                _sd_select(SolutionDocument).where(
                    SolutionDocument.session_id == _uuid.UUID(session_id)
                )
            )
            if existing.scalar_one_or_none() is None:
                sd = SolutionDocument(
                    session_id=_uuid.UUID(session_id),
                    structured_content=doc,
                )
                db.add(sd)
                await db.commit()
            else:
                logger.info(
                    f"[{session_id}] solution_documents already exists — skipping insert"
                )
    except Exception as exc:
        logger.warning(f"[{session_id}] solution_documents insert failed: {exc}")

    # Persist locked decisions synchronously before emitting session_complete
    # so DB rows exist when the client queries immediately after the event.
    if locked:
        await _persist_decisions_db(session_id, locked)

    # Persist termination_reason to the sessions table
    _term = state.get("termination_reason") or "consensus"
    try:
        import uuid as _uuid_tr
        from sqlalchemy import update as _sa_update
        from backend.models import Session as _SessModel
        async with AsyncSessionLocal() as db:
            await db.execute(
                _sa_update(_SessModel)
                .where(_SessModel.id == _uuid_tr.UUID(session_id))
                .values(termination_reason=_term)
            )
            await db.commit()
        logger.info(f"[{session_id}] termination_reason persisted: {_term}")
    except Exception as _tr_exc:
        logger.warning(f"[{session_id}] termination_reason persist failed: {_tr_exc}")

    # Write accumulated token totals to Session DB row
    _cost_acc = _session_cost.get(session_id, {})
    try:
        import uuid as _uuid_tok
        from sqlalchemy import update as _sa_tok_upd
        from backend.models import Session as _SessModel_tok
        async with AsyncSessionLocal() as _db_tok:
            await _db_tok.execute(
                _sa_tok_upd(_SessModel_tok)
                .where(_SessModel_tok.id == _uuid_tok.UUID(session_id))
                .values(
                    total_input_tokens=_cost_acc.get("input_tokens", 0),
                    total_output_tokens=_cost_acc.get("output_tokens", 0),
                    cached_tokens=(
                        _cost_acc.get("cache_creation_tokens", 0)
                        + _cost_acc.get("cache_read_tokens", 0)
                    ),
                )
            )
            await _db_tok.commit()
    except Exception as _tok_exc:
        logger.warning(f"[{session_id}] token totals persist failed: {_tok_exc}")

    await emit(session_id, SESSION_COMPLETE, {
        "solution_document":     doc,
        "locked_decisions":      locked,
        # Legacy fields (kept for backward compat)
        "total_tokens":          _cost_acc.get("input_tokens", 0) + _cost_acc.get("output_tokens", 0),
        "cost_usd":              _cost_acc.get("total_cost_usd", 0.0),
        # Full usage breakdown for CostPanel
        "total_cost_usd":        _cost_acc.get("total_cost_usd", 0.0),
        "total_input_tokens":    _cost_acc.get("input_tokens", 0),
        "total_output_tokens":   _cost_acc.get("output_tokens", 0),
        "cache_creation_tokens": _cost_acc.get("cache_creation_tokens", 0),
        "cache_read_tokens":     _cost_acc.get("cache_read_tokens", 0),
        "total_duration_ms":     _cost_acc.get("total_duration_ms", 0),
        "by_model":              _cost_acc.get("by_model", {}),
    })
    _session_cost.pop(session_id, None)   # prevent unbounded growth
    _clock_cleanup(session_id)            # V5-B: drop per-session CLOCK state
    _done_tokens = _cost_acc.get("input_tokens", 0) + _cost_acc.get("output_tokens", 0)
    dtrace(session_id,
        f"[DONE]      ✓ Session complete"
        f" | tokens={_done_tokens:,}"
        f" | stages={_syn_stages}"
        f" | reason={state.get('termination_reason') or 'consensus'}"
    )

    try:
        from backend.memory.compressor import compress_session
        asyncio.create_task(compress_session(session_id, state["user_id"]))
    except Exception as exc:
        logger.warning(f"[{session_id}] memory compression task failed: {exc}")

    termination = state.get("termination_reason") or "consensus"
    logger.info(f"[{session_id}] synthesis complete, reason={termination}")

    # PHASE-B.1: record the completed run as Stage FINAL in stage_stack.
    # Behavior-inert bookkeeping — proves stage state populates and checkpoints
    # correctly before B.2/B.3 make behavior depend on it.
    _result: dict = {"solution_document": doc, "termination_reason": termination}
    _current_stage = state.get("current_stage")
    if _current_stage is not None:
        # E9: under a clock wrap the closing audit may have FAILED — in that case
        # the stage ships explicitly NOT closed. The non-wrap path is unchanged
        # (closed=True) so existing consensus behaviour is untouched.
        if termination in _CLOCK_HARD_STOPS:
            _closed_flag = (_current_stage.get("verdict") or {}).get("passed") is True
        else:
            _closed_flag = True
        _closed_stage = {**_current_stage, "closed": _closed_flag}
        _result["current_stage"] = _closed_stage
        _result["stage_stack"]   = [_closed_stage]  # appended via Annotated[add] reducer
        logger.info(
            f"[{session_id}] stage_stack: Stage "
            f"{_current_stage.get('stage_id', 'FINAL')} → stage_stack (closed={_closed_flag})"
        )
    return _result


# ── Phase 5: ask_human_node ───────────────────────────────────────────────────

# Per-session cache — prevents double-emit when LangGraph re-runs node on resume
_ask_human_questions: dict[str, str] = {}

# Safety net: cap how many times the graph may pause for human input per session.
# If an expert keeps emitting needs_human_input=true (e.g. bad prompt), this
# prevents an infinite interrupt loop.
_ask_human_count: dict[str, int] = {}
ASK_HUMAN_MAX = 2


async def ask_human_node(state: ChatState) -> dict:
    """
    Mid-conversation human input node.
    Uses interrupt() — same pattern as framing_node.
    Fires when an expert explicitly sets needs_human_input=true.
    Guarded by ASK_HUMAN_MAX to prevent infinite interrupt loops.
    """
    from langgraph.types import interrupt
    session_id = state["session_id"]

    open_qs = state.get("open_questions", [])
    unresolved = [q for q in open_qs if not q.startswith("[RESOLVED]")]

    # ── Safety cap ────────────────────────────────────────────────────────────
    count = _ask_human_count.get(session_id, 0)
    if count >= ASK_HUMAN_MAX:
        logger.warning(
            f"[ROUTE] [{session_id}] ask_human cap ({ASK_HUMAN_MAX}) reached "
            f"— auto-continuing without human input"
        )
        return {
            "messages": [],
            "open_questions": ([f"[RESOLVED] {unresolved[-1]}"] if unresolved else []),
            "awaiting_human": False,
            "human_input": None,
        }
    _ask_human_count[session_id] = count + 1

    question = (
        unresolved[-1] if unresolved
        else "Do you have any additional context to share?"
    )

    if session_id not in _ask_human_questions:
        _ask_human_questions[session_id] = question
        await emit(session_id, HUMAN_INPUT_REQUIRED, {
            "question": question,
            "turn": state["turn_count"],
        })
        logger.info(f"[{session_id}] ask_human: pausing for human input")

    answer = interrupt({"type": "human_input", "question": question})
    _ask_human_questions.pop(session_id, None)

    await emit(session_id, HUMAN_INPUT_RECEIVED, {
        "question": question,
        "answer": str(answer)[:200],
    })

    human_msg = {
        "role": "human",
        "content": f"[Human: {answer}]",
        "turn": state["turn_count"],
        "is_private": False,
    }
    asyncio.create_task(
        _persist_message(session_id, "human", human_msg["content"], False, state["turn_count"])
    )

    return {
        "messages": [human_msg],
        "open_questions": [f"[RESOLVED] {question}"],
        "awaiting_human": False,
        "human_input": str(answer),
    }
