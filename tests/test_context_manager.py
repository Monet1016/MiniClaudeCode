import unittest

from context_manager import ContextManager, estimate_message_tokens, estimate_messages_tokens


class ContextManagerTests(unittest.TestCase):
    def test_estimate_message_tokens_counts_plain_text_message(self):
        message = {"role": "user", "content": "hello world"}

        tokens = estimate_message_tokens(message)

        self.assertGreater(tokens, 0)

    def test_estimate_message_tokens_counts_block_list_message(self):
        message = {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "alpha beta"},
                {"type": "tool_use", "name": "read_file", "input": {"path": "main.py"}},
            ],
        }

        tokens = estimate_message_tokens(message)

        self.assertGreater(tokens, 0)

    def test_estimate_messages_tokens_sums_message_estimates(self):
        messages = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
        ]

        total = estimate_messages_tokens(messages)

        self.assertEqual(
            total,
            estimate_message_tokens(messages[0]) + estimate_message_tokens(messages[1]),
        )

    def test_context_manager_tracks_stats_and_compaction_history(self):
        manager = ContextManager(model="test-model", context_window=120)
        manager.add_message({"role": "user", "content": "replace prepare_context"})
        manager.add_message(
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "read_file", "input": {"path": "agent_loop.py"}},
                ],
            }
        )
        manager.record_compaction(
            {
                "strategy": "structured",
                "trigger": "request",
                "tokens_before": 90,
                "tokens_after": 40,
            }
        )

        stats = manager.get_stats()

        self.assertEqual(2, stats["message_count"])
        self.assertEqual(1, stats["tool_call_count"])
        self.assertEqual("structured", stats["compact_history"][0]["strategy"])
        self.assertGreater(stats["total_tokens"], 0)

    def test_should_auto_compact_uses_threshold(self):
        manager = ContextManager(model="test-model", context_window=40)
        manager.add_message({"role": "user", "content": "x" * 400})

        self.assertTrue(manager.should_auto_compact())

    def test_format_context_details_returns_human_readable_lines(self):
        manager = ContextManager(model="test-model", context_window=200)
        manager.add_message({"role": "user", "content": "keep current goal"})

        details = manager.format_context_details()

        self.assertIn("model:", details)
        self.assertIn("usage:", details)
        self.assertIn("message_count:", details)


if __name__ == "__main__":
    unittest.main()
