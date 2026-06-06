from __future__ import annotations

from tooling import ToolContext, ToolDefinition
from tools.common import fail, ok, safe_path


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    path = payload.get("path", ".")
    if not isinstance(path, str):
        raise TypeError("path must be a string")
    return {"path": path}


def run(payload, context: ToolContext):
    try:
        target = safe_path(payload["path"], context.cwd)
        if not target.exists():
            return fail(f"Path does not exist: {payload['path']}")
        if target.is_file():
            return ok(f"file {target.name}")

        entries = sorted(target.iterdir(), key=lambda item: item.name.lower())
        lines = [
            f"{'dir' if entry.is_dir() else 'file'} {entry.name}"
            for entry in entries
        ]
        return ok("\n".join(lines) if lines else "(empty)")
    except Exception as error:  # noqa: BLE001
        return fail(f"Error: {error}")


TOOL = ToolDefinition(
    name="list_files",
    description="List files and directories relative to the workspace root.",
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": [],
    },
    validator=validate,
    run=run,
)
