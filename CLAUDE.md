# CLAUDE.md — Multi-Agent Consulting Simulator
## Working Memory & Architectural Constitution

> This file is the single source of truth for all architectural decisions, conventions,
> model assignments, and build rules. Read this before writing any code.
> Do NOT re-open closed decisions. Flag conflicts explicitly before proceeding.

---

## 1. Project Identity

**What it is:** A chat-based web app where a customer submits a real-world technical
problem and a simulated team of 8 AI specialist personas collaborates in real time to
produce a structured solution document. Before any agent runs, the system asks the user
targeted clarifying questions until it fully understands the problem.

**Build framework (v3 — live):** LangGraph (Python) hub-and-spoke graph —
`supervisor_node` → expert nodes → `synthesis_node`. Postgres-backed checkpointer
for HITL resume. Entry point: `_run_graph` / `_resume_graph` in `backend/api/sessions.py`.
Orchestration layer: `backend/graph/graph.py` + `backend/graph/nodes.py`.
State: `ChatState` in `backend/graph/state.py` (replaces v2 scratchpad file).

**Current build phase:** v3 LangGraph MVP — Wave 1 safety fixes in progress

---

## 2. Closed Decisions (Do NOT Re-open)

These are locked. If something contradicts them, flag the conflict; don't silently diverge.

| Decision | Answer | Source |
|----------|--------|--------|
| Orchestration model | Hybrid controlled (NOT free delegation) | PRD §6.1 |
| Agent roster | Exactly 8 subagents + 1 Orchestrator main agent | PRD §4 |
| Intra-session memory | Shared scratchpad JSON file via SDK file tools | PRD §7.1 |
| Cross-session memory | Summarized + embedded entries in PostgreSQL | PRD §7.3 |
| Tool exposure | In-process MCP server (4 custom tools) | PRD §5.1 |
| Frontend | React SPA with SSE live feed | PRD §8.1 |
| Persistence | PostgreSQL + Redis + Vector DB | PRD §11 |
| Observability | Logfire / OpenTelemetry | PRD §8.2 |
| Builder output | Advisory only — NOT production-deployable code | PRD §3 |
| Subagent spawning | Subagents CANNOT spawn their own subagents | PRD §5.1 |
| **Vector store (resolved)** | **ChromaDB (embedded, in-process, MVP)** | Open Q #2 resolved |
| **Builder mockup format (resolved)** | **Self-contained HTML** | Open Q #3 resolved |
| **Clarification loop (resolved)** | **Sonnet generates questions, Haiku evaluates completeness, max 3 rounds, then force-proceed** | Added post-Phase 1 |
| **Clarification placement** | **BEFORE complexity classification — agents never see an ambiguous problem** | Added post-Phase 1 |
| **Clarification transport** | **SSE out (questions) + POST /api/sessions/{id}/clarify (answers) + asyncio.Queue bridge** | Added post-Phase 1 |

---

## 3. Model Tier Assignments (Resolved)

| Tier | Model ID | Used For |
|------|----------|----------|
| 🔴 Opus | `claude-opus-4-5` | Orchestrator synthesis call, final solution document generation |
| 🟡 Sonnet | `claude-sonnet-4-5` | All 8 persona agents, Orchestrator routing calls, **clarification question generation** |
| 🟢 Haiku | `claude-haiku-4-5-20251001` | Complexity classifier, **clarification completeness check**, input sanitization, cache-miss quick lookups |

**Rule:** Never use Opus for persona calls. Never use Haiku for anything that requires
multi-step reasoning. If a new call is added, assign a tier explicitly here before coding it.

---

## 4. The Agent Roster

