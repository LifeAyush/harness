"""Tool lookup, validation and dispatch.

Every way a tool call can go wrong (unknown name, bad arguments, an exception,
a timeout) becomes an error ToolResult, not an exception. The loop hands it
back to the model, which can correct itself, so one bad call never kills a run.
"""

from __future__ import annotations

import asyncio
from typing import Iterable

from pydantic import ValidationError

from core.model.interface import ToolCall, ToolSpec
from core.tools.interface import Tool, ToolProvider, ToolResult

MAX_RESULT_CHARS = 20_000


def _truncate(text: str) -> str:
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return text[:MAX_RESULT_CHARS] + f"\n[truncated: {len(text) - MAX_RESULT_CHARS} more characters]"


def _describe(err: ValidationError) -> str:
    parts = []
    for e in err.errors():
        where = ".".join(str(p) for p in e["loc"]) or "arguments"
        parts.append(f"{where}: {e['msg']}")
    return "; ".join(parts)


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()):
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} is already registered")
        self._tools[tool.name] = tool

    def register_provider(self, provider: ToolProvider) -> None:
        for tool in provider.tools():
            self.register(tool)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> list[ToolSpec]:
        return [self._tools[n].spec() for n in self.names()]

    async def dispatch(self, call: ToolCall) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(f"unknown tool {call.name!r}; available: {', '.join(self.names()) or 'none'}", True)
        if call.arguments_error:
            return ToolResult(f"arguments for {call.name} are not a JSON object: {call.arguments_error}", True)
        try:
            args = tool.Input.model_validate(call.arguments or {})
        except ValidationError as err:
            return ToolResult(f"invalid arguments for {call.name}: {_describe(err)}", True)
        try:
            result = await asyncio.wait_for(tool.run(args), timeout=tool.timeout)
        except asyncio.TimeoutError:
            return ToolResult(f"{call.name} timed out after {tool.timeout:g}s", True)
        except Exception as exc:  # the model gets the error text; the run continues
            return ToolResult(f"{call.name} failed: {type(exc).__name__}: {exc}", True)
        return ToolResult(_truncate(result.content), result.is_error)
