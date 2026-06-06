from __future__ import annotations

from pathlib import Path

from tasks_core import TaskStore
from tooling import ToolContext, ToolDefinition
from tools.common import ok


def validate(payload):
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    return {}


def run(payload, context: ToolContext):
    del payload
    runtime = context.runtime or {}
    store = runtime.get("task_store")
    if not isinstance(store, TaskStore):
        store = TaskStore(Path(context.cwd) / ".tasks")
    tasks = store.list_tasks()
    if not tasks:
        return ok("No tasks.")
    return ok(
        "\n".join(
            f"  {task.id}: {task.subject} [{task.status}]"
            + (f" (wt:{task.worktree})" if task.worktree else "")
            for task in tasks
        )
    )


TOOL = ToolDefinition(
    name="list_tasks",
    description="List all tasks.",
    input_schema={"type": "object", "properties": {}, "required": []},
    validator=validate,
    run=run,
)
