from operator import add
from typing import Annotated, Optional, TypedDict


class ChatState(TypedDict):
    # Immutable problem context
    session_id: str
    user_id: str
    problem_statement: str
    enriched_problem: str          # grows after framing questions
    roster: Annotated[list[str], lambda a, b: b]  # overwrite (last write wins)

    # The public conversation channel
    # Each message: {"role": str, "content": str,
    #                "turn": int, "is_private": bool}
    messages: Annotated[list[dict], add]      # append only

    # Decision lifecycle record
    # Each entry: {"id": str, "text": str, "proposed_by": str,
    #              "state": str, "provenance": str|None,
    #              "supersedes_id": str|None}
    decisions: Annotated[list[dict], add]     # append only

    # Open questions that haven't been answered yet
    open_questions: Annotated[list[str], add]

    # The rolling summary of older turns (updated periodically)
    rolling_summary: str

    # Orchestrator control fields
    current_speaker: Optional[str]    # which expert speaks next
    turn_count: int
    awaiting_human: bool              # True when graph is paused
    human_input: Optional[str]        # injected when human responds
    termination_reason: Optional[str]

    # RAG context (populated once at session start)
    rag_chunks: Annotated[list[dict], add]

    # Prior-session summaries injected at session start (append-only)
    # These are BACKGROUND ONLY — best-guess summaries from past sessions.
    memory_context: Annotated[list[str], add]

    # Prior owner rulings injected at session start (append-only)
    # AUTHORITATIVE — actual decisions the owner locked in prior sessions
    # on the same problem thread. Scoped by 0.82 similarity (same lineage guard
    # as memory_context). DISTINCT from memory_context: always injected before
    # summaries and labeled as authoritative constraints, not background context.
    owner_rulings_context: Annotated[list[str], add]

    # Final output
    solution_document: Optional[dict]

    # User-created persona definitions (overwrite reducer — last write wins)
    # Each entry: {role, display_name, system_prompt, emoji, color}
    custom_personas: Annotated[list[dict], lambda a, b: b]

    # ── Independent reviewer fields (Pillar 4) ────────────────────────────────
    # Each finding: {"gap_type": "gap|conflict|risk|redundancy",
    #                "description": str, "agents_affected": list[str],
    #                "severity": "high"|"medium"|"low"}
    reviewer_findings: Annotated[list[dict], lambda a, b: b]  # overwrite
    reviewer_done: bool        # True once reviewer_node completes (or fails)
    cleanup_round_done: bool   # True once cleanup_round_node completes (or fails)

    # ── Wall-clock timeout (FIX-5) ────────────────────────────────────────────
    # unix timestamp set when the session is created (sessions.py initial_state).
    # supervisor_node reads this to enforce SESSION_TIMEOUT_SECONDS.
    session_start_time: Optional[float]

    # TASK-2.1: depth tier — shallow=Sonnet, deep=Opus for expert calls.
    # Reviewer model is independent of this (always Opus, per FIX-P0.2) —
    # do not make reviewer conditional on this field.
    depth_tier: str  # "shallow" | "deep" — set at session creation, read by _run_expert

    # PHASE-A: expert registry — dynamic-ready shape, seeded with fixed roster.
    # Dynamic seating/retirement lands in Phase C.
    # Each seat: {"role": str, "domain_tags": list[str], "seated": bool, "provenance": str}
    # provenance: "seed" | "recruited" | "user_added"  (Phase A only writes "seed")
    expert_registry: Annotated[list[dict], lambda a, b: b]  # overwrite (last write wins)

    # PHASE-B.1: stage scaffolding. Introduces the stage concept WITHOUT behavior change —
    # max_stages_cap=1 means the whole run is one stage (Stage FINAL).
    # Descent, per-stage verdicts, and the brief stack arrive in B.2/B.3.
    #
    # Stage dict shape (extend consistently in B.2/B.3):
    #   {"stage_id": str,          # "FINAL" for top stage; later "S1","S2"...
    #    "label": str,             # human-readable, e.g. "Final Goal"
    #    "brief": Optional[str],   # compacted brief — populated in B.3
    #    "goal_check": Optional[dict],  # F5 goal-pin result — populated in B.2
    #                                   # {"is_solution_in_disguise": bool, "implied_larger_goal": str|None}
    #    "verdict": Optional[dict],# auditor verdict — populated in B.2
    #                               # {"stage_id": str, "passed": bool,
    #                               #  "findings": list[dict], "retry_count": int}
    #    "closed": bool}           # True once the stage is complete
    stage_stack: Annotated[list[dict], add]   # append-only; stages accumulate as descent proceeds
    current_stage: Optional[dict]             # the stage currently executing; overwrite

    # PHASE-B.3: compacted working memory between stages.
    # Distinct from stage_stack (which holds full closed-stage records with verdicts).
    # brief_stack is what descended stages' experts actually read.
    # Each entry: {"stage_id": str, "label": str, "brief": str}
    brief_stack: Annotated[list[dict], add]   # append-only, one entry per closed stage

    # PHASE-B.3: turn offset for per-stage consensus detection.
    # Set to turn_count at the start of each new stage (descend or session start).
    # _check_consensus uses this to count only messages from the current stage.
    stage_turn_offset: int

    # PHASE-B.3: routing signal from stage_transition_node.
    # True = bottomed out → route to synthesis. False = descending → route to supervisor.
    stage_bottomed_out: bool

    # TASK-2.2: reverse-engineered questionnaire state.
    # questionnaire_qa is raw and NEVER fed to framing/council directly —
    # only problem_brief (compacted) is consumed downstream.
    problem_brief: Optional[str]                              # compacted output of questionnaire, consumed by framing
    questionnaire_qa: Annotated[list[dict], add]              # raw Q&A pairs — append only, never fed to council
    questionnaire_question_count: int                         # increments each question asked
    questionnaire_done: bool                                  # True once brief is produced
    contradiction_branches: Annotated[list[dict], add]        # deep-mode: sub-branches that received per-branch cycles

    # ── PHASE-C.2: Baton-pass / expert recruitment ───────────────────────────
    # last_nomination: next_domain nominated by the most recent expert.
    # Consumed once by supervisor_node's baton-pass resolver; None after processing.
    last_nomination: Optional[str]           # overwrite (last write wins)

    # recruitment_pending_domain: domain held across a borderline escalation cycle.
    # Set when gate returns "borderline" and cleared after the user's seat/skip ruling.
    recruitment_pending_domain: Optional[str]  # overwrite

    # ── PHASE-C.1: Moderator escalation channel ───────────────────────────────
    # pending_escalation: set when a fork requires human arbitration.
    # Schema: {"reason": str, "summary": str,
    #          "options": [{"id": str, "label": str, "impact": str}]}
    pending_escalation: Optional[dict]   # overwrite (last write wins)

    # escalation_ruling: the human's choice after the escalation resolves.
    # Schema: {"chosen_option_id": str, "note": str}
    # Stays in state as context for all downstream nodes.
    escalation_ruling: Optional[dict]    # overwrite (last write wins)

    # ── PHASE-C.3: D-o-C + Tripwire per-stage flags ──────────────────────────
    # doc_committed_this_stage: True once all experts committed in a D-o-C round
    # for the current stage. Cleared on stage descent. Replaces the module-level
    # _doc_started dict so the flag survives interrupt/replay and supervisor
    # re-entries without risk of cross-session contamination.
    doc_committed_this_stage: bool       # overwrite (last write wins)

    # tripwire_probe_count: how many tripwire-triggered probes have been used for
    # the current stage. Cleared on stage descent. Replaces _tripwire_probe_count.
    tripwire_probe_count: int            # overwrite (last write wins)

    # FIX-DOC: how many D-o-C rounds have fired in the current stage.
    # Cleared on stage descent. Guards against infinite disagree-or-commit spirals.
    doc_round_count_this_stage: int      # overwrite (last write wins)


