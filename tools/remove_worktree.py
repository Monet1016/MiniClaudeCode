from __future__ import annotations

from pathlib import Path

from tasks_core import TaskStore
from tooling import ToolContext, ToolDefinition
from tools.common import ok
from worktree_core import WorktreeManager


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise TypeError("name must be a non-empty string")
    discard_changes = payload.get("discard_changes", False)
    if not isinstance(discard_changes, bool):
        raise TypeError("discard_changes must be a boolean")
    return {"name": name.strip(), "discard_changes": discard_changes}


def run(payload, context: ToolContext):
    runtime = context.runtime or {}
    manager = runtime.get("worktree_manager")
    if not isinstance(manager, WorktreeManager):
        root = Path(context.cwd)
        manager = WorktreeManager(
            repo_root=root,
            worktrees_root=root / ".worktrees",
            task_store=TaskStore(root / ".tasks"),
        )
    return ok(manager.remove_worktree(payload["name"], payload.get("discard_changes", False)))


TOOL = ToolDefinition(
    name="remove_worktree",
    description="Remove a worktree. Refuses if changes exist.",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "discard_changes": {"type": "boolean"},
        },
        "required": ["name"],
    },
    validator=validate,
    run=run,
)
