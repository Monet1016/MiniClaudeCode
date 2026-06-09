import unittest
from unittest.mock import patch

import background_tasks as background_tasks_module


class BackgroundTaskRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        background_tasks_module._background_tasks.clear()
        background_tasks_module._announced_terminal_states.clear()

    def tearDown(self) -> None:
        background_tasks_module._background_tasks.clear()
        background_tasks_module._announced_terminal_states.clear()

    def test_register_background_task_returns_running_record(self) -> None:
        result = background_tasks_module.register_background_task(
            command="python test.py",
            cwd="D:/workspace",
            pid=4321,
        )

        self.assertTrue(result.task_id.startswith("task_"))
        self.assertEqual("python test.py", result.command)
        self.assertEqual("D:/workspace", result.cwd)
        self.assertEqual(4321, result.pid)
        self.assertEqual("running", result.status)

    def test_collect_background_notifications_emits_completed_task_once(self) -> None:
        result = background_tasks_module.register_background_task(
            command="python test.py",
            cwd="D:/workspace",
            pid=4321,
        )

        with patch.object(background_tasks_module, "_is_process_alive", return_value=False):
            first = background_tasks_module.collect_background_notifications()
            second = background_tasks_module.collect_background_notifications()

        self.assertEqual(1, len(first))
        self.assertIn(result.task_id, first[0])
        self.assertIn("<status>completed</status>", first[0])
        self.assertIn("<command>python test.py</command>", first[0])
        self.assertIn("<summary>Process exited.</summary>", first[0])
        self.assertEqual([], second)


if __name__ == "__main__":
    unittest.main()
