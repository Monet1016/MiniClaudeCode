from __future__ import annotations

from session_tools_core import TodoState
from tooling import ToolContext, ToolDefinition
from tools.common import fail, ok


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    todos = payload.get("todos")
    if not isinstance(todos, list):
        raise TypeError("todos must be an array")
    normalized = []
    for index, todo in enumerate(todos):
        if not isinstance(todo, dict):
            raise TypeError(f"todos[{index}] must be an object")
        normalized.append(dict(todo))
    return {"todos": normalized}


def _resolve_state(context: ToolContext) -> TodoState:
    if context.state is not None and isinstance(context.state.get("todo_state"), TodoState):
        return context.state["todo_state"]
    if context.runtime is not None and isinstance(context.runtime.get("todo_state"), TodoState):
        return context.runtime["todo_state"]
    return TodoState()


def run(payload, context: ToolContext):
    try:
        state = _resolve_state(context)
        output = state.write(payload["todos"])
        if context.state is not None:
            context.state["todo_state"] = state
        if context.runtime is not None:
            context.runtime.setdefault("todo_state", state)
        return ok(output)
    except Exception as error:  # noqa: BLE001
        return fail(f"Error: {error}")


TOOL = ToolDefinition(
    name="todo_write",
    description="Create and manage a task list for the current session.",
    input_schema={
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                        },
                    },
                    "required": ["content", "status"],
                },
            }
        },
        "required": ["todos"],
    },
    validator=validate,
    run=run,
)
