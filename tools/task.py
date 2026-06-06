from __future__ import annotations

from tooling import ToolContext, ToolDefinition
from tools.common import fail, ok


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    description = payload.get("description")
    if not isinstance(description, str) or not description.strip():
        raise TypeError("description must be a non-empty string")
    return {"description": description.strip()}


def run(payload, context: ToolContext):
    runtime = context.runtime or {}
    spawn = runtime.get("spawn_subagent")
    if not callable(spawn):
        return fail("Error: spawn_subagent runtime callback is required")
    return ok(spawn(payload["description"]))


TOOL = ToolDefinition(
    name="task",
    description="Launch a focused subagent. Returns only its final summary.",
    input_schema={
        "type": "object",
        "properties": {"description": {"type": "string"}},
        "required": ["description"],
    },
    validator=validate,
    run=run,
)
