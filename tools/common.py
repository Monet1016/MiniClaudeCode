from __future__ import annotations

from pathlib import Path

from tooling import ToolResult

WORKDIR = Path.cwd()


def safe_path(path_text: str, cwd: str | Path | None = None) -> Path:
    base = Path(cwd).resolve() if cwd is not None else WORKDIR
    path = (base / path_text).resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"Path escapes workspace: {path_text}")
    return path


def ok(output: str) -> ToolResult:
    return ToolResult(ok=True, output=output)


def fail(output: str) -> ToolResult:
    return ToolResult(ok=False, output=output)
