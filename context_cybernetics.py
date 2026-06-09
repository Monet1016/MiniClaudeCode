from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from math import inf
from typing import Any

from context_compactor import CompactBoundary, CompactStrategy, CompactTrigger, CompactionResult


class AnomalyType(str, Enum):
    NONE = "none"
    GROWTH_SURGE = "growth_surge"
    TOOL_ERROR_SPIKE = "tool_error_spike"
    OVERFLOW_RISK = "overflow_risk"


@dataclass(slots=True)
class ContextPressureReading:
    usage_ratio: float
    token_count: int
    token_growth: int
    tool_error_count: int
    anomaly: AnomalyType


@dataclass(slots=True)
class ControlAction:
    strategy: CompactStrategy
    effective_threshold: float
    pid_output: float
    reason: str


@dataclass(slots=True)
class PredictiveOutlook:
    projected_ratio: float
    turns_to_overflow: float
    urgent: bool


class ContextPressureSensor:
    def __init__(self) -> None:
        self.history: deque[int] = deque(maxlen=6)

    def observe(self, stats: dict[str, Any], step: int, tool_error_count: int) -> ContextPressureReading:
        del step
        token_count = int(stats.get("total_tokens", 0))
        previous = self.history[-1] if self.history else token_count
        self.history.append(token_count)
        growth = token_count - previous
        usage_ratio = float(stats.get("usage_ratio", 0.0))
        anomaly = AnomalyType.NONE
        if tool_error_count >= 3:
            anomaly = AnomalyType.TOOL_ERROR_SPIKE
        elif usage_ratio >= 0.98:
            anomaly = AnomalyType.OVERFLOW_RISK
        elif growth > max(50, token_count * 0.08):
            anomaly = AnomalyType.GROWTH_SURGE
        return ContextPressureReading(
            usage_ratio=usage_ratio,
            token_count=token_count,
            token_growth=growth,
            tool_error_count=tool_error_count,
            anomaly=anomaly,
        )


class ContextPIDController:
    def __init__(self, kp: float, ki: float, kd: float, setpoint: float) -> None:
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.setpoint = setpoint
        self.integral = 0.0
        self.previous_error = 0.0

    def update(self, usage_ratio: float) -> float:
        error = usage_ratio - self.setpoint
        self.integral += error
        derivative = error - self.previous_error
        self.previous_error = error
        return (self.kp * error) + (self.ki * self.integral) + (self.kd * derivative)


class PredictiveOverflowGuard:
    def project(
        self,
        reading: ContextPressureReading,
        context_window: int,
        safety_margin_turns: int,
    ) -> PredictiveOutlook:
        growth_ratio = 0.0
        if context_window > 0:
            growth_ratio = reading.token_growth / context_window
        projected_ratio = reading.usage_ratio + (growth_ratio * safety_margin_turns)
        if growth_ratio <= 0:
            turns_to_overflow = inf
        else:
            turns_to_overflow = max(0.0, (1.0 - reading.usage_ratio) / growth_ratio)
        urgent = projected_ratio >= 1.0 or turns_to_overflow <= safety_margin_turns
        return PredictiveOutlook(
            projected_ratio=projected_ratio,
            turns_to_overflow=turns_to_overflow,
            urgent=urgent,
        )


class AdaptiveThresholdManager:
    def __init__(self, base_threshold: float) -> None:
        self.base_threshold = base_threshold
        self.intent = ""
        self.file_count = 0
        self.tool_chain_depth = 0

    def set_intent(self, intent: str | None) -> None:
        self.intent = (intent or "").lower()

    def update_coupling_metrics(self, file_count: int = 0, tool_chain_depth: int = 0) -> None:
        self.file_count = file_count
        self.tool_chain_depth = tool_chain_depth

    def compute_effective_threshold(self) -> float:
        threshold = self.base_threshold
        if any(word in self.intent for word in ("debug", "investigate", "incident")):
            threshold -= 0.04
        if self.file_count >= 3:
            threshold -= 0.02
        if self.tool_chain_depth >= 3:
            threshold -= 0.02
        return max(0.65, min(0.95, threshold))


class CompactionStrategySelector:
    def select(
        self,
        reading: ContextPressureReading,
        pid_output: float,
        outlook: PredictiveOutlook,
        effective_threshold: float,
    ) -> ControlAction:
        if reading.anomaly in {AnomalyType.OVERFLOW_RISK, AnomalyType.TOOL_ERROR_SPIKE}:
            return ControlAction(
                strategy=CompactStrategy.REACTIVE,
                effective_threshold=effective_threshold,
                pid_output=pid_output,
                reason=reading.anomaly.value,
            )
        if outlook.urgent or outlook.projected_ratio >= effective_threshold:
            return ControlAction(
                strategy=CompactStrategy.STRUCTURED,
                effective_threshold=effective_threshold,
                pid_output=pid_output,
                reason="predictive-overflow",
            )
        if reading.usage_ratio >= effective_threshold or pid_output >= 0.18:
            return ControlAction(
                strategy=CompactStrategy.MICRO,
                effective_threshold=effective_threshold,
                pid_output=pid_output,
                reason="warning-band",
            )
        return ControlAction(
            strategy=CompactStrategy.NONE,
            effective_threshold=effective_threshold,
            pid_output=pid_output,
            reason="stable",
        )


