from __future__ import annotations

import subprocess
from pathlib import Path

from tooling import ToolContext, ToolDefinition
from tools.common import fail, ok, safe_path


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")

    command = payload.get("command")
    if not isinstance(command, str) or not command.strip():
        raise TypeError("command must be a non-empty string")

    args = payload.get("args", [])
    if not isinstance(args, list):
        raise TypeError("args must be a list")

    cwd = payload.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise TypeError("cwd must be a string")

    timeout = payload.get("timeout", 120)
    if not isinstance(timeout, int):
        raise TypeError("timeout must be an integer")

    return {
        "command": command.strip(),
        "args": [str(arg) for arg in args],
        "cwd": cwd,
        "timeout": max(1, min(timeout, 600)),
    }


def run(payload, context: ToolContext):
    payload = {
        "command": payload["command"],
        "args": payload.get("args", []),
        "cwd": payload.get("cwd"),
        "timeout": payload.get("timeout", 120),
    }
    workspace_root = Path(context.cwd).resolve()
    effective_cwd = workspace_root if payload["cwd"] is None else safe_path(payload["cwd"], workspace_root)

    try:
        if payload["args"]:
            completed = subprocess.run(
                [payload["command"], *payload["args"]],
                cwd=effective_cwd,
                capture_output=True,
                text=True,
                timeout=payload["timeout"],
                check=False,
            )
        else:
            completed = subprocess.run(
                payload["command"],
                cwd=effective_cwd,
                capture_output=True,
                text=True,
                timeout=payload["timeout"],
                check=False,
                shell=True,
            )
    except FileNotFoundError:
        return fail(f"Command not found: {payload['command']}")
    except subprocess.TimeoutExpired:
        return fail(f"Error: Timeout ({payload['timeout']}s)")
    except Exception as error:  # noqa: BLE001
        return fail(f"Error: {error}")

    output = "\n".join(
        part for part in [completed.stdout.strip(), completed.stderr.strip()] if part
    ).strip()
    output = output or "(no output)"
    if completed.returncode != 0:
        return fail(output)
    return ok(output)


TOOL = ToolDefinition(
    name="run_command",
    description="Run a workspace-scoped development command.",
    input_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "args": {"type": "array", "items": {"type": "string"}},
            "cwd": {"type": "string"},
            "timeout": {"type": "integer"},
        },
        "required": ["command"],
    },
    validator=validate,
    run=run,
)
