from __future__ import annotations

from tooling import ToolContext, ToolDefinition
from tools.common import fail, ok, safe_path


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")

    path = payload.get("path")
    replacements = payload.get("replacements")
    if not isinstance(path, str) or not path:
        raise TypeError("path must be a non-empty string")
    if not isinstance(replacements, list) or not replacements:
        raise TypeError("replacements must be a non-empty list")

    normalized = []
    for item in replacements:
        if not isinstance(item, dict):
            raise TypeError("replacement entries must be objects")
        search = item.get("search")
        replace = item.get("replace")
        if not isinstance(search, str) or not search:
            raise TypeError("replacement search must be a non-empty string")
        if not isinstance(replace, str):
            raise TypeError("replacement replace must be a string")
        normalized.append(
            {
                "search": search.replace("\r\n", "\n"),
                "replace": replace.replace("\r\n", "\n"),
                "replace_all": bool(item.get("replaceAll", item.get("replace_all", False))),
            }
        )
    return {"path": path, "replacements": normalized}


def run(payload, context: ToolContext):
    normalized_replacements = []
    for item in payload["replacements"]:
        normalized_replacements.append(
            {
                "search": item["search"].replace("\r\n", "\n"),
                "replace": item["replace"].replace("\r\n", "\n"),
                "replace_all": bool(item.get("replace_all", item.get("replaceAll", False))),
            }
        )
    payload = {"path": payload["path"], "replacements": normalized_replacements}
    try:
        target = safe_path(payload["path"], context.cwd)
        content = target.read_text(encoding="utf-8")
        for index, replacement in enumerate(payload["replacements"], start=1):
            if replacement["search"] not in content:
                return fail(f"Replacement {index} not found in {payload['path']}")
            if replacement["replace_all"]:
                content = content.replace(replacement["search"], replacement["replace"])
            else:
                content = content.replace(replacement["search"], replacement["replace"], 1)
        target.write_text(content, encoding="utf-8")
        return ok(
            f"Patched {payload['path']} with {len(payload['replacements'])} replacement(s)"
        )
    except Exception as error:  # noqa: BLE001
        return fail(f"Error: {error}")


TOOL = ToolDefinition(
    name="patch_file",
    description="Apply multiple exact-text replacements to one file in a single operation.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "replacements": {"type": "array"},
        },
        "required": ["path", "replacements"],
    },
    validator=validate,
    run=run,
)
