from __future__ import annotations

from pathlib import Path

from tasks_core import TaskStore
from tooling import ToolContext, ToolDefinition
from tools.common import ok


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    subject = payload.get("subject")
    if not isinstance(subject, str) or not subject.strip():
        raise TypeError("subject must be a non-empty string")
    description = payload.get("description", "")
    if not isinstance(description, str):
        raise TypeError("description must be a string")
    blocked_by = payload.get("blockedBy", [])
    if not isinstance(blocked_by, list):
        raise TypeError("blockedBy must be a list")
    return {
        "subject": subject.strip(),
        "description": description,
        "blockedBy": [str(item) for item in blocked_by],
    }


def run(payload, context: ToolContext):
    runtime = context.runtime or {}
    store = runtime.get("task_store")
    if not isinstance(store, TaskStore):
        store = TaskStore(Path(context.cwd) / ".tasks")
    description = payload.get("description", "")
    blocked_by = payload.get("blockedBy", [])
    task = store.create_task(payload["subject"], description, blocked_by)
    deps = f" (blockedBy: {', '.join(blocked_by)})" if blocked_by else ""
    return ok(f"Created {task.id}: {task.subject}{deps}")


TOOL = ToolDefinition(
    name="create_task",
    description="Create a task.",
    input_schema={
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "description": {"type": "string"},
            "blockedBy": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["subject"],
    },
    validator=validate,
    run=run,
)
