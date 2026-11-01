from typing import Any, Callable
from pydantic import BaseModel, ValidationError
from agent.types import ToolCall, ToolResult


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Callable] = {}
        self._schemas: dict[str, type[BaseModel]] = {}

    def register(self, name: str, schema: type[BaseModel], fn: Callable) -> None:
        self._tools[name] = fn
        self._schemas[name] = schema

    def dispatch(self, call: ToolCall) -> ToolResult:
        if call.tool_name not in self._tools:
            return ToolResult(
                tool_name=call.tool_name,
                success=False,
                output=None,
                error=f"unknown tool: {call.tool_name}",
            )

        schema = self._schemas[call.tool_name]
        try:
            validated = schema(**call.args)
        except ValidationError as e:
            return ToolResult(
                tool_name=call.tool_name,
                success=False,
                output=None,
                error=f"invalid args: {e.error_count()} error(s) — {e.errors()[0]['msg']}",
            )

        try:
            output = self._tools[call.tool_name](validated)
            return ToolResult(tool_name=call.tool_name, success=True, output=output)
        except Exception as e:
            return ToolResult(
                tool_name=call.tool_name,
                success=False,
                output=None,
                error=str(e),
            )

    def available(self) -> list[str]:
        return list(self._tools.keys())
