from collections.abc import Callable
from datetime import timedelta
from typing import Any

from mcp import ClientSession
from mcp.types import Tool as MCPToolSchema

from keenbench.findall.agent.core import Tool

TOOL_CALL_TIMEOUT_S = 180.0


def _dispatch(session: ClientSession, name: str) -> Callable[..., Any]:
    async def call(**kwargs: Any) -> str:
        result = await session.call_tool(
            name, kwargs, read_timeout_seconds=timedelta(seconds=TOOL_CALL_TIMEOUT_S)
        )
        parts = [text for block in result.content if (text := getattr(block, "text", None))]
        return "\n".join(parts) or "(empty result)"

    return call


def mcp_tools_from_session(session: ClientSession, mcp_tools: list[MCPToolSchema]) -> list[Tool]:
    tools: list[Tool] = []
    for t in mcp_tools:
        schema = dict(t.inputSchema) if t.inputSchema else {}
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        tools.append(
            Tool(
                name=t.name,
                description=(t.description or f"MCP tool {t.name}")[:1024],
                function=_dispatch(session, t.name),
                parameters_schema=schema,
            )
        )
    return tools
