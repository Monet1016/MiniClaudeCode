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
    def __init__(self, responses, calls=None):
        self._responses = list(responses)
        self._calls = calls
        self.messages = self

    def create(self, **kwargs):
        if self._calls is not None:
            self._calls.append(kwargs)
        if not self._responses:
            raise AssertionError("No more fake responses available")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


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


def build_deps(module, responses, registry, printed, **overrides):
    permissions = FakePermissions()
    hooks = []
    client_calls = overrides.pop("client_calls", None)

    deps_kwargs = dict(
        client=FakeClient(responses, calls=client_calls),
        assemble_system_prompt=lambda context: "system",
        assemble_tool_pool=lambda: ([], registry),
        get_runtime=lambda: {"permissions": permissions},
        update_context=lambda context, messages: context,
        consume_cron_queue=lambda: [],
        trigger_hooks=lambda *args: hooks.append(args) or None,
        terminal_print=printed.append,
        has_tool_use=lambda content: any(getattr(block, "type", None) == "tool_use" for block in content),
        workspace_root=str(ROOT),
        primary_model="test-model",
        fallback_model=None,
    )
    deps_kwargs.update(overrides)
    deps = module.AgentLoopDeps(**deps_kwargs)
    return deps, permissions, hooks


class AgentLoopSplitTests(unittest.TestCase):
    def test_agent_loop_module_exposes_expected_public_api(self) -> None:
        module = load_agent_loop_module()

        for name in (
            "AgentLoopDeps",
            "run_context_cycle",
            "agent_loop",
            "print_turn_assistants",
            "cron_autorun_loop",
        ):
            self.assertTrue(hasattr(module, name))

    def test_run_context_cycle_prefers_cybernetics_and_mutates_messages(self) -> None:
        module = load_agent_loop_module()
        seen = {}
        messages = [{"role": "user", "content": "x" * 400}]

        class FakeCyber:
            def run_cycle(self, current_messages, step, tool_error_count):
                seen["args"] = (step, tool_error_count, list(current_messages))
                return SimpleNamespace(
                    did_compact=True,
                    messages=[{"role": "user", "content": "[Compacted]\n\nsummary"}],
                )

        deps, _, _ = build_deps(
            module,
            responses=[],
            registry=FakeRegistry(ToolResult(ok=True, output="unused")),
            printed=[],
            get_runtime=lambda: {"context_cybernetics": FakeCyber()},
        )

        updated = module.run_context_cycle(messages, deps, step=2, tool_error_count=1)

        self.assertEqual("[Compacted]\n\nsummary", updated[0]["content"])
        self.assertEqual((2, 1), seen["args"][:2])

    def test_run_context_cycle_falls_back_to_compactor_when_cybernetics_missing(self) -> None:
        module = load_agent_loop_module()
        seen = {}
        messages = [{"role": "user", "content": "x" * 400}]

        class FakeCompactor:
            def process_request(self, current_messages, trigger=None):
                seen["trigger"] = trigger
                return SimpleNamespace(
                    did_compact=True,
                    messages=[{"role": "user", "content": "[Compacted fallback]\n\nsummary"}],
                )

        deps, _, _ = build_deps(
            module,
            responses=[],
            registry=FakeRegistry(ToolResult(ok=True, output="unused")),
            printed=[],
            get_runtime=lambda: {"context_compactor": FakeCompactor()},
        )

        updated = module.run_context_cycle(messages, deps, step=3, tool_error_count=0)

        self.assertEqual("[Compacted fallback]\n\nsummary", updated[0]["content"])
        self.assertEqual("request", getattr(seen["trigger"], "value", seen["trigger"]))

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

    def test_agent_loop_reactive_recovery_prefers_cybernetics_before_compactor(self) -> None:
        module = load_agent_loop_module()
        order = []
        final_response = SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="recovered")],
        )

        class FakeCyber:
            def try_reactive_recover(self, messages, reason=None):
                order.append("cyber")
                return SimpleNamespace(did_compact=False, messages=messages)

        class FakeCompactor:
            def reactive_recover(self, messages, focus=None):
                order.append("compactor")
                return SimpleNamespace(
                    did_compact=True,
                    messages=[{"role": "user", "content": "[Reactive compacted]"}],
                )

        printed = []
        deps, _, _ = build_deps(
            module,
            [RuntimeError("prompt too long for context window"), final_response],
            FakeRegistry(ToolResult(ok=True, output="unused")),
            printed,
            get_runtime=lambda: {
                "context_cybernetics": FakeCyber(),
                "context_compactor": FakeCompactor(),
                "permissions": FakePermissions(),
            },
        )
        messages = [{"role": "user", "content": "huge prompt"}]

        module.agent_loop(messages, {}, deps)

        self.assertEqual(["cyber", "compactor"], order)
        self.assertEqual("[Reactive compacted]", messages[0]["content"])

    def test_agent_loop_reactive_recovery_uses_safety_snip_after_failed_recovery(self) -> None:
        module = load_agent_loop_module()
        final_response = SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="recovered after snip")],
        )

        class FakeCyber:
            def try_reactive_recover(self, messages, reason=None):
                return SimpleNamespace(did_compact=False, messages=messages)

        class FakeCompactor:
            def reactive_recover(self, messages, focus=None):
                return SimpleNamespace(did_compact=False, messages=messages)

        printed = []
        deps, _, _ = build_deps(
            module,
            [RuntimeError("prompt too long for context window"), final_response],
            FakeRegistry(ToolResult(ok=True, output="unused")),
            printed,
            get_runtime=lambda: {
                "context_cybernetics": FakeCyber(),
                "context_compactor": FakeCompactor(),
                "permissions": FakePermissions(),
            },
        )
        messages = [{"role": "user", "content": f"message-{index}"} for index in range(12)]

        module.agent_loop(messages, {}, deps)

        self.assertIn("[snipped", messages[2]["content"])

    def test_agent_loop_executes_compact_tool_through_registry(self) -> None:
        module = load_agent_loop_module()
        tool_block = SimpleNamespace(
            type="tool_use",
            name="compact",
            id="tool-1",
            input={"focus": "current task"},
        )
        first_response = SimpleNamespace(stop_reason="tool_use", content=[tool_block])
        final_response = SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="done")],
        )

        class LocalRegistry:
            def __init__(self):
                self.calls = []

            def execute(self, name, tool_input, context):
                self.calls.append((name, tool_input, context))
                return ToolResult(ok=True, output="[Compacted]\n\nsummary")

        registry = LocalRegistry()
        printed = []
        deps, _, _ = build_deps(
            module,
            [first_response, final_response],
            registry,
            printed,
            assemble_tool_pool=lambda: ([{"name": "compact"}], registry),
        )
        messages = [{"role": "user", "content": "compact now"}]

        module.agent_loop(messages, {}, deps)

        self.assertEqual("compact", registry.calls[0][0])
        self.assertEqual("[Compacted]\n\nsummary", messages[2]["content"][0]["content"])

    def test_agent_loop_reactive_compacts_after_prompt_too_long(self) -> None:
        module = load_agent_loop_module()
        client_calls = []
        final_response = SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="recovered")],
        )

        class FakeCompactor:
            def reactive_recover(self, messages, focus=None):
                return SimpleNamespace(
                    did_compact=True,
                    messages=[{"role": "user", "content": "[Reactive compacted]"}],
                )

        printed = []
        deps, _, _ = build_deps(
            module,
            [RuntimeError("prompt too long for context window"), final_response],
            FakeRegistry(ToolResult(ok=True, output="unused")),
            printed,
            client_calls=client_calls,
            get_runtime=lambda: {
                "context_compactor": FakeCompactor(),
                "permissions": FakePermissions(),
            },
        )
        messages = [{"role": "user", "content": "huge prompt"}]

        module.agent_loop(messages, {}, deps)

        self.assertEqual(messages[0]["content"], "[Reactive compacted]")
        self.assertEqual(messages[1]["content"][0].text, "recovered")
        self.assertEqual(client_calls[1]["messages"][0]["content"], "[Reactive compacted]")


if __name__ == "__main__":
    unittest.main()
