from __future__ import annotations

import json
import os
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Literal

PermissionDecision = Literal[
    "allow_once",
    "allow_always",
    "allow_turn",
    "allow_all_turn",
    "deny_once",
    "deny_always",
]

PromptHandler = Callable[[dict[str, Any]], dict[str, Any]]
PERMISSIONS_PATH = Path.home() / ".mini-claude-code" / "permissions.json"
_is_win = sys.platform == "win32"
_normalize_path_cached = lru_cache(maxsize=512)(lambda p: str(Path(p).resolve()))


def _normalize_path(target_path: str | Path) -> str:
    return _normalize_path_cached(str(target_path))


def _is_within_directory(root: str | Path, target: str | Path) -> bool:
    root_str = _normalize_path(root)
    target_str = _normalize_path(target)
    if _is_win:
        target_cmp = target_str.lower()
        root_cmp = root_str.lower().rstrip("\\/")
        return (
            target_cmp == root_cmp
            or target_cmp.startswith(root_cmp + "\\")
            or target_cmp.startswith(root_cmp + "/")
        )
    root_cmp = root_str.rstrip(os.sep)
    return target_str == root_cmp or target_str.startswith(root_cmp + os.sep)


def _matches_directory_prefix(target_path: str, directories: set[str]) -> bool:
    return any(_is_within_directory(directory, target_path) for directory in directories)


def _format_command_signature(command: str, args: list[str]) -> str:
    return " ".join([command, *args]).strip()


def _classify_dangerous_command(command: str, args: list[str]) -> str | None:
    normalized_command = command.strip().lower()
    normalized_args = [arg.strip() for arg in args if str(arg).strip()]
    lowered_args = [arg.lower() for arg in normalized_args]
    signature = _format_command_signature(command, normalized_args)

    if normalized_command == "git":
        if "reset" in lowered_args and "--hard" in lowered_args:
            return f"git reset --hard can discard local changes ({signature})"
        if "clean" in lowered_args:
            return f"git clean can delete untracked files ({signature})"
        if "checkout" in lowered_args and "--" in lowered_args:
            return f"git checkout -- can overwrite working tree files ({signature})"
        if "push" in lowered_args and any(arg in {"--force", "-f"} for arg in lowered_args):
            return f"git push --force rewrites remote history ({signature})"

    if normalized_command == "rm":
        combined_flags = "".join(arg for arg in lowered_args if arg.startswith("-"))
        if "r" in combined_flags and "f" in combined_flags:
            return f"rm -rf can cause catastrophic data loss ({signature})"

    if normalized_command in {"dd", "mkfs", "fdisk", "format"}:
        return f"{normalized_command} can modify or destroy disk partitions ({signature})"

    if normalized_command == "chmod" and (
        "777" in lowered_args or any(arg.endswith("777") for arg in lowered_args)
    ):
        return f"chmod 777 opens permissions to all users ({signature})"

    if normalized_command in {"python", "python3", "node", "bash", "sh", "pwsh", "powershell"}:
        return f"{normalized_command} can execute arbitrary local code ({signature})"

    return None


