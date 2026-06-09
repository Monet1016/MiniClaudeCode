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
            "create_task",
            "connect_mcp",
        ]:
            self.assertIn(expected, names)

        serialized_names = [tool["name"] for tool in tools_schema]
        self.assertLess(serialized_names.index("run_command"), serialized_names.index("bash"))

    def test_assemble_tool_pool_prefers_registry_tool_when_name_collides(self):
        main_module = load_main_module("mini_claude_main_registry_priority")

        _, registry = main_module.assemble_tool_pool()
        names = registry.list_all()

        self.assertIn("run_command", names)
        self.assertIn("todo_write", names)
        self.assertIn("connect_mcp", names)
        self.assertEqual(names.count("run_command"), 1)

    def test_main_tool_pool_keeps_connect_mcp_in_main_layer(self):
        main_module = load_main_module("mini_claude_main_connect_mcp_layer")

        _, registry = main_module.assemble_tool_pool()

        self.assertIsNotNone(registry.find("connect_mcp"))
        self.assertIsNotNone(registry.find("task"))
        self.assertIsNotNone(registry.find("create_task"))

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

    def test_build_context_components_returns_wired_triplet(self):
        main_module = load_main_module("mini_claude_main_context_components")

        manager, compactor, cybernetics = main_module.build_context_components()

        self.assertEqual(main_module.CONTEXT_LIMIT, manager.context_window)
        self.assertEqual(main_module.TOOL_RESULTS_DIR, compactor.tool_results_dir)
        self.assertIs(cybernetics.context_manager, manager)
        self.assertIs(cybernetics.context_compactor, compactor)

    def test_build_runtime_context_exposes_context_control_objects(self):
        main_module = load_main_module("mini_claude_main_runtime_context_objects")
        history = [{"role": "user", "content": "hello"}]

        runtime = main_module.build_runtime_context(messages=history)

        self.assertIs(runtime["messages"], history)
        self.assertTrue(callable(runtime["manual_compact"]))
        self.assertEqual(main_module.CONTEXT_LIMIT, runtime["context_manager"].context_window)
        self.assertIs(runtime["context_cybernetics"].context_manager, runtime["context_manager"])
        self.assertIs(runtime["context_cybernetics"].context_compactor, runtime["context_compactor"])

    def test_build_child_runtime_keeps_manual_compact_but_gets_fresh_context_objects(self):
        main_module = load_main_module("mini_claude_main_child_context_objects")
        parent_runtime = main_module.build_runtime_context(messages=[{"role": "user", "content": "parent"}])
        child_runtime = main_module.build_child_runtime_context(
            parent_runtime=parent_runtime,
            messages=[{"role": "user", "content": "child"}],
            sender="subagent",
            agent_name="subagent",
        )

        self.assertTrue(callable(child_runtime["manual_compact"]))
        self.assertIsNot(child_runtime["context_manager"], parent_runtime["context_manager"])
        self.assertIsNot(child_runtime["context_compactor"], parent_runtime["context_compactor"])
        self.assertIsNot(child_runtime["context_cybernetics"], parent_runtime["context_cybernetics"])
        self.assertEqual("child", child_runtime["messages"][0]["content"])

    def test_build_agent_loop_deps_reuses_same_runtime_across_calls(self):
        main_module = load_main_module("mini_claude_main_runtime_reuse")
        messages = [{"role": "user", "content": "hello"}]

        deps = main_module.build_agent_loop_deps(messages)
        first = deps.get_runtime()
        second = deps.get_runtime()

        self.assertIs(first, second)
        self.assertIs(first["context_manager"], second["context_manager"])

    def test_runtime_context_drops_legacy_compaction_callbacks(self):
        main_module = load_main_module("mini_claude_main_runtime_no_legacy_compaction")

        runtime = main_module.build_runtime_context(messages=[])

        self.assertNotIn("compact_history", runtime)
        self.assertNotIn("reactive_compact", runtime)


if __name__ == "__main__":
    unittest.main()
