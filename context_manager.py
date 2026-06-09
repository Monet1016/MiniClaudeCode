from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


def _flatten_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            if isinstance(block, dict):
                block_type = block.get("type")
                if block_type == "text":
                    parts.append(str(block.get("text", "")))
                elif block_type == "tool_result":
                    parts.append(str(block.get("content", "")))
                elif block_type == "tool_use":
                    parts.append(
                        f"{block.get('name', '')} {json.dumps(block.get('input', {}), default=str)}"
                    )
                else:
                    parts.append(json.dumps(block, default=str))
                continue
            parts.append(str(block))
        return "\n".join(part for part in parts if part)
    if content is None:
        return ""
    return str(content)


def estimate_message_tokens(message: dict[str, Any]) -> int:
    text = _flatten_content(message.get("content"))
    role = str(message.get("role", ""))
    return max(1, (len(role) + len(text)) // 4 + 6)


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(estimate_message_tokens(message) for message in messages)


@dataclass(slots=True)
class ContextManager:
    model: str
    context_window: int
    messages: list[dict[str, Any]] = field(default_factory=list)
    compact_history: list[dict[str, Any]] = field(default_factory=list)

    def add_message(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    def replace_messages(self, messages: list[dict[str, Any]]) -> None:
        self.messages = list(messages)

    def record_compaction(self, event: dict[str, Any]) -> None:
        self.compact_history.append(
            {
                "strategy": str(event.get("strategy", "unknown")),
                "trigger": str(event.get("trigger", "unknown")),
                "tokens_before": int(event.get("tokens_before", 0)),
                "tokens_after": int(event.get("tokens_after", 0)),
            }
        )
        self.compact_history[:] = self.compact_history[-10:]

    def get_stats(self) -> dict[str, Any]:
        total_tokens = estimate_messages_tokens(self.messages)
        tool_call_count = 0
        for message in self.messages:
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_call_count += 1
        usage_ratio = 0.0
        if self.context_window > 0:
            usage_ratio = total_tokens / self.context_window
        return {
            "model": self.model,
            "context_window": self.context_window,
            "total_tokens": total_tokens,
            "usage_ratio": usage_ratio,
            "usage_percentage": round(usage_ratio * 100, 2),
            "message_count": len(self.messages),
            "tool_call_count": tool_call_count,
            "compact_history": list(self.compact_history),
        }

    def should_auto_compact(self, threshold: float = 0.85) -> bool:
        return self.get_stats()["usage_ratio"] >= threshold

    def get_context_summary(self) -> dict[str, Any]:
        stats = self.get_stats()
        latest = stats["compact_history"][-1] if stats["compact_history"] else None
        return {
            "total_tokens": stats["total_tokens"],
            "usage_percentage": stats["usage_percentage"],
            "message_count": stats["message_count"],
            "tool_call_count": stats["tool_call_count"],
            "latest_compaction": latest,
        }

    def format_context_details(self) -> str:
        stats = self.get_stats()
        latest = stats["compact_history"][-1] if stats["compact_history"] else None
        latest_text = "none"
        if latest is not None:
            latest_text = (
                f"{latest['strategy']} ({latest['tokens_before']} -> {latest['tokens_after']})"
            )
        lines = [
            f"model: {self.model}",
            f"usage: {stats['usage_percentage']}%",
            f"message_count: {stats['message_count']}",
            f"tool_call_count: {stats['tool_call_count']}",
            f"latest_compaction: {latest_text}",
        ]
        return "\n".join(lines)
