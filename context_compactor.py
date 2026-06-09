from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from context_manager import estimate_messages_tokens


class CompactTrigger(str, Enum):
    REQUEST = "request"
    MANUAL = "manual"
    REACTIVE = "reactive"


class CompactStrategy(str, Enum):
    NONE = "none"
    MICRO = "micro"
    SESSION_MEMORY = "session_memory"
    STRUCTURED = "structured"
    REACTIVE = "reactive"
    LLM_FALLBACK = "llm_fallback"
    SNIP = "snip"


class CompactBoundary(str, Enum):
    SAFE = "safe"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(slots=True)
class AutoCompactConfig:
    max_bytes: int = 200_000
    persist_threshold: int = 30_000
    keep_recent_tool_results: int = 3
    soft_ratio: float = 0.82
    hard_ratio: float = 0.92
    preserve_tail: int = 6
    snip_max_messages: int = 24


@dataclass(slots=True)
class CompactionResult:
    messages: list[dict[str, Any]]
    trigger: CompactTrigger
    strategy: CompactStrategy
    boundary: CompactBoundary
    did_compact: bool
    tokens_before: int
    tokens_after: int
    notes: list[str] = field(default_factory=list)
    summary_text: str | None = None


def _clone_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return copy.deepcopy(messages)


def _tool_result_blocks(messages: list[dict[str, Any]]):
    for message in messages:
        content = message.get("content")
        if message.get("role") != "user" or not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                yield block


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif block.get("type") == "tool_result":
                    parts.append(str(block.get("content", "")))
                else:
                    parts.append(json.dumps(block, default=str))
            else:
                parts.append(str(block))
        return "\n".join(part for part in parts if part)
    return "" if content is None else str(content)


def _preserve_tail(messages: list[dict[str, Any]], preserve_tail: int) -> list[dict[str, Any]]:
    if preserve_tail <= 0:
        return []
    return _clone_messages(messages[-preserve_tail:])


class ToolResultBudgetManager:
    def __init__(self, tool_results_dir: Path, max_bytes: int, persist_threshold: int) -> None:
        self.tool_results_dir = Path(tool_results_dir)
        self.max_bytes = max_bytes
        self.persist_threshold = persist_threshold

    def _persist(self, tool_use_id: str, output: str) -> str:
        self.tool_results_dir.mkdir(parents=True, exist_ok=True)
        path = self.tool_results_dir / f"{tool_use_id}.txt"
        if not path.exists():
            path.write_text(output, encoding="utf-8")
        return (
            f"<persisted-output>\nFull output: {path}\n"
            f"Preview:\n{output[:2000]}\n</persisted-output>"
        )

    def apply(self, messages: list[dict[str, Any]]) -> int:
        if not messages:
            return 0
        last = messages[-1]
        content = last.get("content")
        if last.get("role") != "user" or not isinstance(content, list):
            return 0
        blocks = [
            block
            for block in content
            if isinstance(block, dict) and block.get("type") == "tool_result"
        ]
        total = sum(len(str(block.get("content", ""))) for block in blocks)
        persisted = 0
        for block in sorted(blocks, key=lambda item: len(str(item.get("content", ""))), reverse=True):
            if total <= self.max_bytes:
                break
            text = str(block.get("content", ""))
            if len(text) <= self.persist_threshold:
                continue
            block["content"] = self._persist(block.get("tool_use_id", "unknown"), text)
            total = sum(len(str(item.get("content", ""))) for item in blocks)
            persisted += 1
        return persisted


class ReadDedupManager:
    def __init__(self) -> None:
        self.cache: dict[str, str] = {}

    def apply(self, messages: list[dict[str, Any]]) -> int:
        deduped = 0
        for block in _tool_result_blocks(messages):
            text = str(block.get("content", ""))
            if len(text) < 120:
                continue
            digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
            current_id = str(block.get("tool_use_id", "unknown"))
            previous_id = self.cache.get(digest)
            if previous_id is None:
                self.cache[digest] = current_id
                continue
            block["content"] = (
                f"[Deduped repeated tool result. Same payload as {previous_id}. "
                "Re-run if a fresh read is required.]"
            )
            deduped += 1
        return deduped


