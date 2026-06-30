"""
Launcher that forces SelectorEventLoop before uvicorn creates its event loop.
Required on Windows + Python 3.14 because psycopg3 (used by the LangGraph
Postgres checkpointer) does not support ProactorEventLoop.

Root cause: uvicorn's asyncio_loop_factory() hardcodes ProactorEventLoop on
Windows (uvicorn/loops/asyncio.py). With loop="none", uvicorn skips its own
factory and falls back to asyncio.new_event_loop(), which respects the
WindowsSelectorEventLoopPolicy set here.

Usage:
    python uvicorn_config.py
"""
import asyncio
import sys
import warnings

# Set BEFORE uvicorn imports anything — asyncio.new_event_loop() (called when
# loop="none") creates a loop based on the active policy.
if sys.platform == "win32":
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=8000,
        loop="none",   # skip uvicorn's hardcoded ProactorEventLoop factory;
                       # fall back to asyncio.new_event_loop() → SelectorEventLoop
    )
