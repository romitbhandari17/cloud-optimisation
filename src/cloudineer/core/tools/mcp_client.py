"""Minimal MCP (Model Context Protocol) tool client.

Lets an agent call tools hosted by an external MCP server (e.g. a shared
"aws-cost-mcp-server") through the exact same ``Tool``/``ToolRegistry`` interface used
for local Python tools. This keeps the framework Python-first today while being
MCP-ready: new tool servers can be plugged in without changing any agent code.

The optional ``mcp`` package (https://pypi.org/project/mcp/) is imported lazily so the
rest of the framework works without it installed; only agents/tools that actually need
an MCP server require it.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from cloudineer.core.tools.base import Tool, ToolRegistry

logger = logging.getLogger(__name__)


class MCPUnavailableError(RuntimeError):
    """Raised when the optional ``mcp`` client package is not installed."""


class MCPToolClient:
    """Connects to an MCP server over stdio and exposes its tools as ``Tool`` objects.

    Example
    -------
    >>> client = MCPToolClient(command="aws-cost-mcp-server")
    >>> registry = ToolRegistry()
    >>> client.register_tools_into(registry)  # doctest: +SKIP
    """

    def __init__(self, *, command: str, args: list[str] | None = None) -> None:
        self._command = command
        self._args = args or []

    def list_remote_tools(self) -> list[dict[str, Any]]:
        return asyncio.run(self._list_remote_tools())

    def call_remote_tool(self, name: str, **kwargs: Any) -> Any:
        return asyncio.run(self._call_remote_tool(name, **kwargs))

    def register_tools_into(self, registry: ToolRegistry) -> None:
        for spec in self.list_remote_tools():
            tool_name = spec["name"]
            registry.register(
                Tool(
                    name=tool_name,
                    description=spec.get("description", ""),
                    func=lambda _name=tool_name, **kw: self.call_remote_tool(_name, **kw),
                )
            )

    async def _session(self):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:  # pragma: no cover - exercised only without mcp installed
            raise MCPUnavailableError(
                "The optional 'mcp' package is required to talk to MCP tool servers. "
                "Install it with `pip install mcp`."
            ) from exc

        params = StdioServerParameters(command=self._command, args=self._args)
        return stdio_client(params), ClientSession

    async def _list_remote_tools(self) -> list[dict[str, Any]]:
        (stdio_cm, ClientSession) = await self._session()
        async with stdio_cm as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return [
                    {"name": t.name, "description": t.description or ""}
                    for t in tools.tools
                ]

    async def _call_remote_tool(self, name: str, **kwargs: Any) -> Any:
        (stdio_cm, ClientSession) = await self._session()
        async with stdio_cm as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments=kwargs)
                return result
