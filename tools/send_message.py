from __future__ import annotations

from teammate_core import GLOBAL_BUS
from tooling import ToolContext, ToolDefinition
from tools.common import ok


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    to = payload.get("to")
    content = payload.get("content")
    if not isinstance(to, str) or not to.strip():
        raise TypeError("to must be a non-empty string")
    if not isinstance(content, str) or not content.strip():
        raise TypeError("content must be a non-empty string")
    return {"to": to.strip(), "content": content}


def run(payload, context: ToolContext):
    runtime = context.runtime or {}
    bus = runtime.get("message_bus", GLOBAL_BUS)
    sender = runtime.get("sender", "lead")
    bus.send(sender, payload["to"], payload["content"])
    return ok(f"Sent to {payload['to']}")


TOOL = ToolDefinition(
    name="send_message",
    description="Send message to a teammate.",
    input_schema={
        "type": "object",
        "properties": {
            "to": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["to", "content"],
    },
    validator=validate,
    run=run,
)
