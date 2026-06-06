from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

KEEP_RECENT_TOOL_RESULTS = 3
PERSIST_THRESHOLD = 30000


def estimate_size(messages: list) -> int:
    return len(json.dumps(messages, default=str))


def collect_tool_results(messages: list):
    found = []
    for message_index, message in enumerate(messages):
        content = message.get("content")
        if message.get("role") != "user" or not isinstance(content, list):
            continue
        for block_index, block in enumerate(content):
            if isinstance(block, dict) and block.get("type") == "tool_result":
                found.append((message_index, block_index, block))
    return found


def persist_large_output(
    tool_use_id: str,
    output: str,
    tool_results_dir: str | Path,
    persist_threshold: int = PERSIST_THRESHOLD,
) -> str:
    if len(output) <= persist_threshold:
        return output
    target_dir = Path(tool_results_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{tool_use_id}.txt"
    if not path.exists():
        path.write_text(output, encoding="utf-8")
    return (
        f"<persisted-output>\nFull output: {path}\n"
        f"Preview:\n{output[:2000]}\n</persisted-output>"
    )


def tool_result_budget(
    messages: list,
    tool_results_dir: str | Path,
    max_bytes: int = 200_000,
    persist_threshold: int = PERSIST_THRESHOLD,
) -> list:
    if not messages:
        return messages
    last = messages[-1]
    content = last.get("content")
    if last.get("role") != "user" or not isinstance(content, list):
        return messages
    blocks = [
        (index, block)
        for index, block in enumerate(content)
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    total = sum(len(str(block.get("content", ""))) for _, block in blocks)
    if total <= max_bytes:
        return messages
    for _, block in sorted(blocks, key=lambda item: len(str(item[1].get("content", ""))), reverse=True):
        if total <= max_bytes:
            break
        text = str(block.get("content", ""))
        block["content"] = persist_large_output(
            block.get("tool_use_id", "unknown"),
            text,
            tool_results_dir,
            persist_threshold=persist_threshold,
        )
        total = sum(len(str(item[1].get("content", ""))) for item in blocks)
    return messages


def snip_compact(messages: list, max_messages: int = 50) -> list:
    if len(messages) <= max_messages:
        return messages
    keep_head = 3
    keep_tail = max_messages - 3
    snipped = len(messages) - keep_head - keep_tail
    return (
        messages[:keep_head]
        + [{"role": "user", "content": f"[snipped {snipped} messages]"}]
        + messages[-keep_tail:]
    )


def micro_compact(messages: list, keep_recent_tool_results: int = KEEP_RECENT_TOOL_RESULTS) -> list:
    tool_results = collect_tool_results(messages)
    if len(tool_results) <= keep_recent_tool_results:
        return messages
    for _, _, block in tool_results[:-keep_recent_tool_results]:
        if len(str(block.get("content", ""))) > 120:
            block["content"] = "[Earlier tool result compacted. Re-run if needed.]"
    return messages


def write_transcript(messages: list, transcript_dir: str | Path) -> Path:
    target_dir = Path(transcript_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"transcript_{int(time.time())}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for message in messages:
            handle.write(json.dumps(message, default=str) + "\n")
    return path


def summarize_history(
    messages: list,
    client: Any,
    model: str,
    extract_text: Callable[[Any], str],
) -> str:
    conversation = json.dumps(messages, default=str)[:80000]
    prompt = (
        "Summarize this coding-agent conversation so work can continue. "
        "Preserve current goal, key findings, changed files, remaining work, "
        "and user constraints.\n\n"
        + conversation
    )
    response = client.messages.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
    )
    return extract_text(response.content) or "(empty summary)"


def compact_history(
    messages: list,
    transcript_dir: str | Path,
    client: Any,
    model: str,
    extract_text: Callable[[Any], str],
    printer: Callable[[str], None] | None = None,
) -> list:
    transcript = write_transcript(messages, transcript_dir)
    if printer is not None:
        printer(f"  \033[36m[compact] transcript saved: {transcript}\033[0m")
    summary = summarize_history(messages, client, model, extract_text)
    return [{"role": "user", "content": f"[Compacted]\n\n{summary}"}]


def reactive_compact(
    messages: list,
    transcript_dir: str | Path,
    client: Any,
    model: str,
    extract_text: Callable[[Any], str],
    printer: Callable[[str], None] | None = None,
) -> list:
    transcript = write_transcript(messages, transcript_dir)
    if printer is not None:
        printer(f"  \033[31m[reactive compact] transcript saved: {transcript}\033[0m")
    try:
        summary = summarize_history(messages, client, model, extract_text)
    except Exception:
        summary = "Earlier conversation was trimmed after a prompt-too-long error."
    return [{"role": "user", "content": f"[Reactive compact]\n\n{summary}"}, *messages[-5:]]
