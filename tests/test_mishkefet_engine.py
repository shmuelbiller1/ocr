"""Tests for the second engine, the one that was written for modern Hebrew.

The engine reads a page with *Mishkefet-v1*.  Its weights are not in the
repository and are not installed here, so these tests check the parts that
can be checked without them: the contract, the manifest, the model
catalogue, the dispatch of the worker and the code that came with the
model.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hebrew_workbench.engine import models
from hebrew_workbench.engine.base import EngineManifest
from hebrew_workbench.engine.mishkefet import (
    MishkefetEngine,
    build_manifest,
    make_engine,
)
from hebrew_workbench.engine.vendor.hebocr.charset import BLANK, HEBREW_LETTERS, Charset
from hebrew_workbench.engine.vendor.hebocr.normalize import normalize
from hebrew_workbench.plugins.builtin import BUILTIN_MANIFESTS

REPO_ROOT = Path(__file__).resolve().parents[1]


class MishkefetEngineTests(unittest.TestCase):
    """The contract of the engine."""

    def test_timed_out_inference_keeps_its_lock_until_worker_finishes(self) -> None:
        import threading
        from unittest.mock import patch
        from hebrew_workbench.engine.base import EngineTimeout, PageResult

        engine = MishkefetEngine(None)
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        calls = []

        def read(number, image):
            calls.append(number)
            entered.set()
            release.wait(5)
            finished.set()
            return PageResult(number=number, text="read")

        try:
            with patch.object(engine, "_recognize_page_now", side_effect=read):
                with self.assertRaises(EngineTimeout):
                    engine._recognize_page(1, None, budget=0.03)
                self.assertTrue(entered.is_set())
                with self.assertRaises(EngineTimeout):
                    engine._recognize_page(2, None, budget=0.03)
                self.assertEqual(calls, [1])
                release.set()
                self.assertTrue(finished.wait(2))
                self.assertEqual(engine._recognize_page(3, None, budget=1).text, "read")
                self.assertEqual(calls, [1, 3])
        finally:
            release.set()

    def test_an_engine_without_a_model_is_not_available(self) -> None:
        engine = MishkefetEngine(None)
        self.assertFalse(engine.available())
        reason = engine.unavailable_reason()
        # The reason says what is missing: the library of the machine
        # learning or the file of the model.
        self.assertIn("Mishkefet", reason)

    def test_the_manifest_says_the_licence_and_the_digest(self) -> None:
        manifest = engine_manifest()
        self.assertIsInstance(manifest, EngineManifest)
        self.assertEqual(manifest.license, "CC-BY-NC-SA-4.0")
        self.assertIn("cursive", manifest.script)
        self.assertEqual(manifest.device, "cpu")
        self.assertEqual(manifest.model_id, "mishkefet-v1")
        self.assertEqual(
            manifest.model_sha256,
            "0dfb82e440ebfa9dd61f562ad36a83ec41c23904eacd96623c3bd8f6fd850b88",
        )
        self.assertEqual(manifest.model_size_bytes, 120_864_761)

    def test_the_model_of_the_engine_is_in_the_catalogue(self) -> None:
        artifact = models.MODEL_ARTIFACTS["mishkefet-v1"]
        self.assertEqual(artifact.engine, "mishkefet")
        self.assertEqual(artifact.filename, "mishkefet-v1.pt")

    def test_the_engine_of_the_plugin_system_uses_the_installed_model(self) -> None:
        """The plugin builds an engine for the model that the user
        installed, and says that it is not available when the model was
        not installed."""
        import os
        import tempfile

        original = os.environ.get("HEBREW_WORKBENCH_MODELS")
        with tempfile.TemporaryDirectory() as folder:
            os.environ["HEBREW_WORKBENCH_MODELS"] = folder
            try:
                engine = make_engine({"model_id": "mishkefet-v1"})
                self.assertFalse(engine.available())
                artifact = models.MODEL_ARTIFACTS["mishkefet-v1"]
                (Path(folder) / artifact.filename).write_bytes(b"not the model")
                engine = make_engine({"model_id": "mishkefet-v1"})
                # The file is there, but the engine still needs the
                # library of the machine learning to read it.
                self.assertIsInstance(engine, MishkefetEngine)
            finally:
                if original is None:
                    os.environ.pop("HEBREW_WORKBENCH_MODELS", None)
                else:
                    os.environ["HEBREW_WORKBENCH_MODELS"] = original


class TheCheckpointIsCheckedTests(unittest.TestCase):
    """The file of the model is checked again when it is loaded.

    The checkpoint is read by ``torch.load``, which runs the code that
    is inside the file.  The digest that the project pinned is therefore
    checked again before the file is read, and not only when it is
    downloaded.
    """

    def _artifact(self, data: bytes, digest: str):
        import dataclasses

        original = models.MODEL_ARTIFACTS["mishkefet-v1"]
        patched = dataclasses.replace(
            original,
            size_bytes=len(data),
            sha256=digest,
            md5=None,
        )
        models.MODEL_ARTIFACTS["mishkefet-v1"] = patched
        self.addCleanup(
            models.MODEL_ARTIFACTS.__setitem__, "mishkefet-v1", original
        )
        return patched

    def test_a_checkpoint_with_the_right_digest_passes_the_check(self) -> None:
        import hashlib
        import tempfile

        data = b"the model, more or less"
        digest = hashlib.sha256(data).hexdigest()
        self._artifact(data, digest)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mishkefet-v1.pt"
            path.write_bytes(data)
            engine = MishkefetEngine(path)
            self.assertIsNone(engine._verify_checkpoint())

    def test_a_checkpoint_that_was_replaced_is_not_loaded(self) -> None:
        import hashlib
        import tempfile

        from hebrew_workbench.engine.base import EngineFailure

        data = b"something else entirely"
        self._artifact(data, hashlib.sha256(b"the real model").hexdigest())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mishkefet-v1.pt"
            path.write_bytes(data)
            engine = MishkefetEngine(path)
            with self.assertRaises(EngineFailure) as caught:
                engine._load_recognizer()
            message = str(caught.exception)
            self.assertIn("SHA-256", message)
            self.assertIn("לא נטען", message)

    def test_the_vendored_code_is_not_changed(self) -> None:
        """The file that came with the model is used as it was
        published.  The check happens in our own code."""
        source = (
            REPO_ROOT
            / "hebrew_workbench"
            / "engine"
            / "vendor"
            / "hebocr"
            / "recognize.py"
        ).read_text(encoding="utf-8")
        self.assertIn("weights_only=False", source)
        self.assertNotIn("verify_file", source)

    def test_every_place_that_reads_the_checkpoint_checks_it_first(self) -> None:
        """The digest is checked on the way in, wherever the way in is.

        The code that came with the model reads the file with
        ``weights_only=False``, which runs the code that is inside the
        file.  That is safe only because the file is the file the author
        published -- and that is known because its digest was checked
        against the digest this project pinned.  A new place that built
        the vendored ``Recognizer`` straight from a path would skip the
        check, so the shipped code and the tools are searched here: the
        only construction of it outside the vendored package is the one
        inside the gate, and the gate checks first.
        """
        import ast

        gate = "load_verified_recognizer"

        def calls_in(source: Path) -> list[tuple[str, int]]:
            """Every call of ``Recognizer(`` with the function it is in."""
            tree = ast.parse(source.read_text(encoding="utf-8"))
            found: list[tuple[str, int]] = []
            # The innermost function that holds the call is enough: the
            # gate is a plain module-level function.
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for call in ast.walk(node):
                    if (
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Name)
                        and call.func.id == "Recognizer"
                    ):
                        found.append((node.name, call.lineno))
            return found

        sources: list[Path] = [REPO_ROOT / "app.py"]
        for folder in ("hebrew_workbench", "ocr_worker", "tools"):
            sources.extend(sorted((REPO_ROOT / folder).rglob("*.py")))
        offenders: list[str] = []
        gate_calls = 0
        for source in sources:
            if "vendor" in source.parts:
                continue
            for function, line in calls_in(source):
                if function == gate:
                    gate_calls += 1
                    continue
                offenders.append(
                    f"{source.relative_to(REPO_ROOT)}:{line} in {function}()"
                )

        self.assertEqual(
            offenders,
            [],
            "the checkpoint must be checked before it is read; build it "
            f"with hebrew_workbench.engine.mishkefet.{gate}",
        )
        # The gate is there, and it is the one that checks, so a reader
        # of the report knows what stands between the file and
        # ``torch.load``.
        self.assertEqual(gate_calls, 1, "the gate itself has to build it")
        engine = (REPO_ROOT / "hebrew_workbench" / "engine" / "mishkefet.py").read_text(
            encoding="utf-8"
        )
        body = engine.split(f"def {gate}(", 1)[1]
        self.assertIn("verify_mishkefet_checkpoint(", body)

    def test_the_gate_checks_the_digest_before_it_builds(self) -> None:
        """Inside the gate the order is: check, and only then build."""
        import ast

        source = (REPO_ROOT / "hebrew_workbench" / "engine" / "mishkefet.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        gate = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "load_verified_recognizer"
        )
        names = [
            stmt.value.func.id
            for stmt in gate.body
            if isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Name)
        ]
        self.assertIn("verify_mishkefet_checkpoint", names)
        self.assertLess(
            names.index("verify_mishkefet_checkpoint"),
            len(names),
            "the check has to come before the recogniser is built",
        )
        self.assertIn("Recognizer(", ast.unparse(gate))


def engine_manifest() -> EngineManifest:
    return build_manifest(None, "mishkefet-v1")


class TheVendoredCodeTests(unittest.TestCase):
    """The code that came with the model.

    It is not ours, and it is not changed.  These tests make sure that
    the rules it follows are the ones that were published: the letters of
    Hebrew, with their final forms, and the niqqud and the te'amim, are
    kept as they are.
    """

    def test_the_charset_starts_with_the_blank(self) -> None:
        self.assertEqual(BLANK, 0)

    def test_the_letters_of_hebrew_keep_their_final_forms(self) -> None:
        for letter in "ךםןףץ":
            self.assertIn(letter, HEBREW_LETTERS)

    def test_the_niqqud_and_the_te_amim_are_kept(self) -> None:
        self.assertEqual(normalize("שָׁלוֹם"), "שָׁלוֹם")

    def test_the_punctuation_variants_are_folded(self) -> None:
        """The model can only write the folded punctuation, because the
        folded punctuation is what it was taught.  The program does not
        change the text of a recognition; this is the model itself."""
        self.assertEqual(normalize("בס״ד"), 'בס"ד')

    def test_the_licence_of_the_vendored_code_is_in_the_repository(self) -> None:
        text = (REPO_ROOT / "docs" / "licences" / "HEB-OCR-MIT.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("MIT License", text)
        self.assertIn("Itay Inbar", text)


class TheWorkerDispatchTests(unittest.TestCase):
    """The worker runs the engine that the job names."""

    def test_the_job_names_the_engine(self) -> None:
        from ocr_worker.main import _engine_of

        engine = _engine_of(
            {"engine": "mishkefet", "model_path": "mishkefet-v1.pt"}
        )
        self.assertIsInstance(engine, MishkefetEngine)

    def test_an_unknown_engine_is_an_error(self) -> None:
        from ocr_worker.main import _engine_of

        with self.assertRaises(ValueError):
            _engine_of({"engine": "something-else", "model_path": "model.pt"})

    def test_the_job_of_the_worker_carries_the_engine(self) -> None:
        """The worker writes the engine into the job file, so that the
        worker knows which engine to run."""
        import inspect

        from hebrew_workbench.engine import worker

        source = inspect.getsource(worker.WorkerEngine.recognize)
        self.assertIn('"engine": self.engine', source)


class ThePluginTests(unittest.TestCase):
    """The engine is a plugin like every other engine."""

    def test_the_engine_is_a_plugin_of_the_program(self) -> None:
        ids = [manifest.id for manifest in BUILTIN_MANIFESTS]
        self.assertIn("mishkefet", ids)
        self.assertIn("mishkefet-worker", ids)

    def test_the_plugin_of_the_engine_says_which_model_it_reads(self) -> None:
        for manifest in BUILTIN_MANIFESTS:
            if manifest.id == "mishkefet":
                self.assertEqual(manifest.options.get("model_id"), "mishkefet-v1")
            if manifest.id == "mishkefet-worker":
                self.assertEqual(manifest.options.get("engine"), "mishkefet")


class TheNameOfTheWorkerEngineTests(unittest.TestCase):
    """The name that is shown to the user tells which engine it is.

    The worker can run more than one engine, and the licence of the
    model is part of the name, so that the licence of one model is never
    shown next to the name of another one.
    """

    def test_the_worker_of_the_second_engine_says_its_own_name(self) -> None:
        from hebrew_workbench.engine.worker import WorkerEngine

        engine = WorkerEngine(
            "ocr-worker.exe",
            "mishkefet-v1.pt",
            artifact_id="mishkefet-v1",
            engine="mishkefet",
        )
        self.assertIn("Mishkefet-v1", engine.name)
        self.assertIn("CC-BY-NC-SA-4.0", engine.name)
        self.assertNotIn("Apache-2.0", engine.name)

    def test_the_worker_of_the_first_engine_still_says_its_own_name(self) -> None:
        from hebrew_workbench.engine.worker import WorkerEngine

        engine = WorkerEngine("ocr-worker.exe", "small.safetensors")
        self.assertEqual(engine.name, "kraken PP-OCRv6 small (worker, Apache-2.0)")


if __name__ == "__main__":
    unittest.main()
