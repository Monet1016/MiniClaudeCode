import ast
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
PROJECT_DIR = ROOT / "mini-claude-code"
MAIN_PATH = PROJECT_DIR / "main.py"
AGENT_LOOP_PATH = PROJECT_DIR / "agent_loop.py"

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


def load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def top_level_function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }


class AgentLoopSplitTests(unittest.TestCase):
    def test_agent_loop_module_exposes_expected_public_api(self):
        self.assertTrue(
            AGENT_LOOP_PATH.exists(),
            "agent_loop.py should be created by the split",
        )

        module = load_module("mini_claude_agent_loop", AGENT_LOOP_PATH)

        for name in (
            "AgentLoopDeps",
            "agent_loop",
            "print_turn_assistants",
            "cron_autorun_loop",
        ):
            self.assertTrue(
                hasattr(module, name),
                f"{name} should be exported from agent_loop.py",
            )

    def _make_deps(self, module, responses, printed, **overrides):
        client_calls = overrides.pop("client_calls", None)

        class FakeClient:
            def __init__(self, queued):
                self.messages = self
                self._queued = list(queued)

            def create(self, **kwargs):
                if client_calls is not None:
                    client_calls.append(kwargs)
                if not self._queued:
                    raise AssertionError("no fake responses left")
                next_item = self._queued.pop(0)
                if isinstance(next_item, Exception):
                    raise next_item
                return next_item

        handlers = {
            "bash": lambda command: f"ran {command}",
        }

        deps_kwargs = dict(
            client=FakeClient(responses),
            assemble_system_prompt=lambda context: "SYSTEM",
            assemble_tool_pool=lambda: ([{"name": "bash"}], handlers),
            update_context=lambda context, messages: context,
            compact_history=lambda messages: messages,
            reactive_compact=lambda messages: messages,
            consume_cron_queue=lambda: [],
            tool_result_budget=lambda messages: messages,
            snip_compact=lambda messages: messages,
            micro_compact=lambda messages: messages,
            estimate_size=lambda messages: 0,
            trigger_hooks=lambda *args: None,
            terminal_print=printed.append,
            has_tool_use=lambda content: any(
                getattr(block, "type", None) == "tool_use"
                for block in content
            ),
            call_tool_handler=lambda handler, tool_input, name: handler(**tool_input),
            context_limit=50_000,
            primary_model="primary-model",
            fallback_model=None,
        )
        deps_kwargs.update(overrides)
        return module.AgentLoopDeps(**deps_kwargs)

    def test_agent_loop_executes_tool_round_and_appends_tool_result(self):
        module = load_module("mini_claude_agent_loop_behavior", AGENT_LOOP_PATH)
        tool_block = SimpleNamespace(
            type="tool_use",
            name="bash",
            id="tool-1",
            input={"command": "echo hi"},
        )
        first_response = SimpleNamespace(
            stop_reason="tool_use",
            content=[tool_block],
        )
        final_response = SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="done")],
        )

        printed = []
        deps = self._make_deps(module, [first_response, final_response], printed)
        messages = [{"role": "user", "content": "say hi"}]

        module.agent_loop(messages, {}, deps)

        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(messages[2]["role"], "user")
        self.assertEqual(messages[2]["content"][0]["type"], "tool_result")
        self.assertEqual(messages[2]["content"][0]["content"], "ran echo hi")
        self.assertEqual(messages[3]["role"], "assistant")
        self.assertTrue(any("> bash" in line for line in printed))
        self.assertIn("ran echo hi", printed)

    def test_agent_loop_retries_max_tokens_with_continuation_prompt(self):
        module = load_module("mini_claude_agent_loop_max_tokens", AGENT_LOOP_PATH)
        first_response = SimpleNamespace(
            stop_reason="max_tokens",
            content=[SimpleNamespace(type="text", text="partial")],
        )
        second_response = SimpleNamespace(
            stop_reason="max_tokens",
            content=[SimpleNamespace(type="text", text="still partial")],
        )
        final_response = SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="complete")],
        )

        printed = []
        deps = self._make_deps(
            module,
            [first_response, second_response, final_response],
            printed,
        )
        messages = [{"role": "user", "content": "write more"}]

        module.agent_loop(messages, {}, deps)

        self.assertEqual(messages[1]["content"][0].text, "still partial")
        self.assertEqual(messages[2]["role"], "user")
        self.assertEqual(messages[2]["content"], module.CONTINUATION_PROMPT)
        self.assertEqual(messages[3]["content"][0].text, "complete")
        self.assertTrue(any("[max_tokens] retry with 16000" in line for line in printed))

    def test_agent_loop_reactive_compacts_after_prompt_too_long(self):
        module = load_module("mini_claude_agent_loop_reactive", AGENT_LOOP_PATH)
        client_calls = []
        compacted_payload = [{"role": "user", "content": "[Reactive compacted]"}]
        final_response = SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="recovered")],
        )

        printed = []
        deps = self._make_deps(
            module,
            [RuntimeError("prompt too long for context window"), final_response],
            printed,
            client_calls=client_calls,
            reactive_compact=lambda messages: compacted_payload,
        )
        messages = [{"role": "user", "content": "huge prompt"}]

        module.agent_loop(messages, {}, deps)

        self.assertEqual(messages[0]["content"], "[Reactive compacted]")
        self.assertEqual(messages[1]["content"][0].text, "recovered")
        self.assertEqual(client_calls[1]["messages"][0]["content"], "[Reactive compacted]")

    def test_with_retry_switches_to_fallback_after_repeated_529(self):
        module = load_module("mini_claude_agent_loop_retry", AGENT_LOOP_PATH)
        printed = []
        state = module.RecoveryState("primary-model")
        attempts = []

        original_sleep = module.time.sleep
        original_retry_delay = module.retry_delay
        module.time.sleep = lambda seconds: None
        module.retry_delay = lambda attempt: 0.0
        try:
            def flaky_call():
                attempts.append(state.current_model)
                if len(attempts) < 3:
                    raise RuntimeError("529 overloaded")
                return state.current_model

            result = module.with_retry(
                flaky_call,
                state,
                fallback_model="fallback-model",
                terminal_print=printed.append,
            )
        finally:
            module.time.sleep = original_sleep
            module.retry_delay = original_retry_delay

        self.assertEqual(result, "fallback-model")
        self.assertEqual(
            attempts,
            ["primary-model", "primary-model", "fallback-model"],
        )
        self.assertTrue(any("[529] retry 1/3" in line for line in printed))
        self.assertTrue(any("[529] switching to fallback-model" in line for line in printed))

    def test_print_turn_assistants_uses_injected_terminal_print(self):
        module = load_module("mini_claude_agent_loop_print", AGENT_LOOP_PATH)
        printed = []
        deps = self._make_deps(module, [], printed)
        messages = [
            {"role": "assistant", "content": [SimpleNamespace(type="text", text="old")]},
            {"role": "assistant", "content": [SimpleNamespace(type="text", text="new")]},
        ]

        module.print_turn_assistants(messages, 1, deps)

        self.assertEqual(printed, ["new"])

    def test_agent_loop_injects_todo_reminder_after_three_tool_rounds(self):
        module = load_module("mini_claude_agent_loop_todo", AGENT_LOOP_PATH)
        module.rounds_since_todo = 3

        final_response = SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="done")],
        )

        printed = []
        deps = self._make_deps(module, [final_response], printed)
        messages = [{"role": "user", "content": "ping"}]

        module.agent_loop(messages, {}, deps)

        reminder_messages = [
            msg for msg in messages
            if msg.get("role") == "user"
            and msg.get("content") == "<reminder>Update your todos.</reminder>"
        ]
        self.assertEqual(len(reminder_messages), 1)
        self.assertEqual(module.rounds_since_todo, 0)

    def test_cron_autorun_loop_runs_one_scheduled_turn(self):
        module = load_module("mini_claude_agent_loop_cron", AGENT_LOOP_PATH)
        printed = []
        history = []
        context = {}

        class StopLoop(Exception):
            pass

        queue_state = {"count": 0}

        def consume_cron_queue():
            if queue_state["count"] == 0:
                queue_state["count"] += 1
                return [SimpleNamespace(prompt="nightly job")]
            raise StopLoop()

        deps = self._make_deps(module, [], printed)
        deps = module.AgentLoopDeps(
            client=deps.client,
            assemble_system_prompt=deps.assemble_system_prompt,
            assemble_tool_pool=deps.assemble_tool_pool,
            update_context=lambda current, messages: {"updated": True},
            compact_history=deps.compact_history,
            reactive_compact=deps.reactive_compact,
            consume_cron_queue=consume_cron_queue,
            tool_result_budget=deps.tool_result_budget,
            snip_compact=deps.snip_compact,
            micro_compact=deps.micro_compact,
            estimate_size=deps.estimate_size,
            trigger_hooks=deps.trigger_hooks,
            terminal_print=printed.append,
            has_tool_use=deps.has_tool_use,
            call_tool_handler=deps.call_tool_handler,
            context_limit=deps.context_limit,
            primary_model=deps.primary_model,
            fallback_model=deps.fallback_model,
        )

        original_sleep = module.time.sleep
        original_agent_loop = module.agent_loop
        try:
            module.time.sleep = lambda _: None
            module.agent_loop = lambda messages, current_context, injected_deps: messages.append(
                {"role": "assistant", "content": [SimpleNamespace(type="text", text="cron done")]}
            )

            with self.assertRaises(StopLoop):
                module.cron_autorun_loop(history, context, deps)
        finally:
            module.time.sleep = original_sleep
            module.agent_loop = original_agent_loop

        self.assertEqual(history[0]["content"], "[Scheduled] nightly job")
        self.assertEqual(history[1]["role"], "assistant")
        self.assertTrue(any("cron done" in text for text in printed))

    def test_main_source_moves_loop_definitions_out_of_main(self):
        function_names = top_level_function_names(MAIN_PATH)

        for moved_name in (
            "prepare_context",
            "build_user_content",
            "inject_background_notifications",
            "call_llm",
            "agent_loop",
            "print_turn_assistants",
            "cron_autorun_loop",
        ):
            self.assertNotIn(
                moved_name,
                function_names,
                f"{moved_name} should no longer be defined in main.py",
            )

        self.assertIn(
            "build_agent_loop_deps",
            function_names,
            "main.py should expose a deps builder after the split",
        )

    def test_source_dependency_direction_is_one_way(self):
        main_source = MAIN_PATH.read_text(encoding="utf-8")
        loop_source = AGENT_LOOP_PATH.read_text(encoding="utf-8")

        self.assertIn("from agent_loop import", main_source)
        self.assertNotIn("from main import", loop_source)
        self.assertNotIn("import main", loop_source)


if __name__ == "__main__":
    unittest.main()
