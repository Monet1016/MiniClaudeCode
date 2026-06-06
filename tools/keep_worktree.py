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
    return {"name": name.strip()}


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
    return ok(manager.keep_worktree(payload["name"]))


TOOL = ToolDefinition(
    name="keep_worktree",
    description="Keep a worktree for manual review.",
    input_schema={
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
    validator=validate,
    run=run,
)
