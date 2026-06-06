from __future__ import annotations

import glob as glob_module
from pathlib import Path

from tooling import ToolContext, ToolDefinition

from tools.common import fail, ok


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    pattern = payload.get("pattern")
    if not isinstance(pattern, str):
        raise TypeError("pattern must be a string")
    return {"pattern": pattern}


def run(payload, context: ToolContext):
    try:
        base = Path(context.cwd).resolve()
        results = []
        for match in glob_module.glob(payload["pattern"], root_dir=base):
            if (base / match).resolve().is_relative_to(base):
                results.append(match)
        return ok("\n".join(results) if results else "(no matches)")
    except Exception as error:  # noqa: BLE001
        return fail(f"Error: {error}")


TOOL = ToolDefinition(
    name="glob",
    description="Find workspace files by glob pattern.",
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
        },
        "required": ["pattern"],
    },
    validator=validate,
    run=run,
)
