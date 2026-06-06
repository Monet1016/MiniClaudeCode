from __future__ import annotations

from tooling import ToolRegistry
from tools.adapters import make_handler_tool
from tools.bash import TOOL as BASH_TOOL
from tools.edit_file import TOOL as EDIT_FILE_TOOL
from tools.glob_search import TOOL as GLOB_TOOL
from tools.grep_files import TOOL as GREP_FILES_TOOL
from tools.list_files import TOOL as LIST_FILES_TOOL
from tools.load_skill import create_load_skill_tool
from tools.patch_file import TOOL as PATCH_FILE_TOOL
from tools.read_file import TOOL as READ_FILE_TOOL
from tools.run_command import TOOL as RUN_COMMAND_TOOL
from tools.write_file import TOOL as WRITE_FILE_TOOL

try:
    from tools.cancel_cron import TOOL as CANCEL_CRON_TOOL
    from tools.check_inbox import TOOL as CHECK_INBOX_TOOL
    from tools.claim_task import TOOL as CLAIM_TASK_TOOL
    from tools.complete_task import TOOL as COMPLETE_TASK_TOOL
    from tools.compact import TOOL as COMPACT_TOOL
    from tools.create_task import TOOL as CREATE_TASK_TOOL
    from tools.create_worktree import TOOL as CREATE_WORKTREE_TOOL
    from tools.get_task import TOOL as GET_TASK_TOOL
    from tools.keep_worktree import TOOL as KEEP_WORKTREE_TOOL
    from tools.list_crons import TOOL as LIST_CRONS_TOOL
    from tools.list_tasks import TOOL as LIST_TASKS_TOOL
    from tools.remove_worktree import TOOL as REMOVE_WORKTREE_TOOL
    from tools.request_plan import TOOL as REQUEST_PLAN_TOOL
    from tools.request_shutdown import TOOL as REQUEST_SHUTDOWN_TOOL
    from tools.review_plan import TOOL as REVIEW_PLAN_TOOL
    from tools.schedule_cron import TOOL as SCHEDULE_CRON_TOOL
    from tools.send_message import TOOL as SEND_MESSAGE_TOOL
    from tools.spawn_teammate import TOOL as SPAWN_TEAMMATE_TOOL
    from tools.task import TOOL as TASK_TOOL
    from tools.todo_write import TOOL as TODO_WRITE_TOOL
except ImportError:
    CANCEL_CRON_TOOL = None
    CHECK_INBOX_TOOL = None
    CLAIM_TASK_TOOL = None
    COMPLETE_TASK_TOOL = None
    COMPACT_TOOL = None
    CREATE_TASK_TOOL = None
    CREATE_WORKTREE_TOOL = None
    GET_TASK_TOOL = None
    KEEP_WORKTREE_TOOL = None
    LIST_CRONS_TOOL = None
    LIST_TASKS_TOOL = None
    REMOVE_WORKTREE_TOOL = None
    REQUEST_PLAN_TOOL = None
    REQUEST_SHUTDOWN_TOOL = None
    REVIEW_PLAN_TOOL = None
    SCHEDULE_CRON_TOOL = None
    SEND_MESSAGE_TOOL = None
    SPAWN_TEAMMATE_TOOL = None
    TASK_TOOL = None
    TODO_WRITE_TOOL = None


SUBAGENT_TOOLS = [
    RUN_COMMAND_TOOL,
    READ_FILE_TOOL,
    WRITE_FILE_TOOL,
    EDIT_FILE_TOOL,
    LIST_FILES_TOOL,
    GREP_FILES_TOOL,
    PATCH_FILE_TOOL,
    BASH_TOOL,
    GLOB_TOOL,
]


def _core_tools(cwd: str):
    return [
        RUN_COMMAND_TOOL,
        READ_FILE_TOOL,
        WRITE_FILE_TOOL,
        EDIT_FILE_TOOL,
        LIST_FILES_TOOL,
        GREP_FILES_TOOL,
        PATCH_FILE_TOOL,
        create_load_skill_tool(cwd),
    ]


def _workflow_tools():
    return [
        tool
        for tool in [
            TODO_WRITE_TOOL,
            TASK_TOOL,
            COMPACT_TOOL,
            CREATE_TASK_TOOL,
            LIST_TASKS_TOOL,
            GET_TASK_TOOL,
            CLAIM_TASK_TOOL,
            COMPLETE_TASK_TOOL,
            CREATE_WORKTREE_TOOL,
            REMOVE_WORKTREE_TOOL,
            KEEP_WORKTREE_TOOL,
            SCHEDULE_CRON_TOOL,
            LIST_CRONS_TOOL,
            CANCEL_CRON_TOOL,
            SPAWN_TEAMMATE_TOOL,
            SEND_MESSAGE_TOOL,
            CHECK_INBOX_TOOL,
            REQUEST_SHUTDOWN_TOOL,
            REQUEST_PLAN_TOOL,
            REVIEW_PLAN_TOOL,
        ]
        if tool is not None
    ]


def _alias_tools():
    return [
        BASH_TOOL,
        GLOB_TOOL,
    ]


def create_builtin_tool_registry(cwd: str, runtime: dict | None = None) -> ToolRegistry:
    del runtime
    return ToolRegistry([*_core_tools(cwd), *_workflow_tools(), *_alias_tools()])


def create_subagent_tool_registry(cwd: str, runtime: dict | None = None) -> ToolRegistry:
    del runtime
    tools = [*SUBAGENT_TOOLS, create_load_skill_tool(cwd)]
    return ToolRegistry(tools)


def serialize_tools_for_llm(registry: ToolRegistry) -> list[dict]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }
        for tool in registry.list()
    ]


__all__ = [
    "create_builtin_tool_registry",
    "create_subagent_tool_registry",
    "make_handler_tool",
    "serialize_tools_for_llm",
]
