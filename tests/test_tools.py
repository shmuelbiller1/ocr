"""Every tool of the repository has to start."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS = (
    "benchmark_ocr.py",
    "build_benchmark.py",
    "write_accuracy_results.py",
    "accuracy_notice.py",
    "inspect_dataset.py",
    "build_release.py",
    "download_model.py",
    "publish_diagnostics.py",
)


class ToolTests(unittest.TestCase):
    def test_every_tool_starts_and_asks_for_help(self) -> None:
        for name in TOOLS:
            with self.subTest(tool=name):
                result = subprocess.run(
                    [sys.executable, str(REPO_ROOT / "tools" / name), "--help"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    f"{name} does not start: {result.stderr[-500:]}",
                )


if __name__ == "__main__":
    unittest.main()
