import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import auth, sessions, stream
from backend.config import settings
from backend.db.postgres import engine
from backend.db.redis_client import close_redis, get_redis

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
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

    # MCP tool registry
    from backend.tools.mcp_server import start_mcp_server
    start_mcp_server()

    # Seed ChromaDB knowledge base (idempotent — skips if already seeded)
    from backend.rag.seeder import seed_knowledge_base
    await seed_knowledge_base()

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    await close_redis()
    await engine.dispose()


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
    return {"status": "ok", "environment": settings.environment}