| # | Agent | Core Responsibility | Tools |
|---|-------|--------------------|----|
| 0 | **Orchestrator** (main agent) | Clarify → Classify → Plan phases → Route → Enforce guardrails → Synthesize | All tools |
| 1 | **Data Engineer** | Pipelines, ingestion, storage, schemas | `search_knowledge_base`, scratchpad read/write |
| 2 | **Data Scientist** | Stats, experimentation, feature design, model evaluation | `search_knowledge_base`, scratchpad read/write |
| 3 | **Solution Engineer** | Build feasibility, integration, implementation mechanics | `search_knowledge_base`, scratchpad read/write |
| 4 | **Solution Architect** | System design, components, patterns, scalability | `search_knowledge_base`, scratchpad read/write |
| 5 | **AI Architect** | AI/ML strategy, model selection, MLOps, governance | `search_knowledge_base`, scratchpad read/write |
| 6 | **AI Engineer** | LLM integration, inference pipelines, RAG/agent build | `search_knowledge_base`, scratchpad read/write |
| 7 | **Full-Stack / UI Builder** | Frontend/backend proposals + illustrative UI mockups | `search_knowledge_base`, `generate_ui_mockup`, scratchpad read/write |
| 8 | **Project Manager** | Timeline, sequencing, dependencies, risk | `estimate_timeline`, scratchpad read/write |

**Guardrail rules (enforced in code, not just prompts):**
1. Architecture agents (AI Architect, Solution Architect) MUST run before implementation agents.
2. Project Manager is ALWAYS the last substantive agent before synthesis.
3. No agent re-opens a locked decision unless new information explicitly warrants it.
4. Hard limit: 12 agent turns OR 4-minute wall-clock timeout → force synthesis.
5. **No agent runs while session status is `clarifying` — the dispatcher checks this.**

---

## 5. Full Session Lifecycle — v3 LangGraph (State Machine)

```
POST /api/sessions
  → creates DB Session (status=clarifying)
  → fires _run_graph as BackgroundTask
       │
       ▼
  graph.astream() → supervisor_node
       │
       ▼
  framing_node  (enriches problem; interrupt() pauses for human clarification)
  POST /api/sessions/{id}/respond + _resume_graph resume clarification
       │
       ▼
  roster_selection_node  (selects expert panel for this session)
       │
       ▼
  supervisor_node  (routes to next expert via _supervisor_route LLM call)
       │
       ├─ expert node (ai_architect / solution_architect / data_engineer / ...)
       │    SSE → agent_start / token / agent_end
       │    Returns to supervisor_node
       │
       ├─ human_input node  (ask_human_node — interrupt() for mid-session input)
       │    POST /api/sessions/{id}/respond to resume
       │
       ├─ Consensus / turn-ceiling / budget-exceeded → termination_reason set
       │
       └─ synthesis_node  (Opus call → structured solution document)
            SSE → session_complete
            status = COMPLETED
            Post-session: compress → MemoryEntry → PostgreSQL

Error / timeout path:
  _run_graph except non-Interrupt → SSE error event → status = FAILED
```

**Note:** v2 clarifier phases (clarification_required / clarification_complete SSE events,
POST /api/sessions/{id}/clarify) are deprecated in v3. Clarification is handled by
`framing_node` + `interrupt()` using the standard respond endpoint.

---

## 6. v3 Execution Model (LangGraph hub-and-spoke)

v3 does NOT use rigid phases. The supervisor routes dynamically:

```
supervisor_node (_supervisor_route Sonnet call)
  → picks next expert by role based on remaining open questions + decisions
  → expert node speaks, appends to ChatState.messages, proposes decisions
  → returns to supervisor_node
  → repeats until: consensus | turn ceiling (_TURN_CEILING=20) | budget exceeded
  → routes to synthesis_node
```

Termination reasons: `consensus` | `consensus_by_supervisor` | `ceiling` |
`budget_exceeded` | `user_finalize`

*(v2 rigid Phase 0–5 plan is legacy — not executed in production)*

---

## 7. Clarification — v3 (framing_node + interrupt)

**In v3:** clarification is handled by `framing_node` in `backend/graph/nodes.py`
using LangGraph `interrupt()`. The user responds via `POST /api/sessions/{id}/respond`,
which fires `_resume_graph`. No separate clarifier module is invoked.

The sections below (7.1–7.5) describe the **v2 legacy design** (not executed):

### 7.1 [v2 LEGACY] Module: `backend/orchestrator/clarifier.py`

