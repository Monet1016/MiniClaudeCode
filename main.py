import json
import os
import re
import subprocess
import threading
from _thread import interrupt_main
from datetime import datetime
from pathlib import Path

try:
    import readline

    readline.parse_and_bind("set bind-tty-special-chars off")
    READLINE_AVAILABLE = True
except ImportError:
    READLINE_AVAILABLE = False

from anthropic import Anthropic
from dotenv import load_dotenv

from agent_loop import (
    AgentLoopDeps,
    agent_lock,
    agent_loop,
    cron_autorun_loop,
    print_turn_assistants,
)
from context_compaction import (
    compact_history as compact_history_core,
    estimate_size,
    micro_compact as micro_compact_core,
    reactive_compact as reactive_compact_core,
    snip_compact as snip_compact_core,
    tool_result_budget as tool_result_budget_core,
)
from cron_core import CronStore
from permissions import PermissionManager
from protocol_core import ProtocolStore
from session_tools_core import TodoState
from skills import list_skills as list_skill_records, load_skill as load_skill_record
from subagent_core import extract_text, has_tool_use, spawn_subagent as spawn_subagent_core
from tasks_core import TaskStore
from teammate_core import GLOBAL_BUS, MessageBus
from tooling import ToolContext, ToolRegistry
from tools import (
    create_builtin_tool_registry as build_core_tool_registry,
    create_subagent_tool_registry as build_subagent_tool_registry,
    make_handler_tool,
    serialize_tools_for_llm,
)
from worktree_core import WorktreeManager
from workspace import resolve_workspace_path

load_dotenv(override=True)
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]
PRIMARY_MODEL = MODEL
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL_ID")

TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TOOL_RESULTS_DIR = WORKDIR / ".task_outputs" / "tool-results"
MAILBOX_DIR = WORKDIR / ".mailboxes"
MAILBOX_DIR.mkdir(exist_ok=True)

CONTEXT_LIMIT = 50000
KEEP_RECENT_TOOL_RESULTS = 3
PERSIST_THRESHOLD = 30000
PROMPT = "\033[36ms20 >> \033[0m"
CLI_ACTIVE = False

TASK_STORE = TaskStore(WORKDIR / ".tasks")
WORKTREE_MANAGER = WorktreeManager(
    repo_root=WORKDIR,
    worktrees_root=WORKDIR / ".worktrees",
    task_store=TASK_STORE,
)
CRON_STORE = CronStore(WORKDIR / ".scheduled_tasks.json")
TODO_STATE = TodoState()
BUS = MessageBus(MAILBOX_DIR)
GLOBAL_BUS.mailbox_dir = MAILBOX_DIR
PROTOCOL_STORE = ProtocolStore()
active_teammates: dict[str, bool] = {}
BACKGROUND_PERMISSION_ABORT = False
BACKGROUND_PERMISSION_SCOPE: str | None = None


def handle_background_permission_request(request: dict[str, object]) -> None:
    global BACKGROUND_PERMISSION_ABORT, BACKGROUND_PERMISSION_SCOPE
    scope = request.get("scope", "(unknown scope)")
    BACKGROUND_PERMISSION_ABORT = True
    BACKGROUND_PERMISSION_SCOPE = str(scope)
    print(
        "\n\033[31m[permission] background task requested interactive approval; "
        f"stopping session. scope: {scope}\033[0m"
    )
    interrupt_main()


def consume_background_permission_abort() -> str | None:
    global BACKGROUND_PERMISSION_ABORT, BACKGROUND_PERMISSION_SCOPE
    if not BACKGROUND_PERMISSION_ABORT:
        return None
    scope = BACKGROUND_PERMISSION_SCOPE
    BACKGROUND_PERMISSION_ABORT = False
    BACKGROUND_PERMISSION_SCOPE = None
    return scope


