from __future__ import annotations

from pathlib import Path

from tasks_core import TaskStore
from tooling import ToolContext, ToolDefinition
from tools.common import fail, ok


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise TypeError("task_id must be a non-empty string")
    return {"task_id": task_id.strip()}


def run(payload, context: ToolContext):
    runtime = context.runtime or {}
    store = runtime.get("task_store")
    if not isinstance(store, TaskStore):
        store = TaskStore(Path(context.cwd) / ".tasks")
    try:
        return ok(store.complete_task(payload["task_id"]))
    except FileNotFoundError:
        return fail(f"Error: task {payload['task_id']} not found")


TOOL = ToolDefinition(
    name="complete_task",
    description="Complete an in-progress task.",
    input_schema={
        "type": "object",
        "properties": {"task_id": {"type": "string"}},
        "required": ["task_id"],
    },
    validator=validate,
    run=run,
)
