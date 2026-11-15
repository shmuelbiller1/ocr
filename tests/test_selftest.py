"""Tests for the built-in self-test used by the packaging job."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# The self-test creates a real window.  On a build machine there is no
# display, so the tests ask Qt for its offscreen platform.
if sys.platform.startswith("linux"):
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
            self.assertIn("document-output", names)

    def test_the_report_is_written_where_the_one_click_program_asks(self) -> None:
        """The one-click program starts the application in another folder.

        The launcher unpacks the application into a folder of its own and
        starts it with *that* folder as the working folder, while the
        build asks for the report in the folder of the build.  When the
        report was confined to the folders of the program, it was refused
        there, nothing was written, and the one-click program stopped
        without saying a word.  The report is a place the person - or the
        build - pointed at, so it is written there.
        """
        from unittest.mock import patch

        from hebrew_workbench import selftest

        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "one-click-lite-selftest.json"
            # The folders of the program are somewhere else entirely,
            # which is what they are for the unpacked application.
            with patch(
                "hebrew_workbench.safe_paths.default_bases",
                return_value=[str(Path(folder) / "somewhere-else")],
            ):
                written = selftest._write_report(report, {"ok": True})
            self.assertTrue(written, "the report was refused")
            self.assertTrue(report.is_file(), "the report was not written")
            self.assertEqual(json.loads(report.read_text(encoding="utf-8")), {"ok": True})


if __name__ == "__main__":
    unittest.main()
