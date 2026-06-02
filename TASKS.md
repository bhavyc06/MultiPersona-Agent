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
- [x] ⚙️ Write `backend/config.py` — `Settings` class (pydantic-settings, loads from `.env`)
- [x] ⚙️ Write `backend/main.py` — FastAPI app, register routers, lifespan (startup/shutdown)
- [x] ⚙️ Write `backend/api/auth.py`:
  - `POST /api/auth/register`
  - `POST /api/auth/login` → returns JWT
  - JWT middleware — `get_current_user` dependency
- [x] ⚙️ Write `backend/api/sessions.py` — stub `POST /api/sessions` (accepts problem, returns session_id)
- [x] ⚙️ Write `backend/api/stream.py` — stub `GET /api/sessions/{id}/stream` (returns empty SSE)
- [x] ⚙️ Confirm: `uvicorn backend.main:app --reload` starts, `/docs` loads, auth endpoints respond

### 0.5 React Frontend Shell
- [x] ⚙️ Vite: `npm create vite@latest frontend -- --template react`
- [x] ⚙️ Install: `axios`, `react-router-dom`
- [x] ⚙️ Write `App.jsx` — router with two routes: `/login` and `/session`
- [x] ⚙️ Write stub `ChatInterface.jsx` — text input + submit button, calls `POST /api/sessions`
- [x] ⚙️ Write stub `LiveAgentFeed.jsx` — EventSource hook, logs events to console
- [ ] ⚙️ Confirm: `npm run dev` starts, form submits, SSE stream connects (empty)

### 0.6 Phase 0 Checkpoint
- [x] ⚙️ End-to-end smoke test: submit a problem → session_id returned → SSE stream opens
- [x] ⚙️ Both Docker services healthy, DB migrations applied
- [x] ⚙️ No hardcoded secrets anywhere (grep check)
- [ ] ⚙️ Update `CLAUDE.md §1` current phase → "Phase 1: Orchestrator + Agent Definitions"

---

## Phase 1 — Orchestrator + Agent Definitions
*Goal: Orchestrator classifies a problem, builds a phase plan, and dispatches real subagents
that read the scratchpad and write structured JSON output. No tools yet — agents reason from
scratchpad context only.*

### 1.1 Scratchpad Manager
- [x] ⚙️ Write `backend/scratchpad/manager.py`

### 1.2 SSE Emitter
- [x] ⚙️ Write `backend/sse/emitter.py`

### 1.3 Haiku Complexity Classifier
- [x] 🟢 Write `backend/orchestrator/classifier.py`

### 1.4 Phase Planner
- [x] ⚙️ Write `backend/orchestrator/phase_planner.py`

### 1.5 Guardrail Layer
- [x] ⚙️ Write `backend/orchestrator/guardrails.py`

### 1.6 Subagent Definitions
- [x] ⚙️ Write `backend/agents/base_agent.py`
- [x] ⚙️ Write all 8 `.claude/agents/*.md` files (3-section template CLAUDE.md §11)
- [x] ⚙️ Write `backend/agents/definitions.py`

### 1.7 Orchestrator Main Agent
- [x] 🟡 Write `backend/orchestrator/main_agent.py`

### 1.8 Phase Barrier
- [x] ⚙️ Write `backend/orchestrator/phase_barrier.py`

### 1.9 Agent Dispatcher
- [x] 🟡 Write `backend/agents/dispatcher.py`

### 1.10 Phase 1 Checkpoint
- [x] 🟡 "Build a real-time ML feature store" → complexity=complex → Phase 1 ran
- [x] ⚙️ scratchpad has outputs for ai_architect + solution_architect
- [x] ⚙️ decision_log has 13 locked decisions after phase barrier
- [x] ⚙️ SSE events in correct order: session_started → phase_start → agent_start × 2 → token × 2 → agent_end × 2 → phase_complete
- [x] ⚙️ Hard stop enforced in code (turn_count >= 12 OR elapsed >= 240s)
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
| 2026-06-02 | 0.4–0.6 | FastAPI shell + React frontend + smoke tests passed | passlib→bcrypt direct; EmailStr→str (no email-validator dep) |
| 2026-06-02 | 1.1–1.10 | Phase 1 complete — all 8 agents, orchestrator, scratchpad, SSE, phase barrier | ClaudeAdapter: asyncio.to_thread + stdin-pipe (not -p) to avoid CLAUDE.md context injection on Windows |
| 2026-06-02 | 1.5 | Clarification loop complete — 10/10 checkpoint assertions passed | SessionStatus enum + migration 0002; clarifier.py (Sonnet questions + Haiku readiness); asyncio.Queue bridge; scratchpad clarification_context block; enriched_problem flows to agents |
| 2026-06-02 | 2.1–2.6 | Phase 2 complete — Tools + RAG — 8/8 checkpoint assertions passed | ChromaDB seeded (8 KB files, ~120 chunks); sentence-transformers all-MiniLM-L6-v2 + cross-encoder reranker; Redis RAG cache; InProcessMCPServer; dispatcher pre-fetches rag_chunks; token budget tracking |
| 2026-06-02 | 3.1–3.5 | Phase 3 complete — Memory — 7/7 checkpoint assertions passed | Fernet encryption; Sonnet compressor; cosine-similarity retrieval in Python (numpy); cross-user isolation verified; 2 memories injected into Part 2 scratchpad |
| 2026-06-03 | 4.1–4.9 | Phase 4 complete — Frontend — 3/3 automated assertions passed | useSSEStream w/ exponential backoff; ClarificationPanel; AgentCard+PhaseCluster; LiveAgentFeed; SolutionDocument (marked); UiMockupViewer (sandboxed iframe); export endpoint; fix: Windows cp1252 → UTF-8 for solution.json |
