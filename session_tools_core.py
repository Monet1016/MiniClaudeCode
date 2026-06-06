from __future__ import annotations


class TodoState:
    def __init__(self) -> None:
        self.current: list[dict] = []

    def write(self, todos: list[dict]) -> str:
        for index, todo in enumerate(todos):
            if "content" not in todo or "status" not in todo:
                raise ValueError(f"todos[{index}] missing 'content' or 'status'")
            if todo["status"] not in ("pending", "in_progress", "completed"):
                raise ValueError(f"todos[{index}] has invalid status '{todo['status']}'")
        self.current = todos
        return f"Updated {len(self.current)} todos"
