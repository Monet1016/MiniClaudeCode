from __future__ import annotations

from protocol_core import ProtocolStore
from teammate_core import GLOBAL_BUS
from tooling import ToolContext, ToolDefinition
from tools.common import ok


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    teammate = payload.get("teammate")
    if not isinstance(teammate, str) or not teammate.strip():
        raise TypeError("teammate must be a non-empty string")
    return {"teammate": teammate.strip()}


def run(payload, context: ToolContext):
    runtime = context.runtime or {}
    bus = runtime.get("message_bus", GLOBAL_BUS)
    store = runtime.get("protocol_store")
    if not isinstance(store, ProtocolStore):
        store = ProtocolStore()
        if context.runtime is not None:
            context.runtime["protocol_store"] = store
    sender = runtime.get("sender", "lead")
    request_id = store.create_shutdown_request(sender=sender, target=payload["teammate"])
    bus.send(
        sender,
        payload["teammate"],
        "Shut down.",
        "shutdown_request",
        {"request_id": request_id},
    )
    return ok(f"Shutdown request sent to {payload['teammate']}")


TOOL = ToolDefinition(
    name="request_shutdown",
    description="Request a teammate to shut down.",
    input_schema={
        "type": "object",
        "properties": {"teammate": {"type": "string"}},
        "required": ["teammate"],
    },
    validator=validate,
    run=run,
)
