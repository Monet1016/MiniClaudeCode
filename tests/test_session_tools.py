import time
import unittest
from pathlib import Path

from tooling import ToolContext


ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = ROOT / "tests" / "fixtures_runtime"


def fresh_dir(prefix: str) -> Path:
    path = TMP_ROOT / f"{prefix}_{time.time_ns()}"
    path.mkdir(parents=True, exist_ok=True)
    return path


class SessionToolTests(unittest.TestCase):
    def test_context_compactor_persists_large_outputs(self):
        from context_compactor import AutoCompactConfig, CompactTrigger, ContextCompactor

        root = fresh_dir("tool_result_budget")
        compactor = ContextCompactor(
            context_window=1000,
            workspace=root,
            memory_manager=None,
            estimate_fn=lambda message: len(str(message)) // 4 + 1,
            transcript_dir=root / ".transcripts",
            tool_results_dir=root,
            config=AutoCompactConfig(
                max_bytes=100,
                persist_threshold=90,
                keep_recent_tool_results=1,
            ),
        )
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool_1",
                        "content": "x" * 120,
                    },
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool_2",
                        "content": "y" * 80,
                    },
                ],
            }
        ]

        result = compactor.process_request(messages, trigger=CompactTrigger.REQUEST)

        persisted = result.messages[0]["content"][0]["content"]
        self.assertIn("<persisted-output>", persisted)
        self.assertIn("tool_1.txt", persisted)
        self.assertTrue((root / "tool_1.txt").exists())

    def test_compact_tool_delegates_to_manual_compact_callback(self):
        from tools.compact import TOOL

        captured = {}

        def manual_compact(messages, focus=None):
            captured["messages"] = list(messages)
            captured["focus"] = focus
            return [{"role": "user", "content": "[Compacted]\n\nsummary"}]

        context = ToolContext(
            cwd=".",
            runtime={
                "messages": [{"role": "user", "content": "hello"}],
                "manual_compact": manual_compact,
            },
        )

        result = TOOL.run({"focus": "current task"}, context)

        self.assertTrue(result.ok)
        self.assertEqual("[Compacted]\n\nsummary", result.output)
        self.assertEqual([{"role": "user", "content": "hello"}], captured["messages"])
        self.assertEqual("current task", captured["focus"])


if __name__ == "__main__":
    unittest.main()
