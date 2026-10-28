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


if __name__ == "__main__":
    unittest.main()
