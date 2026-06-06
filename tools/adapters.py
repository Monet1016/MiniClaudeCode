from __future__ import annotations

from typing import Any, Callable

from tooling import ToolContext, ToolDefinition, ToolResult


def _validate_handler_payload(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    return payload


def make_handler_tool(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    handler: Callable[..., Any],
) -> ToolDefinition:
    def run(payload: dict[str, Any], context: ToolContext) -> ToolResult:
        del context
        try:
            result = handler(**payload)
            return ToolResult(ok=True, output=str(result))
        except TypeError as error:
            return ToolResult(ok=False, output=f"Error: {error}")
        except Exception as error:  # noqa: BLE001
            return ToolResult(ok=False, output=f"Error: {error}")

    return ToolDefinition(
        name=name,
        description=description,
        input_schema=input_schema,
        validator=_validate_handler_payload,
        run=run,
    )
