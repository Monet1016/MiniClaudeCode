from __future__ import annotations

from tooling import ToolContext, ToolDefinition

from tools.common import fail, ok, safe_path


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    path = payload.get("path")
    old_text = payload.get("old_text")
    new_text = payload.get("new_text")
    if not isinstance(path, str):
        raise TypeError("path must be a string")
    if not isinstance(old_text, str):
        raise TypeError("old_text must be a string")
    if not isinstance(new_text, str):
        raise TypeError("new_text must be a string")
    return {
        "path": path,
        "old_text": old_text,
        "new_text": new_text,
    }


def run(payload, context: ToolContext):
    try:
        file_path = safe_path(payload["path"], context.cwd)
        if context.permissions is not None:
            preview = (
                f"path: {payload['path']}\n"
                f"old: {payload['old_text'][:80]}\n"
                f"new: {payload['new_text'][:80]}"
            )
            context.permissions.ensure_edit(str(file_path), preview)
        text = file_path.read_text()
        if payload["old_text"] not in text:
            return fail(f"Error: text not found in {payload['path']}")
        file_path.write_text(text.replace(payload["old_text"], payload["new_text"], 1))
        return ok(f"Edited {payload['path']}")
    except Exception as error:  # noqa: BLE001
        return fail(f"Error: {error}")


TOOL = ToolDefinition(
    name="edit_file",
    description="Replace the first matching text in a workspace file.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_text": {"type": "string"},
            "new_text": {"type": "string"},
        },
        "required": ["path", "old_text", "new_text"],
    },
    validator=validate,
    run=run,
)
