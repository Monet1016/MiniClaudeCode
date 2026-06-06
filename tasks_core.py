from __future__ import annotations

import json
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: str
    owner: str | None
    blockedBy: list[str]
    worktree: str | None = None


class TaskStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _task_path(self, task_id: str) -> Path:
        return self.root / f"{task_id}.json"

    def save_task(self, task: Task) -> None:
        self._task_path(task.id).write_text(json.dumps(asdict(task), indent=2), encoding="utf-8")

    def load_task(self, task_id: str) -> Task:
        return Task(**json.loads(self._task_path(task_id).read_text(encoding="utf-8")))

    def list_tasks(self) -> list[Task]:
        return [
            Task(**json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(self.root.glob("task_*.json"))
        ]

    def get_task_json(self, task_id: str) -> str:
        return json.dumps(asdict(self.load_task(task_id)), indent=2)

    def create_task(
        self,
        subject: str,
        description: str = "",
        blockedBy: list[str] | None = None,
    ) -> Task:
        task = Task(
            id=f"task_{int(time.time())}_{random.randint(0, 9999):04d}",
            subject=subject,
            description=description,
            status="pending",
            owner=None,
            blockedBy=blockedBy or [],
        )
        self.save_task(task)
        return task

    def can_start(self, task_id: str) -> bool:
        task = self.load_task(task_id)
        for dep_id in task.blockedBy:
            if not self._task_path(dep_id).exists():
                return False
            if self.load_task(dep_id).status != "completed":
                return False
        return True

    def claim_task(self, task_id: str, owner: str = "agent") -> str:
        task = self.load_task(task_id)
        if task.status != "pending":
            return f"Task {task_id} is {task.status}, cannot claim"
        if task.owner:
            return f"Task {task_id} already owned by {task.owner}"
        if not self.can_start(task_id):
            deps = [
                dep_id
                for dep_id in task.blockedBy
                if self._task_path(dep_id).exists() and self.load_task(dep_id).status != "completed"
            ]
            missing = [dep_id for dep_id in task.blockedBy if not self._task_path(dep_id).exists()]
            parts = []
            if deps:
                parts.append(f"blocked by: {deps}")
            if missing:
                parts.append(f"missing deps: {missing}")
            return "Cannot start - " + ", ".join(parts)
        task.owner = owner
        task.status = "in_progress"
        self.save_task(task)
        return f"Claimed {task.id} ({task.subject})"

    def complete_task(self, task_id: str) -> str:
        task = self.load_task(task_id)
        if task.status != "in_progress":
            return f"Task {task_id} is {task.status}, cannot complete"
        task.status = "completed"
        self.save_task(task)
        unblocked = [
            item.subject
            for item in self.list_tasks()
            if item.status == "pending" and item.blockedBy and self.can_start(item.id)
        ]
        message = f"Completed {task.id} ({task.subject})"
        if unblocked:
            message += f"\nUnblocked: {', '.join(unblocked)}"
        return message

    def bind_worktree(self, task_id: str, worktree_name: str) -> None:
        task = self.load_task(task_id)
        task.worktree = worktree_name
        self.save_task(task)

    def scan_unclaimed_tasks(self) -> list[Task]:
        return [
            task
            for task in self.list_tasks()
            if task.status == "pending" and not task.owner and self.can_start(task.id)
        ]
