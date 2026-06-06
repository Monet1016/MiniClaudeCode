from __future__ import annotations

from tooling import ToolContext, ToolDefinition
from tools.common import fail, ok


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    name = payload.get("name")
    role = payload.get("role")
    prompt = payload.get("prompt")
    if not isinstance(name, str) or not name.strip():
        raise TypeError("name must be a non-empty string")
    if not isinstance(role, str) or not role.strip():
        raise TypeError("role must be a non-empty string")
    if not isinstance(prompt, str) or not prompt.strip():
        raise TypeError("prompt must be a non-empty string")
    return {
        "name": name.strip(),
        "role": role.strip(),
        "prompt": prompt.strip(),
    }


def run(payload, context: ToolContext):
    runtime = context.runtime or {}
    spawn = runtime.get("spawn_teammate")
    if not callable(spawn):
        return fail("Error: spawn_teammate runtime callback is required")
    return ok(spawn(payload["name"], payload["role"], payload["prompt"]))


TOOL = ToolDefinition(
    name="spawn_teammate",
    description="Spawn an autonomous teammate.",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "role": {"type": "string"},
            "prompt": {"type": "string"},
        },
        "required": ["name", "role", "prompt"],
    },
    validator=validate,
    run=run,
)
