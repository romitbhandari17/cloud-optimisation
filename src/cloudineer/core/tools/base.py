"""Tool base class and registry.

A ``Tool`` is a single named unit of work an agent can call: "describe EC2 instances",
"get cost and usage", "get CloudWatch metric statistics", etc. Tools are plain Python
callables by default, but the same interface is used for tools exposed by an external
MCP server (see ``core/tools/mcp_client.py``), so an agent never needs to know whether
a tool runs in-process or over MCP.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Tool:
    """A callable tool with a name and a short description.

    ``func`` takes keyword arguments and returns a JSON-serialisable result. Keeping
    the signature uniform (``**kwargs -> Any``) means the same ``Tool`` wrapper works
    for local Python functions, boto3-backed calls and MCP tool invocations.
    """

    name: str
    description: str
    func: Callable[..., Any]

    def __call__(self, **kwargs: Any) -> Any:
        return self.func(**kwargs)


class ToolRegistry:
    """Holds the tools available to an agent for a single assessment run."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool {tool.name!r} is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool {name!r}. Registered: {sorted(self._tools)}") from exc

    def call(self, name: str, **kwargs: Any) -> Any:
        return self.get(name)(**kwargs)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
