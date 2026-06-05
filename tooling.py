from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(slots=True)
class ToolResult:
    ok: bool
    output: str


@dataclass(slots=True)
class ToolContext:
    cwd: str
    state: dict[str, Any] | None = None
    runtime: dict[str, Any] | None = None


Validator = Callable[[Any], Any]
Runner = Callable[[Any, ToolContext], ToolResult]


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    validator: Validator
    run: Runner


class ToolRegistry:
    def __init__(self, tools: list[ToolDefinition] | None = None) -> None:
        self._tools = []
        self._tool_index: dict[str, ToolDefinition] = {}
        for tool in tools or []:
            if tool.name in self._tool_index:
                raise ValueError(f"Duplicate tool name: {tool.name}")
            self._tools.append(tool)
            self._tool_index[tool.name] = tool

    def list(self) -> list[ToolDefinition]:
        return list(self._tools)

    def list_all(self) -> list[str]:
        return list(self._tool_index.keys())

    def find(self, name: str) -> ToolDefinition | None:
        return self._tool_index.get(name)

    def execute(self, tool_name: str, input_data: Any, context: ToolContext) -> ToolResult:
        tool = self.find(tool_name)
        if tool is None:
            return ToolResult(ok=False, output=f"Unknown tool: {tool_name}")

        try:
            parsed = tool.validator(input_data)
        except Exception as error:  # noqa: BLE001
            return ToolResult(
                ok=False,
                output=f"Validation error in {tool_name}: {error}",
            )

        try:
            result = tool.run(parsed, context)
            if not isinstance(result, ToolResult):
                raise TypeError(
                    f"Tool {tool_name} must return ToolResult, got {type(result).__name__}"
                )
            if result.output is None:
                result.output = ""
        except Exception as error:  # noqa: BLE001
            return ToolResult(
                ok=False,
                output=f"Error running {tool_name}: {error}",
            )

        return result
