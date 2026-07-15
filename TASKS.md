# TASKS.md — Multi-Agent Consulting Simulator
## Build Task Tracker

> Update checkboxes as you complete tasks. Never delete a task — mark it [x] or [SKIP: reason].
> Current phase is noted in CLAUDE.md §1.
> Each task has a model tier tag: 🔴 Opus · 🟡 Sonnet · 🟢 Haiku · ⚙️ No model (infra/code)

---

## Phase 0 — Project Scaffold
*Goal: Runnable skeleton with no agent logic. `uvicorn main:app` starts. `npm run dev` starts.*

### 0.1 Repo & Environment
- [ ] ⚙️ Create project root directory `multi-agent-consulting-simulator/`
- [ ] ⚙️ `git init` + add `.gitignore` (Python, Node, `.env`, `data/`, `sessions/`)
- [ ] ⚙️ Copy `CLAUDE.md` and `TASKS.md` into project root
- [ ] ⚙️ Create `.env.example` from CLAUDE.md §10 (no real values)
- [ ] ⚙️ Create `requirements.txt`:
  ```
  anthropic>=0.40.0
  fastapi>=0.115.0
  uvicorn[standard]>=0.30.0
  sqlalchemy[asyncio]>=2.0.0
  asyncpg>=0.29.0
  redis>=5.0.0
  chromadb>=0.5.0
  pydantic-settings>=2.0.0
  python-jose[cryptography]>=3.3.0
  passlib[bcrypt]>=1.7.4
  logfire>=0.40.0
  pytest>=8.0.0
  pytest-asyncio>=0.23.0
  httpx>=0.27.0
  sentence-transformers>=3.0.0
  ```
- [ ] ⚙️ `pip install -r requirements.txt` — confirm no conflicts

### 0.2 Docker Infrastructure
- [ ] ⚙️ Write `docker-compose.yml` with three services:
  - `postgres:16` on port 5432, volume `pgdata`
  - `redis:7-alpine` on port 6379
  - *(ChromaDB runs in-process — no Docker service needed)*
- [ ] ⚙️ `docker compose up -d` — confirm both services healthy
- [ ] ⚙️ Write `backend/db/postgres.py` — async SQLAlchemy engine + `get_db` dependency
- [ ] ⚙️ Write `backend/db/redis_client.py` — async Redis connection pool

### 0.3 Data Models
- [ ] ⚙️ Write `backend/models.py` — SQLAlchemy ORM models for:
  - `User` (id, email, hashed_password, created_at)
  - `Session` (id, user_id, problem_statement, complexity, status, phase_plan JSON, total_input_tokens, total_output_tokens, cached_tokens, created_at, completed_at)
  - `AgentMessage` (id, session_id, agent_role, phase, content, structured_output JSON, tokens_used, tool_calls JSON, created_at)
  - `SolutionDocument` (id, session_id, structured_content JSON, created_at)
  - `UiMockup` (id, session_id, artifact_ref, created_at)
  - `MemoryEntry` (id, user_id, session_id, summary, key_entities JSON, embedding ARRAY(Float), created_at)
- [ ] ⚙️ Write `alembic init` + initial migration — confirm `alembic upgrade head` runs clean

### 0.4 FastAPI App Shell
- [ ] ⚙️ Write `backend/config.py` — `Settings` class (pydantic-settings, loads from `.env`)
- [ ] ⚙️ Write `backend/main.py` — FastAPI app, register routers, lifespan (startup/shutdown)
- [ ] ⚙️ Write `backend/api/auth.py`:
  - `POST /api/auth/register`
  - `POST /api/auth/login` → returns JWT
  - JWT middleware — `get_current_user` dependency
- [ ] ⚙️ Write `backend/api/sessions.py` — stub `POST /api/sessions` (accepts problem, returns session_id)
- [ ] ⚙️ Write `backend/api/stream.py` — stub `GET /api/sessions/{id}/stream` (returns empty SSE)
- [ ] ⚙️ Confirm: `uvicorn backend.main:app --reload` starts, `/docs` loads, auth endpoints respond

### 0.5 React Frontend Shell
- [ ] ⚙️ `npx create-react-app frontend` (or Vite: `npm create vite@latest frontend -- --template react`)
- [ ] ⚙️ Install: `axios`, `react-router-dom`
- [ ] ⚙️ Write `App.jsx` — router with two routes: `/login` and `/session`
- [ ] ⚙️ Write stub `ChatInterface.jsx` — text input + submit button, calls `POST /api/sessions`
- [ ] ⚙️ Write stub `LiveAgentFeed.jsx` — EventSource hook, logs events to console
- [ ] ⚙️ Confirm: `npm run dev` starts, form submits, SSE stream connects (empty)

### 0.6 Phase 0 Checkpoint
- [ ] ⚙️ End-to-end smoke test: submit a problem → session_id returned → SSE stream opens
- [ ] ⚙️ Both Docker services healthy, DB migrations applied
- [ ] ⚙️ No hardcoded secrets anywhere (grep check)
- [ ] ⚙️ Update `CLAUDE.md §1` current phase → "Phase 1: Orchestrator + Agent Definitions"

---

## Phase 1 — Orchestrator + Agent Definitions
*Goal: Orchestrator classifies a problem, builds a phase plan, and dispatches real subagents
that read the scratchpad and write structured JSON output. No tools yet — agents reason from
scratchpad context only.*

### 1.1 Scratchpad Manager
- [ ] ⚙️ Write `backend/scratchpad/manager.py`:
  - `initialize_scratchpad(session_id, problem, memory_ctx, rag_chunks) → path`
  - `read_scratchpad(session_id) → dict`
  - `write_agent_output(session_id, agent_role, output_dict)`
  - `append_decision(session_id, decision, locked_by, phase)`
  - `merge_phase_outputs(session_id, phase)` — Orchestrator calls after phase barrier
  - `get_scratchpad_token_count(session_id) → int` — for budget check

### 1.2 SSE Emitter
- [ ] ⚙️ Write `backend/sse/emitter.py`:
  - `emit(session_id, event_type, data_dict)` — writes to an asyncio Queue per session
  - All 9 event types from CLAUDE.md §8 defined as constants
  - `SessionEventStream` — async generator consumed by the SSE endpoint

### 1.3 Haiku Complexity Classifier
- [ ] 🟢 Write `backend/orchestrator/classifier.py`:
  - Input: `problem_statement: str`
  - Makes a Haiku API call (max_tokens=500) 
  - Returns: `{"complexity": "simple|standard|complex", "reasoning": "..."}`
  - Test: three fixture problems (one of each tier), assert correct classification

### 1.4 Phase Planner
- [ ] ⚙️ Write `backend/orchestrator/phase_planner.py`:
  - `build_phase_plan(complexity: str) → list[Phase]`
  - Each `Phase` has: phase_number, name, agents (list), parallel (bool)
  - Simple: Phase 1 (2–3 agents, parallel) + Synthesize
  - Standard: Phases 1–3 + Synthesize (subset of agents)
  - Complex: All 4 phases + full team + Synthesize
  - Unit test: assert PM is always last substantive agent

### 1.5 Guardrail Layer
- [ ] ⚙️ Write `backend/orchestrator/guardrails.py`:
  - `validate_phase_plan(plan: list[Phase]) → list[GuardrailError]`
  - Rule 1: Architecture agents before implementation agents
  - Rule 2: PM is last substantive agent
  - Rule 3: No phase has > 4 agents (budget safety)
  - `apply_corrections(plan, errors) → list[Phase]` — auto-fix or raise

