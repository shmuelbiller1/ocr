"""No weights/network needed: explicit profiles, exact raw retention, safe LMs."""
from __future__ import annotations

import dataclasses
import hashlib
import pickle
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from hebrew_workbench.engine.base import EngineFailure, OCRResult
from hebrew_workbench.engine.mishkefet import MishkefetEngine, make_engine
from hebrew_workbench.engine.mishkefet_decoding import (
    DECODING_ARTIFACTS, _load_data, decoding_mode, load_language_models,
)
from hebrew_workbench.project import DocumentEntry


class DecodingTests(unittest.TestCase):
    def test_raw_is_default_and_invalid_modes_are_rejected(self):
        self.assertEqual(MishkefetEngine().mode, "raw")
        self.assertEqual(decoding_mode({}), "raw")
        for mode in ("best", None, 12):
            with self.assertRaises(ValueError):
                MishkefetEngine(mode=mode)

    def test_factory_and_configure_preserve_mode(self):
        engine = make_engine({"decoding_mode": "assisted"})
        self.assertEqual(engine.mode, "assisted")
        engine._recognizer = object()
        engine.configure({"decoding_mode": "beam"})
        self.assertIsNone(engine._recognizer)
        self.assertEqual(engine.mode, "beam")
        with engine._page_lock:
            with self.assertRaises(ValueError):
                engine.configure({"decoding_mode": "raw"})
        self.assertEqual(engine.mode, "beam")

    def test_raw_and_assisted_use_same_crops_but_never_overwrite_raw(self):
        for mode in ("raw", "beam", "assisted"):
            with self.subTest(mode=mode):
                engine = MishkefetEngine(mode=mode)
                recognizer = Mock(beam_width=12)
                original = 'שָׁלוֹם ר״ת\nיידיש'
                def raw(crops, **kwargs):
                    if mode != "raw":
                        self.assertEqual(recognizer.beam_width, 0)
                    return [original], [0.7]
                recognizer.read.side_effect = raw
                recognizer.read_tta.return_value = ["alternative"]
                engine._recognizer = recognizer
                box = types.SimpleNamespace(x=0, y=0, w=10, h=5)
                crops = [object()]
                segment = types.SimpleNamespace(segment_page=lambda image: (crops, [box], 0))
                with patch.dict("sys.modules", {"hebrew_workbench.engine.vendor.hebocr.page.segment": segment}):
                    result = engine._recognize_page_now(1, object())
                self.assertEqual(result.text, original)
                self.assertEqual(result.assisted_text, None if mode == "raw" else "alternative")
                if mode != "raw":
                    recognizer.read_tta.assert_called_once_with(crops)
                    self.assertEqual(recognizer.beam_width, 12)
                else:
                    recognizer.read_tta.assert_not_called()

    def test_assisted_serialization_uses_the_same_blank_line_policy_as_raw(self):
        engine = MishkefetEngine(mode="beam")
        recognizer = Mock(beam_width=12)
        recognizer.read.return_value = ([" raw ", ""], [0.7, 0.0])
        recognizer.read_tta.return_value = [" alternative ", "  "]
        engine._recognizer = recognizer
        box = types.SimpleNamespace(x=0, y=0, w=10, h=5)
        segment = types.SimpleNamespace(segment_page=lambda image: ([1, 2], [box, box], 0))
        with patch.dict("sys.modules", {"hebrew_workbench.engine.vendor.hebocr.page.segment": segment}):
            page = engine._recognize_page_now(1, object())
        self.assertEqual(page.text, "raw")
        self.assertEqual(page.assisted_text, "alternative")

    def test_beam_setting_is_restored_if_raw_reading_fails(self):
        engine = MishkefetEngine(mode="beam")
        recognizer = Mock(beam_width=12)
        recognizer.read.side_effect = RuntimeError("broken")
        engine._recognizer = recognizer
        segment = types.SimpleNamespace(segment_page=lambda image: ([1], [1], 0))
        with patch.dict("sys.modules", {"hebrew_workbench.engine.vendor.hebocr.page.segment": segment}):
            with self.assertRaises(RuntimeError):
                engine._recognize_page_now(1, object())
        self.assertEqual(recognizer.beam_width, 12)

    def test_advanced_options_are_explicit_and_raw_never_loads_language_models(self):
        for mode in ("raw", "beam", "assisted"):
            with self.subTest(mode=mode):
                engine = MishkefetEngine("model.pt", mode=mode)
                factory = Mock()
                module = types.SimpleNamespace(Recognizer=factory)
                with patch.object(engine, "_verify_checkpoint"), patch.dict("sys.modules", {
                    "hebrew_workbench.engine.vendor.hebocr.recognize": module
                }), patch("hebrew_workbench.engine.mishkefet.load_language_models", return_value=("char", "word")) as lms:
                    engine._load_recognizer()
                kwargs = factory.call_args.kwargs
                self.assertEqual(kwargs.get("beam_width", 0), 0 if mode == "raw" else 12)
                self.assertEqual(kwargs.get("tta", 0), 0 if mode == "raw" else 3)
                if mode == "assisted":
                    self.assertEqual(kwargs["lm"], "char")
                    self.assertEqual(kwargs["word_lm"], "word")
                    self.assertEqual(kwargs["word_weight"], 0.2)
                else:
                    lms.assert_not_called()

    def test_missing_language_models_fail_explicitly_without_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(EngineFailure):
                load_language_models(Path(folder))

    def test_older_projects_and_results_remain_raw(self):
        entry = DocumentEntry.from_dict({"path": "page.png"})
        self.assertIsNone(entry.assisted_transcription)
        self.assertEqual(entry.decoding_mode, "raw")
        self.assertIsNone(OCRResult("raw", "engine").assisted_text)

    def test_project_roundtrip_retains_both_outputs_exactly(self):
        entry = DocumentEntry("page.png", transcription="manual edit",
                              original_transcription='ר״ת\nשָׁלוֹם',
                              assisted_transcription="alternative", decoding_mode="assisted")
        self.assertEqual(DocumentEntry.from_dict(entry.to_dict()), entry)

    def test_worker_dispatch_propagates_mode_and_rejects_invalid_mode(self):
        from ocr_worker.main import _engine_of
        self.assertEqual(_engine_of({"engine": "mishkefet", "model_path": "model.pt",
                                    "decoding_mode": "assisted"}).mode, "assisted")
        with self.assertRaises(ValueError):
            _engine_of({"engine": "mishkefet", "model_path": "model.pt", "decoding_mode": "unknown"})

    def test_worker_factory_propagates_profile_to_subprocess_engine(self):
        from hebrew_workbench.engine.worker import WorkerEngine
        engine = WorkerEngine("worker.exe", "model.pt", engine="mishkefet",
                              artifact_id="mishkefet-v1", mode="assisted")
        self.assertEqual(engine.mode, "assisted")
        self.assertIn("assisted", engine.manifest().notes)
        engine.configure({"decoding_mode": "raw"})
        self.assertEqual(engine.mode, "raw")
        with self.assertRaises(ValueError):
            WorkerEngine("worker.exe", "small.safetensors", mode="assisted")


