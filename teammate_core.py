from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

from tasks_core import TaskStore


class MessageBus:
    def __init__(self, mailbox_dir: str | Path | None = None) -> None:
        self.mailbox_dir = Path(mailbox_dir) if mailbox_dir is not None else None
        self._boxes = defaultdict(list)
        if self.mailbox_dir is not None:
            self.mailbox_dir.mkdir(parents=True, exist_ok=True)

    def send(
        self,
        from_name: str,
        to_name: str,
        content: str,
        msg_type: str = "message",
        metadata: dict | None = None,
    ) -> None:
        message = {
            "from": from_name,
            "to": to_name,
            "content": content,
            "type": msg_type,
            "ts": time.time(),
            "metadata": metadata or {},
        }
        if self.mailbox_dir is None:
            self._boxes[to_name].append(message)
            return
        inbox = self.mailbox_dir / f"{to_name}.jsonl"
        with inbox.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(message) + "\n")

    def read_inbox(self, name: str) -> list[dict]:
        if self.mailbox_dir is None:
            items = list(self._boxes[name])
            self._boxes[name].clear()
            return items
        inbox = self.mailbox_dir / f"{name}.jsonl"
        if not inbox.exists():
            return []
        items = [json.loads(line) for line in inbox.read_text(encoding="utf-8").splitlines() if line.strip()]
        inbox.write_text("", encoding="utf-8")
        return items


def scan_unclaimed_tasks(task_store: TaskStore) -> list[dict]:
    return [
        {
            "id": task.id,
            "subject": task.subject,
            "status": task.status,
            "owner": task.owner,
            "worktree": task.worktree,
        }
        for task in task_store.scan_unclaimed_tasks()
    ]


GLOBAL_BUS = MessageBus()