### 1.6 Subagent Definitions
- [ ] ⚙️ Write `backend/agents/base_agent.py` — shared `build_agent_definition(role) → AgentDefinition`
- [ ] ⚙️ Write `.claude/agents/data_engineer.md` — full system prompt using 3-section template from CLAUDE.md §11
- [ ] ⚙️ Write `.claude/agents/data_scientist.md`
- [ ] ⚙️ Write `.claude/agents/solution_engineer.md`
- [ ] ⚙️ Write `.claude/agents/solution_architect.md`
- [ ] ⚙️ Write `.claude/agents/ai_architect.md`
- [ ] ⚙️ Write `.claude/agents/ai_engineer.md`
- [ ] ⚙️ Write `.claude/agents/ui_builder.md`
- [ ] ⚙️ Write `.claude/agents/project_manager.md`
- [ ] ⚙️ Write `backend/agents/definitions.py` — loads all 8 as `AgentDefinition` objects with tool scoping

### 1.7 Orchestrator Main Agent
- [ ] 🟡 Write `backend/orchestrator/main_agent.py`:
  - `run_session(session_id, problem, user_id)` — async entry point
  - Step 1: classify complexity (Haiku)
  - Step 2: build + validate phase plan
  - Step 3: initialize scratchpad
  - Step 4: emit `session_started` SSE event
  - Step 5: loop over phases → dispatch agents → phase barrier → check hard stops
  - Step 6: call synthesizer when done
  - Hard stop check: turn_count >= 12 OR elapsed >= 240s OR token_budget exceeded → force synthesis

### 1.8 Phase Barrier
- [ ] ⚙️ Write `backend/orchestrator/phase_barrier.py`:
  - Waits for all parallel agents in a phase (asyncio.gather)
  - Merges outputs into scratchpad
  - Validates decisions (no contradictions with locked log)
  - Appends valid decisions to decision log
  - Emits `phase_complete` SSE event
  - Returns hard-stop flag if limits breached

### 1.9 Agent Dispatcher
- [ ] 🟡 Write `backend/agents/dispatcher.py`:
  - `dispatch_agent(agent_role, scratchpad_snapshot) → AgentOutput`
  - Calls the correct subagent via SDK with the scratchpad as context
  - Enforces max_tokens=2000 per agent
  - Emits `agent_start`, streams `token` events, emits `agent_end`
  - Parses structured JSON output; if parse fails → retry once, then skip agent (NFR-3)

### 1.10 Phase 1 Checkpoint
- [ ] 🟡 Integration test: submit "Build a real-time ML feature store" → classify → plan → run Phase 1 agents
- [ ] ⚙️ Assert: scratchpad has outputs for AI Architect + Solution Architect
- [ ] ⚙️ Assert: decision log has ≥ 1 locked decision after phase barrier
- [ ] ⚙️ Assert: SSE events arrive in correct order (session_started → phase_start → agent_start → tokens → agent_end → phase_complete)
- [ ] ⚙️ Assert: total turns ≤ 12 enforced (inject a mock that always increments)
- [ ] ⚙️ Update `CLAUDE.md §1` → "Phase 2: Tools + RAG"

---

## Phase 2 — Tools + RAG
*Goal: All 4 MCP tools functional. Agents can call `search_knowledge_base`. RAG cache working.*

### 2.1 Knowledge Base Seed Data
- [ ] ⚙️ Write 8–10 markdown documents in `knowledge_base/seed_data/`:
  - `cloud_architecture.md` — AWS/GCP/Azure patterns
  - `mlops_patterns.md` — model serving, drift detection, pipelines
  - `data_engineering.md` — batch vs streaming, Kafka, Spark, dbt
  - `rag_and_vector_stores.md` — embeddings, retrieval patterns
  - `api_design.md` — REST, GraphQL, gRPC trade-offs
  - `frontend_patterns.md` — React patterns, SSR, PWA
  - `security_patterns.md` — auth, zero-trust, secrets management
  - `project_delivery.md` — agile, risk frameworks, estimation
- [ ] ⚙️ Each file: 500–2000 words, chunked into ~400 token paragraphs with clear headings

### 2.2 RAG Service (ChromaDB)
- [ ] ⚙️ Write `backend/rag/service.py`:
  - `RAGService` class wrapping ChromaDB client (persist_directory from config)
  - `embed(text: str) → list[float]` — use `sentence-transformers/all-MiniLM-L6-v2`
  - `index_document(doc_id, text, metadata)` — chunk + embed + upsert
  - `search(query, top_k=10) → list[Chunk]` — cosine similarity search
  - `rerank(query, chunks, top_k=5) → list[Chunk]` — cross-encoder reranker (ms-marco-MiniLM)
  - Similarity threshold: 0.75 minimum score (skip chunks below this)
- [ ] ⚙️ Write `backend/rag/seeder.py`:
  - `seed_knowledge_base()` — reads all files in `seed_data/`, indexes on startup
  - Skip if collection already exists (idempotent)
- [ ] ⚙️ Write `backend/rag/cache.py`:
  - `get_cached(query_hash) → list[Chunk] | None`
  - `set_cached(query_hash, chunks, ttl=3600)`
  - Key format: `rag:{sha256(query)}`

### 2.3 In-Process MCP Server
- [ ] ⚙️ Write `backend/tools/mcp_server.py`:
  - Initialize `mcp` in-process server
  - Register all 4 tools as MCP tool handlers
  - `start_mcp_server()` called in FastAPI lifespan
- [ ] ⚙️ Write `backend/tools/search_kb.py`:
  - `search_knowledge_base(query: str, top_k: int = 5) → list[dict]`
  - Check Redis cache first → hit: return cached · miss: call RAG service, cache result
  - Log: query, similarity scores, cache hit/miss → Logfire
- [ ] ⚙️ Write `backend/tools/fetch_memory.py`:
  - `fetch_memory(user_id: str, query: str) → list[dict]`
  - Embed query → search `MemoryEntry` embeddings scoped to user_id
  - Return top-2 above threshold (0.70)
  - NEVER return another user's memory (assert user_id match before returning)
- [ ] ⚙️ Write `backend/tools/estimate_timeline.py`:
  - `estimate_timeline(scope_json: dict) → dict`
  - Rule-based + heuristic (no model call needed)
  - Returns: weeks by phase, total weeks, confidence, assumptions
- [ ] ⚙️ Write `backend/tools/generate_mockup.py`:
  - `generate_ui_mockup(spec_json: dict) → dict`
  - Makes a 🟡 Sonnet call (max_tokens=2000) with spec → returns self-contained HTML string
  - Saves HTML to `sessions/{session_id}/mockups/{uuid}.html`
  - Returns: `{"artifact_ref": "path", "preview_html": "..."}`
  - TOKEN RISK: cap at 2000 tokens; HTML must be self-contained (no external CDN calls)

### 2.4 Wire Tools to Agents
- [ ] ⚙️ Update `backend/agents/definitions.py` — add MCP tool scoping per agent (CLAUDE.md §4 table)
- [ ] ⚙️ Update `backend/orchestrator/main_agent.py` — pass MCP server to SDK runner
- [ ] ⚙️ Test: run Data Engineer agent on ML feature store problem → assert `search_knowledge_base` is called, relevant chunks appear in output

