import ast
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from skills import list_skills, load_skill
from tooling import ToolContext
from tools.bash import TOOL as BASH_TOOL
from tools.edit_file import TOOL as EDIT_FILE_TOOL
from tools.grep_files import TOOL as GREP_FILES_TOOL
from tools.list_files import TOOL as LIST_FILES_TOOL
from tools.load_skill import create_load_skill_tool
from tools.patch_file import TOOL as PATCH_FILE_TOOL
from tools.read_file import TOOL as READ_FILE_TOOL
from tools.run_command import TOOL as RUN_COMMAND_TOOL
from tools.write_file import TOOL as WRITE_FILE_TOOL


ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = ROOT / "tests" / "fixtures_runtime"


def fresh_dir(prefix: str) -> Path:
    path = TMP_ROOT / f"{prefix}_{time.time_ns()}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_create_builtin_tool_registry_source():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    function_source = None
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == "create_builtin_tool_registry":
            function_source = ast.get_source_segment(source, node)
            break
    if function_source is None:
        raise AssertionError("create_builtin_tool_registry not found in main.py")
    return function_source


class RecordingPermissions:
    def __init__(self) -> None:
        self.path_calls: list[tuple[str, str]] = []
        self.command_calls: list[tuple[str, list[str], str, str | None]] = []
        self.edit_calls: list[tuple[str, str]] = []

    def ensure_path_access(self, target_path, intent: str) -> bool:
        self.path_calls.append((str(Path(target_path).resolve(strict=False)), intent))
        return True

    def ensure_command(
        self,
        command: str,
        args: list[str],
        command_cwd,
        force_prompt_reason: str | None = None,
    ) -> bool:
        self.command_calls.append(
            (
                command,
                list(args),
                str(Path(command_cwd).resolve(strict=False)),
                force_prompt_reason,
            )
        )
        return True

    def ensure_edit(self, target_path, diff_preview: str) -> bool:
        self.edit_calls.append(
            (str(Path(target_path).resolve(strict=False)), diff_preview)
        )
        return True


class LoadSkillToolTests(unittest.TestCase):
    def test_create_load_skill_tool_reads_skill_manifest(self) -> None:
        root = fresh_dir("load_skill_success")
        skill_dir = root / "skills" / "example"
        skill_dir.mkdir(parents=True, exist_ok=True)
        manifest = skill_dir / "SKILL.md"
        manifest.write_text(
            "---\n"
            "name: example\n"
            "description: Example skill\n"
            "---\n\n"
            "# Example\n\n"
            "body\n",
            encoding="utf-8",
        )

        tool = create_load_skill_tool(str(root))
        result = tool.run({"name": "example"}, ToolContext(cwd=str(root)))

        self.assertTrue(result.ok)
        self.assertIn("SKILL: example", result.output)
        self.assertIn(f"PATH: {manifest}", result.output)
        self.assertIn("# Example", result.output)

    def test_create_load_skill_tool_reports_unknown_skill(self) -> None:
        root = fresh_dir("load_skill_missing")
        tool = create_load_skill_tool(str(root))

        result = tool.run({"name": "missing"}, ToolContext(cwd=str(root)))

        self.assertFalse(result.ok)
        self.assertEqual("Unknown skill: missing", result.output)


class SkillsModuleTests(unittest.TestCase):
    def test_list_skills_and_load_skill_share_records(self) -> None:
        root = fresh_dir("skills_module")
        skill_dir = root / "skills" / "writer"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: writer\n"
            "description: Writing helper\n"
            "---\n\n"
            "content\n",
            encoding="utf-8",
        )

        skills = list_skills(str(root))
        record = load_skill(str(root), "writer")

        self.assertEqual(["writer"], [skill.name for skill in skills])
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual("Writing helper", record.description)
        self.assertEqual("content", record.content.split("---", 2)[2].strip())


