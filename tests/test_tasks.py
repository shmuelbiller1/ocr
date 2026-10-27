"""Tests for running slow work without freezing the window."""

from __future__ import annotations

import os
import sys
import unittest

if sys.platform.startswith("linux"):
    # The machine that runs the tests has no screen.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hebrew_workbench.ui.tasks import TaskThread  # noqa: E402
from tests.qt_app import application  # noqa: E402


class TaskThreadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = application()

    def wait_for(self, task: TaskThread) -> None:
        self.assertTrue(task.wait(10000), "the task did not finish")
        self.app.processEvents()

    def test_a_finished_task_reports_its_result(self) -> None:
        results: list = []
        task = TaskThread(lambda progress, cancel: "the result")
        task.succeeded.connect(results.append)
        task.start()
        self.wait_for(task)
        self.assertEqual(results, ["the result"])

    def test_a_task_that_fails_reports_the_reason(self) -> None:
        failures: list[str] = []
        task = TaskThread(lambda progress, cancel: 1 / 0)
        task.failed.connect(failures.append)
        task.start()
        self.wait_for(task)
        self.assertEqual(len(failures), 1)

    def test_a_cancelled_task_is_not_a_failure(self) -> None:
        """A task the user stopped is not an error."""
        cancelled: list[bool] = []
        failures: list[str] = []
        results: list = []

        def work(progress, cancel):
            task.cancel()
            return "the result"

        task = TaskThread(work)
        task.cancelled.connect(lambda: cancelled.append(True))
        task.failed.connect(failures.append)
        task.succeeded.connect(results.append)
        task.start()
        self.wait_for(task)
        self.assertEqual(cancelled, [True])
        self.assertEqual(failures, [])
        self.assertEqual(results, [])

    def test_the_task_says_that_it_was_cancelled(self) -> None:
        task = TaskThread(lambda progress, cancel: None)
        self.assertFalse(task.is_cancelled)
        task.cancel()
        self.assertTrue(task.is_cancelled)


if __name__ == "__main__":
    unittest.main()