class MicrocompactEngine:
    def __init__(self, keep_recent_tool_results: int) -> None:
        self.keep_recent_tool_results = keep_recent_tool_results

    def apply(self, messages: list[dict[str, Any]]) -> int:
        blocks = list(_tool_result_blocks(messages))
        if len(blocks) <= self.keep_recent_tool_results:
            return 0
        cleared = 0
        for block in blocks[:-self.keep_recent_tool_results]:
            content = str(block.get("content", ""))
            if len(content) <= 120:
                continue
            if content.startswith("<persisted-output>"):
                continue
            cleared += max(0, len(content) - 42)
            block["content"] = "[Earlier tool result compacted. Re-run if needed.]"
        return cleared


class SessionMemoryCompactEngine:
    def __init__(self, memory_manager: Any | None, preserve_tail: int) -> None:
        self.memory_manager = memory_manager
        self.preserve_tail = preserve_tail

    def compact(
        self,
        messages: list[dict[str, Any]],
        trigger: CompactTrigger,
        boundary: CompactBoundary,
        tokens_before: int,
        focus: str | None = None,
    ) -> CompactionResult | None:
        if self.memory_manager is None:
            return None
        summary = None
        if hasattr(self.memory_manager, "build_session_summary"):
            summary = self.memory_manager.build_session_summary(messages, focus=focus)
        elif hasattr(self.memory_manager, "summarize_session"):
            summary = self.memory_manager.summarize_session(messages, focus=focus)
        if not summary:
            return None
        compacted = [{"role": "user", "content": f"[Session compact]\n\n{summary}"}]
        compacted.extend(_preserve_tail(messages, self.preserve_tail))
        tokens_after = estimate_messages_tokens(compacted)
        return CompactionResult(
            messages=compacted,
            trigger=trigger,
            strategy=CompactStrategy.SESSION_MEMORY,
            boundary=boundary,
            did_compact=True,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            notes=["session memory compact"],
            summary_text=str(summary),
        )


class AutoCompactDispatcher:
    def __init__(self, config: AutoCompactConfig) -> None:
        self.config = config

    def choose(
        self,
        token_count: int,
        context_window: int,
        has_memory: bool,
        force_strategy: CompactStrategy | None = None,
    ) -> tuple[CompactStrategy, CompactBoundary]:
        if context_window <= 0:
            return CompactStrategy.STRUCTURED, CompactBoundary.CRITICAL
        usage_ratio = token_count / context_window
        if usage_ratio >= self.config.hard_ratio:
            boundary = CompactBoundary.CRITICAL
        elif usage_ratio >= self.config.soft_ratio:
            boundary = CompactBoundary.WARNING
        else:
            boundary = CompactBoundary.SAFE
        if force_strategy is not None:
            return force_strategy, boundary
        if boundary == CompactBoundary.SAFE:
            return CompactStrategy.NONE, boundary
        if boundary == CompactBoundary.WARNING:
            if has_memory:
                return CompactStrategy.SESSION_MEMORY, boundary
            return CompactStrategy.MICRO, boundary
        if has_memory:
            return CompactStrategy.SESSION_MEMORY, boundary
        return CompactStrategy.STRUCTURED, boundary


class ReactiveCompactEngine:
    def __init__(self, owner: "ContextCompactor") -> None:
        self.owner = owner

    def recover(self, messages: list[dict[str, Any]], focus: str | None = None) -> CompactionResult:
        structured = self.owner._structured_compact(
            messages,
            trigger=CompactTrigger.REACTIVE,
            boundary=CompactBoundary.CRITICAL,
            focus=focus,
        )
        if structured.tokens_after <= int(self.owner.context_window * self.owner.config.hard_ratio):
            structured.strategy = CompactStrategy.REACTIVE
            structured.notes.append("reactive structured recovery")
            return structured
        fallback = self.owner._llm_fallback(messages, trigger=CompactTrigger.REACTIVE, focus=focus)
        if fallback is not None:
            fallback.notes.append("reactive llm fallback")
            return fallback
        return self.owner._snip_fallback(
            messages,
            trigger=CompactTrigger.REACTIVE,
            boundary=CompactBoundary.CRITICAL,
            note="reactive snip fallback",
        )