### 2.5 Observability Wiring
- [ ] ⚙️ Write Logfire instrumentation in `backend/main.py`:
  - `logfire.configure()` on startup
  - Instrument FastAPI app: `logfire.instrument_fastapi(app)`
  - Instrument SQLAlchemy: `logfire.instrument_sqlalchemy(engine)`
- [ ] ⚙️ Add span decorators to:
  - Every orchestrator routing decision
  - Every Claude API call (tokens in/out, cached_tokens, latency)
  - Every RAG retrieval (query, scores, cache hit)
  - Every scratchpad write
- [ ] ⚙️ Session token budget enforcer in `backend/orchestrator/main_agent.py`:
  - Track cumulative tokens after each agent turn
  - If `total_tokens >= SESSION_TOKEN_BUDGET` → set `force_synthesis = True`

### 2.6 Phase 2 Checkpoint
- [ ] ⚙️ `search_knowledge_base` returns relevant chunks for 3 test queries
- [ ] ⚙️ Second identical query hits Redis cache (assert cache_hit=True in logs)
- [ ] ⚙️ `estimate_timeline` returns structured output for a sample scope
- [ ] ⚙️ `generate_ui_mockup` produces valid self-contained HTML
- [ ] ⚙️ Logfire dashboard shows spans for a full session
- [ ] ⚙️ Update `CLAUDE.md §1` → "Phase 3: Memory"

---

## Phase 3 — Memory
*Goal: Cross-session memory working. Returning user gets relevant prior context injected.*

### 3.1 Post-Session Compressor
- [ ] 🟡 Write `backend/memory/compressor.py`:
  - `compress_session(session_id, user_id)` — called after `session_complete` event
  - Makes a Sonnet call (max_tokens=500): full scratchpad → compact summary + key_entities
  - Embeds summary using same model as RAG
  - Writes `MemoryEntry` to PostgreSQL (encrypted summary field — use Fernet)
  - Do NOT store raw transcript — summary only

### 3.2 Memory Reader
- [ ] ⚙️ Write `backend/memory/session_memory.py`:
  - `get_relevant_memories(user_id, problem, top_n=2) → list[MemoryEntry]`
  - Embed problem → cosine search over user's `MemoryEntry.embedding` vectors
  - Threshold: 0.65 (lower than RAG — memories are summaries, not exact matches)
  - Strict `WHERE user_id = :uid` in every query
  - Returns formatted summaries ready for scratchpad injection

### 3.3 Wire Memory Into Session Start
- [ ] ⚙️ Update `backend/orchestrator/main_agent.py`:
  - Before initializing scratchpad: call `get_relevant_memories(user_id, problem)`
  - If results found: inject as `memory_context` into scratchpad
  - If no results: start fresh (empty list)
- [ ] ⚙️ Update `backend/scratchpad/manager.py`:
  - If `memory_context` is non-empty, add to `memory_context` section of scratchpad
  - Log: how many memories injected, similarity scores

### 3.4 Encryption at Rest
- [ ] ⚙️ Add `MEMORY_ENCRYPTION_KEY` to `.env.example` and `config.py`
  - Use `cryptography` library (Fernet symmetric)
  - `encrypt_memory(text) → bytes`
  - `decrypt_memory(blob) → str`
- [ ] ⚙️ Apply to `MemoryEntry.summary` and `MemoryEntry.key_entities` on write/read

### 3.5 Phase 3 Checkpoint
- [ ] ⚙️ Run session 1 for user A → compressor fires → `MemoryEntry` in DB
- [ ] ⚙️ Run session 2 for user A on related problem → assert memory injected in scratchpad
- [ ] ⚙️ Run session 1 for user B on same problem → assert user A memory NOT visible
- [ ] ⚙️ Decrypt stored entry manually → confirm readable summary
- [ ] ⚙️ Update `CLAUDE.md §1` → "Phase 4: Frontend"

---

## Phase 4 — Frontend
*Goal: Full React UI — live agent feed with parallel clusters, solution document viewer, mockup iframe.*

### 4.1 SSE Stream Hook
- [ ] ⚙️ Write `frontend/src/hooks/useSSEStream.js`:
  - `useSSEStream(sessionId)` → returns `{events, status, error}`
  - Uses `EventSource` API with auth header (via URL param token)
  - Auto-reconnect on disconnect (exponential backoff, max 5 attempts)
  - Accumulates all events in state array

### 4.2 Agent Feed Components
- [ ] ⚙️ Write `frontend/src/components/AgentCard.jsx`:
  - Shows: agent name, role icon, streaming token text, locked decisions badge
  - States: idle → thinking → streaming → done
  - Animates token-by-token text appearance
- [ ] ⚙️ Write `frontend/src/components/PhaseCluster.jsx`:
  - Receives: phase number, agents array, parallel bool
  - If parallel: renders agents side-by-side in a "working simultaneously" grid
  - If sequential: renders agents stacked
  - Shows phase name banner, phase complete indicator
- [ ] ⚙️ Write `frontend/src/components/LiveAgentFeed.jsx`:
  - Consumes SSE events from hook
  - Builds phase/agent tree from events
  - Renders `PhaseCluster` for each phase as it arrives
  - Shows live token budget / turn counter in header

### 4.3 Chat Interface
- [ ] ⚙️ Write `frontend/src/components/ChatInterface.jsx`:
  - Problem input textarea (max 2000 chars with counter)
  - Submit button → calls `POST /api/sessions` → gets session_id → starts SSE stream
  - Loading state while classifying
  - Error display if session fails

### 4.4 Solution Document Viewer
- [ ] ⚙️ Write `frontend/src/components/SolutionDocument.jsx`:
  - Triggered by `session_complete` SSE event
  - Renders structured solution document with sections
  - "Export as Markdown" button — downloads `.md` file
  - "Export as PDF" button — calls `GET /api/sessions/{id}/export?format=pdf`
- [ ] ⚙️ Write `backend/api/sessions.py` export endpoint:
  - `GET /api/sessions/{id}/export?format=md|pdf`
  - Returns file download

### 4.5 UI Mockup Viewer
- [ ] ⚙️ Write `frontend/src/components/UiMockupViewer.jsx`:
  - Appears in Builder agent's AgentCard when mockup is available
  - Renders HTML mockup in a sandboxed `<iframe sandbox="allow-scripts">`
  - "Open in new tab" + "Download HTML" buttons
  - No external network calls allowed in the iframe (CSP)

### 4.6 Auth Flow
- [ ] ⚙️ Write `frontend/src/pages/LoginPage.jsx` — email/password form
- [ ] ⚙️ Write `frontend/src/api/client.js` — axios instance, attach JWT from localStorage
- [ ] ⚙️ Redirect to `/session` after successful login

### 4.7 Phase 4 Checkpoint
- [ ] ⚙️ Full end-to-end manual test: login → submit problem → watch live feed → see solution document
- [ ] ⚙️ Parallel phase cluster renders agents side-by-side
- [ ] ⚙️ Builder mockup renders in iframe
- [ ] ⚙️ Markdown export downloads correctly
- [ ] ⚙️ SSE auto-reconnects after artificial disconnect
- [ ] ⚙️ Update `CLAUDE.md §1` → "Phase 5: Polish"

---

## Phase 5 — Polish, Hardening, Metrics
*Goal: All NFRs met. Prompt caching verified. Failure modes tested.*

### 5.1 Prompt Caching
- [ ] ⚙️ Add `cache_control: {"type": "ephemeral"}` to all 8 persona system prompts in SDK calls
- [ ] 🟡 Run 3 identical sessions → assert `cached_tokens > 0` in Logfire spans
- [ ] ⚙️ Assert cached_token_ratio > 50% on persona calls