INITIAL_STATE: dict = {
    "messages": [],
    "decisions": [],
    "open_questions": [],
    "rolling_summary": "",
    "current_speaker": None,
    "turn_count": 0,
    "awaiting_human": False,
    "human_input": None,
    "termination_reason": None,
    "rag_chunks": [],
    "memory_context": [],
    "owner_rulings_context": [],        # PHASE-C.4a: prior owner rulings (authoritative)
    "solution_document": None,
    "enriched_problem": "",
    "roster": [],
    "custom_personas": [],
    "reviewer_findings": [],
    "reviewer_done": False,
    "cleanup_round_done": False,
    "session_start_time": None,  # set to time.time() in sessions.py initial_state
    "expert_registry": [],           # PHASE-A: seeded at session creation in sessions.py
    "stage_stack": [],               # PHASE-B.1: accumulates closed stages; seeded in sessions.py
    "current_stage": None,           # PHASE-B.1: seeded to Stage FINAL in sessions.py
    "brief_stack": [],               # PHASE-B.3: compacted briefs of closed stages
    "stage_turn_offset": 0,          # PHASE-B.3: turn_count at start of current stage
    "stage_bottomed_out": False,     # PHASE-B.3: routing signal from stage_transition_node
    "depth_tier": "shallow",         # TASK-2.1: safe default — existing callers unaffected
    "problem_brief": None,           # TASK-2.2: set by questionnaire, consumed by framing
    "questionnaire_qa": [],
    "questionnaire_question_count": 0,
    "questionnaire_done": False,
    "contradiction_branches": [],
    "last_nomination": None,            # PHASE-C.2
    "recruitment_pending_domain": None, # PHASE-C.2
    "pending_escalation": None,         # PHASE-C.1
    "escalation_ruling": None,          # PHASE-C.1
    "doc_committed_this_stage": False,  # PHASE-C.3
    "tripwire_probe_count": 0,          # PHASE-C.3
    "doc_round_count_this_stage": 0,    # FIX-DOC: cleared on stage descent
}