class LanguageModelIntegrityTests(unittest.TestCase):
    def load_fixture(self, data):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        folder = Path(temp.name)
        artifact = DECODING_ARTIFACTS["mishkefet-char-lm"]
        patched = dataclasses.replace(artifact, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        (folder / artifact.filename).write_bytes(data)
        return folder, patched

    def test_only_pinned_bytes_can_be_deserialized(self):
        folder, artifact = self.load_fixture(pickle.dumps({"counts": {"א": 2}}))
        with patch.dict(DECODING_ARTIFACTS, {artifact.id: artifact}):
            self.assertEqual(_load_data(folder, artifact.id), {"counts": {"א": 2}})
            (folder / artifact.filename).write_bytes(b"bad")
            with self.assertRaises(EngineFailure):
                _load_data(folder, artifact.id)

    def test_executable_pickle_globals_are_rejected_even_with_matching_digest(self):
        folder, artifact = self.load_fixture(pickle.dumps(Path("not executable")))
        with patch.dict(DECODING_ARTIFACTS, {artifact.id: artifact}):
            with self.assertRaises(pickle.UnpicklingError):
                _load_data(folder, artifact.id)

    def test_all_downloads_are_pinned_noncommercial_and_revision_specific(self):
        for artifact in DECODING_ARTIFACTS.values():
            self.assertEqual(len(artifact.sha256), 64)
            self.assertNotIn("/main/", artifact.url)
            self.assertEqual(artifact.license, "CC-BY-NC-SA-4.0")
            self.assertGreater(artifact.size_bytes, 0)


class ComparisonToolTests(unittest.TestCase):
    def test_reference_collision_is_rejected_without_overwriting(self):
        import contextlib
        import io
        from tools import compare_mishkefet
        with tempfile.TemporaryDirectory() as folder:
            reference = Path(folder) / "decoding-raw.txt"
            reference.write_bytes(b"independent reference\r\n")
            with patch.object(compare_mishkefet, "MishkefetEngine") as factory, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    compare_mishkefet.main(["--document", "page.pdf", "--model", "model.pt",
                                           "--output", folder, "--transcript", str(reference),
                                           "--verified-by", "reviewer"])
            factory.assert_not_called()
            self.assertEqual(reference.read_bytes(), b"independent reference\r\n")

    def test_comparison_preserves_crlf_exactly_in_reference_and_readings(self):
        import contextlib
        import io
        import json
        from tools import compare_mishkefet
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            text = "first\r\nsecond\r\n"
            reference = root / "reference.txt"
            reference.write_bytes(text.encode("utf-8"))
            factory = Mock()
            factory.return_value.recognize.side_effect = [
                OCRResult(text, "engine"), OCRResult(text, "engine", assisted_text=text)]
            with patch.object(compare_mishkefet, "MishkefetEngine", factory), contextlib.redirect_stdout(io.StringIO()):
                status = compare_mishkefet.main(["--document", "page.pdf", "--model", "model.pt",
                    "--output", str(root / "out"), "--transcript", str(reference), "--verified-by", "reviewer"])
            self.assertEqual(status, 0)
            self.assertEqual((root / "out" / "decoding-assisted.txt").read_bytes(), text.encode("utf-8"))
            report = json.loads((root / "out" / "decoding-comparison.json").read_text())
            self.assertEqual(report["readings"]["assisted"]["cer"], 0)
            self.assertEqual(report["readings"]["raw"]["cer"], 0)

    def test_unverified_report_has_no_scores_and_keeps_outputs_separate(self):
        import contextlib
        import io
        import json
        from tools import compare_mishkefet
        with tempfile.TemporaryDirectory() as folder:
            raw = OCRResult("raw", "engine", duration_seconds=1)
            compared = OCRResult("raw", "engine", duration_seconds=5,
                                 assisted_text="alternative", decoding_mode="assisted")
            factory = Mock()
            factory.return_value.recognize.side_effect = [raw, compared]
            with patch.object(compare_mishkefet, "MishkefetEngine", factory), contextlib.redirect_stdout(io.StringIO()):
                status = compare_mishkefet.main(["--document", "page.pdf", "--model", "model.pt", "--output", folder])
            self.assertEqual(status, 0)
            report = json.loads((Path(folder) / "decoding-comparison.json").read_text())
            self.assertEqual(report["accuracy"], "unverified")
            self.assertNotIn("cer", report["readings"]["assisted"])
            self.assertEqual((Path(folder) / "decoding-raw.txt").read_text(), "raw")
            self.assertEqual((Path(folder) / "decoding-assisted.txt").read_text(), "alternative")


if __name__ == "__main__":
    unittest.main()