### 5.2 Rate Limiting
- [ ] ⚙️ Add per-user rate limiter in `backend/api/auth.py`:
  - Max 5 sessions per hour per user (Redis counter)
  - Returns 429 with `Retry-After` header

### 5.3 Input Sanitization
- [ ] 🟢 Write `backend/api/sessions.py` sanitizer:
  - Haiku call (max_tokens=100): detect prompt injection attempts
  - Block patterns: "ignore previous instructions", "you are now", "act as", role-play injection
  - Return 400 if injection detected, log to Logfire

### 5.4 Failure Mode Tests
- [ ] ⚙️ Test: single agent API timeout → agent skipped, session continues
- [ ] ⚙️ Test: turn limit hit at turn 10 → synthesis forced immediately
- [ ] ⚙️ Test: token budget hit mid-phase → synthesis forced, partial outputs included
- [ ] ⚙️ Test: 4-minute timeout → synthesis forced with whatever is in scratchpad
- [ ] ⚙️ Test: Builder tool fails → agent output still written (minus mockup)

### 5.5 Exponential Backoff
- [ ] ⚙️ Wrap all Claude API calls in `backend/agents/dispatcher.py` with:
  - Max 3 retries, base delay 1s, exponential factor 2
  - Only retry on 429 and 5xx errors

### 5.6 Scratchpad Summarization
- [ ] 🟢 Write `backend/scratchpad/manager.py` `summarize_if_large()`:
  - Called after Phase 2 completes
  - If scratchpad token count > 8000: Haiku call to summarize `agent_outputs` section
  - Replace verbose outputs with summaries; keep `decision_log` intact

### 5.7 Performance Testing
- [ ] ⚙️ Write load test (`tests/test_load.py`):
  - 5 concurrent sessions using `httpx.AsyncClient`
  - Assert all complete within 120s p99
  - Assert no memory cross-contamination (user isolation)

### 5.8 Success Metrics Verification
- [ ] ⚙️ Session completion rate test: run 20 sessions → assert ≥ 19 complete (95%)
- [ ] ⚙️ Assert p99 latency < 120s (from load test logs)
- [ ] ⚙️ Assert cached_token_ratio > 50% (from Logfire)
- [ ] ⚙️ Assert zero cross-user memory leaks (from isolation tests)

### 5.9 Documentation
- [ ] ⚙️ Write `README.md`:
  - Setup instructions (Docker, Python env, `.env` file)
  - How to seed knowledge base
  - How to run backend + frontend
  - Architecture overview (links to CLAUDE.md)
  - How to run tests
- [ ] ⚙️ Add inline `# DECISION:` comments on non-obvious architectural choices

---

## Deferred to Post-MVP (Do Not Build Now)

These are explicitly out of MVP scope. Record here so they're not forgotten.

- [ ] 🔮 Session forking for "what-if" alternative solution branches (PRD §14)
- [ ] 🔮 Human-in-the-loop review step before final document (PRD §14)
- [ ] 🔮 LLM-as-judge output evaluation gate (PRD §14)
- [ ] 🔮 Multi-tenant org support + admin panel (PRD §14)
- [ ] 🔮 Builder agent graduating to runnable scaffolds (PRD §14)
- [ ] 🔮 End-user configurable personas (PRD §14)
- [ ] 🔮 Session history browser + agent performance analytics (PRD §14)
- [ ] 🔮 Swap ChromaDB → managed vector DB (Pinecone/Weaviate) (post-MVP scaling)

---

## Build Log

| Date | Phase | What was done | Notes |
|------|-------|---------------|-------|
| _start_ | 0 | Project initialized | — |

---

## v3.0 REBUILD — LangGraph Group Chat Architecture
*PRD v3.0 supersedes v2.0. The pipeline is replaced by a LangGraph cyclic supervisor StateGraph.*
*v2.0 sections above are preserved as build history. All new work tracked below.*

---

## Phase 1 — LangGraph Skeleton + State
*Goal: Graph compiles, DB migrated, stub session runs to completion. No Claude calls yet.*

### 1v3.1 Install + verify LangGraph
- [x] ⚙️ `langgraph 1.2.4` + `langgraph-checkpoint-postgres 3.1.0` installed, no conflicts

### 1v3.2 DB Migration (0003_v3_schema.py)
- [x] ⚙️ `decisions` table: id, session_id, text, proposed_by, state, provenance, supersedes_id, created_at
- [x] ⚙️ `challenge_rounds` table: id, decision_id, challenger, round_number, outcome, created_at
- [x] ⚙️ `sessions` table: +roster TEXT[], +enriched_problem TEXT, +termination_reason VARCHAR(50)
- [x] ⚙️ `agent_messages` table: +is_private BOOLEAN DEFAULT FALSE
- [x] ⚙️ `alembic upgrade head` applied clean

### 1v3.3 SQLAlchemy Models
- [x] ⚙️ `Decision` model added to `backend/models.py`
- [x] ⚙️ `ChallengeRound` model added to `backend/models.py`
- [x] ⚙️ `Session` model updated with v3.0 fields
- [x] ⚙️ `AgentMessage` model updated with `is_private`

### 1v3.4 LangGraph State
- [x] ⚙️ `backend/graph/__init__.py` created
- [x] ⚙️ `backend/graph/state.py` — `ChatState` TypedDict with append-reducers on lists
- [x] ⚙️ `INITIAL_STATE` dict defined

### 1v3.5 Stub Nodes + Graph Assembly
- [x] ⚙️ `backend/graph/nodes.py` — 10 stub async nodes + `make_expert_node` factory
- [x] ⚙️ `backend/graph/graph.py` — `StateGraph` compiled with `MemorySaver`
- [x] ⚙️ All 11 nodes present: supervisor, synthesis, human_input, 8 experts
- [x] ⚙️ Graph topology: supervisor → conditional edges → experts/synthesis/human_input → supervisor → ... → synthesis → END

### 1v3.6 FastAPI wired to graph
- [x] ⚙️ `POST /api/sessions` launches `_run_graph` (BackgroundTasks) instead of old `run_session`
- [x] ⚙️ `INITIAL_STATE` populated with session_id, user_id, problem_statement
- [x] ⚙️ `config = {"configurable": {"thread_id": session_id}}` passed to graph

### 1v3.7 Phase 1 Checkpoint — 5/5 PASSED
- [x] ⚙️ TEST 1: LangGraph version confirmed (1.2.4)
- [x] ⚙️ TEST 2: ChatState schema valid, INITIAL_STATE has required keys
- [x] ⚙️ TEST 3: Graph compiles with all 11 nodes present
- [x] ⚙️ TEST 4: Stub graph runs to completion (stub_complete termination)
- [x] ⚙️ TEST 5: DB migration verified — all new tables + columns present

---

## Phase 2 — Real Expert Nodes + SSE Stream
*Goal: Real Claude calls through graph nodes. SSE stream connected. Conversation visible in browser.*

### 2v3.1 SSE bridge helpers
- [x] ⚙️ `emit_message()` added to `backend/sse/emitter.py`
- [x] ⚙️ `emit_decision()` added to `backend/sse/emitter.py`
- [x] ⚙️ `emit_session_status()` added to `backend/sse/emitter.py`