def permission_prompt_handler(request: dict[str, object]) -> dict[str, object]:
    print(f"\n\033[33m[permission] {request['summary']}\033[0m")
    for detail in request.get("details", []):
        print(f"  {detail}")
    print(f"  scope: {request['scope']}")
    for choice in request.get("choices", []):
        print(f"  {choice['key']}: {choice['label']}")

    allowed_keys = {
        str(choice["key"]): str(choice["decision"])
        for choice in request.get("choices", [])
    }
    response = input("  Select choice: ").strip()
    decision = allowed_keys.get(response)
    if decision is None:
        decision = "deny_once"
    return {"decision": decision}


def build_permission_manager() -> PermissionManager:
    return PermissionManager(
        str(WORKDIR),
        prompt=permission_prompt_handler,
        background_prompt_handler=handle_background_permission_request,
    )


PERMISSIONS = build_permission_manager()


def terminal_print(text: str):
    if threading.current_thread() is threading.main_thread() or not CLI_ACTIVE:
        print(text)
        return
    line = ""
    if READLINE_AVAILABLE:
        try:
            line = readline.get_line_buffer()
        except Exception:
            line = ""
    print(f"\r\033[K{text}")
    print(PROMPT + line, end="", flush=True)


def list_skills() -> str:
    skill_records = list_skill_records(str(WORKDIR))
    if not skill_records:
        return "(no skills found)"
    return "\n".join(f"- {skill.name}: {skill.description}" for skill in skill_records)


def load_skill(name: str) -> str:
    skill = load_skill_record(str(WORKDIR), name)
    if skill is None:
        available = ", ".join(record.name for record in list_skill_records(str(WORKDIR))) or "(none)"
        return f"Skill not found: {name}. Available: {available}"
    return skill.content


def create_builtin_tool_registry(cwd: str | None = None) -> ToolRegistry:
    if cwd is None:
        cwd = str(WORKDIR)
    try:
        return build_core_tool_registry(cwd)
    except TypeError as error:
        try:
            return build_core_tool_registry()
        except TypeError:
            raise error


def create_subagent_tool_registry() -> ToolRegistry:
    return build_subagent_tool_registry(str(WORKDIR))


def runtime_state(messages: list | None = None, sender: str = "lead", agent_name: str = "lead") -> dict:
    permissions = globals().get("PERMISSIONS")
    return {
        "messages": messages if messages is not None else [],
        "compact_history": compact_history,
        "spawn_subagent": spawn_subagent,
        "spawn_teammate": spawn_teammate_thread,
        "message_bus": BUS,
        "protocol_store": PROTOCOL_STORE,
        "task_store": TASK_STORE,
        "worktree_manager": WORKTREE_MANAGER,
        "cron_store": CRON_STORE,
        "todo_state": TODO_STATE,
        "permissions": permissions,
        "sender": sender,
        "agent_name": agent_name,
    }


def build_runtime_context(messages: list | None = None, sender: str = "lead", agent_name: str = "lead") -> dict:
    runtime = runtime_state(messages=messages, sender=sender, agent_name=agent_name)
    runtime["spawn_subagent"] = build_spawn_subagent_callback(runtime)
    return runtime


def build_child_runtime_context(
    parent_runtime: dict,
    messages: list | None = None,
    sender: str = "subagent",
    agent_name: str = "subagent",
) -> dict:
    runtime = dict(parent_runtime)
    runtime.update(
        {
            "messages": messages if messages is not None else [],
            "compact_history": compact_history,
            "sender": sender,
            "agent_name": agent_name,
        }
    )
    runtime["spawn_subagent"] = build_spawn_subagent_callback(runtime)
    return runtime


def build_spawn_subagent_callback(parent_runtime: dict):
    def _spawn(description: str) -> str:
        registry = create_subagent_tool_registry()
        child_runtime = build_child_runtime_context(
            parent_runtime=parent_runtime,
            messages=[],
            sender="subagent",
            agent_name="subagent",
        )
        return spawn_subagent_core(
            description,
            client=client,
            model=MODEL,
            system=SUB_SYSTEM,
            registry=registry,
            tools_schema=serialize_tools_for_llm(registry),
            trigger_hooks=trigger_hooks,
            cwd=str(WORKDIR),
            runtime=child_runtime,
        )

    return _spawn


