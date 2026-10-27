"""The check of the engine says clearly what is wrong."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "check_engine.py"


class CheckEngineTests(unittest.TestCase):
    def run_script(self, folder: Path) -> subprocess.CompletedProcess:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(folder)
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True,
            text=True,
            env=environment,
            cwd=str(REPO_ROOT),
        )

    def test_a_pair_that_does_not_work_is_reported(self) -> None:
        """The failure of torchvision while it is imported is reported."""
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            (folder / "torch.py").write_text(
                '__version__ = "2.14.0"\n'
                "class _Ops:\n"
                "    class torchvision:\n"
                "        nms = None\n"
                "ops = _Ops()\n",
                encoding="utf-8",
            )
            (folder / "torchvision.py").write_text(
                'raise RuntimeError("operator torchvision::nms does not exist")\n',
                encoding="utf-8",
            )
            result = self.run_script(folder)

        self.assertEqual(result.returncode, 1)
        self.assertIn("torchvision::nms", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_a_pair_that_works_is_reported(self) -> None:
        """A working pair is said so."""
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            (folder / "torch.py").write_text(
                '__version__ = "2.14.0"\n'
                "class _Ops:\n"
                "    class torchvision:\n"
                "        nms = None\n"
                "ops = _Ops()\n",
                encoding="utf-8",
            )
            (folder / "torchvision.py").write_text(
                '__version__ = "0.29.0"\n', encoding="utf-8"
            )
            result = self.run_script(folder)

        self.assertEqual(result.returncode, 0)
        self.assertIn("torch 2.14.0", result.stdout)
        self.assertIn("torchvision 0.29.0", result.stdout)
        self.assertIn("the operations of torchvision work", result.stdout)


if __name__ == "__main__":
    unittest.main()