```python
# Public interface
async def run_clarification_loop(
    session_id: str,
    problem: str,
    max_rounds: int = 3
) -> ClarificationResult:
    ...

@dataclass
class ClarificationResult:
    enriched_problem: str        # original problem + all Q&A context combined
    rounds: list[ClarificationRound]
    is_complete: bool            # True = user answered enough; False = max rounds hit
```

### 7.2 Per-round logic

```
Round N:
  1. Sonnet call (max_tokens=600):
     - Input: original problem + all prior Q&A pairs
     - System: "You are a consulting intake specialist. Identify the 2-4 most
       critical unknowns that would change the technical approach. Ask only
       questions whose answers would materially affect the solution. Do not
       ask questions already answered. Return JSON:
       {\"questions\": [\"...\", \"...\"]}"
     - If no questions needed → return {"questions": []} → proceed immediately

  2. Emit SSE: clarification_required {questions, round, total_rounds: 3}

  3. Await asyncio.Queue[session_id] with timeout=300s (5 min)
     - Timeout → treat as "proceed with what we have"

  4. Haiku call (max_tokens=100):
     - Input: original problem + all Q&A so far
     - System: "Do we have enough information to scope a technical solution?
       Answer only: {\"ready\": true} or {\"ready\": false}"
     - ready=true → exit loop
     - ready=false AND round < max_rounds → continue
     - round == max_rounds → exit loop regardless
```

### 7.3 New API endpoint

```
POST /api/sessions/{session_id}/clarify
Body: {"answers": {"0": "answer to q0", "1": "answer to q1", ...}}
Auth: JWT required
Effect: puts answers dict into per-session asyncio.Queue
Returns: {"received": true, "round": N}
```

### 7.4 Per-session answer queue

```python
# backend/orchestrator/clarifier.py (module level)
_answer_queues: dict[str, asyncio.Queue] = {}

def get_answer_queue(session_id: str) -> asyncio.Queue:
    if session_id not in _answer_queues:
        _answer_queues[session_id] = asyncio.Queue(maxsize=1)
    return _answer_queues[session_id]

def cleanup_answer_queue(session_id: str) -> None:
    _answer_queues.pop(session_id, None)
```

### 7.5 Scratchpad `clarification_context` block

Added to scratchpad schema. ALL agents read this at turn start.

```json
"clarification_context": {
  "rounds": [
    {
      "round": 1,
      "questions": ["What is the expected daily data volume?", "..."],
      "answers": {"0": "~500GB/day", "1": "..."}
    }
  ],
  "enriched_problem": "Original problem + full clarification Q&A context in prose form",
  "is_complete": true
}
```

**Agents use `enriched_problem`, not `problem_statement`, as their primary input.**

---

## 8. SSE Event Types (user-facing live feed)

```
clarification_required → {questions: ["...", "..."], round: N, max_rounds: 3}
clarification_complete → {enriched_problem: "...", rounds_taken: N}
session_started        → {session_id, complexity, phase_plan}
phase_start            → {phase, agents, parallel: bool}
agent_start            → {agent_role, phase}
token                  → {agent_role, text}          ← streamed word by word
agent_end              → {agent_role, decisions_locked: []}
phase_complete         → {phase, decisions_locked: []}
scratchpad_update      → {field, value}
session_complete       → {solution_document, total_tokens, cost_usd}
error                  → {code, message, recoverable: bool}
```

---

## 9. Session Status Enum

```python
class SessionStatus(str, Enum):
    CLARIFYING  = "clarifying"   # waiting for user answers
    READY       = "ready"        # clarification done, agents not started yet
    RUNNING     = "running"      # agents executing
    COMPLETED   = "completed"    # solution document produced
    FAILED      = "failed"       # unrecoverable error
```

---

## 10. The Shared Scratchpad (intra-session memory)

**Location:** `sessions/{session_id}/scratchpad.json`

