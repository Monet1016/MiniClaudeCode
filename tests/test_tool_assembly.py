import os
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import create_builtin_tool_registry, serialize_tools_for_llm


ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = ROOT / "main.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeAnthropic:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class FakeThread:
    started = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def start(self):
        FakeThread.started.append(
            {
                "args": self.args,
                "kwargs": self.kwargs,
            }
        )


def load_main_module(module_name: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(module_name, MAIN_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None

    anthropic_module = types.ModuleType("anthropic")
    anthropic_module.Anthropic = FakeAnthropic

    dotenv_module = types.ModuleType("dotenv")
    dotenv_module.load_dotenv = lambda **kwargs: None

    FakeThread.started = []
    with patch.dict(
        sys.modules,
        {
            "anthropic": anthropic_module,
            "dotenv": dotenv_module,
        },
    ), patch.dict(os.environ, {"MODEL_ID": "test-model"}, clear=False), patch.object(
        threading,
        "Thread",
        FakeThread,
    ):
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

    return module


class BuiltinRegistryAssemblyTests(unittest.TestCase):
    def test_builtin_registry_contains_new_core_tools_and_aliases(self):
        registry = create_builtin_tool_registry(str(ROOT))
        tool_names = registry.list_all()

        for expected in [
            "run_command",
            "list_files",
            "grep_files",
            "patch_file",
            "load_skill",
            "bash",
            "glob",
        ]:
            self.assertIn(expected, tool_names)

    def test_serialized_tools_put_new_names_before_aliases(self):
        registry = create_builtin_tool_registry(str(ROOT))
        serialized = serialize_tools_for_llm(registry)
        names = [tool["name"] for tool in serialized]

        self.assertLess(names.index("run_command"), names.index("bash"))
        self.assertLess(names.index("list_files"), names.index("glob"))


class MainToolPoolAssemblyTests(unittest.TestCase):
    def test_assemble_tool_pool_keeps_core_tools_and_main_workflow_tools(self):
        main_module = load_main_module("mini_claude_main_tool_pool_phase1")

        tools_schema, registry = main_module.assemble_tool_pool()
        names = registry.list_all()

        for expected in [
            "run_command",
            "list_files",
            "grep_files",
            "patch_file",
            "todo_write",
            "task",
            "connect_mcp",
        ]:
            self.assertIn(expected, names)

        serialized_names = [tool["name"] for tool in tools_schema]
        self.assertLess(serialized_names.index("run_command"), serialized_names.index("bash"))

    def test_create_subagent_tool_registry_exposes_phase1_core_tools(self):
        main_module = load_main_module("mini_claude_main_subagent_phase1")

        registry = main_module.create_subagent_tool_registry()

        for expected in [
            "run_command",
            "read_file",
            "write_file",
            "edit_file",
            "list_files",
            "grep_files",
            "patch_file",
            "load_skill",
            "bash",
            "glob",
        ]:
            self.assertIn(expected, registry.list_all())


if __name__ == "__main__":
    unittest.main()
