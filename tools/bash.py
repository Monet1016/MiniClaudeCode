from __future__ import annotations

from tooling import ToolDefinition
from tools.run_command import TOOL as RUN_COMMAND_TOOL


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    command = payload.get("command")
    if not isinstance(command, str) or not command.strip():
        raise TypeError("command must be a non-empty string")
    run_in_background = payload.get("run_in_background", False)
    if not isinstance(run_in_background, bool):
        raise TypeError("run_in_background must be a boolean")
    return {
        "command": command.strip(),
        "args": [],
        "cwd": None,
        "timeout": 120,
        "run_in_background": run_in_background,
    }


def run(payload, context):
    return RUN_COMMAND_TOOL.run(payload, context)


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
