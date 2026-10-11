import logging
from typing import Any, List, Optional, Tuple

from .server import MCPServer, MCPServerSse
from .util import FunctionTool, MCPUtil
from .agent_tools import MCPToolsIntegration

logger = logging.getLogger("nexa.mcp")


async def get_mcp_tools(
    server_url: str,
    timeout: float = 10.0,
    server_name: Optional[str] = None
) -> Tuple[Optional[MCPServerSse], List[Any]]:
    """
    Connect to an SSE MCP server, discover its tools, and convert them to LiveKit function tools.
    Returns (server_instance, list_of_decorated_tools).
    If connection fails or server is offline, returns (None, []) without raising exceptions.
    """
    if not server_url or not server_url.strip():
        return None, []

    server = MCPServerSse(
        params={"url": server_url.strip(), "sse_read_timeout": None},
        cache_tools_list=True,
        name=server_name or f"SSE Server ({server_url.strip()})",
    )

    try:
        tools = await MCPToolsIntegration.prepare_dynamic_tools(
            mcp_servers=[server],
            auto_connect=True,
            connect_timeout=timeout,
        )
        if not getattr(server, "connected", False):
            await server.cleanup()
            return None, []
        return server, tools
    except Exception as e:
        logger.warning(f"Failed to initialize MCP server at {server_url}: {e}")
        try:
            await server.cleanup()
        except Exception:
            pass
        return None, []


__all__ = [
    "MCPServer",
    "MCPServerSse",
    "FunctionTool",
    "MCPUtil",
    "MCPToolsIntegration",
    "get_mcp_tools",
]
