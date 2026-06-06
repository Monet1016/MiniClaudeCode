import unittest

from tooling import ToolContext, ToolDefinition, ToolRegistry, ToolResult


class ToolingTests(unittest.TestCase):
    def test_tool_context_exposes_permissions_and_runtime(self) -> None:
        context = ToolContext(
            cwd="D:/workspace",
            permissions={"write": False},
            runtime={"session": "abc"},
        )

        self.assertEqual({"write": False}, context.permissions)
        self.assertEqual({"session": "abc"}, context.runtime)

    def test_tool_definition_preserves_metadata(self) -> None:
        tool = ToolDefinition(
            name="sample",
            description="sample tool",
            input_schema={},
            validator=lambda data: data,
            run=lambda parsed, context: ToolResult(ok=True, output="ok"),
            metadata={"category": "filesystem"},
        )

        self.assertEqual({"category": "filesystem"}, tool.metadata)

    def test_execute_returns_unknown_tool_message(self) -> None:
        registry = ToolRegistry()

        result = registry.execute("missing", {}, ToolContext(cwd="."))

        self.assertFalse(result.ok)
        self.assertEqual("Unknown tool: missing", result.output)

    def test_execute_returns_validation_error_message(self) -> None:
        def validator(_: object) -> object:
            raise ValueError("bad input")

        registry = ToolRegistry(
            [
                ToolDefinition(
                    name="sample",
                    description="sample tool",
                    input_schema={},
                    validator=validator,
                    run=lambda parsed, context: ToolResult(ok=True, output="ok"),
                )
            ]
        )

        result = registry.execute("sample", {}, ToolContext(cwd="."))

        self.assertFalse(result.ok)
        self.assertEqual("Validation error in sample: bad input", result.output)

    def test_execute_returns_runtime_error_message(self) -> None:
        registry = ToolRegistry(
            [
                ToolDefinition(
                    name="sample",
                    description="sample tool",
                    input_schema={},
                    validator=lambda data: data,
                    run=lambda parsed, context: (_ for _ in ()).throw(RuntimeError("boom")),
                )
            ]
        )

        result = registry.execute("sample", {}, ToolContext(cwd="."))

        self.assertFalse(result.ok)
        self.assertEqual("Error running sample: boom", result.output)

    def test_execute_normalizes_none_output_to_empty_string(self) -> None:
        registry = ToolRegistry(
            [
                ToolDefinition(
                    name="sample",
                    description="sample tool",
                    input_schema={},
                    validator=lambda data: data,
                    run=lambda parsed, context: ToolResult(ok=True, output=None),
                )
            ]
        )

        result = registry.execute("sample", {}, ToolContext(cwd="."))

        self.assertTrue(result.ok)
        self.assertEqual("", result.output)

    def test_execute_truncates_large_output(self) -> None:
        registry = ToolRegistry(
            [
                ToolDefinition(
                    name="sample",
                    description="sample tool",
                    input_schema={},
                    validator=lambda data: data,
                    run=lambda parsed, context: ToolResult(ok=True, output="x" * 25000),
                )
            ]
        )

        result = registry.execute("sample", {}, ToolContext(cwd="."))

        self.assertTrue(result.ok)
        self.assertLess(len(result.output), 25000)
        self.assertIn("truncated", result.output.lower())

    def test_execute_truncates_large_validation_error_output(self) -> None:
        oversized = "x" * 25000

        def validator(_: object) -> object:
            raise ValueError(oversized)

        registry = ToolRegistry(
            [
                ToolDefinition(
                    name="sample",
                    description="sample tool",
                    input_schema={},
                    validator=validator,
                    run=lambda parsed, context: ToolResult(ok=True, output="ok"),
                )
            ]
        )

        result = registry.execute("sample", {}, ToolContext(cwd="."))

        self.assertFalse(result.ok)
        self.assertLess(len(result.output), len(f"Validation error in sample: {oversized}"))
        self.assertIn("truncated", result.output.lower())

    def test_execute_truncates_large_runtime_error_output(self) -> None:
        oversized = "x" * 25000

        def run(_: object, __: ToolContext) -> ToolResult:
            raise RuntimeError(oversized)

        registry = ToolRegistry(
            [
                ToolDefinition(
                    name="sample",
                    description="sample tool",
                    input_schema={},
                    validator=lambda data: data,
                    run=run,
                )
            ]
        )

        result = registry.execute("sample", {}, ToolContext(cwd="."))

        self.assertFalse(result.ok)
        self.assertTrue(result.output.startswith("Error running sample:"))
        self.assertLess(len(result.output), len(f"Error running sample: {oversized}"))
        self.assertIn("truncated", result.output.lower())

    def test_execute_reports_protocol_error_when_runner_returns_non_tool_result(self) -> None:
        registry = ToolRegistry(
            [
                ToolDefinition(
                    name="sample",
                    description="sample tool",
                    input_schema={},
                    validator=lambda data: data,
                    run=lambda parsed, context: "not a tool result",
                )
            ]
        )

        result = registry.execute("sample", {}, ToolContext(cwd="."))

        self.assertFalse(result.ok)
        self.assertTrue(result.output.startswith("Error running sample:"))
        self.assertIn("ToolResult", result.output)


if __name__ == "__main__":
    unittest.main()
