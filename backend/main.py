import logging
import sys
from contextlib import asynccontextmanager

# Load .env before any AWS/boto3 imports — pydantic_settings only loads
# its declared fields, leaving AWS_ACCESS_KEY_ID etc. out of os.environ.
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# psycopg3 (used by LangGraph Postgres checkpointer) requires SelectorEventLoop
# on Windows — ProactorEventLoop (Python 3.14 default) is not supported.
if sys.platform == "win32":
    import asyncio as _asyncio
    import warnings as _warnings
    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore", DeprecationWarning)
        _asyncio.set_event_loop_policy(_asyncio.WindowsSelectorEventLoopPolicy())

from backend.api import auth, sessions, stream
from backend.config import settings
from backend.db.postgres import engine
from backend.db.redis_client import close_redis, get_redis

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────

    # FIX-6: process-global state — multi-worker blocked until Wave 2 SessionRuntime
    import os as _os
    _web_concurrency = _os.environ.get("WEB_CONCURRENCY")
    if _web_concurrency:
        try:
            if int(_web_concurrency) > 1:
                raise RuntimeError(
                    "Multi-worker deployment detected. This server uses process-global state "
                    "(SSE queues, safety counters, steer flags in backend/graph/nodes.py) "
                    "and must run with a single worker until FIX-6 (SessionRuntime) is "
                    "complete. Set WEB_CONCURRENCY=1."
                )
        except ValueError:
            pass  # non-integer WEB_CONCURRENCY — ignore

    await get_redis()

    # Logfire observability (silent no-op when LOGFIRE_TOKEN is empty)
    try:
        import logfire
        if settings.logfire_token:
            logfire.configure(token=settings.logfire_token)
        else:
            logfire.configure(send_to_logfire=False)
        logfire.instrument_fastapi(app)
        logger.info("Logfire configured")
    except Exception as exc:
        logger.warning(f"Logfire setup skipped: {exc}")

    # MCP tool registry boots but its registry is not called by v3 graph nodes (known gap — see CLAUDE.md §11)
    # start_mcp_server() removed — dead weight in v3 until Wave 2 MCP integration

    # Seed ChromaDB knowledge base (idempotent — skips if already seeded)
    from backend.rag.seeder import seed_knowledge_base
    await seed_knowledge_base()

    # ── LangGraph Postgres checkpointer ───────────────────────────────────────
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.checkpoint.memory import MemorySaver
    from backend.graph.graph import init_graph

    pool = None
    checkpointer_kind = "memory"
    try:
        pool = AsyncConnectionPool(
            conninfo=settings.postgres_conn_string,
            min_size=1,
            max_size=10,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
            open=False,
        )
        await pool.open()
        checkpointer = AsyncPostgresSaver(conn=pool)
        await checkpointer.setup()
        checkpointer_kind = "postgres"
        logger.info("LangGraph Postgres checkpointer ready")
    except Exception as exc:
        # FIX-7: was silently falling back to MemorySaver on any boot error
        if settings.environment != "development":
            raise  # fail fast outside development — HITL resume requires Postgres durability
        logger.error(
            "⚠ CHECKPOINTER DEGRADED: running with in-memory MemorySaver. "
            "HITL resume will not survive restarts. Set Postgres URL to fix. "
            f"({exc})"
        )
        if pool is not None:
            await pool.close()
            pool = None
        checkpointer = MemorySaver()

    app.state.pg_pool = pool
    app.state.checkpointer_kind = checkpointer_kind
    await init_graph(checkpointer=checkpointer)

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    await close_redis()
    await engine.dispose()
    if getattr(app.state, "pg_pool", None) is not None:
        await app.state.pg_pool.close()
        logger.info("Postgres connection pool closed")


app = FastAPI(
    title="Multi-Agent Consulting Simulator",
    version="0.1.0",
    description="8 AI specialist personas collaborate in real time to solve technical problems.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(sessions.router, prefix="/api", tags=["sessions"])
app.include_router(stream.router, prefix="/api", tags=["stream"])


@app.get("/health", tags=["infra"])
async def health():
    from fastapi.responses import JSONResponse
    kind = getattr(app.state, "checkpointer_kind", "unknown")
    degraded = kind == "memory" and settings.environment != "development"
    body = {
        "status": "degraded" if degraded else "ok",
        "environment": settings.environment,
        "checkpointer": kind,
    }
    return JSONResponse(content=body, status_code=503 if degraded else 200)