PROMPT_SECTIONS = {
    "identity": "You are a coding agent. Act, don't explain.",
    "tools": (
        "Available tools: run_command, read_file, write_file, edit_file, list_files, "
        "grep_files, patch_file, load_skill, bash, glob, todo_write, task, compact, "
        "create_task, list_tasks, get_task, claim_task, complete_task, schedule_cron, "
        "list_crons, cancel_cron, spawn_teammate, send_message, check_inbox, "
        "request_shutdown, request_plan, review_plan, create_worktree, "
        "remove_worktree, keep_worktree, connect_mcp. "
        "MCP tools are prefixed mcp__{server}__{tool}."
    ),
    "workspace": f"Working directory: {WORKDIR}",
    "memory": "Relevant memories are injected below when available.",
}


def assemble_system_prompt(context: dict) -> str:
    sections = [
        PROMPT_SECTIONS["identity"],
        PROMPT_SECTIONS["tools"],
        PROMPT_SECTIONS["workspace"],
    ]
    sections.append(f"Current time: {datetime.now().isoformat(timespec='seconds')}")
    sections.append("Skills catalog:\n" + list_skills() + "\nUse load_skill(name) when a skill is relevant.")
    if context.get("memories"):
        sections.append(f"Relevant memories:\n{context['memories']}")
    mcp_names = list(mcp_clients.keys())
    if mcp_names:
        sections.append(f"Connected MCP servers: {', '.join(mcp_names)}")
    return "\n\n".join(sections)


def safe_path(path_text: str, cwd: Path | None = None) -> Path:
    return resolve_workspace_path(cwd or WORKDIR, path_text)


def run_bash(command: str, cwd: Path | None = None, run_in_background: bool = False) -> str:
    del run_in_background
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=cwd or WORKDIR,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    output = (completed.stdout + completed.stderr).strip()
    return output[:50000] if output else "(no output)"


def run_read(path: str, limit: int | None = None, offset: int = 0, cwd: Path | None = None) -> str:
    try:
        lines = safe_path(path, cwd).read_text().splitlines()
        offset = max(int(offset or 0), 0)
        lines = lines[offset:]
        if limit is not None and int(limit) < len(lines):
            lines = lines[: int(limit)] + [f"... ({len(lines) - int(limit)} more lines)"]
        return "\n".join(lines)
    except Exception as error:
        return f"Error: {error}"


def run_write(path: str, content: str, cwd: Path | None = None) -> str:
    try:
        file_path = safe_path(path, cwd)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as error:
        return f"Error: {error}"