**Schema (updated — clarification_context is NEW):**
```json
{
  "session_id": "string",
  "problem_statement": "string",               ← raw original, never modified
  "clarification_context": {                   ← NEW — populated before agents run
    "rounds": [
      {
        "round": 1,
        "questions": ["..."],
        "answers": {"0": "..."}
      }
    ],
    "enriched_problem": "string",              ← agents use this, not problem_statement
    "is_complete": true
  },
  "complexity": "simple | standard | complex",
  "memory_context": ["prior summary 1", "..."],
  "rag_chunks": [{"content": "...", "score": 0.0, "source": "..."}],
  "decision_log": [
    {"decision": "...", "locked_by": "agent_name", "phase": 1, "timestamp": "..."}
  ],
  "open_questions": ["..."],
  "agent_outputs": {
    "data_engineer": {"recommended_approach": "...", "decisions_to_lock": [], "open_questions": [], "risks": []},
    "...": {}
  },
  "phase_plan": [{"phase": 1, "agents": [], "parallel": true}]
}
```

**Rules:**
- Subagents READ the full scratchpad at turn start.
- Subagents WRITE only to their own `agent_outputs.<role>` slot.
- Agents MUST read `clarification_context.enriched_problem` as their primary problem input.
- Orchestrator merges at phase barrier and appends to `decision_log`.
- Decision log is append-only — never mutate existing entries.

---

## 11. Four Custom MCP Tools (v2 design — known gap in v3)

`backend/tools/mcp_server.py` boots at startup but its registry is **not invoked
by v3 graph nodes**. Expert nodes call `ClaudeAdapter.complete()` directly; no
MCP tool dispatch occurs in the live system. This is a tracked Wave 2 gap.

| Tool | Description | Model that calls it (v2 design) |
|------|-------------|---------------------|
| `search_knowledge_base(query, top_k=5)` | Vector search over tech/cloud KB, reranks, caches in Redis | Persona agents |
| `fetch_memory(user_id, query)` | Semantic search over past session summaries, top-2 | Orchestrator at session start |
| `estimate_timeline(scope_json)` | Delivery estimation heuristics | Project Manager |
| `generate_ui_mockup(spec_json)` | Produces self-contained HTML mockup | UI Builder |

---

## 12. Project Structure

```
multi-agent-consulting-simulator/
├── CLAUDE.md
├── TASKS.md
├── .env.example
├── docker-compose.yml
├── requirements.txt
│
├── .claude/
│   └── agents/
│       ├── data_engineer.md
│       ├── data_scientist.md
│       ├── solution_engineer.md
│       ├── solution_architect.md
│       ├── ai_architect.md
│       ├── ai_engineer.md
│       ├── ui_builder.md
│       └── project_manager.md
│
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── models.py
│   ├── claude_client.py             ← ClaudeAdapter (CLI subprocess; Bedrock migration pending)
│   │
│   ├── api/
│   │   ├── sessions.py              ← POST /api/sessions; _run_graph / _resume_graph entry points
│   │   │                               POST /api/sessions/{id}/respond  ← HITL resume
│   │   ├── stream.py                ← GET /api/sessions/{id}/stream (SSE)
│   │   └── auth.py
│   │
│   ├── graph/                       ← v3 LIVE orchestration engine
│   │   ├── graph.py                 ← build_graph / init_graph (LangGraph StateGraph)
│   │   ├── nodes.py                 ← all node functions + module-level state dicts
│   │   ├── state.py                 ← ChatState TypedDict
│   │   └── contradiction.py
│   │
│   ├── orchestrator/                ← v2 LEGACY — not invoked in production
│   │   ├── main_agent.py
│   │   ├── clarifier.py
│   │   ├── classifier.py
│   │   ├── phase_planner.py
│   │   ├── guardrails.py
│   │   ├── phase_barrier.py
│   │   └── synthesizer.py
│   │
│   ├── agents/                      ← v2 LEGACY — not invoked in production
│   │   ├── base_agent.py
│   │   └── definitions.py
│   │
│   ├── tools/
│   │   ├── mcp_server.py            ← boots at startup; registry NOT called by v3 nodes (known gap)
│   │   ├── search_kb.py
│   │   ├── fetch_memory.py
│   │   ├── estimate_timeline.py
│   │   └── generate_mockup.py
│   │
│   ├── memory/
│   │   ├── session_memory.py
│   │   └── compressor.py
│   │
│   ├── rag/
│   │   ├── service.py
│   │   ├── seeder.py
│   │   └── cache.py
│   │
│   ├── scratchpad/                  ← v2 LEGACY — replaced by ChatState / LangGraph checkpointer
│   │   └── manager.py
│   │
│   ├── sse/
│   │   └── emitter.py
│   │
│   └── db/
│       ├── postgres.py
│       └── redis_client.py
│
├── frontend/
│   ├── package.json
│   └── src/
│       ├── App.jsx
│       ├── components/
│       │   ├── ChatInterface.jsx
│       │   ├── ClarificationPanel.jsx   ← NEW: renders questions, collects answers
│       │   ├── LiveAgentFeed.jsx
│       │   ├── PhaseCluster.jsx
│       │   ├── AgentCard.jsx
│       │   ├── SolutionDocument.jsx
│       │   └── UiMockupViewer.jsx
│       ├── hooks/
│       │   └── useSSEStream.js
│       └── api/
│           └── client.js
│
└── knowledge_base/
    └── seed_data/
```

