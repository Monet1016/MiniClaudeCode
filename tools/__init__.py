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


def _alias_tools():
    return [
        BASH_TOOL,
        GLOB_TOOL,
    ]


def create_builtin_tool_registry(cwd: str, runtime: dict | None = None) -> ToolRegistry:
    del runtime
    return ToolRegistry([*_core_tools(cwd), *_alias_tools()])


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
    "make_handler_tool",
    "serialize_tools_for_llm",
]
