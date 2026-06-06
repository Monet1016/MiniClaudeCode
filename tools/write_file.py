from __future__ import annotations

from tooling import ToolContext, ToolDefinition

from tools.common import fail, ok, safe_path


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    path = payload.get("path")
    content = payload.get("content")
    if not isinstance(path, str):
        raise TypeError("path must be a string")
    if not isinstance(content, str):
        raise TypeError("content must be a string")
    return {"path": path, "content": content}


def run(payload, context: ToolContext):
    try:
        file_path = safe_path(payload["path"], context.cwd)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(payload["content"])
        return ok(f"Wrote {len(payload['content'])} bytes to {payload['path']}")
    except Exception as error:  # noqa: BLE001
        return fail(f"Error: {error}")


TOOL = ToolDefinition(
    name="write_file",
    description="Write a file in the workspace.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    },
    validator=validate,
    run=run,
)
