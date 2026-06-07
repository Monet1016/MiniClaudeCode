from __future__ import annotations

from tooling import ToolContext, ToolDefinition

from tools.common import fail, ok, resolve_path


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    path = payload.get("path")
    if not isinstance(path, str):
        raise TypeError("path must be a string")
    limit = payload.get("limit")
    if limit is not None and not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    offset = payload.get("offset", 0)
    if not isinstance(offset, int):
        raise TypeError("offset must be an integer")
    return {
        "path": path,
        "limit": limit,
        "offset": offset,
    }


def run(payload, context: ToolContext):
    try:
        target = resolve_path(payload["path"], context.cwd)
        if context.permissions is not None:
            context.permissions.ensure_path_access(str(target), "read")
        lines = target.read_text().splitlines()
        offset = max(int(payload.get("offset", 0) or 0), 0)
        limit = payload.get("limit")
        limit = int(limit) if limit is not None else None
        lines = lines[offset:]
        if limit is not None and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return ok("\n".join(lines))
    except Exception as error:  # noqa: BLE001
        return fail(f"Error: {error}")


TOOL = ToolDefinition(
    name="read_file",
    description="Read a file from the workspace.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "limit": {"type": "integer"},
            "offset": {"type": "integer"},
        },
        "required": ["path"],
    },
    validator=validate,
    run=run,
)
