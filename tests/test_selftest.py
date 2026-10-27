"""Tests for the built-in self-test used by the packaging job."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

# The self-test creates a real window.  On a build machine there is no
# display, so the tests ask Qt for its offscreen platform.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hebrew_workbench.selftest import main, run_checks  # noqa: E402


class SelfTestTests(unittest.TestCase):
    def test_every_check_passes(self) -> None:
        results = run_checks()
        failed = [result for result in results if not result.ok]
        self.assertEqual(failed, [], f"failing checks: {[r.name for r in failed]}")

    def test_report_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "selftest.json"
            code = main(report)
            self.assertEqual(code, 0)
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            names = {item["name"] for item in payload["results"]}
            self.assertIn("gui-startup", names)
            self.assertIn("engine-contract", names)


if __name__ == "__main__":
    unittest.main()