---

## 13. Environment Variables

```bash
ANTHROPIC_API_KEY=
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/consulting_sim
REDIS_URL=redis://localhost:6379/0
CHROMA_PERSIST_DIR=./data/chroma
JWT_SECRET=
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60
SESSION_MAX_TURNS=12
SESSION_TIMEOUT_SECONDS=240
SESSION_TOKEN_BUDGET=150000
CLARIFICATION_MAX_ROUNDS=3
CLARIFICATION_ANSWER_TIMEOUT_SECONDS=300
MODEL_OPUS=claude-opus-4-5
MODEL_SONNET=claude-sonnet-4-5
MODEL_HAIKU=claude-haiku-4-5-20251001
LOGFIRE_TOKEN=
ENVIRONMENT=development
USE_CLI=true
```

---

## 14. Agent System Prompt Template (mandatory three sections)

Every agent system prompt MUST contain these three sections in order:

```markdown
## Role Definition
You are the [ROLE NAME] in a multi-agent consulting team...
[Role-specific expertise and boundaries]

## Decision Log Instructions
At the start of your turn, read the `decision_log` in the scratchpad.
Every entry in the decision log is a LOCKED CONSTRAINT. You must not
re-open, question, or contradict any locked decision. If a locked
decision affects your domain, build on it — do not replace it.

IMPORTANT: Read `clarification_context.enriched_problem` as your
primary problem statement — it contains the original problem plus
all clarifications the user has provided. Do NOT use `problem_statement`
alone as your input.

## Output Schema
You MUST respond with valid JSON matching this schema exactly:
{
  "recommended_approach": "string — your core recommendation",
  "decisions_to_lock": ["string", ...],
  "open_questions": ["string", ...],
  "risks": ["string", ...]
}
Do not include any text outside this JSON object.
```

---

## 15. Token and Cost Rules

- **Clarification questions (Sonnet):** max_tokens=600 per round
- **Clarification completeness check (Haiku):** max_tokens=100
- **Per-agent max_tokens output cap:** 2000 tokens
- **Synthesis call max_tokens:** 4000 tokens
- **Haiku calls max_tokens:** 500 tokens
- **Session token budget:** 150,000 tokens total
- **Prompt caching:** Enable on ALL persona system prompts
- **RAG cache:** Redis TTL 1 hour
- **Scratchpad summarization:** If > 8,000 tokens after Phase 2, summarize agent_outputs

**If any code path could cause unbounded token spend, flag it with `# TOKEN RISK:`**

---

## 16. Security Rules

- JWT required on all `/api/*` endpoints including `/api/sessions/{id}/clarify`
- Input sanitized for prompt injection before hitting any agent
- API keys NEVER in frontend code or responses
- File-writing tools gated by SDK permission hooks
- Builder HTML mockups sandboxed to `sessions/{session_id}/mockups/`
- Memory queries ALWAYS scoped to `user_id`
- Answer queue keyed by session_id — user must own the session (JWT check)

---

## 17. Conventions

- **Python:** async/await throughout, pydantic v2, ruff linting
- **Imports:** absolute imports only
- **Tests:** pytest + pytest-asyncio, one test file per module
- **No magic strings:** all model IDs, event names from `config.py`
- **Never block the event loop:** all DB and Redis calls must be async