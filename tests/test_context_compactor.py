import time
import unittest
from pathlib import Path

from context_compactor import (
    AutoCompactConfig,
    CompactStrategy,
    CompactTrigger,
    ContextCompactor,
)


ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = ROOT / "tests" / "fixtures_runtime"


def fresh_dir(prefix: str) -> Path:
    path = TMP_ROOT / f"{prefix}_{time.time_ns()}"
    path.mkdir(parents=True, exist_ok=True)
    return path


class ContextCompactorTests(unittest.TestCase):
    def build_compactor(self, root: Path, llm_summarizer=None, memory_manager=None) -> ContextCompactor:
        return ContextCompactor(
            context_window=240,
            workspace=root,
            memory_manager=memory_manager,
            estimate_fn=lambda message: len(str(message)) // 4 + 1,
            transcript_dir=root / ".transcripts",
            tool_results_dir=root / ".tool-results",
            llm_summarizer=llm_summarizer,
            config=AutoCompactConfig(
                max_bytes=100,
                persist_threshold=90,
                keep_recent_tool_results=1,
                soft_ratio=0.70,
                hard_ratio=0.85,
                preserve_tail=2,
                snip_max_messages=6,
            ),
        )

    def test_process_request_persists_large_tool_results(self):
        root = fresh_dir("context_compactor_budget")
        compactor = self.build_compactor(root)
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
                        "content": "y" * 40,
                    },
                ],
            }
        ]

        result = compactor.process_request(messages, trigger=CompactTrigger.REQUEST)

        self.assertIn("<persisted-output>", result.messages[0]["content"][0]["content"])
        self.assertTrue((root / ".tool-results" / "tool_1.txt").exists())

    def test_process_request_dedups_repeated_tool_results(self):
        root = fresh_dir("context_compactor_dedup")
        compactor = self.build_compactor(root)
        repeated = "same output " * 20
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tool_1", "content": repeated},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tool_2", "content": repeated},
                ],
            },
        ]

        result = compactor.process_request(messages, trigger=CompactTrigger.REQUEST)

        self.assertIn("Deduped repeated tool result", result.messages[1]["content"][0]["content"])

    def test_structured_compact_preserves_summary_and_tail(self):
        root = fresh_dir("context_compactor_structured")
        compactor = self.build_compactor(root)
        messages = [
            {"role": "user", "content": "Current goal: replace prepare_context in agent_loop.py"},
            {"role": "assistant", "content": "We should rename it to run_context_cycle."},
            {"role": "assistant", "content": "Touched files: agent_loop.py and main.py"},
            {"role": "user", "content": "Current blocker: prompt too long after compact tool"},
            {"role": "assistant", "content": "Need controller-first recovery before fallback."},
        ]

        result = compactor.process_request(
            messages,
            trigger=CompactTrigger.MANUAL,
            focus="context migration",
            force_strategy=CompactStrategy.STRUCTURED,
        )

        self.assertTrue(result.did_compact)
        self.assertEqual(CompactStrategy.STRUCTURED, result.strategy)
        self.assertIn("run_context_cycle", result.messages[0]["content"])
        self.assertEqual(messages[-2:], result.messages[-2:])

    def test_structured_compact_keeps_tool_use_and_result_pair_together(self):
        root = fresh_dir("context_compactor_pairs")
        compactor = self.build_compactor(root)
        messages = [
            {"role": "user", "content": "Current goal: preserve tool coherence"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "read_file",
                        "input": {"path": "agent_loop.py"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": "def run_context_cycle(...): ...",
                    }
                ],
            },
            {"role": "assistant", "content": "Need to keep the tool pair coherent."},
            {"role": "user", "content": "Preserve the recent tail without splitting pairs."},
        ]

        result = compactor.process_request(
            messages,
            trigger=CompactTrigger.MANUAL,
            force_strategy=CompactStrategy.STRUCTURED,
        )

        tail = result.messages[1:]
        has_tool_use = any(
            isinstance(item.get("content"), list)
            and any(
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and block.get("id") == "toolu_1"
                for block in item["content"]
            )
            for item in tail
        )
        has_tool_result = any(
            isinstance(item.get("content"), list)
            and any(
                isinstance(block, dict)
                and block.get("type") == "tool_result"
                and block.get("tool_use_id") == "toolu_1"
                for block in item["content"]
            )
            for item in tail
        )

        self.assertEqual(has_tool_use, has_tool_result)

    def test_reactive_recover_uses_llm_fallback_when_needed(self):
        root = fresh_dir("context_compactor_reactive")
        compactor = self.build_compactor(
            root,
            llm_summarizer=lambda messages, focus=None: "llm fallback summary",
        )
        compactor.context_window = 30
        messages = [
            {"role": "user", "content": "x" * 500},
            {"role": "assistant", "content": "y" * 500},
            {"role": "user", "content": "z" * 500},
        ]

        result = compactor.reactive_recover(messages, focus="prompt too long")

        self.assertTrue(result.did_compact)
        self.assertEqual(CompactStrategy.LLM_FALLBACK, result.strategy)
        self.assertIn("llm fallback summary", result.messages[0]["content"])

    def test_format_pipeline_status_reports_observable_fields(self):
        root = fresh_dir("context_compactor_status")
        compactor = self.build_compactor(root)

        status = compactor.format_pipeline_status()

        self.assertIn("passes:", status)
        self.assertIn("persisted:", status)
        self.assertIn("dedup_cache:", status)
        self.assertIn("micro_cleared:", status)
        self.assertIn("boundaries:", status)
        self.assertIn("circuit_breaker_open:", status)


if __name__ == "__main__":
    unittest.main()
