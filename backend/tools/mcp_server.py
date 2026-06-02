import logging
from typing import Callable

logger = logging.getLogger(__name__)


class InProcessMCPServer:
    """
    Lightweight in-process tool registry for the CLI prototype.
    Production: replace with FastMCP / Anthropic SDK in-process MCP server.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Callable] = {}

    def tool(self, func: Callable) -> Callable:
        """Decorator: register an async function as an MCP tool."""
        self._tools[func.__name__] = func
        return func

    async def call(self, tool_name: str, **kwargs):
        if tool_name not in self._tools:
            raise ValueError(f"Unknown MCP tool: {tool_name!r}. Available: {self.tool_names}")
        return await self._tools[tool_name](**kwargs)

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())


# Module-level singleton
mcp_server = InProcessMCPServer()


def start_mcp_server() -> None:
    """Register all 4 tools. Called once in FastAPI lifespan."""
    from backend.tools.estimate_timeline import estimate_timeline
    from backend.tools.fetch_memory import fetch_memory
    from backend.tools.generate_mockup import generate_ui_mockup
    from backend.tools.search_kb import search_knowledge_base

    for fn in (search_knowledge_base, fetch_memory, estimate_timeline, generate_ui_mockup):
        mcp_server.tool(fn)

    logger.info(f"MCP server: {mcp_server.tool_names}")
