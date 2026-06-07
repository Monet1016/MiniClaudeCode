from __future__ import annotations

import fnmatch
import re

from tooling import ToolContext, ToolDefinition
from tools.common import fail, ok, resolve_path

SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", "dist", "build"}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".db", ".pyc"}


def _normalize_patterns(value):
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        raise TypeError("include/exclude must be a string or list")
    return [str(item) for item in value]


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")

    pattern = payload.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        raise TypeError("pattern must be a non-empty string")

    context_lines = payload.get("context_lines", 0)
    if not isinstance(context_lines, int):
        raise TypeError("context_lines must be an integer")

    return {
        "pattern": pattern,
        "path": payload.get("path", "."),
        "include": _normalize_patterns(payload.get("include")),
        "exclude": _normalize_patterns(payload.get("exclude")),
        "case_sensitive": bool(payload.get("case_sensitive", False)),
        "context_lines": min(max(context_lines, 0), 5),
    }


def run(payload, context: ToolContext):
    payload = {
        "pattern": payload["pattern"],
        "path": payload.get("path", "."),
        "include": payload.get("include"),
        "exclude": payload.get("exclude"),
        "case_sensitive": bool(payload.get("case_sensitive", False)),
        "context_lines": payload.get("context_lines", 0),
    }
    try:
        root = resolve_path(payload["path"], context.cwd)
        if context.permissions is not None:
            context.permissions.ensure_path_access(str(root), "search")
        flags = 0 if payload["case_sensitive"] else re.IGNORECASE
        regex = re.compile(payload["pattern"], flags)
        results: list[str] = []
        total_matches = 0
        matched_files = 0

        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue

            relative_parts = path.relative_to(root).parts
            if any(part in SKIP_DIRS for part in relative_parts):
                continue
            if path.suffix.lower() in BINARY_SUFFIXES:
                continue

            relative_path = path.relative_to(root).as_posix()
            include_patterns = payload["include"] if isinstance(payload["include"], list) else ([payload["include"]] if payload["include"] else None)
            exclude_patterns = payload["exclude"] if isinstance(payload["exclude"], list) else ([payload["exclude"]] if payload["exclude"] else None)

            if include_patterns and not any(
                fnmatch.fnmatch(relative_path, pattern) or fnmatch.fnmatch(path.name, pattern)
                for pattern in include_patterns
            ):
                continue
            if exclude_patterns and any(
                fnmatch.fnmatch(relative_path, pattern) or fnmatch.fnmatch(path.name, pattern)
                for pattern in exclude_patterns
            ):
                continue

            text = path.read_text(encoding="utf-8", errors="ignore")
            file_matches = 0
            for line_number, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    file_matches += 1
                    total_matches += 1
                    results.append(f"{relative_path}:{line_number}: {line}")

            if file_matches:
                matched_files += 1

        if not results:
            return ok("No matches found.")
        results.extend(["", f"{total_matches} match(es) in {matched_files} file(s)"])
        return ok("\n".join(results))
    except Exception as error:  # noqa: BLE001
        return fail(f"Error: {error}")


TOOL = ToolDefinition(
    name="grep_files",
    description="Search UTF-8 text files under a directory using a regex pattern.",
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string"},
            "include": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ]
            },
            "exclude": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ]
            },
            "case_sensitive": {"type": "boolean"},
            "context_lines": {"type": "integer"},
        },
        "required": ["pattern"],
    },
    validator=validate,
    run=run,
)
