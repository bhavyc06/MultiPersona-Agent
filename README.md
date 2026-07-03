# Multi-Agent Consulting Simulator

A chat-based web app where a customer submits a real-world technical problem and a simulated team of 8 AI specialist personas (AI Architect, Solution Architect, Data Engineer, Data Scientist, AI Engineer, Solution Engineer, UI Builder, and Project Manager) collaborates in real time — going through a structured clarification loop, parallel reasoning phases, and Opus-powered synthesis — to produce a structured solution document.

## Architecture Overview

- **Clarification loop** — Sonnet generates targeted questions; Haiku checks readiness; user answers via POST; answers enrich the problem statement before any agent runs
- **RAG** — ChromaDB + sentence-transformers retrieves relevant KB chunks for each agent; Redis caches results (TTL 1 hour)
- **Agent phases** — Frame → Data → Build → Plan (parallel within each phase, sequential across phases)
- **Synthesis** — Opus synthesizes all agent outputs into a structured solution document
- **Cross-session memory** — Sonnet compresses completed sessions; Fernet-encrypted summaries stored in PostgreSQL with cosine-similarity retrieval for returning users
- **Frontend** — React (Vite) SPA with SSE live feed, ClarificationPanel, per-agent cards, PhaseCluster grid

See [CLAUDE.md](CLAUDE.md) for the full architectural decision log, agent roster, model tier assignments, and all closed decisions.

## Prerequisites

- Python 3.11+
- Node.js 18+
- Docker Desktop (for PostgreSQL and Redis)
- Claude Code CLI: `npm install -g @anthropic-ai/claude-code` (authenticated)

## Setup

```bash
# 1. Clone
git clone <repo-url> && cd multi-agent-consulting-simulator

# 2. Configure environment
cp .env.example .env
# Fill in JWT_SECRET (any random string for dev)

# 3. Start infrastructure
docker compose up -d

# 4. Python dependencies
pip install -r requirements.txt

# 5. Run database migrations
python -m alembic upgrade head

# 6. Generate memory encryption key and add to .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# → paste output as MEMORY_ENCRYPTION_KEY= in .env
```

## Running

```bash
# Backend (terminal 1)
# Run with a single worker (--workers 1). Multi-worker support requires
# the SessionRuntime Redis backend (Wave 2 work item).
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1

# Frontend (terminal 2)
cd frontend && npm install && npm run dev

# Open
open http://localhost:5173
```

The backend seeds the ChromaDB knowledge base on first startup (~30s while models download).

## How It Works

1. Submit a technical problem in the chat interface
2. Answer 1–3 rounds of clarifying questions (AI-generated, Sonnet)
3. Watch 8 specialist agents reason in parallel — agent cards stream their outputs live
4. Read the synthesized solution document when complete
5. Export as Markdown

## Running Tests

```bash
# Phase checkpoints (each requires a running server)
python -m tests.checkpoint_1      # Phase 1: agents + scratchpad
python -m tests.checkpoint_1_5    # Phase 1.5: clarification loop
python -m tests.checkpoint_2      # Phase 2: RAG + tools
python -m tests.checkpoint_3      # Phase 3: cross-session memory (~15 min)
python -m tests.checkpoint_4      # Phase 4: export endpoint

# Phase 5 hardening
python -m tests.test_failure_modes
```

## Production Notes

- Set `ANTHROPIC_API_KEY=` and `USE_CLI=false` in `.env`
- Implement `ApiClaudeAdapter.complete()` in `backend/claude_client.py` using the Anthropic SDK
- Add `cache_control: {"type": "ephemeral"}` to all 8 persona system prompts for ~90% token cost reduction
- Set `LOGFIRE_TOKEN=` for the observability dashboard (spans already instrumented)
- Replace ChromaDB with a managed vector store (Pinecone, Weaviate) for horizontal scaling
- Set a strong random `JWT_SECRET` and `MEMORY_ENCRYPTION_KEY` (never reuse dev values)
