User types problem
        ↓
POST /api/sessions → session_id returned
        ↓
Background task: _run_graph() fires
  (LangGraph StateGraph with MemorySaver checkpointer)
        ↓
┌─────────────────────────────────────────────────────┐
│ GRAPH ENTRY: supervisor_node                        │
│                                                     │
│ On first turn:                                      │
│   1. Fetch cross-session memory (fetch_memory tool) │
│   2. RAG pre-fetch (search_knowledge_base tool)     │
│   3. Decide roster (manual pick OR auto-select      │
│      from problem via Sonnet call)                  │
│   4. Ask framing questions via LangGraph interrupt  │
│      → SSE → clarification_required                 │
│      → chat PAUSES, waits for human                 │
│      → POST /api/sessions/{id}/clarify resumes it   │
│   enriched_problem = original + all Q&A             │
└─────────────────────────────────────────────────────┘
        ↓
        ↓ (graph resumes from checkpoint after human answers)
        ↓
┌─────────────────────────────────────────────────────┐
│ SUPERVISOR LOOP  ← this cycles every turn           │
│                                                     │
│ After EVERY expert message, control returns here.   │
│ Supervisor evaluates the full ChatState and decides:│
│                                                     │
│  A. Route to an expert node                         │
│     → MoE gating: only activate relevant experts    │
│     → Sonnet call with persona system prompt        │
│     → Expert thinks privately, posts to public      │
│       channel (is_private=False message)            │
│     → SSE → message event streams to frontend       │
│     → Supervisor checks for contradictions          │
│                                                     │
│  B. Route BACK to challenged expert (contradiction) │
│     → Max 2 debate rounds per decision              │
│     → If converged: decision.state = 'locked'       │
│     → If deadlocked after 2 rounds: interrupt()     │
│       → show human both positions + 3 options:      │
│         1. "Go with best" → supervisor decides      │
│         2. "Show reasoning" → surface private       │
│            reasoning, stay paused until decisive    │
│         3. Human states own decision → locked       │
│                                                     │
│  C. Interrupt to ask human for info                 │
│     → Any expert can trigger this mid-conversation  │
│     → LangGraph interrupt() halts the graph         │
│     → Chat pauses, question shown to user           │
│     → Graph resumes from checkpoint on answer       │
│                                                     │
│  D. Terminate + synthesise (checked every turn):    │
│     Priority 1: user said "finalize"                │
│     Priority 2: consensus reached                   │
│       (no open questions + no contested decisions   │
│        + required experts contributed)              │
│     Priority 3: hard ceiling hit                    │
│       (turn limit OR wall-clock timeout             │
│        OR token budget exceeded)                    │
└─────────────────────────────────────────────────────┘
        ↓ (termination condition met)
        ↓
┌─────────────────────────────────────────────────────┐
│ SYNTHESIS NODE                                      │
│ Opus reads full public chat transcript              │
│   + all locked decisions (with provenance)          │
│   + rolling summary of older turns                  │
│ Produces structured solution document               │
│ Saved to DB (solution_documents table)              │
│ SSE → session_complete                              │
└─────────────────────────────────────────────────────┘
        ↓
Background: compress_session()
  Sonnet: distil to 200-word summary
  Embed summary (all-MiniLM-L6-v2)
  Encrypt (Fernet)
  Store in PostgreSQL memory_entries
        ↓
Next session for same user:
  fetch_memory() → inject top-2 relevant summaries
  Supervisor sees prior context at session start


─────────────────────────────────────────────────────
DECISION LIFECYCLE (append-only, never hard-deleted)
─────────────────────────────────────────────────────

  PROPOSED ──────────────────────────→ LOCKED
    │                                    │
    ↓ (another expert contests it)       │ (new info
  CHALLENGED                             │  emerges)
    │                                    ↓
    ↓ (resolved within 2 rounds      SUPERSEDED
       OR human arbitrated)          (linked to
    → LOCKED                          replacement)


─────────────────────────────────────────────────────
CONTEXT MODEL (two-tier)
─────────────────────────────────────────────────────

  PUBLIC CHANNEL (all experts see this):
    - All chat messages
    - Proposed + locked decisions
    - Enriched problem statement
    - RAG chunks
    - Rolling summary of older turns

  PRIVATE REASONING (per-expert, not shared):
    - Each expert's internal chain-of-thought
    - Only surfaced on demand during arbitration
      when human chooses "Show me the reasoning"


─────────────────────────────────────────────────────
WHAT STAYS FROM v2.0 / WHAT CHANGED
─────────────────────────────────────────────────────

  UNCHANGED:
    PostgreSQL + Redis + ChromaDB infrastructure
    JWT auth (register/login/get_current_user)
    RAG service (embeddings, reranker, KB, cache)
    Cross-session memory (compression, encryption)
    8 expert persona prompts (reused as node prompts)
    4 custom tools (search_kb, fetch_memory,
      estimate_timeline, generate_ui_mockup)
    Claude CLI adapter with retry/backoff
    SSE emitter (emit(), get_queue())
    Logfire observability
    Rate limiting + input sanitization

  REPLACED:
    run_session() linear loop
      → LangGraph StateGraph (_run_graph)
    Fixed phases + phase_barrier
      → Dynamic supervisor routing (concept deleted)
    scratchpad JSON file
      → LangGraph ChatState object
    Upfront-only clarifier (asyncio.Queue)
      → interrupt() node (callable at any point)
    Phase-cluster frontend
      → Chat interface (Phase 7 of build)


─────────────────────────────────────────────────────
BUILD PHASES (v3.0)
─────────────────────────────────────────────────────

  Phase 1: LangGraph skeleton + State + DB migration  ✅ DONE
  Phase 2: Real expert nodes + Claude calls + SSE
  Phase 3: Supervisor routing + MoE gating
  Phase 4: Contradiction detection + arbitration
  Phase 5: Interrupt nodes (human-in-loop)
  Phase 6: Synthesis + memory + termination
  Phase 7: Chat frontend (replace phase-cluster UI)
  Phase 8: Hardening + observability + tests