from __future__ import annotations

from pathlib import Path


def resolve_workspace_path(cwd: str | Path, path_text: str) -> Path:
    base = Path(cwd).resolve()
    target = (base / path_text).resolve()
    if not target.is_relative_to(base):
        raise ValueError(f"Path escapes workspace: {path_text}")
    return target