class CoreToolTests(unittest.TestCase):
    def test_run_command_supports_args_and_timeout(self) -> None:
        root = fresh_dir("run_command")

        result = RUN_COMMAND_TOOL.run(
            {"command": "python", "args": ["-c", "print('ok')"], "timeout": 5},
            ToolContext(cwd=str(root)),
        )

        self.assertTrue(result.ok)
        self.assertEqual("ok", result.output.strip())

    def test_run_command_checks_command_cwd_access_and_command_permissions(self) -> None:
        root = fresh_dir("run_command_permissions")
        permissions = RecordingPermissions()

        result = RUN_COMMAND_TOOL.run(
            {"command": "python", "args": ["-c", "print('ok')"], "cwd": "."},
            ToolContext(cwd=str(root), permissions=permissions),
        )

        self.assertTrue(result.ok)
        self.assertEqual(
            [(str(root.resolve()), "command_cwd")],
            permissions.path_calls,
        )
        self.assertEqual(
            [("python", ["-c", "print('ok')"], str(root.resolve()), None)],
            permissions.command_calls,
        )

    def test_run_command_shell_mode_forces_permission_prompt_reason(self) -> None:
        root = fresh_dir("run_command_shell_permissions")
        permissions = RecordingPermissions()

        with patch("tools.run_command.subprocess.run") as subprocess_run:
            subprocess_run.return_value.stdout = "ok\n"
            subprocess_run.return_value.stderr = ""
            subprocess_run.return_value.returncode = 0

            result = RUN_COMMAND_TOOL.run(
                {"command": "python -c \"print('ok')\""},
                ToolContext(cwd=str(root), permissions=permissions),
            )

        self.assertTrue(result.ok)
        self.assertEqual(
            [
                (
                    "python -c \"print('ok')\"",
                    [],
                    str(root.resolve()),
                    "shell command executes arbitrary local code (python -c \"print('ok')\")",
                )
            ],
            permissions.command_calls,
        )

    def test_list_files_lists_entries_in_directory(self) -> None:
        root = fresh_dir("list_files")
        (root / "a.txt").write_text("a", encoding="utf-8")
        (root / "sub").mkdir()

        result = LIST_FILES_TOOL.run({"path": "."}, ToolContext(cwd=str(root)))

        self.assertTrue(result.ok)
        self.assertIn("file a.txt", result.output)
        self.assertIn("dir sub", result.output)

    def test_list_files_checks_list_permission(self) -> None:
        root = fresh_dir("list_files_permissions")
        permissions = RecordingPermissions()

        result = LIST_FILES_TOOL.run(
            {"path": "."},
            ToolContext(cwd=str(root), permissions=permissions),
        )

        self.assertTrue(result.ok)
        self.assertEqual(
            [(str(root.resolve()), "list")],
            permissions.path_calls,
        )

    def test_bash_alias_delegates_to_run_command(self) -> None:
        root = fresh_dir("bash_alias")

        result = BASH_TOOL.run(
            {"command": "python -c \"print('alias')\""},
            ToolContext(cwd=str(root)),
        )

        self.assertTrue(result.ok)
        self.assertIn("alias", result.output)

    def test_bash_alias_flows_through_run_command_permissions(self) -> None:
        root = fresh_dir("bash_alias_permissions")
        permissions = RecordingPermissions()

        with patch("tools.run_command.subprocess.run") as subprocess_run:
            subprocess_run.return_value.stdout = "alias\n"
            subprocess_run.return_value.stderr = ""
            subprocess_run.return_value.returncode = 0

            result = BASH_TOOL.run(
                {"command": "echo alias"},
                ToolContext(cwd=str(root), permissions=permissions),
            )

        self.assertTrue(result.ok)
        self.assertEqual(
            [(str(root.resolve()), "command_cwd")],
            permissions.path_calls,
        )
        self.assertEqual(
            [
                (
                    "echo alias",
                    [],
                    str(root.resolve()),
                    "shell command executes arbitrary local code (echo alias)",
                )
            ],
            permissions.command_calls,
        )

    def test_grep_files_finds_matching_lines(self) -> None:
        root = fresh_dir("grep_files")
        (root / "demo.py").write_text("print('hello')\nprint('world')\n", encoding="utf-8")

        result = GREP_FILES_TOOL.run({"pattern": "world", "path": "."}, ToolContext(cwd=str(root)))

        self.assertTrue(result.ok)
        self.assertIn("demo.py:2:", result.output)
        self.assertIn("1 match(es) in 1 file(s)", result.output)

    def test_grep_files_checks_search_permission(self) -> None:
        root = fresh_dir("grep_files_permissions")
        permissions = RecordingPermissions()
        (root / "demo.py").write_text("print('world')\n", encoding="utf-8")

        result = GREP_FILES_TOOL.run(
            {"pattern": "world", "path": "."},
            ToolContext(cwd=str(root), permissions=permissions),
        )

        self.assertTrue(result.ok)
        self.assertEqual(
            [(str(root.resolve()), "search")],
            permissions.path_calls,
        )

    def test_patch_file_applies_multiple_replacements(self) -> None:
        root = fresh_dir("patch_file")
        target = root / "demo.py"
        target.write_text("alpha = 1\nbeta = 1\n", encoding="utf-8")

        result = PATCH_FILE_TOOL.run(
            {
                "path": "demo.py",
                "replacements": [
                    {"search": "alpha = 1", "replace": "alpha = 2"},
                    {"search": "beta = 1", "replace": "beta = 3"},
                ],
            },
            ToolContext(cwd=str(root)),
        )

        self.assertTrue(result.ok)
        self.assertEqual("alpha = 2\nbeta = 3\n", target.read_text(encoding="utf-8"))

    def test_read_file_checks_read_permission_before_access(self) -> None:
        root = fresh_dir("read_file_permissions")
        permissions = RecordingPermissions()
        target = root / "note.txt"
        target.write_text("hello\n", encoding="utf-8")

        result = READ_FILE_TOOL.run(
            {"path": "note.txt"},
            ToolContext(cwd=str(root), permissions=permissions),
        )

        self.assertTrue(result.ok)
        self.assertEqual(
            [(str(target.resolve()), "read")],
            permissions.path_calls,
        )

    def test_in_workspace_read_still_works_without_permissions(self) -> None:
        root = fresh_dir("read_without_permissions")
        (root / "demo.txt").write_text("hello\nworld\n", encoding="utf-8")

        result = READ_FILE_TOOL.run({"path": "demo.txt"}, ToolContext(cwd=str(root)))

        self.assertTrue(result.ok)
        self.assertEqual("hello\nworld", result.output)

    def test_write_file_checks_edit_permission_with_write_preview(self) -> None:
        root = fresh_dir("write_file_permissions")
        permissions = RecordingPermissions()

        result = WRITE_FILE_TOOL.run(
            {"path": "note.txt", "content": "hello"},
            ToolContext(cwd=str(root), permissions=permissions),
        )

        self.assertTrue(result.ok)
        self.assertEqual(1, len(permissions.edit_calls))
        self.assertEqual(str((root / "note.txt").resolve()), permissions.edit_calls[0][0])
        self.assertIn("write file", permissions.edit_calls[0][1].lower())

    def test_edit_file_checks_edit_permission_with_old_and_new_preview(self) -> None:
        root = fresh_dir("edit_file_permissions")
        permissions = RecordingPermissions()
        target = root / "note.txt"
        target.write_text("alpha beta", encoding="utf-8")

        result = EDIT_FILE_TOOL.run(
            {"path": "note.txt", "old_text": "alpha", "new_text": "gamma"},
            ToolContext(cwd=str(root), permissions=permissions),
        )

        self.assertTrue(result.ok)
        self.assertEqual(1, len(permissions.edit_calls))
        preview = permissions.edit_calls[0][1]
        self.assertIn("old:", preview)
        self.assertIn("new:", preview)

    def test_patch_file_checks_edit_permission_with_replacement_count_preview(self) -> None:
        root = fresh_dir("patch_file_permissions")
        permissions = RecordingPermissions()
        target = root / "demo.py"
        target.write_text("alpha = 1\nbeta = 1\n", encoding="utf-8")

        result = PATCH_FILE_TOOL.run(
            {
                "path": "demo.py",
                "replacements": [
                    {"search": "alpha = 1", "replace": "alpha = 2"},
                    {"search": "beta = 1", "replace": "beta = 3"},
                ],
            },
            ToolContext(cwd=str(root), permissions=permissions),
        )

        self.assertTrue(result.ok)
        self.assertEqual(1, len(permissions.edit_calls))
        self.assertIn("2 replacement", permissions.edit_calls[0][1])


