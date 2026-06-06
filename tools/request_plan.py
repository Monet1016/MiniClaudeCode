from __future__ import annotations

from teammate_core import GLOBAL_BUS
from tooling import ToolContext, ToolDefinition
from tools.common import ok


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    teammate = payload.get("teammate")
    task = payload.get("task")
    if not isinstance(teammate, str) or not teammate.strip():
        raise TypeError("teammate must be a non-empty string")
    if not isinstance(task, str) or not task.strip():
        raise TypeError("task must be a non-empty string")
    return {"teammate": teammate.strip(), "task": task.strip()}


def run(payload, context: ToolContext):
    runtime = context.runtime or {}
    bus = runtime.get("message_bus", GLOBAL_BUS)
    sender = runtime.get("sender", "lead")
    bus.send(
        sender,
        payload["teammate"],
        f"Submit plan for: {payload['task']}",
        "message",
    )
    return ok(f"Asked {payload['teammate']} to submit a plan")


TOOL = ToolDefinition(
    name="request_plan",
    description="Ask a teammate to submit a plan.",
    input_schema={
        "type": "object",
        "properties": {
            "teammate": {"type": "string"},
            "task": {"type": "string"},
        },
        "required": ["teammate", "task"],
    },
    validator=validate,
    run=run,
)
