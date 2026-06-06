from __future__ import annotations

from protocol_core import ProtocolStore
from teammate_core import GLOBAL_BUS
from tooling import ToolContext, ToolDefinition
from tools.common import ok


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    request_id = payload.get("request_id")
    approve = payload.get("approve")
    feedback = payload.get("feedback", "")
    if not isinstance(request_id, str) or not request_id.strip():
        raise TypeError("request_id must be a non-empty string")
    if not isinstance(approve, bool):
        raise TypeError("approve must be a boolean")
    if not isinstance(feedback, str):
        raise TypeError("feedback must be a string")
    return {
        "request_id": request_id.strip(),
        "approve": approve,
        "feedback": feedback,
    }


def run(payload, context: ToolContext):
    runtime = context.runtime or {}
    bus = runtime.get("message_bus", GLOBAL_BUS)
    store = runtime.get("protocol_store")
    if not isinstance(store, ProtocolStore):
        store = ProtocolStore()
        if context.runtime is not None:
            context.runtime["protocol_store"] = store
    result = store.review_plan(
        payload["request_id"],
        approve=payload["approve"],
        feedback=payload["feedback"],
    )
    state = store.pending.get(payload["request_id"])
    if state is not None:
        bus.send(
            runtime.get("sender", "lead"),
            state.sender,
            payload["feedback"] or ("Approved" if payload["approve"] else "Rejected"),
            "plan_approval_response",
            {"request_id": payload["request_id"], "approve": payload["approve"]},
        )
    return ok(result)


TOOL = ToolDefinition(
    name="review_plan",
    description="Approve or reject a submitted plan.",
    input_schema={
        "type": "object",
        "properties": {
            "request_id": {"type": "string"},
            "approve": {"type": "boolean"},
            "feedback": {"type": "string"},
        },
        "required": ["request_id", "approve"],
    },
    validator=validate,
    run=run,
)
