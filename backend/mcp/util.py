import json
import logging
from typing import Any, Dict, List, Optional
from mcp.types import Tool as MCPTool
from .server import MCPServer

logger = logging.getLogger("nexa.mcp.util")


class FunctionTool:
    """Intermediate representation of an MCP tool ready for LiveKit conversion."""

    def __init__(
        self,
        name: str,
        description: str,
        params_json_schema: Dict[str, Any],
        on_invoke_tool: Any,
    ):
        self.name = name
        self.description = description
        self.params_json_schema = params_json_schema
        self.on_invoke_tool = on_invoke_tool

    def __repr__(self) -> str:
        return f"FunctionTool(name={self.name})"


class MCPUtil:
    """Utilities for converting MCP tools into invocable function representations."""

    @classmethod
    async def get_function_tools(cls, server: MCPServer) -> List[FunctionTool]:
        tools = await server.list_tools()
        function_tools = []
        for tool in tools:
            try:
                ft = cls.to_function_tool(tool, server)
                function_tools.append(ft)
            except Exception as e:
                logger.warning(f"Could not convert tool '{getattr(tool, 'name', 'unknown')}': {e}")
        return function_tools

    @classmethod
    def to_function_tool(cls, tool: MCPTool, server: MCPServer) -> FunctionTool:
        schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None) or {}
        tool_name = tool.name
        description = tool.description or f"Tool {tool_name} from {server.name}"

        async def invoke_tool(context: Any, input_json: str, current_name: str = tool_name) -> str:
            try:
                arguments = json.loads(input_json) if input_json else {}
            except Exception as e:
                return f"Error parsing input arguments for tool '{current_name}': {e}"

            try:
                result = await server.call_tool(current_name, arguments)
                is_error = getattr(result, "isError", False)
                if not is_error and isinstance(result, dict):
                    is_error = result.get("isError", False)

                # Parse CallToolResult content
                content_items = getattr(result, "content", None)
                if content_items is None and isinstance(result, dict):
                    content_items = result.get("content")

                res_text = ""
                if content_items and isinstance(content_items, list):
                    texts = []
                    for item in content_items:
                        if hasattr(item, "text"):
                            texts.append(str(item.text))
                        elif isinstance(item, dict) and "text" in item:
                            texts.append(str(item["text"]))
                        elif isinstance(item, (str, int, float, bool)):
                            texts.append(str(item))
                        else:
                            try:
                                texts.append(json.dumps(item.model_dump() if hasattr(item, "model_dump") else item))
                            except Exception:
                                texts.append(str(item))
                    res_text = "\n".join(texts).strip()
                elif hasattr(result, "model_dump"):
                    res_text = json.dumps(result.model_dump())
                elif isinstance(result, (dict, list)):
                    res_text = json.dumps(result)
                elif result is not None:
                    res_text = str(result).strip()

                if is_error:
                    err_msg = res_text or "Unspecified error"
                    logger.warning(f"MCP tool '{current_name}' returned error: {err_msg}")
                    return f"MCP tool '{current_name}' failed: {err_msg}"

                if not res_text:
                    return f"Tool '{current_name}' executed but returned an empty response."

                return res_text

            except Exception as e:
                logger.error(f"Error executing MCP tool '{current_name}': {e}")
                return f"Error executing tool '{current_name}': {e}"

        return FunctionTool(
            name=tool_name,
            description=description,
            params_json_schema=schema,
            on_invoke_tool=invoke_tool,
        )