def run_edit(path: str, old_text: str, new_text: str, cwd: Path | None = None) -> str:
    try:
        file_path = safe_path(path, cwd)
        text = file_path.read_text()
        if old_text not in text:
            return f"Error: text not found in {path}"
        file_path.write_text(text.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as error:
        return f"Error: {error}"


def run_glob(pattern: str, cwd: Path | None = None) -> str:
    import glob as glob_module

    try:
        base = cwd or WORKDIR
        results = []
        for match in glob_module.glob(pattern, root_dir=base):
            if (base / match).resolve().is_relative_to(base):
                results.append(match)
        return "\n".join(results) if results else "(no matches)"
    except Exception as error:
        return f"Error: {error}"


def run_todo_write(todos: list) -> str:
    return TODO_STATE.write(todos)


def consume_lead_inbox(route_protocol: bool = True) -> list[dict]:
    messages = BUS.read_inbox("lead")
    if route_protocol:
        for message in messages:
            metadata = message.get("metadata", {})
            request_id = metadata.get("request_id", "")
            msg_type = message.get("type", "")
            if request_id and msg_type.endswith("_response"):
                PROTOCOL_STORE.match_response(msg_type, request_id, metadata.get("approve", False))
    return messages


def scan_unclaimed_tasks() -> list[dict]:
    return [
        {
            "id": task.id,
            "subject": task.subject,
            "status": task.status,
            "owner": task.owner,
            "worktree": task.worktree,
        }
        for task in TASK_STORE.scan_unclaimed_tasks()
    ]


def spawn_teammate_thread(name: str, role: str, prompt: str) -> str:
    if name in active_teammates:
        return f"Teammate '{name}' already exists"

    protocol_ctx = {"waiting_plan": None}
    system = (
        f"You are '{name}', a {role}. Use tools to complete tasks. "
        "If a task has a worktree, work in that directory."
    )

    def handle_inbox_message(message: dict, messages: list) -> bool:
        msg_type = message.get("type", "message")
        metadata = message.get("metadata", {})
        request_id = metadata.get("request_id", "")
        if msg_type == "shutdown_request":
            BUS.send(name, "lead", "Shutting down.", "shutdown_response", {"request_id": request_id, "approve": True})
            return True
        if msg_type == "plan_approval_response":
            approve = metadata.get("approve", False)
            if request_id == protocol_ctx["waiting_plan"]:
                protocol_ctx["waiting_plan"] = None
            messages.append(
                {
                    "role": "user",
                    "content": "[Plan approved]" if approve else f"[Plan rejected] {message['content']}",
                }
            )
        return False

    def run() -> None:
        wt_ctx = {"path": None}
        messages = [{"role": "user", "content": prompt}]
        registry = ToolRegistry(
            [
                make_handler_tool(
                    name="bash",
                    description="Run a shell command.",
                    input_schema={"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
                    handler=lambda command: run_bash(command, cwd=Path(wt_ctx["path"]) if wt_ctx["path"] else None),
                ),
                make_handler_tool(
                    name="read_file",
                    description="Read file.",
                    input_schema={
                        "type": "object",
                        "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}, "offset": {"type": "integer"}},
                        "required": ["path"],
                    },
                    handler=lambda path, limit=None, offset=0: run_read(path, limit=limit, offset=offset, cwd=Path(wt_ctx["path"]) if wt_ctx["path"] else None),
                ),
                make_handler_tool(
                    name="write_file",
                    description="Write file.",
                    input_schema={
                        "type": "object",
                        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                        "required": ["path", "content"],
                    },
                    handler=lambda path, content: run_write(path, content, cwd=Path(wt_ctx["path"]) if wt_ctx["path"] else None),
                ),
                make_handler_tool(
                    name="send_message",
                    description="Send message to another agent.",
                    input_schema={
                        "type": "object",
                        "properties": {"to": {"type": "string"}, "content": {"type": "string"}},
                        "required": ["to", "content"],
                    },
                    handler=lambda to, content: (BUS.send(name, to, content), "Sent")[1],
                ),
                make_handler_tool(
                    name="list_tasks",
                    description="List all tasks.",
                    input_schema={"type": "object", "properties": {}, "required": []},
                    handler=lambda: "\n".join(
                        f"  {task.id}: {task.subject} [{task.status}]" + (f" (wt:{task.worktree})" if task.worktree else "")
                        for task in TASK_STORE.list_tasks()
                    )
                    or "No tasks.",
                ),
                make_handler_tool(
                    name="claim_task",
                    description="Claim a pending task.",
                    input_schema={"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]},
                    handler=lambda task_id: _claim_teammate_task(task_id, name, wt_ctx),
                ),
                make_handler_tool(
                    name="complete_task",
                    description="Mark an in-progress task as completed.",
                    input_schema={"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]},
                    handler=lambda task_id: _complete_teammate_task(task_id, wt_ctx),
                ),
            ]
        )
        sub_tools = serialize_tools_for_llm(registry)
        while True:
            if len(messages) <= 3:
                messages.insert(
                    0,
                    {
                        "role": "user",
                        "content": f"<identity>You are '{name}', role: {role}. Continue your work.</identity>",
                    },
                )
            should_shutdown = False
            for _ in range(10):
                inbox = BUS.read_inbox(name)
                for message in inbox:
                    if handle_inbox_message(message, messages):
                        should_shutdown = True
                        break
                if should_shutdown:
                    break
                if protocol_ctx["waiting_plan"]:
                    threading.Event().wait(0.1)
                    continue
                if inbox:
                    non_protocol = [item for item in inbox if item.get("type") == "message"]
                    if non_protocol:
                        messages.append({"role": "user", "content": "<inbox>" + json.dumps(non_protocol) + "</inbox>"})
                try:
                    response = client.messages.create(
                        model=MODEL,
                        system=system,
                        messages=messages[-20:],
                        tools=sub_tools,
                        max_tokens=8000,
                    )
                except Exception:
                    break
                messages.append({"role": "assistant", "content": response.content})
                if not has_tool_use(response.content):
                    break
                results = []
                for block in response.content:
                    if getattr(block, "type", None) != "tool_use":
                        continue
                    tool_result = registry.execute(
                        block.name,
                        block.input,
                        ToolContext(
                            cwd=wt_ctx["path"] or str(WORKDIR),
                            permissions=PERMISSIONS,
                        ),
                    )
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": tool_result.output})
                messages.append({"role": "user", "content": results})
            if should_shutdown:
                break
            threading.Event().wait(0.1)
        summary = "Done."
        for message in reversed(messages):
            if message["role"] == "assistant" and isinstance(message["content"], list):
                for block in message["content"]:
                    if getattr(block, "type", None) == "text":
                        summary = block.text
                        break
                else:
                    continue
                break
        BUS.send(name, "lead", summary, "result")
        active_teammates.pop(name, None)

    active_teammates[name] = True
    threading.Thread(target=run, daemon=True).start()
    return f"Teammate '{name}' spawned as {role}"


def _claim_teammate_task(task_id: str, owner: str, wt_ctx: dict) -> str:
    result = TASK_STORE.claim_task(task_id, owner=owner)
    if "Claimed" in result:
        task = TASK_STORE.load_task(task_id)
        wt_ctx["path"] = str((WORKDIR / ".worktrees" / task.worktree)) if task.worktree else None
    return result


def _complete_teammate_task(task_id: str, wt_ctx: dict) -> str:
    result = TASK_STORE.complete_task(task_id)
    wt_ctx["path"] = None
    return result


HOOKS = {"UserPromptSubmit": [], "PreToolUse": [], "PostToolUse": [], "Stop": []}


def register_hook(event: str, callback):
    HOOKS[event].append(callback)


def trigger_hooks(event: str, *args):
    for callback in HOOKS[event]:
        result = callback(*args)
        if result is not None:
            return result
    return None


def permission_hook(block):
    if block.name.startswith("mcp__") and "deploy" in block.name:
        print(f"\n\033[33m[permission] MCP destructive-looking tool: {block.name}\033[0m")
        choice = input("  Allow? [y/N] ").strip().lower()
        if choice not in ("y", "yes"):
            return "Permission denied by user"
    return None


def log_hook(block):
    print(f"\033[90m[HOOK] {block.name}\033[0m")
    return None


def large_output_hook(block, output):
    if len(str(output)) > 100000:
        print(f"\033[33m[HOOK] large output from {block.name}: {len(str(output))} chars\033[0m")
    return None


def user_prompt_hook(query: str):
    print(f"\033[90m[HOOK] UserPromptSubmit: {WORKDIR}\033[0m")
    return None


def stop_hook(messages: list):
    tool_count = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            tool_count += sum(1 for item in content if isinstance(item, dict) and item.get("type") == "tool_result")
    print(f"\033[90m[HOOK] Stop: {tool_count} tool result(s)\033[0m")
    return None


register_hook("UserPromptSubmit", user_prompt_hook)
register_hook("PreToolUse", permission_hook)
register_hook("PreToolUse", log_hook)
register_hook("PostToolUse", large_output_hook)
register_hook("Stop", stop_hook)

SUB_SYSTEM = (
    f"You are a coding subagent at {WORKDIR}. "
    "Complete the task, then return a concise final summary. "
    "Do not spawn more agents."
)


def spawn_subagent(description: str) -> str:
    return build_spawn_subagent_callback(
        build_runtime_context(messages=[], sender="lead", agent_name="lead")
    )(description)


def tool_result_budget(messages: list, max_bytes: int = 200_000) -> list:
    return tool_result_budget_core(
        messages,
        tool_results_dir=TOOL_RESULTS_DIR,
        max_bytes=max_bytes,
        persist_threshold=PERSIST_THRESHOLD,
    )


def snip_compact(messages: list, max_messages: int = 50) -> list:
    return snip_compact_core(messages, max_messages=max_messages)


def micro_compact(messages: list) -> list:
    return micro_compact_core(messages, keep_recent_tool_results=KEEP_RECENT_TOOL_RESULTS)


def compact_history(messages: list) -> list:
    return compact_history_core(
        messages,
        transcript_dir=TRANSCRIPT_DIR,
        client=client,
        model=MODEL,
        extract_text=extract_text,
        printer=print,
    )


def reactive_compact(messages: list) -> list:
    return reactive_compact_core(
        messages,
        transcript_dir=TRANSCRIPT_DIR,
        client=client,
        model=MODEL,
        extract_text=extract_text,
        printer=print,
    )


threading.Thread(target=CRON_STORE.cron_scheduler_loop, daemon=True).start()


class MCPClient:
    def __init__(self, name: str):
        self.name = name
        self.tools: list[dict] = []
        self._handlers: dict[str, callable] = {}

    def register(self, tool_defs: list[dict], handlers: dict[str, callable]):
        self.tools = tool_defs
        self._handlers = handlers

    def call_tool(self, tool_name: str, args: dict) -> str:
        handler = self._handlers.get(tool_name)
        if not handler:
            return f"MCP error: unknown tool '{tool_name}'"
        try:
            return handler(**args)
        except Exception as error:
            return f"MCP error: {error}"


mcp_clients: dict[str, MCPClient] = {}
_DISALLOWED_CHARS = re.compile(r"[^a-zA-Z0-9_-]")


def normalize_mcp_name(name: str) -> str:
    return _DISALLOWED_CHARS.sub("_", name)


def _mock_server_docs():
    server = MCPClient("docs")
    server.register(
        tool_defs=[
            {
                "name": "search",
                "description": "Search documentation. (readOnly)",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
            {
                "name": "get_version",
                "description": "Get API version. (readOnly)",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
        ],
        handlers={
            "search": lambda query: f"[docs] Found 3 results for '{query}'",
            "get_version": lambda: "[docs] API v2.1.0",
        },
    )
    return server


def _mock_server_deploy():
    server = MCPClient("deploy")
    server.register(
        tool_defs=[
            {
                "name": "trigger",
                "description": "Trigger a deployment. (destructive - requires approval in real CC)",
                "inputSchema": {
                    "type": "object",
                    "properties": {"service": {"type": "string"}},
                    "required": ["service"],
                },
            },
            {
                "name": "status",
                "description": "Check deployment status. (readOnly)",
                "inputSchema": {
                    "type": "object",
                    "properties": {"service": {"type": "string"}},
                    "required": ["service"],
                },
            },
        ],
        handlers={
            "trigger": lambda service: f"[deploy] Triggered: {service}",
            "status": lambda service: f"[deploy] {service}: running (v1.4.2)",
        },
    )
    return server


MOCK_SERVERS = {"docs": _mock_server_docs, "deploy": _mock_server_deploy}


def connect_mcp(name: str) -> str:
    if name in mcp_clients:
        return f"MCP server '{name}' already connected"
    factory = MOCK_SERVERS.get(name)
    if not factory:
        available = ", ".join(MOCK_SERVERS.keys())
        return f"Unknown server '{name}'. Available: {available}"
    server = factory()
    mcp_clients[name] = server
    tool_names = [tool["name"] for tool in server.tools]
    print(f"  \033[31m[mcp] connected: {name} -> {tool_names}\033[0m")
    return f"Connected to MCP server '{name}'. Discovered {len(server.tools)} tools: {', '.join(tool_names)}"


def run_connect_mcp(name: str) -> str:
    return connect_mcp(name)


def assemble_tool_pool() -> tuple[list[dict], object]:
    all_tools = create_builtin_tool_registry(str(WORKDIR)).list()
    for server_name, mcp_client in mcp_clients.items():
        safe_server = normalize_mcp_name(server_name)
        for tool_def in mcp_client.tools:
            safe_tool = normalize_mcp_name(tool_def["name"])
            prefixed = f"mcp__{safe_server}__{safe_tool}"
            tool_name = tool_def["name"]

            def call_mcp_tool(_tool_name=tool_name, _mcp_client=mcp_client, **kwargs):
                return _mcp_client.call_tool(_tool_name, kwargs)

            all_tools.append(
                make_handler_tool(
                    name=prefixed,
                    description=tool_def.get("description", ""),
                    input_schema=tool_def.get("inputSchema", {}),
                    handler=call_mcp_tool,
                )
            )

    all_tools.append(
        make_handler_tool(
            name="connect_mcp",
            description="Connect to an MCP server (docs, deploy) and discover tools.",
            input_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            handler=run_connect_mcp,
        )
    )
    registry = ToolRegistry(all_tools)
    return serialize_tools_for_llm(registry), registry


MEMORY_DIR = WORKDIR / ".memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"


def update_context(context: dict, messages: list) -> dict:
    del context, messages
    memories = ""
    if MEMORY_INDEX.exists():
        memories = MEMORY_INDEX.read_text()[:2000]
    return {
        "memories": memories,
        "connected_mcp": list(mcp_clients.keys()),
        "active_teammates": list(active_teammates.keys()),
    }


def consume_cron_queue():
    return CRON_STORE.consume_cron_queue()


def build_agent_loop_deps(messages: list) -> AgentLoopDeps:
    return AgentLoopDeps(
        client=client,
        assemble_system_prompt=assemble_system_prompt,
        assemble_tool_pool=assemble_tool_pool,
        get_runtime=lambda: build_runtime_context(
            messages=messages,
            sender="lead",
            agent_name="lead",
        ),
        update_context=update_context,
        compact_history=compact_history,
        reactive_compact=reactive_compact,
        consume_cron_queue=consume_cron_queue,
        tool_result_budget=tool_result_budget,
        snip_compact=snip_compact,
        micro_compact=micro_compact,
        estimate_size=estimate_size,
        trigger_hooks=trigger_hooks,
        terminal_print=terminal_print,
        has_tool_use=has_tool_use,
        workspace_root=str(WORKDIR),
        context_limit=CONTEXT_LIMIT,
        primary_model=PRIMARY_MODEL,
        fallback_model=FALLBACK_MODEL,
    )


if __name__ == "__main__":
    CLI_ACTIVE = True
    print("s20: comprehensive agent")
    print("Enter a question, press Enter to send. Type q to quit.\n")
    history = []
    context = update_context({}, [])
    deps = build_agent_loop_deps(history)
    threading.Thread(target=cron_autorun_loop, args=(history, context, deps), daemon=True).start()
    while True:
        try:
            query = input(PROMPT)
            if query.strip().lower() in ("q", "exit", ""):
                break
            trigger_hooks("UserPromptSubmit", query)
            turn_start = len(history)
            history.append({"role": "user", "content": query})
            with agent_lock:
                agent_loop(history, context, deps)
                context = update_context(context, history)
                print_turn_assistants(history, turn_start, deps)
            inbox = consume_lead_inbox(route_protocol=True)
            if inbox:
                def inbox_label(message):
                    request_id = message.get("metadata", {}).get("request_id", "")
                    suffix = f" req:{request_id}" if request_id else ""
                    return f"{message.get('type', 'message')}{suffix}"

                inbox_text = "\n".join(
                    f"From {message['from']} [{inbox_label(message)}]: {message['content'][:200]}"
                    for message in inbox
                )
                history.append({"role": "user", "content": f"[Inbox]\n{inbox_text}"})
            print()
        except EOFError:
            break
        except KeyboardInterrupt:
            scope = consume_background_permission_abort()
            if scope is None:
                print()
                break
            print(
                "\033[31mSession interrupted because a background task required "
                f"interactive permission approval: {scope}\033[0m"
            )
            print()
            continue
