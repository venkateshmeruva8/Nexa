import asyncio
import logging
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from typing import Any, Dict, List, Optional, Tuple

from mcp.types import CallToolResult, Tool as MCPTool
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession

logger = logging.getLogger("nexa.mcp.server")


class MCPServer:
    """Abstract base interface for MCP servers."""

    @property
    def name(self) -> str:
        raise NotImplementedError

    async def connect(self) -> None:
        raise NotImplementedError

    async def list_tools(self) -> List[MCPTool]:
        raise NotImplementedError

    async def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        raise NotImplementedError

    async def cleanup(self) -> None:
        raise NotImplementedError


class MCPServerSse(MCPServer):
    """
    MCP server implementation using HTTP Server-Sent Events (SSE) transport.
    Suitable for remote or containerized MCP endpoints such as n8n.
    """

    def __init__(
        self,
        params: Dict[str, Any],
        cache_tools_list: bool = True,
        name: Optional[str] = None,
    ):
        self.params = params
        self.url = params.get("url", "")
        self.cache_tools_list = cache_tools_list
        self._name = name or f"SSE Server at {self.url or 'unknown'}"
        self.session: Optional[ClientSession] = None
        self.exit_stack: AsyncExitStack = AsyncExitStack()
        self._cleanup_lock: asyncio.Lock = asyncio.Lock()
        self._tools_cache: Optional[List[MCPTool]] = None
        self._cache_dirty = True
        self.connected = False

    @property
    def name(self) -> str:
        return self._name

    async def connect(self, timeout: float = 5.0) -> None:
        """Connect to the remote SSE MCP server with timeout protection and clean stream initialization."""
        if not self.url:
            raise ValueError("No URL provided for SSE MCP server.")

        async def _do_connect():
            # Ensure any prior resources are cleanly closed before opening new streams
            await self.cleanup()
            self.exit_stack = AsyncExitStack()

            streams_cm = sse_client(
                url=self.url,
                headers=self.params.get("headers"),
                timeout=self.params.get("timeout", timeout),
                sse_read_timeout=self.params.get("sse_read_timeout", None),
            )
            read_stream, write_stream = await self.exit_stack.enter_async_context(streams_cm)
            session = await self.exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()
            self.session = session
            self.connected = True
            logger.info(f"Connected to MCP SSE server: {self.name}")

        try:
            await asyncio.wait_for(_do_connect(), timeout=timeout)
        except Exception as e:
            logger.warning(f"Failed to connect to MCP SSE server '{self.name}': {type(e).__name__} - {e}")
            await self.cleanup()
            raise

    async def list_tools(self) -> List[MCPTool]:
        """Retrieve list of available tools from the server."""
        if not self.connected or not self.session:
            logger.info(f"MCP server '{self.name}' not connected prior to list_tools. Attempting proactive reconnect...")
            try:
                await self.connect()
            except Exception as conn_err:
                raise RuntimeError(f"Server '{self.name}' not connected and reconnect failed.") from conn_err

        if not self.session:
            raise RuntimeError(f"Server '{self.name}' not connected.")

        if self.cache_tools_list and not self._cache_dirty and self._tools_cache is not None:
            return self._tools_cache

        try:
            result = await self.session.list_tools()
            self._tools_cache = getattr(result, "tools", [])
            self._cache_dirty = False
            logger.info(f"Discovered {len(self._tools_cache)} tools from {self.name}")
            return self._tools_cache
        except Exception as e:
            logger.warning(f"Error listing tools from {self.name}: {e}")
            self.connected = False
            self.session = None
            raise

    async def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        """Invoke a tool on the remote MCP server with proactive pre-call reconnect and zero duplicate in-flight retry."""
        # 1. Proactive reconnect if disconnected prior to execution
        if not self.connected or not self.session:
            logger.info(f"MCP server '{self.name}' not connected prior to tool call. Attempting proactive reconnect...")
            try:
                await self.connect()
            except Exception as conn_err:
                logger.error(f"Failed to proactively reconnect to MCP server '{self.name}': {conn_err}")
                raise RuntimeError(f"Server '{self.name}' not connected and reconnect failed.") from conn_err

        if not self.session:
            raise RuntimeError(f"Server '{self.name}' not connected.")

        args = arguments or {}
        try:
            logger.debug(f"Calling MCP tool '{tool_name}' on {self.name}")
            return await self.session.call_tool(tool_name, args)
        except Exception as e:
            # Mark disconnected on any error so future calls know the stream is dead
            logger.error(f"Error calling MCP tool '{tool_name}' on {self.name}: {e}")
            self.connected = False
            self.session = None
            # DO NOT automatically retry: execution may have started on server
            raise

    async def cleanup(self) -> None:
        """Clean up network streams and session resources."""
        async with self._cleanup_lock:
            self.connected = False
            self.session = None
            try:
                await self.exit_stack.aclose()
                logger.debug(f"Cleaned up MCP server: {self.name}")
            except BaseException as e:
                logger.debug(f"Error during MCP cleanup for {self.name}: {e}")
            finally:
                self.exit_stack = AsyncExitStack()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()