class MainCompatibilityTests(unittest.TestCase):
    def test_create_builtin_tool_registry_passes_cwd_when_supported(self) -> None:
        calls = []

        def build_core_tool_registry(cwd):
            calls.append(cwd)
            return ("new-signature", cwd)

        namespace = {
            "ToolRegistry": object,
            "WORKDIR": Path("D:/workspace"),
            "build_core_tool_registry": build_core_tool_registry,
        }
        exec(load_create_builtin_tool_registry_source(), namespace)

        result = namespace["create_builtin_tool_registry"]("D:/workspace")

        self.assertEqual(("new-signature", "D:/workspace"), result)
        self.assertEqual(["D:/workspace"], calls)

    def test_create_builtin_tool_registry_falls_back_for_legacy_signature(self) -> None:
        calls = []

        def build_core_tool_registry():
            calls.append("called")
            return "legacy-signature"

        namespace = {
            "ToolRegistry": object,
            "WORKDIR": Path("D:/workspace"),
            "build_core_tool_registry": build_core_tool_registry,
        }
        exec(load_create_builtin_tool_registry_source(), namespace)

        result = namespace["create_builtin_tool_registry"]("D:/workspace")

        self.assertEqual("legacy-signature", result)
        self.assertEqual(["called"], calls)


if __name__ == "__main__":
    unittest.main()
