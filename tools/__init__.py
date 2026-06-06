from tooling import ToolRegistry
from tools.adapters import make_handler_tool
from tools.bash import TOOL as BASH_TOOL
from tools.edit_file import TOOL as EDIT_FILE_TOOL
from tools.glob_search import TOOL as GLOB_TOOL
from tools.read_file import TOOL as READ_FILE_TOOL
from tools.write_file import TOOL as WRITE_FILE_TOOL


BUILTIN_CORE_TOOLS = [
    BASH_TOOL,
    READ_FILE_TOOL,
    WRITE_FILE_TOOL,
    EDIT_FILE_TOOL,
    GLOB_TOOL,
]


def create_builtin_tool_registry() -> ToolRegistry:
    return ToolRegistry(list(BUILTIN_CORE_TOOLS))


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
    "BUILTIN_CORE_TOOLS",
    "create_builtin_tool_registry",
    "make_handler_tool",
    "serialize_tools_for_llm",
]
