from __future__ import annotations

from tooling import ToolContext, ToolDefinition
from tools.common import fail, ok


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    focus = payload.get("focus")
    if focus is not None and not isinstance(focus, str):
        raise TypeError("focus must be a string")
    return {"focus": focus}


def run(payload, context: ToolContext):
    runtime = context.runtime or {}
    manual_compact = runtime.get("manual_compact")
    messages = runtime.get("messages")
    if not callable(manual_compact):
        return fail("Error: manual_compact runtime callback is required")
    if not isinstance(messages, list):
        return fail("Error: runtime messages list is required")
    compacted = manual_compact(messages, payload.get("focus"))
    if not compacted:
        return ok("[Compacted]")
    first = compacted[0]
    return ok(str(first.get("content", "")))


TOOL = ToolDefinition(
    name="compact",
    description="Request an explicit context compaction for the current session.",
    input_schema={
        "type": "object",
        "properties": {"focus": {"type": "string"}},
        "required": [],
    },
    validator=validate,
    run=run,
)
