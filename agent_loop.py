from __future__ import annotations

from dataclasses import dataclass
import random
import threading
import time
from typing import Any, Callable

from background_tasks import collect_background_notifications
from context_compactor import CompactTrigger
from tooling import ToolContext

DEFAULT_MAX_TOKENS = 8000
ESCALATED_MAX_TOKENS = 16000
MAX_RETRIES = 3
MAX_CONSECUTIVE_529 = 2
MAX_RECOVERY_RETRIES = 2
BASE_DELAY_MS = 500
CONTINUATION_PROMPT = "Continue from the previous response. Do not repeat completed work."


@dataclass
class AgentLoopDeps:
    client: Any
    assemble_system_prompt: Callable[[dict], str]
    assemble_tool_pool: Callable[[], tuple[list[dict], Any]]
    get_runtime: Callable[[], dict]
    update_context: Callable[[dict, list], dict]
    consume_cron_queue: Callable[[], list]
    trigger_hooks: Callable[..., Any]
    terminal_print: Callable[[str], None]
    has_tool_use: Callable[[Any], bool]
    workspace_root: str
    primary_model: str
    fallback_model: str | None


class RecoveryState:
    def __init__(self, primary_model: str):
        self.has_escalated = False
        self.recovery_count = 0
        self.consecutive_529 = 0
        self.has_attempted_reactive_compact = False
        self.current_model = primary_model


rounds_since_todo = 0
agent_lock = threading.Lock()


def _block_value(block: Any, field: str, default: Any = None) -> Any:
    if isinstance(block, dict):
        return block.get(field, default)
    return getattr(block, field, default)


def _tool_context(deps: AgentLoopDeps) -> ToolContext:
    runtime = deps.get_runtime()
    return ToolContext(
        cwd=deps.workspace_root,
        permissions=runtime.get("permissions"),
        runtime=runtime,
    )


def retry_delay(attempt: int) -> float:
    base = min(BASE_DELAY_MS * (2 ** attempt), 32000) / 1000
    return base + random.uniform(0, base * 0.25)


def with_retry(
    fn: Callable[[], Any],
    state: RecoveryState,
    terminal_print: Callable[[str], None] | None = None,
    fallback_model: str | None = None,
) -> Any:
    emit = terminal_print or (lambda text: None)
    for attempt in range(MAX_RETRIES):
        try:
            result = fn()
            state.consecutive_529 = 0
            return result
        except Exception as exc:
            name = type(exc).__name__.lower()
            message = str(exc).lower()
            if "ratelimit" in name or "429" in message:
                delay = retry_delay(attempt)
                emit(
                    f"  \033[33m[429] retry {attempt + 1}/{MAX_RETRIES} "
                    f"after {delay:.1f}s\033[0m"
                )
                time.sleep(delay)
                continue
            if "overloaded" in name or "529" in message or "overloaded" in message:
                state.consecutive_529 += 1
                if state.consecutive_529 >= MAX_CONSECUTIVE_529 and fallback_model:
                    state.current_model = fallback_model
                    state.consecutive_529 = 0
                    emit(f"  \033[31m[529] switching to {fallback_model}\033[0m")
                delay = retry_delay(attempt)
                emit(
                    f"  \033[33m[529] retry {attempt + 1}/{MAX_RETRIES} "
                    f"after {delay:.1f}s\033[0m"
                )
                time.sleep(delay)
                continue
            raise
    raise RuntimeError(f"Max retries ({MAX_RETRIES}) exceeded")


def is_prompt_too_long_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        ("prompt" in message and "long" in message)
        or "context_length_exceeded" in message
        or "max_context_window" in message
    )


def run_context_cycle(messages: list, deps: AgentLoopDeps, step: int, tool_error_count: int) -> list:
    runtime = deps.get_runtime()
    context_manager = runtime.get("context_manager")
    context_cybernetics = runtime.get("context_cybernetics")
    context_compactor = runtime.get("context_compactor")

    if context_manager is not None:
        context_manager.replace_messages(messages)

    run_cycle = getattr(context_cybernetics, "run_cycle", None)
    if callable(run_cycle):
        result = run_cycle(
            messages,
            step=step,
            tool_error_count=tool_error_count,
        )
        if getattr(result, "did_compact", False):
            messages[:] = result.messages
            return messages

    process_request = getattr(context_compactor, "process_request", None)
    if callable(process_request):
        result = process_request(messages, trigger=CompactTrigger.REQUEST)
        if getattr(result, "did_compact", False):
            messages[:] = result.messages

    return messages


def safety_snip_messages(messages: list, max_messages: int = 8) -> list:
    if len(messages) <= max_messages:
        return list(messages)
    keep_head = 2
    keep_tail = max(1, max_messages - 3)
    snipped = len(messages) - keep_head - keep_tail
    return (
        list(messages[:keep_head])
        + [{"role": "user", "content": f"[snipped {snipped} messages]"}]
        + list(messages[-keep_tail:])
    )


def build_user_content(results: list[dict]) -> list[dict]:
    return list(results)


def inject_background_notifications(messages: list) -> None:
    notes = collect_background_notifications()
    if notes:
        messages.append(
            {
                "role": "user",
                "content": [{"type": "text", "text": note} for note in notes],
            }
        )


def call_llm(
    messages: list,
    context: dict,
    tools: list,
    state: RecoveryState,
    max_tokens: int,
    deps: AgentLoopDeps,
) -> Any:
    system = deps.assemble_system_prompt(context)
    return with_retry(
        lambda: deps.client.messages.create(
            model=state.current_model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
        ),
        state,
        deps.terminal_print,
        deps.fallback_model,
    )


