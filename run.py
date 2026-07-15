"""
Server startup script.

Replaces: python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
Use:      python run.py [--host HOST] [--port PORT] [--reload]

Forces asyncio.SelectorEventLoop on Windows (Python 3.12+/3.14+) so that
psycopg3 (used by the LangGraph Postgres checkpointer) works correctly.
Python 3.14 defaults to ProactorEventLoop on Windows; psycopg3 requires
SelectorEventLoop. Using loop_factory= in asyncio.run() is the correct
Python 3.12+ approach — set_event_loop_policy is deprecated in 3.14.
"""
import asyncio
import selectors
import sys
import argparse


def _selector_loop_factory() -> asyncio.SelectorEventLoop:
    return asyncio.SelectorEventLoop(selectors.SelectSelector())


async def _serve(host: str, port: int, reload: bool) -> None:
    import uvicorn
    config = uvicorn.Config(
        "backend.main:app",
        host=host,
        port=port,
        log_level="info",
        reload=reload,
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start the consulting-simulator backend")
    parser.add_argument("--host",   default="127.0.0.1")
    parser.add_argument("--port",   type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev only)")
    args = parser.parse_args()

    if sys.platform == "win32":
        # loop_factory forces every coroutine inside uvicorn — including lifespan,
        # pool.open(), and all psycopg3 calls — onto a SelectorEventLoop.
        asyncio.run(
            _serve(args.host, args.port, args.reload),
            loop_factory=_selector_loop_factory,
        )
    else:
        asyncio.run(_serve(args.host, args.port, args.reload))
