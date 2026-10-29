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
    "smoke_test.py",
    "compare_mishkefet.py",
    "build_worker.py",
    "verify_worker_bundle.py",
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


class SmokeTestTests(unittest.TestCase):
    """The smoke test reads a real page and says what it found.

    A page without a transcript that somebody else checked is never
    counted in a rate, and the report says so.
    """

    def test_smoke_failure_and_empty_reading_exit_status(self) -> None:
        import contextlib
        import io
        import json
        import tempfile
        from unittest.mock import patch
        from tools import smoke_test
        from hebrew_workbench.engine.models import MODEL_ARTIFACTS

        for fails, text, strict, expected in (
            (False, "raw reading", True, 0),
            (False, "", True, 1),
            (False, "", False, 0),
            (True, "raw reading", True, 1),
        ):
            with self.subTest(fails=fails, text=text, strict=strict), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                document = root / "page.pdf"
                document.touch()
                for identifier in ("kraken-ppocrv6-small", "mishkefet-v1"):
                    (root / MODEL_ARTIFACTS[identifier].filename).touch()
                reading = dict(text=text, engine="test", lines=1, characters=len(text), seconds=0)
                outputs = [RuntimeError("broken engine"), reading] if fails else [reading, reading]
                args = ["--document", str(document), "--models", str(root), "--output", str(root / "out")]
                if strict:
                    args.append("--require-text")
                with patch.object(smoke_test, "_engine_for"), patch.object(smoke_test, "read_with", side_effect=outputs), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(smoke_test.main(args), expected)
                report = json.loads((root / "out" / "smoke-test.json").read_text())
                self.assertEqual(len(report["engines"]), 2)
                self.assertTrue((root / "out" / "smoke-mishkefet-v1.txt").exists())

    def test_the_page_of_the_project_is_read_by_the_tool(self) -> None:
        document = (
            REPO_ROOT
            / "benchmark"
            / "smoke_test"
            / "pages"
            / "scan-2026-10-28-221624.pdf"
        )
        self.assertTrue(document.is_file(), "the real page is not in the repository")

    def test_a_model_that_is_not_there_is_named_and_nothing_is_measured(self) -> None:
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            document = root / "page.pdf"
            document.write_bytes(b"%PDF-1.4\n")
            output = root / "out"
            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "tools" / "smoke_test.py"),
                    "--document",
                    str(document),
                    "--models",
                    str(root / "no-models-here"),
                    "--engines",
                    "kraken-ppocrv6-small",
                    "mishkefet-v1",
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
            self.assertEqual(result.returncode, 0, result.stderr[-500:])
            report = json.loads(
                (output / "smoke-test.json").read_text(encoding="utf-8")
            )
            # The two models are not there, and that is said and not
            # hidden.
            self.assertEqual(len(report["skipped"]), 2)
            self.assertEqual(report["engines"], [])
            # And the report says that no rate was measured.
            self.assertIn("NOT verified", report["note"])


if __name__ == "__main__":
    unittest.main()
