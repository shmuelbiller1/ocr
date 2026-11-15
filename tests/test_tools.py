"""Every tool of the repository has to start."""

from __future__ import annotations

import subprocess
import sys
import tempfile
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


class ThePinsOfTheBuildTests(unittest.TestCase):
    """The versions the build installs are the versions the program asks for.

    The two jobs that install the dependencies name every package with
    its version, so that the version is pinned where the command is read
    and no file has to be opened to know what is installed.  That is a
    second place where the pins are written, and a pin that is changed
    in ``requirements.txt`` alone would be measured in one job and
    packaged in the other.  This test keeps the two together.
    """

    def _installed(self) -> list[list[str]]:
        """The pinned packages of every "Install dependencies" step.

        ``pip`` itself is not a dependency of the program, and it is not
        compared.
        """
        import re

        workflow = (
            REPO_ROOT / ".github" / "workflows" / "windows.yml"
        ).read_text(encoding="utf-8")
        steps: list[list[str]] = []
        for step in re.split(r"\n      - name: ", workflow):
            if not step.startswith("Install dependencies\n"):
                continue
            pins = re.findall(r'"([A-Za-z0-9][A-Za-z0-9._-]*==[0-9][^"]*)"', step)
            steps.append(sorted(p for p in pins if not p.startswith("pip==")))
        return steps

    def test_the_build_installs_the_versions_of_requirements(self) -> None:
        requirements = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
        wanted = sorted(
            line.strip()
            for line in requirements.splitlines()
            if line.strip() and not line.startswith("#")
        )
        installed = self._installed()
        self.assertTrue(installed, "no 'Install dependencies' step was found")
        for pins in installed:
            self.assertEqual(
                pins,
                wanted,
                "the workflow and requirements.txt have drifted apart",
            )

    def test_the_line_that_cannot_be_wheel_only_is_not(self) -> None:
        """kraken asks for a package that has no wheel for Windows.

        kraken asks for ``coremltools~=9.0``, and that package publishes
        wheels for macOS and Linux only.  A wheel-only install of kraken
        therefore has nothing to install on Windows, and the build of the
        worker stopped with no kraken at all.  That one line builds the
        package from the source archive that was published for it; every
        other line of the build stays wheel-only.  This test is here so
        that nobody puts the flag back without reading why it is not
        there.
        """
        workflow = (REPO_ROOT / ".github" / "workflows" / "windows.yml").read_text(
            encoding="utf-8"
        )
        lines = [
            line
            for line in workflow.splitlines()
            if "kraken==" in line and "pip install" in line
        ]
        self.assertTrue(lines, "kraken is not installed by the build any more")
        for line in lines:
            self.assertNotIn(
                "--only-binary :all:",
                line,
                "kraken asks for coremltools, and coremltools has no wheel "
                "for Windows: this line has to be allowed to build it",
            )
        # And the reason is written where the line is read.
        self.assertIn("coremltools", workflow)
        self.assertIn("wheel-only", workflow)


class TheReportAndTheCorpusAgreeTests(unittest.TestCase):
    """A folder that was typed is the folder the report was written from.

    The report of the accuracy names its pages against the folder it was
    given, resolved; the tool that reads the report names them against
    the folder it was given.  When one of the two resolved the folder
    and the other did not, the two names did not meet and the build
    stopped.  Both resolve now, and this is the run that failed.
    """

    def test_the_corpus_of_the_report_may_be_typed_as_it_comes(self) -> None:
        import json
        import os
        import subprocess

        corpus = REPO_ROOT / "benchmark" / "modern_cursive"
        manifest = json.loads((corpus / "corpus.json").read_text(encoding="utf-8"))
        page = next(
            row
            for row in manifest["pages"]
            if (corpus / row["transcript"]).is_file()
        )
        ground_truth = (corpus / page["transcript"]).read_text(encoding="utf-8")
        # The report is what ``benchmark_ocr.py`` writes: the pages are
        # named against the resolved folder, because that is the folder
        # the report was measured from.
        report = {
            "engines": [
                {
                    "model": "mishkefet-v1",
                    "results": [
                        {
                            "page": (corpus / page["image"])
                            .resolve()
                            .relative_to(corpus.resolve())
                            .as_posix(),
                            "hypothesis_text": "שלום",
                            "reference_sample": ground_truth[:40],
                        }
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as folder:
            report_path = Path(folder) / "ocr-accuracy.json"
            report_path.write_text(
                json.dumps(report, ensure_ascii=False), encoding="utf-8"
            )
            output = Path(folder) / "suggestions.json"
            # The folder is handed over as it is typed, next to nothing
            # resolved, from the folder of the repository - the way the
            # build hands it over.
            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "tools" / "benchmark_suggestions.py"),
                    "--ocr-report",
                    str(report_path),
                    "--corpus",
                    os.path.join("benchmark", "modern_cursive"),
                    "--output",
                    str(output),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=300,
            )
            self.assertEqual(
                result.returncode,
                0,
                f"the tool stopped: {result.stderr[-500:]}",
            )
            written = json.loads(output.read_text(encoding="utf-8"))
            # A case was built from the report, so the two names met.
            self.assertGreaterEqual(
                written["post_ocr"]["spelling_and_grammar"]["cases"], 1
            )


if __name__ == "__main__":
    unittest.main()