class CyberneticFeedbackLoop:
    def __init__(self) -> None:
        self.effectiveness: deque[float] = deque(maxlen=10)

    def record(self, result: CompactionResult) -> None:
        if result.tokens_before <= 0:
            self.effectiveness.append(0.0)
            return
        delta = max(0, result.tokens_before - result.tokens_after)
        self.effectiveness.append(delta / result.tokens_before)

    def score(self) -> float:
        if not self.effectiveness:
            return 0.0
        return sum(self.effectiveness) / len(self.effectiveness)


class ContextCyberneticsOrchestrator:
    def __init__(
        self,
        context_manager: Any,
        context_compactor: Any,
        kp: float,
        ki: float,
        kd: float,
        pid_setpoint: float,
        base_threshold: float,
        safety_margin_turns: int,
        enabled: bool = True,
    ) -> None:
        self.context_manager = context_manager
        self.context_compactor = context_compactor
        self.safety_margin_turns = safety_margin_turns
        self.enabled = enabled
        self.sensor = ContextPressureSensor()
        self.controller = ContextPIDController(kp=kp, ki=ki, kd=kd, setpoint=pid_setpoint)
        self.predictor = PredictiveOverflowGuard()
        self.threshold_manager = AdaptiveThresholdManager(base_threshold=base_threshold)
        self.selector = CompactionStrategySelector()
        self.feedback = CyberneticFeedbackLoop()
        self.last_reading: ContextPressureReading | None = None
        self.last_pid_output = 0.0
        self.last_outlook: PredictiveOutlook | None = None
        self.last_threshold = base_threshold

    def set_intent(self, intent: str | None) -> None:
        self.threshold_manager.set_intent(intent)

    def update_coupling_metrics(self, file_count: int = 0, tool_chain_depth: int = 0) -> None:
        self.threshold_manager.update_coupling_metrics(file_count=file_count, tool_chain_depth=tool_chain_depth)

    def _noop_result(self, messages: list[dict[str, Any]]) -> CompactionResult:
        token_count = int(self.context_manager.get_stats().get("total_tokens", 0))
        return CompactionResult(
            messages=list(messages),
            trigger=CompactTrigger.REQUEST,
            strategy=CompactStrategy.NONE,
            boundary=CompactBoundary.SAFE,
            did_compact=False,
            tokens_before=token_count,
            tokens_after=token_count,
        )

    def run_cycle(self, messages: list[dict[str, Any]], step: int, tool_error_count: int) -> CompactionResult:
        self.context_manager.replace_messages(messages)
        if not self.enabled:
            return self._noop_result(messages)
        stats = self.context_manager.get_stats()
        reading = self.sensor.observe(stats, step=step, tool_error_count=tool_error_count)
        pid_output = self.controller.update(reading.usage_ratio)
        outlook = self.predictor.project(
            reading,
            context_window=self.context_manager.context_window,
            safety_margin_turns=self.safety_margin_turns,
        )
        threshold = self.threshold_manager.compute_effective_threshold()
        action = self.selector.select(reading, pid_output, outlook, threshold)

        self.last_reading = reading
        self.last_pid_output = pid_output
        self.last_outlook = outlook
        self.last_threshold = threshold

        if action.strategy == CompactStrategy.NONE:
            return self._noop_result(messages)

        force_strategy = action.strategy
        if force_strategy == CompactStrategy.REACTIVE:
            force_strategy = CompactStrategy.STRUCTURED
        result = self.context_compactor.process_request(
            messages,
            trigger=CompactTrigger.REQUEST,
            force_strategy=force_strategy,
        )
        self.context_manager.replace_messages(result.messages)
        self.context_manager.record_compaction(
            {
                "strategy": result.strategy.value,
                "trigger": result.trigger.value,
                "tokens_before": result.tokens_before,
                "tokens_after": result.tokens_after,
            }
        )
        self.feedback.record(result)
        return result

    def try_reactive_recover(self, messages: list[dict[str, Any]], reason: str | None = None) -> CompactionResult:
        self.context_manager.replace_messages(messages)
        result = self.context_compactor.reactive_recover(messages, focus=reason)
        self.context_manager.replace_messages(result.messages)
        self.context_manager.record_compaction(
            {
                "strategy": result.strategy.value,
                "trigger": result.trigger.value,
                "tokens_before": result.tokens_before,
                "tokens_after": result.tokens_after,
            }
        )
        self.feedback.record(result)
        return result

    def get_stats(self) -> dict[str, Any]:
        compactor_stats = self.context_compactor.get_stats()
        return {
            **compactor_stats,
            "current_sensor_reading": self.last_reading,
            "pid_output": self.last_pid_output,
            "predicted_turns_to_overflow": (
                None if self.last_outlook is None else self.last_outlook.turns_to_overflow
            ),
            "effective_threshold": self.last_threshold,
            "feedback_effectiveness": self.feedback.score(),
        }
