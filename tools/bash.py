from __future__ import annotations

import subprocess

from tooling import ToolContext, ToolDefinition

from tools.common import fail, ok


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    command = payload.get("command")
    if not isinstance(command, str):
        raise TypeError("command must be a string")
    run_in_background = payload.get("run_in_background", False)
    if not isinstance(run_in_background, bool):
        raise TypeError("run_in_background must be a boolean")
    return {
        "command": command,
        "run_in_background": run_in_background,
    }


def run(payload, context: ToolContext):
    try:
        result = subprocess.run(
            payload["command"],
            shell=True,
            cwd=context.cwd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = (result.stdout + result.stderr).strip()
        output = output[:50000] if output else "(no output)"
        if result.returncode != 0:
            return fail(output)
        return ok(output)
    except subprocess.TimeoutExpired:
        return fail("Error: Timeout (120s)")


TOOL = ToolDefinition(
    name="bash",
    description="Run a shell command in the current workspace.",
    input_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "run_in_background": {"type": "boolean"},
        },
        "required": ["command"],
    },
    validator=validate,
    run=run,
)
