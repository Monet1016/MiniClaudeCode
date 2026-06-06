from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Callable

from tasks_core import TaskStore

VALID_WT_NAME = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class WorktreeManager:
    def __init__(
        self,
        repo_root: Path,
        worktrees_root: Path,
        task_store: TaskStore | None,
        git_runner: Callable[[list[str], Path], tuple[bool, str]] | None = None,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.worktrees_root = Path(worktrees_root)
        self.task_store = task_store
        self.git_runner = git_runner
        self.worktrees_root.mkdir(parents=True, exist_ok=True)

    def validate_worktree_name(self, name: str) -> str | None:
        if not name:
            return "Worktree name cannot be empty"
        if name in (".", ".."):
            return f"'{name}' is not a valid worktree name"
        if not VALID_WT_NAME.match(name):
            return (
                f"Invalid worktree name '{name}': "
                "only letters, digits, dots, underscores, dashes (1-64 chars)"
            )
        return None

    def run_git(self, args: list[str]) -> tuple[bool, str]:
        if self.git_runner is not None:
            return self.git_runner(args, self.repo_root)
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False, "Error: git timeout"
        output = (completed.stdout + completed.stderr).strip()
        return completed.returncode == 0, output[:5000] if output else "(no output)"

    def log_event(self, event_type: str, worktree_name: str, task_id: str = "") -> None:
        event = {
            "type": event_type,
            "worktree": worktree_name,
            "task_id": task_id,
            "ts": time.time(),
        }
        events_file = self.worktrees_root / "events.jsonl"
        with events_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")

    def bind_task_to_worktree(self, task_id: str, worktree_name: str) -> None:
        if self.task_store is None:
            return
        self.task_store.bind_worktree(task_id, worktree_name)

    def _count_worktree_changes(self, path: Path) -> tuple[int, int]:
        try:
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=path,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            files = len([line for line in status.stdout.strip().splitlines() if line.strip()])
            commits = subprocess.run(
                ["git", "log", "@{push}..HEAD", "--oneline"],
                cwd=path,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            commit_count = len([line for line in commits.stdout.strip().splitlines() if line.strip()])
            return files, commit_count
        except Exception:
            return -1, -1

    def create_worktree(self, name: str, task_id: str = "") -> str:
        error = self.validate_worktree_name(name)
        if error:
            return f"Error: {error}"
        if task_id and self.task_store is not None:
            try:
                self.task_store.load_task(task_id)
            except FileNotFoundError:
                return f"Error: task {task_id} not found"
        path = self.worktrees_root / name
        if path.exists():
            return f"Worktree '{name}' already exists at {path}"
        ok, result = self.run_git(["worktree", "add", str(path), "-b", f"wt/{name}", "HEAD"])
        if not ok:
            return f"Git error: {result}"
        if task_id:
            self.bind_task_to_worktree(task_id, name)
        self.log_event("create", name, task_id)
        return f"Worktree '{name}' created at {path}"

    def remove_worktree(self, name: str, discard_changes: bool = False) -> str:
        error = self.validate_worktree_name(name)
        if error:
            return error
        path = self.worktrees_root / name
        if not path.exists():
            return f"Worktree '{name}' not found"
        if not discard_changes:
            files, commits = self._count_worktree_changes(path)
            if files < 0:
                return "Cannot verify status. Use discard_changes=true to force."
            if files > 0 or commits > 0:
                return (
                    f"Worktree '{name}' has {files} file(s), {commits} commit(s). "
                    "Use discard_changes=true or keep_worktree."
                )
        ok, _ = self.run_git(["worktree", "remove", str(path), "--force"])
        if not ok:
            return f"Failed to remove worktree '{name}'"
        self.run_git(["branch", "-D", f"wt/{name}"])
        self.log_event("remove", name)
        return f"Worktree '{name}' removed"

    def keep_worktree(self, name: str) -> str:
        error = self.validate_worktree_name(name)
        if error:
            return error
        self.log_event("keep", name)
        return f"Worktree '{name}' kept for review (branch: wt/{name})"