def _read_permission_store() -> dict[str, Any]:
    if not PERMISSIONS_PATH.exists():
        return {}
    try:
        data = json.loads(PERMISSIONS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_permission_store(store: dict[str, Any]) -> None:
    PERMISSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=PERMISSIONS_PATH.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(store, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_path, PERMISSIONS_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _write_permission_store_to(path: Path, store: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(store, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


class PermissionManager:
    def __init__(
        self,
        workspace_root: str,
        prompt: PromptHandler | None = None,
        permissions_path: Path | None = None,
        prompt_handler: PromptHandler | None = None,
    ) -> None:
        self.workspace_root = _normalize_path(workspace_root)
        self.prompt = prompt if prompt is not None else prompt_handler
        self.permissions_path = permissions_path
        self.allowed_directory_prefixes: set[str] = set()
        self.denied_directory_prefixes: set[str] = set()
        self.session_allowed_paths: set[str] = set()
        self.session_denied_paths: set[str] = set()
        self.allowed_command_patterns: set[str] = set()
        self.denied_command_patterns: set[str] = set()
        self.session_allowed_commands: set[str] = set()
        self.session_denied_commands: set[str] = set()
        self.allowed_edit_targets: set[str] = set()
        self.denied_edit_targets: set[str] = set()
        self.session_allowed_edits: set[str] = set()
        self.session_denied_edits: set[str] = set()
        self.turn_allowed_edits: set[str] = set()
        self.turn_allow_all_edits = False
        self._initialize()


    def _store_path(self) -> Path:
        return self.permissions_path or PERMISSIONS_PATH


    def _initialize(self) -> None:
        store = _read_permission_store() if self.permissions_path is None else self._read_custom_store()
        self.allowed_directory_prefixes |= {
            _normalize_path(item) for item in store.get("allowedDirectoryPrefixes", [])
        }
        self.denied_directory_prefixes |= {
            _normalize_path(item) for item in store.get("deniedDirectoryPrefixes", [])
        }
        self.allowed_command_patterns |= set(store.get("allowedCommandPatterns", []))
        self.denied_command_patterns |= set(store.get("deniedCommandPatterns", []))
        self.allowed_edit_targets |= {
            _normalize_path(item) for item in store.get("allowedEditTargets", [])
        }
        self.denied_edit_targets |= {
            _normalize_path(item) for item in store.get("deniedEditTargets", [])
        }


    def _read_custom_store(self) -> dict[str, Any]:
        path = self._store_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}


    def _persist(self) -> None:
        store = {
            "allowedDirectoryPrefixes": sorted(self.allowed_directory_prefixes),
            "deniedDirectoryPrefixes": sorted(self.denied_directory_prefixes),
            "allowedCommandPatterns": sorted(self.allowed_command_patterns),
            "deniedCommandPatterns": sorted(self.denied_command_patterns),
            "allowedEditTargets": sorted(self.allowed_edit_targets),
            "deniedEditTargets": sorted(self.denied_edit_targets),
        }
        if self.permissions_path is None:
            _write_permission_store(store)
            return
        _write_permission_store_to(self.permissions_path, store)


    def begin_turn(self) -> None:
        self.turn_allowed_edits.clear()
        self.turn_allow_all_edits = False


    def end_turn(self) -> None:
        self.begin_turn()


    def get_summary(self) -> list[str]:
        summary = [f"cwd: {self.workspace_root}"]
        summary.append(
            "extra allowed dirs: "
            + (
                ", ".join(sorted(self.allowed_directory_prefixes)[:4])
                if self.allowed_directory_prefixes
                else "none"
            )
        )
        summary.append(
            "dangerous allowlist: "
            + (
                ", ".join(sorted(self.allowed_command_patterns)[:4])
                if self.allowed_command_patterns
                else "none"
            )
        )
        if self.allowed_edit_targets:
            summary.append(
                "trusted edit targets: " + ", ".join(sorted(self.allowed_edit_targets)[:2])
            )
        return summary


    def ensure_path_access(self, target_path: str, intent: str) -> None:
        normalized_target = _normalize_path(target_path)
        if _is_within_directory(self.workspace_root, normalized_target):
            return
        if normalized_target in self.session_denied_paths or _matches_directory_prefix(
            normalized_target, self.denied_directory_prefixes
        ):
            raise RuntimeError(f"Access denied for path outside cwd: {normalized_target}")
        if normalized_target in self.session_allowed_paths or _matches_directory_prefix(
            normalized_target, self.allowed_directory_prefixes
        ):
            return
        if self.prompt is None:
            raise RuntimeError(f"Access denied for path outside cwd: {normalized_target}")

        scope_directory = (
            normalized_target
            if intent in {"list", "command_cwd"}
            else str(Path(normalized_target).parent)
        )
        result = self.prompt(
            {
                "kind": "path",
                "summary": f"mini-claude-code wants {intent.replace('_', ' ')} access outside the current cwd",
                "details": [
                    f"cwd: {self.workspace_root}",
                    f"target: {normalized_target}",
                    f"scope directory: {scope_directory}",
                ],
                "scope": scope_directory,
                "choices": [
                    {"key": "y", "label": "allow once", "decision": "allow_once"},
                    {"key": "a", "label": "allow this directory", "decision": "allow_always"},
                    {"key": "n", "label": "deny once", "decision": "deny_once"},
                    {"key": "d", "label": "deny this directory", "decision": "deny_always"},
                ],
            }
        )
        decision = result.get("decision")
        if decision == "allow_once":
            self.session_allowed_paths.add(normalized_target)
            return
        if decision == "allow_always":
            self.allowed_directory_prefixes.add(scope_directory)
            self._persist()
            return
        if decision == "deny_always":
            self.denied_directory_prefixes.add(scope_directory)
            self._persist()
        else:
            self.session_denied_paths.add(normalized_target)
        raise RuntimeError(f"Access denied for path outside cwd: {normalized_target}")


    def ensure_command(
        self,
        command: str,
        args: list[str],
        command_cwd: str,
        force_prompt_reason: str | None = None,
    ) -> None:
        self.ensure_path_access(command_cwd, "command_cwd")
        reason = force_prompt_reason or _classify_dangerous_command(command, args)
        if not reason:
            return
        signature = _format_command_signature(command, args)
        if signature in self.session_denied_commands or signature in self.denied_command_patterns:
            raise RuntimeError(f"Command denied: {signature}")
        if signature in self.session_allowed_commands or signature in self.allowed_command_patterns:
            return
        if self.prompt is None:
            raise RuntimeError(f"Command requires approval: {signature}")

        result = self.prompt(
            {
                "kind": "command",
                "summary": "mini-claude-code wants approval for this command",
                "details": [f"cwd: {command_cwd}", f"command: {signature}", f"reason: {reason}"],
                "scope": signature,
                "choices": [
                    {"key": "y", "label": "allow once", "decision": "allow_once"},
                    {"key": "a", "label": "always allow this command", "decision": "allow_always"},
                    {"key": "n", "label": "deny once", "decision": "deny_once"},
                    {"key": "d", "label": "always deny this command", "decision": "deny_always"},
                ],
            }
        )
        decision = result.get("decision")
        if decision == "allow_once":
            self.session_allowed_commands.add(signature)
            return
        if decision == "allow_always":
            self.allowed_command_patterns.add(signature)
            self._persist()
            return
        if decision == "deny_always":
            self.denied_command_patterns.add(signature)
            self._persist()
        else:
            self.session_denied_commands.add(signature)
        raise RuntimeError(f"Command denied: {signature}")


    def ensure_edit(self, target_path: str, diff_preview: str) -> None:
        normalized_target = _normalize_path(target_path)
        if normalized_target in self.session_denied_edits or normalized_target in self.denied_edit_targets:
            raise RuntimeError(f"Edit denied: {normalized_target}")
        if (
            normalized_target in self.session_allowed_edits
            or normalized_target in self.turn_allowed_edits
            or self.turn_allow_all_edits
            or normalized_target in self.allowed_edit_targets
        ):
            return
        if self.prompt is None:
            raise RuntimeError(f"Edit requires approval: {normalized_target}")

        result = self.prompt(
            {
                "kind": "edit",
                "summary": "mini-claude-code wants to modify a file",
                "details": [f"path: {normalized_target}", diff_preview],
                "scope": normalized_target,
                "choices": [
                    {"key": "y", "label": "allow once", "decision": "allow_once"},
                    {"key": "t", "label": "allow this turn", "decision": "allow_turn"},
                    {"key": "T", "label": "allow all edits this turn", "decision": "allow_all_turn"},
                    {"key": "a", "label": "always allow this file", "decision": "allow_always"},
                    {"key": "n", "label": "deny once", "decision": "deny_once"},
                    {"key": "d", "label": "always deny this file", "decision": "deny_always"},
                ],
            }
        )
        decision = result.get("decision")
        if decision == "allow_once":
            self.session_allowed_edits.add(normalized_target)
            return
        if decision == "allow_turn":
            self.turn_allowed_edits.add(normalized_target)
            return
        if decision == "allow_all_turn":
            self.turn_allow_all_edits = True
            return
        if decision == "allow_always":
            self.allowed_edit_targets.add(normalized_target)
            self._persist()
            return
        if decision == "deny_always":
            self.denied_edit_targets.add(normalized_target)
            self._persist()
        else:
            self.session_denied_edits.add(normalized_target)
        raise RuntimeError(f"Edit denied: {normalized_target}")