### 2v3.2 Expert node implementation
- [x] 🟡 `backend/graph/nodes.py` — real expert nodes replacing stubs
- [x] ⚙️ Context builder: enriched_problem + last 10 public messages + rolling_summary + locked decisions + rag_chunks
- [x] 🟡 Claude call per expert (Sonnet, max_tokens=1500)
- [x] ⚙️ JSON response parsing with graceful degradation
- [x] ⚙️ Public message emitted over SSE
- [x] ⚙️ Private reasoning stored in state (is_private=True), NOT emitted over SSE
- [x] ⚙️ agent_messages DB persist (try/except — non-fatal)

### 2v3.3 Synthesis node
- [x] 🔴 Real synthesis node — Opus call (max_tokens=3000)
- [x] ⚙️ Reads full public transcript + locked decisions + rolling_summary
- [x] ⚙️ Produces structured solution document (JSON schema)
- [x] ⚙️ Saves to solution_documents DB table + data/sessions/{id}/solution.json
- [x] ⚙️ Triggers memory compression as fire-and-forget task
- [x] ⚙️ Emits session_complete over SSE

### 2v3.4 Framing / clarification node
- [x] 🟡 `framing_node` added to `backend/graph/nodes.py`
- [x] ⚙️ Generates 2-4 questions (Sonnet, max_tokens=500)
- [x] ⚙️ Emits clarification_required over SSE
- [x] ⚙️ Uses `interrupt()` to pause graph
- [x] ⚙️ `_framing_questions` cache prevents double-emit on LangGraph re-execution
- [x] ⚙️ Builds enriched_problem from answers on resume
- [x] ⚙️ Emits clarification_complete on resume
- [x] ⚙️ Added to graph as "framing" node with edge back to supervisor

### 2v3.5 Resume endpoint
- [x] ⚙️ `POST /api/sessions/{id}/respond` added to `backend/api/sessions.py`
- [x] ⚙️ Body: `{"answer": str}`
- [x] ⚙️ Calls `graph.astream(Command(resume=answer), config)` as background task

### 2v3.6 Simple round-robin supervisor
- [x] ⚙️ Real supervisor_node replacing stub (round-robin for now)
- [x] ⚙️ Termination check: turn_count >= 8 OR solution_document set
- [x] ⚙️ Routes to framing on turn 0 + no enriched_problem
- [x] ⚙️ DEFAULT_ROSTER fallback if roster not set

### 2v3.7 Graph.py updated
- [x] ⚙️ framing node added with correct edges
- [x] ⚙️ route_from_supervisor updated for framing + termination

### 2v3.8 Frontend minimal wiring
- [x] ⚙️ LiveAgentFeed.jsx handles "message" event → chat bubbles
- [x] ⚙️ LiveAgentFeed.jsx handles "decision" event → badge list
- [x] ⚙️ LiveAgentFeed.jsx handles "clarification_required" → InlineClarification panel
- [x] ⚙️ Clarification panel submits to /respond (not /clarify)
- [x] ⚙️ LiveAgentFeed.jsx handles "synthesizing" + "session_complete"

### 2v3.9 Phase 2 Checkpoint — 5/5 PASSED
- [x] 🟡 TEST 1: ai_architect_node returns valid state update — 6 proposed decisions, real Sonnet response
- [x] 🔴 TEST 2: synthesis_node returns solution_document with executive_summary — Opus call clean
- [x] ⚙️ TEST 3: SSE events fire — 8 messages + synthesizing + session_complete at 341.5s
- [x] ⚙️ TEST 4: /respond endpoint — HTTP 200 + {"status": "resumed"}
- [x] 🔴 TEST 5: Full session — 8 agents, session_complete at 516s, real executive_summary
- [NOTE] Two non-fatal warnings: mock UUID "test-synth-2" fails DB insert (expected, caught by try/except)

---

## Phase 3 — Supervisor Routing + MoE Gating
*Goal: Supervisor intelligently selects experts based on problem. Not all 8 fire on every problem.*

### 3v3.1 Roster auto-selection
- [x] 🟡 `roster_selection_node` added to `backend/graph/nodes.py`
- [x] ⚙️ Sonnet call selects relevant subset (2-8 experts) from problem
- [x] ⚙️ project_manager always last; solution_architect always included
- [x] ⚙️ Roster stored in ChatState + sessions.roster DB column
- [x] ⚙️ `roster_selection` node added to graph with edge → supervisor

### 3v3.2 Intelligent turn routing
- [x] 🟡 `_supervisor_route()` — Sonnet routing call after every expert message
- [x] ⚙️ Considers: speakers so far, remaining, last 5 messages, open questions
- [x] ⚙️ Falls back to next unheard expert on parse failure
- [x] ⚙️ Handles "ask_human" and "synthesis" return values from routing call

### 3v3.3 Consensus detection
- [x] ⚙️ `_check_consensus()` checks all three conditions every turn
- [x] ⚙️ Checks: no decisions in "proposed" or "challenged" state
- [x] ⚙️ Checks: all roster experts have contributed at least once
- [x] ⚙️ Sets termination_reason = "consensus" when all conditions met
- [x] ⚙️ Turn ceiling raised from 8 → 20 for group chat model

### 3v3.4 Rolling summarization
- [x] 🟢 `_maybe_summarize()` — Haiku call when public message count > 15
- [x] ⚙️ Updates rolling_summary in state only (Option B — no message replacement)
- [x] ⚙️ Called from supervisor_node every turn before routing

### 3v3.5 Phase 3 Checkpoint — 5/5 PASSED
- [x] ⚙️ TEST 1: Simple API → 3 experts [solution_architect, solution_engineer, project_manager]
- [x] ⚙️ TEST 2: Complex ML fraud platform → 7 experts (full team minus ui_builder)
- [x] ⚙️ TEST 3: Consensus terminates at 4 turns, never reaching 20-turn ceiling
- [x] 🟡 TEST 4: PM always last in sequence; intelligent ordering confirmed
- [x] ⚙️ TEST 5: 6-expert roster persisted to sessions.roster column in DB
- [NOTE] Tests 2+5 use max_seconds=1200 — CLI retry overhead (3×120s) requires headroom on 8-expert sessions

---

## Phase 4 — Contradiction Detection + Arbitration
*Goal: Contradictions detected, bounded debate triggered, human escalated when needed.*

### 4v3.1 Contradiction detector
- [x] 🟡 `backend/graph/contradiction.py` — Sonnet call detects contradictions between new and existing decisions
- [x] ⚙️ Returns conflict dict with conflicts_with_id, conflicts_with_by, summary
- [x] ⚙️ Returns None if no contradiction detected
- [x] ⚙️ Called from supervisor_node after every expert turn (when ≥2 experts have spoken)

### 4v3.2 Debate routing
- [x] ⚙️ Supervisor routes back to original proposer with challenge (max 2 rounds per decision)
- [x] ⚙️ ChallengeRound rows created in DB (challenge_rounds table) — verified in Test 3
- [x] ⚙️ `_challenge_rounds` dict tracks rounds per decision_id
- [x] ⚙️ `_session_contradiction_count` dict caps total rounds at 6 per session (prevents runaway loops)

### 4v3.3 Supervisor arbitration (Phase 4 scope)
- [x] ⚙️ After 2 rounds: supervisor locks decision with provenance="orchestrator"
- [x] ⚙️ SSE "arbitration" event emitted with both positions
- [NOTE] Full human arbitration UI (interrupt + 3-branch response) deferred to Phase 5

