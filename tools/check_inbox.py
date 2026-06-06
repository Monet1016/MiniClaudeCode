from __future__ import annotations

from protocol_core import ProtocolStore
from teammate_core import GLOBAL_BUS
from tooling import ToolContext, ToolDefinition
from tools.common import ok


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    return {}


def run(payload, context: ToolContext):
    del payload
    runtime = context.runtime or {}
    bus = runtime.get("message_bus", GLOBAL_BUS)
    store = runtime.get("protocol_store")
    if not isinstance(store, ProtocolStore):
        store = None
    agent = runtime.get("agent_name", "lead")
    messages = bus.read_inbox(agent)
    if not messages:
        return ok("(inbox empty)")
    lines = []
    for message in messages:
        metadata = message.get("metadata", {})
        request_id = metadata.get("request_id", "")
        if request_id and message.get("type", "").endswith("_response") and store is not None:
            store.match_response(message["type"], request_id, metadata.get("approve", False))
        tag = (
            f" [{message['type']} req:{request_id}]"
            if request_id
            else f" [{message['type']}]"
        )
        lines.append(f"[{message['from']}]{tag} {message['content'][:200]}")
    return ok("\n".join(lines))


TOOL = ToolDefinition(
    name="check_inbox",
    description="Check inbox for messages and protocol responses.",
    input_schema={"type": "object", "properties": {}, "required": []},
    validator=validate,
    run=run,
)
