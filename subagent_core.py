from __future__ import annotations

from typing import Any, Callable

from tooling import ToolContext


def extract_text(content) -> str:
    if not isinstance(content, list):
        return str(content)
    return "\n".join(
        getattr(block, "text", "")
        for block in content
        if getattr(block, "type", None) == "text"
    ).strip()


def has_tool_use(content) -> bool:
    return any(getattr(block, "type", None) == "tool_use" for block in content)


def spawn_subagent(
    description: str,
    *,
    client: Any,
    model: str,
    system: str | None = None,
    system_prompt: str | None = None,
    registry_factory: Callable[[], Any] | None = None,
    serialize_tools: Callable[[Any], list[dict]] | None = None,
    registry: Any | None = None,
    tools_schema: list[dict] | None = None,
    trigger_hooks: Callable[..., Any],
    cwd: str | None = None,
    workspace_root: str | None = None,
    runtime: dict | None = None,
) -> str:
    if registry is None:
        if registry_factory is None:
            raise ValueError("registry or registry_factory is required")
        registry = registry_factory()
    if tools_schema is None:
        if serialize_tools is None:
            raise ValueError("tools_schema or serialize_tools is required")
        tools_schema = serialize_tools(registry)
    effective_system = system_prompt if system_prompt is not None else system
    if effective_system is None:
        raise ValueError("system or system_prompt is required")
    effective_cwd = workspace_root if workspace_root is not None else cwd
    if effective_cwd is None:
        raise ValueError("cwd or workspace_root is required")
    messages = [{"role": "user", "content": description}]
    for _ in range(30):
        response = client.messages.create(
            model=model,
            system=effective_system,
            messages=messages,
            tools=tools_schema,
            max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})
        if not has_tool_use(response.content):
            break
        results = []
        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            blocked = trigger_hooks("PreToolUse", block)
            if blocked:
                output = str(blocked)
            else:
                tool_result = registry.execute(
                    block.name,
                    block.input,
                    ToolContext(cwd=effective_cwd, runtime=runtime),
                )
                output = tool_result.output
                trigger_hooks("PostToolUse", block, output)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                }
            )
        messages.append({"role": "user", "content": results})
    for message in reversed(messages):
        if message["role"] == "assistant":
            text = extract_text(message["content"])
            if text:
                return text
    return "Subagent finished without a text summary."