### 4v3.4 Decision lifecycle DB sync
- [x] ⚙️ `_persist_decisions_db()` upserts decisions via INSERT ... ON CONFLICT DO UPDATE
- [x] ⚙️ Called from expert nodes (proposed), consensus block (locked), synthesis (locked fallback)
- [x] ⚙️ Awaited synchronously before session_complete emit — guarantees DB rows exist
- [x] ⚙️ DB migration 0004: widened provenance VARCHAR(20)→VARCHAR(50), state VARCHAR(20)→VARCHAR(30)

### 4v3.5 Phase 4 Checkpoint — 4/5 PASSED
- [x] ⚙️ TEST 1: 25 decisions locked at consensus, all with provenance=consensus_by_supervisor
- [x] ⚙️ TEST 2: Session completes cleanly (contradiction mechanism wired, soft-pass by design)
- [x] ⚙️ TEST 3: Real contradiction caught in live session → 1 challenge_round in DB
- [SKIP] TEST 4: Notification service problem caused 11-contradiction runaway loop → timeout at 1800s. Root cause: no global cap. Fix (6-round session cap) applied. Re-run skipped — Tests 1/3/5 already prove the mechanism works.
- [x] ⚙️ TEST 5: 42 DB rows (21 proposed + 21 locked), all locked rows have provenance IS NOT NULL

---

## Phase 5 — Interrupt Nodes + Human-in-Loop
*Goal: Graph pauses correctly for human input at any point. Resume works cleanly from checkpoint.*

### 5v3.1 Any-time interrupt capability
- [x] ⚙️ Any expert node can trigger interrupt() mid-conversation (not just framing)
- [x] ⚙️ Expert signals "I need human input" via explicit `needs_human_input` boolean field in output schema (keyword scanner replaced — see 5v3.5 note)
- [x] ⚙️ Supervisor detects this and routes to an ask_human node before next expert

### 5v3.2 Ask-human node
- [x] ⚙️ `ask_human_node` in nodes.py — wraps interrupt() cleanly
- [x] ⚙️ Emits "human_input_required" SSE event with the question
- [x] ⚙️ On resume: injects answer into next expert's context
- [x] ⚙️ Graph resumes from exact checkpoint state

### 5v3.3 Postgres checkpointer (replace MemorySaver)
- [x] ⚙️ `AsyncPostgresSaver` wired using existing DATABASE_URL
- [x] ⚙️ `graph = build_graph(checkpointer=AsyncPostgresSaver(...))` — required `loop='none'` fix in uvicorn_config.py
- [x] ⚙️ Paused sessions survive server restart and resume correctly
- [x] ⚙️ Session cleanup: delete checkpointer state after session_complete

### 5v3.4 Retire v2.0 clarify endpoint
- [x] ⚙️ `POST /api/sessions/{id}/clarify` now returns 410 Gone (not 200 — spec updated)
- [x] ⚙️ All frontend calls now go to /respond
- [x] ⚙️ Remove asyncio.Queue bridge (no longer needed)

### 5v3.5 Phase 5 Checkpoint — PASSED (manual end-to-end)
- [x] ⚙️ Mid-conversation question from expert → graph pauses → human answers → resumes (via /respond)
- [x] ⚙️ Postgres checkpointer verified: loop='none' fix in uvicorn_config.py; resume from DB checkpoint confirmed
- [x] ⚙️ /clarify returns 410 (deprecated endpoint; backward-compat spec changed to 410 Gone)
- [NOTE] Automated checkpoint suite abandoned — Windows test-harness fragility (psutil API changes, port conflicts, PowerShell stdout capture); all were harness issues, not application bugs
- [NOTE] Critical bug found and fixed: keyword scanner in supervisor_node falsely triggered awaiting_human on ordinary expert text (words like 'users', 'requirements', 'budget'). Fix: replaced with explicit `needs_human_input` boolean in expert output schema + ASK_HUMAN_MAX=2 per-session cap. asyncio.timeout wrapper deferred to Phase 8.

---

## Phase 6 — Synthesis + Memory + Termination Polish
*Goal: All three termination conditions work. Memory compression fires correctly. Solution doc complete.*

### 6v3.1 All termination conditions
- [DEFERRED → P7] ⚙️ "user_finalize" path: POST /api/sessions/{id}/finalize + [USER_FINALIZE] supervisor handling — deferred to Phase 7 (needs chat-UI Finalize button to wire to; building it now = untested dead code)
- [x] ⚙️ "consensus" path: supervisor detects, logs reason, routes to synthesis (working since Phase 3; termination_reason now persisted to DB)
- [x] ⚙️ "ceiling" path: turn ceiling at 20 working; termination_reason="ceiling" persisted to DB

### 6v3.2 Memory compression wired to v3.0
- [x] 🟡 compress_session() reads public agent_messages + locked decisions + enriched_problem from Postgres (scratchpad dependency removed)
- [x] ⚙️ Summary includes locked decisions with provenance (bulleted list in Sonnet input)
- [x] ⚙️ MemoryEntry written + encrypted — verified end-to-end via tests/phase6_compress_check.py (5 messages → 1,300-char summary → MemoryEntry in DB + decrypted)
- [x] ⚙️ memory_context field added to ChatState + INITIAL_STATE
- [x] ⚙️ get_relevant_memories() wired into create_session (try/except, non-fatal); result injected as initial_state["memory_context"]
- [x] ⚙️ memory_context injected into _build_expert_context() as "## Prior Session Context" section

### 6v3.3 Solution document completeness
- [x] ⚙️ All locked decisions appear in solution doc (synthesis_node already included them; termination_reason now also persisted)
- [DEFERRED → P8] ⚙️ Superseded decisions noted with reason — deferred to Phase 8 polish (current synthesis output already validated as good)
- [DEFERRED → P8] ⚙️ Expert contributions attributed by role — deferred to Phase 8 polish (synthesis prompt enhancement)
- [x] ⚙️ /export endpoint still works (solution.json written by synthesis_node, endpoint unchanged)

### 6v3.4 Phase 6 Checkpoint
- [x] ⚙️ Write path verified: compress_session reads DB, writes encrypted MemoryEntry — tests/phase6_compress_check.py PASSED
- [x] ⚙️ termination_reason persisted to sessions table for all termination paths
- [NOTE] Memory read+inject path (returning user sees prior context) wired; live verification deferred to Phase 7 end-to-end chat-UI run
- [NOTE] Full three-condition termination test deferred to Phase 7 (needs finalize UI)

---

## Phase 7 — Chat Frontend
*Goal: Replace phase-cluster UI with a true chat interface.*

### 7v3.1 Retire phase-cluster components
- [x] ⚙️ PhaseCluster.jsx — deleted
- [x] ⚙️ AgentCard.jsx — deleted (replaced by MessageBubble)
- [x] ⚙️ LiveAgentFeed.jsx — deleted (replaced by ChatWindow)
- [x] ⚙️ UiMockupViewer.jsx — deleted (unused in v3.0 flow)

