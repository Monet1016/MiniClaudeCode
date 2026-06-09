from __future__ import annotations

import os
import sys
import time
import uuid
from typing import Any

from tooling import BackgroundTaskResult


_background_tasks: dict[str, dict[str, Any]] = {}
_announced_terminal_states: set[str] = set()


def _is_process_alive(pid: int) -> bool | None:
    if sys.platform == "win32":
        try:
            kernel32 = __import__("ctypes").windll.kernel32
            process = kernel32.OpenProcess(0x1000, False, pid)
            if not process:
                return False
            exit_code = __import__("ctypes").c_ulong()
            try:
                if not kernel32.GetExitCodeProcess(process, __import__("ctypes").byref(exit_code)):
                    return None
                return exit_code.value == 259
            finally:
                kernel32.CloseHandle(process)
        except Exception:  # noqa: BLE001
            return None

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None


def register_background_task(command: str, cwd: str, pid: int | None) -> BackgroundTaskResult:
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    record = {
        "task_id": task_id,
        "command": command,
        "cwd": cwd,
        "pid": pid,
        "status": "running",
        "started_at": int(time.time() * 1000),
    }
    _background_tasks[task_id] = record
    return BackgroundTaskResult(**record)


def list_background_tasks() -> list[BackgroundTaskResult]:
    for record in _background_tasks.values():
        if record["status"] != "running" or record["pid"] is None:
            continue
        alive = _is_process_alive(record["pid"])
        if alive is False:
            record["status"] = "completed"
        elif alive is None:
            record["status"] = "failed"

    return [BackgroundTaskResult(**record) for record in _background_tasks.values()]


def collect_background_notifications() -> list[str]:
    notifications: list[str] = []
    for task in list_background_tasks():
        if task.status == "running" or task.task_id in _announced_terminal_states:
            continue
        notifications.append(
            "<task_notification>"
            f"<task_id>{task.task_id}</task_id>"
            f"<status>{task.status}</status>"
            f"<command>{task.command}</command>"
            "<summary>Process exited.</summary>"
            "</task_notification>"
        )
        _announced_terminal_states.add(task.task_id)
    return notifications