def agent_loop(messages: list, context: dict, deps: AgentLoopDeps) -> None:
    global rounds_since_todo
    tools, registry = deps.assemble_tool_pool()
    state = RecoveryState(deps.primary_model)
    max_tokens = DEFAULT_MAX_TOKENS
    permissions = deps.get_runtime().get("permissions")
    step = 0
    tool_error_count = 0

    if permissions is not None:
        permissions.begin_turn()

    try:
        while True:
            step += 1
            fired = deps.consume_cron_queue()
            for job in fired:
                prompt = getattr(job, "prompt", None)
                if prompt is None and isinstance(job, dict):
                    prompt = job.get("prompt")
                messages.append({"role": "user", "content": f"[Scheduled] {prompt}"})
                deps.terminal_print(f"  \033[35m[cron inject] {str(prompt)[:60]}\033[0m")

            inject_background_notifications(messages)

            if rounds_since_todo >= 3:
                messages.append(
                    {
                        "role": "user",
                        "content": "<reminder>Update your todos.</reminder>",
                    }
                )
                rounds_since_todo = 0

            run_context_cycle(messages, deps, step=step, tool_error_count=tool_error_count)
            context = deps.update_context(context, messages)
            tools, registry = deps.assemble_tool_pool()

            try:
                response = call_llm(messages, context, tools, state, max_tokens, deps)
            except Exception as exc:
                if is_prompt_too_long_error(exc) and not state.has_attempted_reactive_compact:
                    deps.terminal_print("  \033[31m[prompt too long] attempting reactive recover\033[0m")
                    runtime = deps.get_runtime()
                    context_cybernetics = runtime.get("context_cybernetics")
                    context_compactor = runtime.get("context_compactor")
                    recovered = None
                    if context_cybernetics is not None:
                        recovered = context_cybernetics.try_reactive_recover(messages, reason=str(exc))
                    if (recovered is None or not getattr(recovered, "did_compact", False)) and context_compactor is not None:
                        recovered = context_compactor.reactive_recover(messages, focus=str(exc))
                    if recovered is not None and getattr(recovered, "did_compact", False):
                        messages[:] = recovered.messages
                        state.has_attempted_reactive_compact = True
                        continue
                    messages[:] = safety_snip_messages(messages)
                    state.has_attempted_reactive_compact = True
                    continue
                messages.append(
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "text",
                                "text": f"[Error] {type(exc).__name__}: {exc}",
                            }
                        ],
                    }
                )
                return

            if getattr(response, "stop_reason", None) == "max_tokens":
                if not state.has_escalated:
                    max_tokens = ESCALATED_MAX_TOKENS
                    state.has_escalated = True
                    deps.terminal_print(f"  \033[33m[max_tokens] retry with {max_tokens}\033[0m")
                    continue
                messages.append({"role": "assistant", "content": response.content})
                if state.recovery_count < MAX_RECOVERY_RETRIES:
                    messages.append({"role": "user", "content": CONTINUATION_PROMPT})
                    state.recovery_count += 1
                    continue
                return

            max_tokens = DEFAULT_MAX_TOKENS
            state.has_escalated = False
            messages.append({"role": "assistant", "content": response.content})
            if not deps.has_tool_use(response.content):
                deps.trigger_hooks("Stop", messages)
                return

            results = []
            compacted_now = False
            for block in response.content:
                if _block_value(block, "type") != "tool_use":
                    continue
                deps.terminal_print(f"\033[36m> {_block_value(block, 'name')}\033[0m")

                blocked = deps.trigger_hooks("PreToolUse", block)
                if blocked:
                    tool_error_count += 1
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": _block_value(block, "id"),
                            "content": str(blocked),
                        }
                    )
                    continue

                tool_result = registry.execute(
                    _block_value(block, "name"),
                    _block_value(block, "input", {}),
                    _tool_context(deps),
                )
                output = tool_result.output
                deps.trigger_hooks("PostToolUse", block, tool_result)
                if tool_result.background_task is not None:
                    task = tool_result.background_task
                    deps.terminal_print(
                        f"  \033[33m[background] {task.task_id}: {task.command[:60]}\033[0m"
                    )
                else:
                    deps.terminal_print(str(output)[:300])

                if getattr(tool_result, "ok", True):
                    tool_error_count = 0
                else:
                    tool_error_count += 1

                if _block_value(block, "name") == "todo_write":
                    rounds_since_todo = 0
                else:
                    rounds_since_todo += 1

                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": _block_value(block, "id"),
                        "content": output,
                    }
                )

            if compacted_now:
                continue
            messages.append({"role": "user", "content": build_user_content(results)})
    finally:
        if permissions is not None:
            permissions.end_turn()


def print_turn_assistants(messages: list, turn_start: int, deps: AgentLoopDeps) -> None:
    for msg in messages[turn_start:]:
        if msg.get("role") != "assistant":
            continue
        for block in msg.get("content", []):
            if _block_value(block, "type") == "text":
                deps.terminal_print(str(_block_value(block, "text", "")))


def cron_autorun_loop(history: list, context: dict, deps: AgentLoopDeps) -> None:
    while True:
        time.sleep(1)
        fired = deps.consume_cron_queue()
        if not fired:
            continue
        with agent_lock:
            turn_start = len(history)
            for job in fired:
                prompt = getattr(job, "prompt", None)
                if prompt is None and isinstance(job, dict):
                    prompt = job.get("prompt")
                history.append({"role": "user", "content": f"[Scheduled] {prompt}"})
                deps.terminal_print(f"  [cron auto] {str(prompt)[:60]}")
            agent_loop(history, context, deps)
            context.update(deps.update_context(context, history))
            print_turn_assistants(history, turn_start, deps)