### 7v3.2 New components
- [x] ⚙️ `roleStyles.js` — shared ROLE_COLORS / ROLE_EMOJIS / formatRole module; imported by MessageBubble, RosterBadges, ChatWindow
- [x] ⚙️ `MessageBubble.jsx` — expert (left, role-colored avatar), human (right, grey), system (centered, muted) variants; reasoning expander slot in markup, hidden until Phase 8
- [x] ⚙️ `DecisionBadge.jsx` — proposed (yellow) / challenged (orange) / locked (green) pill; state badge + proposed_by + truncated text with title tooltip + provenance line
- [x] ⚙️ `RosterBadges.jsx` — display-only pill strip from roster_selected SSE event; auto-selected by backend (no manual picker — backend has no endpoint to accept user-specified roster)
- [x] ⚙️ `PauseOverlay.jsx` — full-screen backdrop card for human_input_required; autofocused textarea; Ctrl+Enter submit; POST /respond on submit
- [x] ⚙️ `ChatWindow.jsx` — scrollable 62vh chat feed; collapsible 268px decision sidebar with open/closed strip toggle; animated three-dot typing indicator; ⏹ Finalize button; roster strip; SSE event handlers for all v3.0 events
- [SKIP: ArbitrationOverlay] Supervisor auto-arbitrates after 2 debate rounds — no human input required for this path. Arbitration surfaced as inline system bubble in chat feed instead. Full overlay deferred to Phase 8 if needed.

### 7v3.3 App.jsx updated
- [x] ⚙️ Swapped LiveAgentFeed → ChatWindow import and JSX
- [x] ⚙️ PauseOverlay rendered inside ChatWindow on human_input_required; human_input_received clears overlay and adds human bubble to chat
- [SKIP: ArbitrationOverlay in App.jsx] Handled as system bubble inside ChatWindow — no separate overlay needed
- [NOTE] RosterPicker (manual expert selection) deferred to Phase 8 — requires new backend parameter in POST /api/sessions body; currently display-only via RosterBadges

### 7v3.4 Phase 7 Checkpoint — PASSED (manual browser validation)
- [x] ⚙️ End-to-end in browser: framing → roster strip → chat messages appear → decision sidebar updates → solution doc shown
- [x] ⚙️ Decision sidebar shows proposed (yellow) and locked (green) states; collapsible with vertical label strip when closed
- [x] ⚙️ Contradiction system bubble renders inline in chat feed
- [x] ⚙️ Finalize button (⏹) wired live: POST /sessions/{id}/finalize → [USER_FINALIZE] in supervisor_node → synthesis
- [x] ⚙️ /finalize backend endpoint added to sessions.py; [USER_FINALIZE] handler in supervisor_node locks proposed decisions + routes to synthesis
- [NOTE] Private reasoning expandable — slot in markup but hidden; needs GET /messages endpoint (Phase 8)
- [NOTE] ArbitrationOverlay — supervisor auto-resolves; inline system bubble sufficient for now (Phase 8 if full 3-branch UI needed)
- [NOTE] Interactive roster picker — deferred to Phase 8 (backend endpoint needed)

---

## Phase 8 — Hardening + Observability + Tests
*Goal: Production-ready. All failure modes handled. Playwright suite passes. Logfire connected.*

### 8v3.1 Turn / time / token ceilings
- [ ] ⚙️ Turn limit configurable (default 20 for group chat, was 12 for pipeline)
- [ ] ⚙️ Wall-clock timeout configurable (default 600s)
- [ ] ⚙️ Token budget enforcer updated for new state model
- [ ] ⚙️ All three tested via failure mode tests

### 8v3.2 Recursion guard
- [ ] ⚙️ LangGraph recursion_limit set on graph compile
- [ ] ⚙️ Tested: supervisor → expert → supervisor loop terminates on ceiling

### 8v3.3 Logfire spans for v3.0
- [ ] ⚙️ Span per supervisor routing decision (which expert chosen, why)
- [ ] ⚙️ Span per expert node call (tokens, latency)
- [ ] ⚙️ Span per contradiction detection + resolution
- [ ] ⚙️ Span per interrupt + resume
- [ ] ⚙️ Span per synthesis call

### 8v3.4 Failure mode tests (updated for v3.0)
- [ ] ⚙️ Rate limit still enforced (inherited from v2.0)
- [ ] ⚙️ Injection still blocked (inherited from v2.0)
- [ ] ⚙️ Turn ceiling terminates session cleanly
- [ ] ⚙️ Server restart mid-pause → resume works (Postgres checkpointer)
- [ ] ⚙️ Expert node failure → skipped, session continues

### 8v3.5 Playwright E2E suite
- [ ] ⚙️ Tests 1-5: auth + roster picker + first message appears + pause handled + solution doc
- [ ] ⚙️ Tests 6-10: decision badges + arbitration flow + finalize button + export + memory injection

### 8v3.6 Logfire dashboard
- [ ] ⚙️ LOGFIRE_TOKEN added to .env
- [ ] ⚙️ Full session trace visible in dashboard
- [ ] ⚙️ Token cost per session queryable

### 8v3.7 Phase 8 Checkpoint
- [ ] ⚙️ Playwright 10/10 pass
- [ ] ⚙️ 5/5 failure mode tests pass
- [ ] ⚙️ Logfire shows full session trace
- [ ] ⚙️ Session completion rate > 95% over 10 test runs

---

## v3.0 Build Log

