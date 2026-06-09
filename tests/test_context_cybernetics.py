import unittest
from types import SimpleNamespace

from context_compactor import CompactBoundary, CompactStrategy, CompactTrigger, CompactionResult
from context_cybernetics import (
    AdaptiveThresholdManager,
    CompactionStrategySelector,
    ContextCyberneticsOrchestrator,
    ContextPIDController,
    ContextPressureSensor,
    PredictiveOverflowGuard,
)
from context_manager import ContextManager


class RecordingCompactor:
    def __init__(self):
        self.process_calls = []
        self.reactive_calls = []

    def process_request(self, messages, trigger=CompactTrigger.REQUEST, focus=None, force_strategy=None):
        self.process_calls.append(
            {
                "messages": list(messages),
                "trigger": trigger,
                "focus": focus,
                "force_strategy": force_strategy,
            }
        )
        return CompactionResult(
            messages=[{"role": "user", "content": "[Compacted]\n\nsummary"}],
            trigger=trigger,
            strategy=force_strategy or CompactStrategy.STRUCTURED,
            boundary=CompactBoundary.WARNING,
            did_compact=True,
            tokens_before=120,
            tokens_after=50,
        )

    def reactive_recover(self, messages, focus=None):
        self.reactive_calls.append({"messages": list(messages), "focus": focus})
        return CompactionResult(
            messages=[{"role": "user", "content": "[Reactive compact]\n\nsummary"}],
            trigger=CompactTrigger.REACTIVE,
            strategy=CompactStrategy.REACTIVE,
            boundary=CompactBoundary.CRITICAL,
            did_compact=True,
            tokens_before=160,
            tokens_after=40,
        )

    def get_stats(self):
        return {
            "total_optimization_passes": len(self.process_calls) + len(self.reactive_calls),
            "tool_results_persisted": 0,
            "dedup_cache_size": 0,
            "microcompact_tokens_cleared": 0,
            "auto_compact_boundary_count": 0,
            "circuit_breaker_open": False,
        }


class ContextCyberneticsTests(unittest.TestCase):
    def test_sensor_tracks_growth(self):
        manager = ContextManager(model="test-model", context_window=200)
        sensor = ContextPressureSensor()
        manager.add_message({"role": "user", "content": "short"})
        first = sensor.observe(manager.get_stats(), step=1, tool_error_count=0)
        manager.add_message({"role": "user", "content": "x" * 400})
        second = sensor.observe(manager.get_stats(), step=2, tool_error_count=1)

        self.assertGreater(second.token_count, first.token_count)

    def test_pid_output_rises_above_setpoint(self):
        controller = ContextPIDController(kp=2.0, ki=0.15, kd=0.3, setpoint=0.70)

        low = controller.update(0.50)
        high = controller.update(0.92)

        self.assertLess(low, high)

    def test_predictive_guard_marks_urgent_when_growth_is_high(self):
        guard = PredictiveOverflowGuard()
        reading = SimpleNamespace(usage_ratio=0.82, token_count=820, token_growth=140)

        outlook = guard.project(reading, context_window=1000, safety_margin_turns=3)

        self.assertTrue(outlook.urgent)

    def test_adaptive_threshold_drops_for_debugging_and_coupling(self):
        manager = AdaptiveThresholdManager(base_threshold=0.85)
        manager.set_intent("debugging")
        manager.update_coupling_metrics(file_count=4, tool_chain_depth=3)

        threshold = manager.compute_effective_threshold()

        self.assertLess(threshold, 0.85)

    def test_strategy_selector_returns_structured_for_urgent_outlook(self):
        selector = CompactionStrategySelector()
        reading = SimpleNamespace(usage_ratio=0.83, anomaly=None)
        outlook = SimpleNamespace(projected_ratio=0.97, turns_to_overflow=1, urgent=True)

        action = selector.select(reading, pid_output=0.21, outlook=outlook, effective_threshold=0.84)

        self.assertEqual(CompactStrategy.STRUCTURED, action.strategy)

    def test_orchestrator_runs_compactor_and_records_feedback(self):
        manager = ContextManager(model="test-model", context_window=60)
        manager.add_message({"role": "user", "content": "x" * 500})
        compactor = RecordingCompactor()
        orchestrator = ContextCyberneticsOrchestrator(
            context_manager=manager,
            context_compactor=compactor,
            kp=2.0,
            ki=0.15,
            kd=0.3,
            pid_setpoint=0.70,
            base_threshold=0.85,
            safety_margin_turns=3,
            enabled=True,
        )
        orchestrator.set_intent("debugging")
        orchestrator.update_coupling_metrics(file_count=3, tool_chain_depth=2)

        result = orchestrator.run_cycle(manager.messages, step=2, tool_error_count=1)

        self.assertTrue(result.did_compact)
        self.assertEqual(1, len(compactor.process_calls))
        self.assertGreater(orchestrator.get_stats()["feedback_effectiveness"], 0.0)

    def test_try_reactive_recover_delegates_to_compactor(self):
        manager = ContextManager(model="test-model", context_window=80)
        manager.add_message({"role": "user", "content": "x" * 500})
        compactor = RecordingCompactor()
        orchestrator = ContextCyberneticsOrchestrator(
            context_manager=manager,
            context_compactor=compactor,
            kp=2.0,
            ki=0.15,
            kd=0.3,
            pid_setpoint=0.70,
            base_threshold=0.85,
            safety_margin_turns=3,
            enabled=True,
        )

        result = orchestrator.try_reactive_recover(manager.messages, reason="prompt too long")

        self.assertTrue(result.did_compact)
        self.assertEqual(1, len(compactor.reactive_calls))


if __name__ == "__main__":
    unittest.main()
