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
    del payload
    runtime = context.runtime or {}
    compact_history = runtime.get("compact_history")
    messages = runtime.get("messages")
    if not callable(compact_history):
        return fail("Error: compact_history runtime callback is required")
    if not isinstance(messages, list):
        return fail("Error: runtime messages list is required")
    compacted = compact_history(messages)
    if not compacted:
        return ok("[Compacted]")
    latest = compacted[-1]
    return ok(str(latest.get("content", "")))


TOOL = ToolDefinition(
    name="compact",
    description="Summarize earlier conversation and continue with compacted context.",
    input_schema={
        "type": "object",
        "properties": {"focus": {"type": "string"}},
        "required": [],
    },
    validator=validate,
    run=run,
)