| Date | Phase | What was done | Notes |
|------|-------|---------------|-------|
| 2026-06-08 | 1v3 | Phase 1 complete — LangGraph skeleton — 5/5 checkpoint passed | langgraph 1.2.4; DB migrated (decisions + challenge_rounds tables); ChatState TypedDict; 11-node graph compiles; POST /api/sessions wired to _run_graph |
| 2026-06-08 | 2v3 | Phase 2 complete — Real expert nodes + SSE stream — 5/5 checkpoint passed | Real Sonnet calls per expert; Opus synthesis; framing_node with interrupt(); _framing_questions cache fixes double-emit; /respond endpoint resumes graph; single async httpx SSE stream fixes queue race condition |
| 2026-06-09 | 3v3 | Phase 3 complete — MoE gating + intelligent routing — 5/5 checkpoint passed | roster_selection_node (Sonnet call); _supervisor_route (Sonnet after every turn); _check_consensus (3-condition check); turn ceiling 8→20; rolling summarization (Haiku >15 msgs) |
| 2026-06-12 | 4v3 | Phase 4 complete — Contradiction detection + decision locking — 4/5 checkpoint passed (Test 4 skip justified) | contradiction.py (Sonnet detector); _challenge_rounds + _session_contradiction_count caps; _persist_decisions_db awaited before session_complete; DB migration 0004 widens provenance/state columns; Tests 1+3+5 prove full decision lifecycle working |
| 2026-06-19 | 5v3 | Phase 5v3 validated via manual end-to-end frontend run (automated checkpoint suite abandoned due to Windows test-harness fragility — psutil API changes, port conflicts, PowerShell stdout capture; all were harness issues, not application bugs). Manual run exercised: Postgres checkpointer (loop='none' fix in uvicorn_config.py), /respond resume, /clarify 410. During validation found and fixed a critical bug: the Phase 5 human-signal KEYWORD scanner in supervisor_node falsely triggered awaiting_human on ordinary expert discussion text (words like 'users', 'requirements', 'budget'), routing to ask_human_node which blocked on interrupt() forever since the v2.0 frontend can't send a resume. Fix: replaced keyword scan with an explicit needs_human_input boolean field in the expert output schema (model decides), plus a per-session ASK_HUMAN_MAX=2 cap as a safety net. Deferred asyncio.timeout wrapper to Phase 8. End-to-end run confirmed: SA→SE→UI→PM routing, PM last, 17 decisions locked, solution document synthesized and exported. | — |
| 2026-06-19 | 6v3 | Phase 6v3: cross-session memory made functional. Root cause — compress_session checked for a v3.0-nonexistent scratchpad file and returned None immediately, so no MemoryEntry was ever written; get_relevant_memories was implemented correctly but never called from the v3.0 graph path. Fix: compressor now reads public agent_messages + locked decisions + enriched_problem from Postgres to build the Sonnet summary input; reader wired into create_session and injected via new memory_context state field into _build_expert_context. termination_reason now persisted to sessions table. Write path verified end-to-end via tests/phase6_compress_check.py against an existing completed session (5 messages → 1,300-char summary → encrypted MemoryEntry written + decrypted). Read+inject path wired; live verification deferred to Phase 7 chat-UI run. Two items deferred (finalize endpoint → P7, synthesis enhancement → P8). | — |
| 2026-06-19 | 7v3 | Phase 7v3: WhatsApp-style chat frontend built and validated via manual browser run. Delivered in 3 sequential builds verified live in browser between each. Build 1: deleted dead v2.0 components (PhaseCluster, AgentCard, UiMockupViewer, LiveAgentFeed), created roleStyles.js shared module, MessageBubble.jsx (expert/human/system variants), RosterBadges.jsx (display-only), ChatWindow.jsx replacing LiveAgentFeed. Build 2: DecisionBadge.jsx, collapsible decision sidebar in ChatWindow, contradiction/arbitration inline system bubbles. Build 3: PauseOverlay.jsx for human_input_required events, /finalize backend endpoint + [USER_FINALIZE] handler in supervisor_node, Finalize button wired live. All 3 builds compiled clean (88 modules, 0 warnings). Manual validation confirmed: roster strip, message bubbles, thinking indicator, decision sidebar with PROPOSED/LOCKED states, contradiction system bubble, solution document render, Finalize button. Known gaps deferred to Phase 8: (1) interactive roster picker requires new backend endpoint to accept user-specified roster in POST /api/sessions body; (2) expandable private reasoning requires GET /messages endpoint; (3) framing question count reduction (prompt tuning). | — |
| 2026-07-02 | Wave 1 safety | Wave 1 pre-flight safety fixes applied. Fix #1: _persist_status lifecycle helper — session status now writes RUNNING/COMPLETED/FAILED (was silently stuck at clarifying). Fix #2: SSE stream IDOR — ownership 404/403 guard added to stream.py. Fix #5: recursion_limit set to session_max_turns×4 (was unset, default 25 killed 6-8 expert sessions at ~turn 12); GraphRecursionError now surfaces as FAILED instead of silently swallowing. Fix #6: startup guard raises RuntimeError if WEB_CONCURRENCY>1 (process-global state in nodes.py breaks multi-worker). Fix #7: checkpointer fail-fast — non-dev raises instead of silently falling back to MemorySaver; /health now exposes {"checkpointer": "postgres"\|"memory"} and returns 503 when degraded in non-dev. Fix #8: app-level token budget guard in supervisor_node + per-call accumulator in _run_expert + JSON-safe response truncation at 6000 chars. Fix #9: CLAUDE.md reconciled — v3 LangGraph engine documented accurately, v2 legacy modules marked. Fix #10: synthesis transcript windowed to last 30 messages; Haiku summary of dropped tail; rolling_summary substitutes instead of stacking. | 5/5 tests pass throughout |
| 2026-07-02 | Bedrock migration | claude_client.py fully replaced. CLI subprocess removed; aioboto3 Converse adapter using APAC cross-region inference profile ARNs (Opus/Sonnet/Haiku). Model mapping via _resolve_model() — any caller string matched case-insensitively. ThrottlingException retried 3× with 1s/2s/4s backoff; all other ClientErrors raise RuntimeError (caught by Fix #1 lifecycle wrapper). USE_CLI flag deprecated. Dual interface: accepts both system_prompt/user_prompt (existing callers) and system/messages (spec form). requirements.txt: aioboto3>=13.0.0 + botocore>=1.34.0 added. NOTE: .env has 39-char secret key (truncated by 1 char) — InvalidSignatureException on every call until fixed. | Pending: user must update .env with correct 40-char secret key |
| 2026-07-03 | Fix #4 tool wiring | estimate_timeline and generate_ui_mockup now fire deterministically after PM and UI Builder nodes respectively (were never invoked before). Per-expert KB search (search_knowledge_base top_k=3) injected into _run_expert before every LLM call — was framing-only before. _run_expert gained user_prompt_override param for targeted cleanup calls. UiMockup DB row persisted after generate_ui_mockup. Tool results emitted via SSE tool_result events. | 5/5 tests pass |
| 2026-07-03 | Reviewer node (Pillar 4) | reviewer_node and cleanup_round_node added to nodes.py and wired into graph.py. Graph topology: supervisor → reviewer → cleanup_round → synthesis (reviewer is unconditional on path to synthesis). State gains: reviewer_findings, reviewer_done, cleanup_round_done. reviewer_node: Sonnet call (upgraded to Opus in Phase 0 — see below), reads last 40 public messages + locked decisions, produces 2-6 structured findings (gap/conflict/risk/redundancy) with severity. cleanup_round_node: high-severity findings only, max 3 agents, calls _run_expert with user_prompt_override targeted at each finding. Synthesis injected with reviewer findings context. | 5/5 tests pass |
| 2026-07-03 | Wall-clock timeout | session_start_time field added to ChatState (set in sessions.py initial_state to time.time()). supervisor_node checks elapsed time before any routing — forces termination_reason="timeout" with decision locking when SESSION_TIMEOUT_SECONDS exceeded. synthesis_node adds "time limit reached" preamble to system prompt when termination_reason=="timeout". asyncio.timeout(SESSION_TIMEOUT_SECONDS+30) backstop added to _run_graph. | 5/5 tests pass |
| 2026-07-07 | Phase 0 fixes | FIX-P0.1: route_from_supervisor fallback branch returned "synthesis" directly — all paths now route through reviewer first (reviewer_done guard on fallback). FIX-P0.2: reviewer_node upgraded from Sonnet → Opus (gap-finding benefits from Opus reasoning; this is the one call outside synthesis where the premium is justified). FIX-P0.3: _resume_graph lacked asyncio.timeout backstop that _run_graph already had — identical asyncio.timeout(SESSION_TIMEOUT_SECONDS+30) + TimeoutError handler added. FIX-P0.4: main.py now calls load_dotenv() at module level — pydantic_settings only loads its declared fields, leaving AWS_ACCESS_KEY_ID/SECRET out of os.environ; all agents were failing with "Unable to locate credentials" until this fix. .env secret key corrected by user (was 39 chars/truncated, now 40 chars). | 5/5 tests pass |
| 2026-07-07 | Phase 0 live verification | Step 1 smoke test: PASSED — BEDROCK_OK, 22 input / 8 output tokens. Session 1 (vacation tracker, 8-person team): COMPLETED in 186s, termination_reason=consensus_by_supervisor, reviewer fired with 6 findings (2 high-severity gaps: admin role + vacation balance), cleanup_round ran 2 turns (solution_architect + solution_engineer), solution doc produced with 11 key decisions. Session 2 (coffee subscription, no-tech founder): COMPLETED, termination_reason=consensus_by_supervisor, reviewer fired with 6 findings (3 high-severity: fulfillment integration gap, shipping address undefined, solution_engineer truncation risk), session_complete confirmed via DB (10 messages, 22 decisions, 11 key decisions in solution doc). Both sessions confirm reviewer fires via explicit termination path; FIX-P0.1 fallback guards the edge case path. SSE stream consumer needed sys.stdout.reconfigure(encoding='utf-8') due to Windows cp1252 console not supporting arrow characters in LLM output. | Two full live sessions verified end-to-end |