class ContextCompactor:
    def __init__(
        self,
        context_window: int,
        workspace: str | Path,
        memory_manager: Any | None,
        estimate_fn: Callable[[dict[str, Any]], int] | None = None,
        transcript_dir: str | Path | None = None,
        tool_results_dir: str | Path | None = None,
        llm_summarizer: Callable[[list[dict[str, Any]], str | None], str] | None = None,
        config: AutoCompactConfig | None = None,
    ) -> None:
        self.context_window = context_window
        self.workspace = Path(workspace)
        self.memory_manager = memory_manager
        self.estimate_fn = estimate_fn
        self.transcript_dir = Path(transcript_dir or (self.workspace / ".transcripts"))
        self.tool_results_dir = Path(tool_results_dir or (self.workspace / ".task_outputs" / "tool-results"))
        self.llm_summarizer = llm_summarizer
        self.config = config or AutoCompactConfig()
        self.total_optimization_passes = 0
        self.tool_results_persisted = 0
        self.microcompact_tokens_cleared = 0
        self.auto_compact_boundary_count = 0
        self.circuit_breaker_open = False
        self.budget_manager = ToolResultBudgetManager(
            self.tool_results_dir,
            self.config.max_bytes,
            self.config.persist_threshold,
        )
        self.read_dedup_manager = ReadDedupManager()
        self.microcompact_engine = MicrocompactEngine(self.config.keep_recent_tool_results)
        self.session_memory_engine = SessionMemoryCompactEngine(
            self.memory_manager,
            self.config.preserve_tail,
        )
        self.dispatcher = AutoCompactDispatcher(self.config)
        self.reactive_engine = ReactiveCompactEngine(self)

    def _estimate(self, messages: list[dict[str, Any]]) -> int:
        if self.estimate_fn is None:
            return estimate_messages_tokens(messages)
        return sum(int(self.estimate_fn(message)) for message in messages)

    def _extract_summary_parts(self, messages: list[dict[str, Any]]) -> dict[str, list[str] | str]:
        texts: list[tuple[str, str]] = []
        for message in messages:
            text = _content_text(message.get("content"))
            if text:
                texts.append((str(message.get("role", "")), text))

        goal = "Continue the current task."
        for role, text in reversed(texts):
            if role == "user":
                goal = text.splitlines()[0][:240]
                break

        decisions: list[str] = []
        blockers: list[str] = []
        files: list[str] = []
        for _, text in texts[-12:]:
            for line in [item.strip() for item in text.splitlines() if item.strip()]:
                lower = line.lower()
                if any(word in lower for word in ("should", "replace", "rename", "use", "keep")):
                    if line not in decisions:
                        decisions.append(line[:240])
                if any(word in lower for word in ("error", "fail", "blocked", "blocker")):
                    if line not in blockers:
                        blockers.append(line[:240])
                for token in line.replace(",", " ").split():
                    if "." in token and "/" in token or token.endswith((".py", ".md", ".txt", ".json")):
                        cleaned = token.strip("[](){}'\"")
                        if cleaned not in files:
                            files.append(cleaned)

        recent_tail = [text[:240] for _, text in texts[-4:]]
        return {
            "goal": goal,
            "decisions": decisions[:5],
            "files": files[:12],
            "blockers": blockers[:5],
            "tail": recent_tail,
        }

    def _structured_summary(self, messages: list[dict[str, Any]], focus: str | None = None) -> str:
        parts = self._extract_summary_parts(messages)
        lines = ["[Compacted]"]
        if focus:
            lines.extend(["", f"Focus: {focus}"])
        lines.extend(["", "Goal:", f"- {parts['goal']}"])
        lines.extend(["", "Key decisions:"])
        for item in parts["decisions"] or ["(none captured)"]:
            lines.append(f"- {item}")
        lines.extend(["", "Touched files:"])
        for item in parts["files"] or ["(none captured)"]:
            lines.append(f"- {item}")
        lines.extend(["", "Open blockers:"])
        for item in parts["blockers"] or ["(none captured)"]:
            lines.append(f"- {item}")
        lines.extend(["", "Recent tail:"])
        for item in parts["tail"] or ["(empty tail)"]:
            lines.append(f"- {item}")
        return "\n".join(lines)

    def _structured_compact(
        self,
        messages: list[dict[str, Any]],
        trigger: CompactTrigger,
        boundary: CompactBoundary,
        focus: str | None = None,
    ) -> CompactionResult:
        tokens_before = self._estimate(messages)
        summary = self._structured_summary(messages, focus=focus)
        compacted = [{"role": "user", "content": summary}]
        compacted.extend(_preserve_tail(messages, self.config.preserve_tail))
        tokens_after = self._estimate(compacted)
        return CompactionResult(
            messages=compacted,
            trigger=trigger,
            strategy=CompactStrategy.STRUCTURED,
            boundary=boundary,
            did_compact=True,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            notes=["structured compact"],
            summary_text=summary,
        )

    def _llm_fallback(
        self,
        messages: list[dict[str, Any]],
        trigger: CompactTrigger,
        focus: str | None = None,
    ) -> CompactionResult | None:
        if self.llm_summarizer is None:
            return None
        summary = self.llm_summarizer(messages, focus)
        compacted = [{"role": "user", "content": f"[Reactive compact]\n\n{summary}"}]
        compacted.extend(_preserve_tail(messages, self.config.preserve_tail))
        return CompactionResult(
            messages=compacted,
            trigger=trigger,
            strategy=CompactStrategy.LLM_FALLBACK,
            boundary=CompactBoundary.CRITICAL,
            did_compact=True,
            tokens_before=self._estimate(messages),
            tokens_after=self._estimate(compacted),
            notes=["llm fallback compact"],
            summary_text=summary,
        )

    def _snip_fallback(
        self,
        messages: list[dict[str, Any]],
        trigger: CompactTrigger,
        boundary: CompactBoundary,
        note: str,
    ) -> CompactionResult:
        if len(messages) <= self.config.snip_max_messages:
            trimmed = _clone_messages(messages)
        else:
            keep_head = 2
            keep_tail = max(1, self.config.snip_max_messages - 3)
            snipped = len(messages) - keep_head - keep_tail
            trimmed = (
                _clone_messages(messages[:keep_head])
                + [{"role": "user", "content": f"[snipped {snipped} messages]"}]
                + _clone_messages(messages[-keep_tail:])
            )
        return CompactionResult(
            messages=trimmed,
            trigger=trigger,
            strategy=CompactStrategy.SNIP,
            boundary=boundary,
            did_compact=True,
            tokens_before=self._estimate(messages),
            tokens_after=self._estimate(trimmed),
            notes=[note],
        )

    def process_request(
        self,
        messages: list[dict[str, Any]],
        trigger: CompactTrigger = CompactTrigger.REQUEST,
        focus: str | None = None,
        force_strategy: CompactStrategy | None = None,
    ) -> CompactionResult:
        working = _clone_messages(messages)
        tokens_before = self._estimate(working)
        deduped = self.read_dedup_manager.apply(working)
        persisted = self.budget_manager.apply(working)
        cleared = self.microcompact_engine.apply(working)
        self.tool_results_persisted += persisted
        self.microcompact_tokens_cleared += cleared

        strategy, boundary = self.dispatcher.choose(
            token_count=self._estimate(working),
            context_window=self.context_window,
            has_memory=self.memory_manager is not None,
            force_strategy=force_strategy,
        )
        if boundary != CompactBoundary.SAFE:
            self.auto_compact_boundary_count += 1

        if strategy == CompactStrategy.SESSION_MEMORY:
            session_result = self.session_memory_engine.compact(
                working,
                trigger=trigger,
                boundary=boundary,
                tokens_before=tokens_before,
                focus=focus,
            )
            if session_result is not None:
                self.total_optimization_passes += 1
                return session_result
            strategy = CompactStrategy.STRUCTURED

        if strategy == CompactStrategy.STRUCTURED:
            result = self._structured_compact(working, trigger=trigger, boundary=boundary, focus=focus)
            self.total_optimization_passes += 1
            return result

        did_change = persisted > 0 or deduped > 0 or cleared > 0
        result = CompactionResult(
            messages=working,
            trigger=trigger,
            strategy=CompactStrategy.MICRO if did_change else CompactStrategy.NONE,
            boundary=boundary,
            did_compact=did_change,
            tokens_before=tokens_before,
            tokens_after=self._estimate(working),
            notes=[],
        )
        self.total_optimization_passes += 1
        return result

    def reactive_recover(self, messages: list[dict[str, Any]], focus: str | None = None) -> CompactionResult:
        return self.reactive_engine.recover(messages, focus=focus)

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_optimization_passes": self.total_optimization_passes,
            "tool_results_persisted": self.tool_results_persisted,
            "dedup_cache_size": len(self.read_dedup_manager.cache),
            "microcompact_tokens_cleared": self.microcompact_tokens_cleared,
            "auto_compact_boundary_count": self.auto_compact_boundary_count,
            "circuit_breaker_open": self.circuit_breaker_open,
        }

    def format_pipeline_status(self) -> str:
        stats = self.get_stats()
        return "\n".join(
            [
                f"passes: {stats['total_optimization_passes']}",
                f"persisted: {stats['tool_results_persisted']}",
                f"dedup_cache: {stats['dedup_cache_size']}",
                f"micro_cleared: {stats['microcompact_tokens_cleared']}",
                f"boundaries: {stats['auto_compact_boundary_count']}",
                f"circuit_breaker_open: {stats['circuit_breaker_open']}",
            ]
        )
