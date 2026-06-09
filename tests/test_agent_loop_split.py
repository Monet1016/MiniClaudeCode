import importlib.util
import itertools
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tooling import BackgroundTaskResult, ToolResult


ROOT = Path(__file__).resolve().parents[1]
_MODULE_COUNTER = itertools.count()


def load_agent_loop_module():
    module_name = f"agent_loop_test_{next(_MODULE_COUNTER)}"
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "agent_loop.py")
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load agent_loop.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.messages = self

    def create(self, **kwargs):
        if not self._responses:
            raise AssertionError("No more fake responses available")
        return self._responses.pop(0)


class FakeRegistry:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def execute(self, tool_name, input_data, context):
        self.calls.append((tool_name, input_data, context))
        return self.result


class FakePermissions:
    def __init__(self) -> None:
        self.begin_calls = 0
        self.end_calls = 0

    def begin_turn(self) -> None:
        self.begin_calls += 1

    def end_turn(self) -> None:
        self.end_calls += 1


def make_tool_use_block():
    return SimpleNamespace(
        type="tool_use",
        id="toolu_1",
        name="bash",
        input={"command": "python test.py", "run_in_background": True},
    )


def make_slow_tool_use_block():
    return SimpleNamespace(
        type="tool_use",
        id="toolu_1",
        name="bash",
        input={"command": "npm install"},
    )


def make_text_block(text):
    return SimpleNamespace(type="text", text=text)


def make_response(content, stop_reason="end_turn"):
    return SimpleNamespace(content=content, stop_reason=stop_reason)


def build_deps(module, responses, registry, printed):
    permissions = FakePermissions()
    hooks = []

    deps = module.AgentLoopDeps(
        client=FakeClient(responses),
        assemble_system_prompt=lambda context: "system",
        assemble_tool_pool=lambda: ([], registry),
        get_runtime=lambda: {"permissions": permissions},
        update_context=lambda context, messages: context,
        compact_history=lambda messages: messages,
        reactive_compact=lambda messages: messages,
        consume_cron_queue=lambda: [],
        tool_result_budget=lambda messages: messages,
        snip_compact=lambda messages: messages,
        micro_compact=lambda messages: messages,
        estimate_size=lambda messages: 0,
        trigger_hooks=lambda *args: hooks.append(args) or None,
        terminal_print=printed.append,
        has_tool_use=lambda content: any(getattr(block, "type", None) == "tool_use" for block in content),
        workspace_root=str(ROOT),
        context_limit=10_000,
        primary_model="test-model",
        fallback_model=None,
    )
    return deps, permissions, hooks


class AgentLoopSplitTests(unittest.TestCase):
    def test_agent_loop_reports_background_tool_result_without_background_worker(self) -> None:
        module = load_agent_loop_module()
        background_task = BackgroundTaskResult(
            task_id="task_0001",
            command="python test.py",
            cwd=str(ROOT),
            pid=4321,
            status="running",
            started_at=1710000000,
        )
        registry = FakeRegistry(
            ToolResult(
                ok=True,
                output="Background command started.\nTASK: task_0001\nPID: 4321",
                background_task=background_task,
            )
        )
        printed = []
        deps, permissions, hooks = build_deps(
            module,
            responses=[
                make_response([make_tool_use_block()]),
                make_response([make_text_block("done")]),
            ],
            registry=registry,
            printed=printed,
        )
        messages = [{"role": "user", "content": "run the test"}]

        with patch.object(module, "collect_background_notifications", return_value=[]):
            module.agent_loop(messages, {}, deps)

        self.assertEqual(1, len(registry.calls))
        self.assertEqual(1, permissions.begin_calls)
        self.assertEqual(1, permissions.end_calls)
        self.assertIn(("PostToolUse", unittest.mock.ANY, registry.result), hooks)
        tool_result_message = next(
            message
            for message in messages
            if message["role"] == "user"
            and isinstance(message["content"], list)
            and message["content"]
            and message["content"][0].get("type") == "tool_result"
        )
        self.assertEqual(
            "Background command started.\nTASK: task_0001\nPID: 4321",
            tool_result_message["content"][0]["content"],
        )
        self.assertTrue(any("[background] task_0001" in line for line in printed))

    def test_agent_loop_emits_background_notifications_from_registry(self) -> None:
        module = load_agent_loop_module()
        registry = FakeRegistry(ToolResult(ok=True, output="Background command started."))
        printed = []
        deps, permissions, _hooks = build_deps(
            module,
            responses=[
                make_response([make_tool_use_block()]),
                make_response([make_text_block("done")]),
            ],
            registry=registry,
            printed=printed,
        )
        messages = [{"role": "user", "content": "run the test"}]
        notification = (
            "<task_notification>\n"
            "  <task_id>task_0001</task_id>\n"
            "  <status>completed</status>\n"
            "  <command>python test.py</command>\n"
            "  <summary>Process exited.</summary>\n"
            "</task_notification>"
        )

        with patch.object(
            module,
            "collect_background_notifications",
            side_effect=[[], [notification], []],
        ):
            module.agent_loop(messages, {}, deps)

        self.assertEqual(1, len(registry.calls))
        self.assertEqual(1, permissions.begin_calls)
        self.assertEqual(1, permissions.end_calls)
        self.assertEqual("assistant", messages[1]["role"])
        self.assertEqual("tool_use", messages[1]["content"][0].type)
        self.assertEqual("user", messages[2]["role"])
        self.assertEqual("tool_result", messages[2]["content"][0]["type"])
        self.assertEqual("Background command started.", messages[2]["content"][0]["content"])
        self.assertEqual("user", messages[3]["role"])
        self.assertEqual("text", messages[3]["content"][0]["type"])
        self.assertIn("<task_notification>", messages[3]["content"][0]["text"])
        self.assertNotIn("<task_notification>", messages[2]["content"][0]["content"])
        self.assertEqual("assistant", messages[4]["role"])
        self.assertEqual("text", messages[4]["content"][0].type)
        self.assertEqual("done", messages[4]["content"][0].text)

    def test_agent_loop_does_not_auto_background_slow_command_without_flag(self) -> None:
        module = load_agent_loop_module()
        registry = FakeRegistry(ToolResult(ok=True, output="ran synchronously"))
        printed = []
        deps, permissions, _hooks = build_deps(
            module,
            responses=[
                make_response([make_slow_tool_use_block()]),
                make_response([make_text_block("done")]),
            ],
            registry=registry,
            printed=printed,
        )
        messages = [{"role": "user", "content": "install dependencies"}]

        with patch.object(module, "collect_background_notifications", return_value=[]):
            module.agent_loop(messages, {}, deps)

        self.assertEqual(1, len(registry.calls))
        self.assertEqual(1, permissions.begin_calls)
        self.assertEqual(1, permissions.end_calls)
        self.assertFalse(any("[background]" in line for line in printed))
        self.assertFalse(any("Background task" in str(line) for line in printed))
        self.assertEqual("user", messages[2]["role"])
        self.assertEqual("tool_result", messages[2]["content"][0]["type"])
        self.assertEqual("ran synchronously", messages[2]["content"][0]["content"])
        self.assertFalse(
            any(
                "Background task" in block.get("content", "")
                for message in messages
                if isinstance(message.get("content"), list)
                for block in message["content"]
                if isinstance(block, dict) and block.get("type") == "tool_result"
            )
        )


if __name__ == "__main__":
    unittest.main()
