"""Tests for the engine registry and the worker protocol."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from hebrew_workbench.engine.base import (
    EngineManifest,
    EngineUnavailable,
    OCRResult,
)
from hebrew_workbench.engine.registry import EngineRegistry
from hebrew_workbench.engine.worker import WorkerEngine

STUB_WORKER = '''\
import json, sys
args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
job = json.loads(open(args["--job"], encoding="utf-8").read())
payload = {
    "text": "שלום עולם",
    "engine_name": "stub worker",
    "duration_seconds": 0.1,
    "pages": [{"number": 1, "text": "שלום עולם", "lines": [{"text": "שלום עולם", "confidence": 0.9}]}],
}
json.dump(payload, open(args["--result"], "w", encoding="utf-8"))
'''

FAILING_WORKER = '''\
import sys
sys.stderr.write("the model file is missing\\n")
sys.exit(3)
'''

# A worker that reports what went wrong in its result file, the way the
# real worker does.
FAILING_WORKER_WITH_REPORT = '''\
import json, sys
args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
json.dump(
    {"error": "the model file is missing", "traceback": "..."},
    open(args["--result"], "w", encoding="utf-8"),
)
sys.exit(1)
'''


def write_stub(folder: Path, name: str, source: str) -> Path:
    """Write a stub worker that can be started like the real one."""
    script = folder / f"{name}.py"
    script.write_text(source, encoding="utf-8")
    if os.name == "nt":
        launcher = folder / f"{name}.bat"
        launcher.write_text(
            f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8"
        )
    else:
        launcher = folder / name
        launcher.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8"
        )
        launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
    return launcher


class RegistryTests(unittest.TestCase):
    def test_the_default_engine_fails_closed(self) -> None:
        registry = EngineRegistry()
        self.assertFalse(registry.available())
        self.assertIsNone(registry.manifest())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "page.png"
            path.write_bytes(b"x")
            with self.assertRaises(EngineUnavailable):
                registry.transcribe(path)

    def test_the_status_mentions_the_license_of_the_engine(self) -> None:
        class Fake:
            name = "fake engine"

            def available(self) -> bool:
                return True

            def manifest(self) -> EngineManifest:
                return EngineManifest(
                    id="fake",
                    name="fake engine",
                    version="1.0",
                    script="Hebrew",
                    license="Apache-2.0",
                    license_url="https://example.invalid/",
                )

            def recognize(self, file_path: Path) -> OCRResult:
                return OCRResult("שלום", self.name)

        registry = EngineRegistry(Fake())
        self.assertTrue(registry.available())
        status = registry.status()
        self.assertIn("Apache-2.0", status)
        self.assertIn("Hebrew", status)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "page.png"
            path.write_bytes(b"x")
            self.assertEqual(registry.transcribe(path).text, "שלום")

    def test_a_broken_engine_raises_an_engine_error(self) -> None:
        from hebrew_workbench.engine.base import EngineError

        class Broken:
            name = "broken engine"

            def available(self) -> bool:
                return True

            def recognize(self, file_path: Path) -> OCRResult:
                raise RuntimeError("the model is corrupt")

        registry = EngineRegistry(Broken())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "page.png"
            path.write_bytes(b"x")
            with self.assertRaises(EngineError):
                registry.transcribe(path)


class WorkerTests(unittest.TestCase):
    def test_the_worker_result_is_read_back(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            worker = write_stub(root, "stub-worker", STUB_WORKER)
            model = root / "small.safetensors"
            model.write_bytes(b"weights")
            document = root / "page.png"
            document.write_bytes(b"image")

            engine = WorkerEngine(worker, model)
            self.assertTrue(engine.available())
            result = engine.recognize(document)
            self.assertEqual(result.text, "שלום עולם")
            self.assertEqual(result.pages[0].number, 1)
            self.assertEqual(result.pages[0].lines[0].text, "שלום עולם")

    def test_a_failing_worker_reports_the_reason(self) -> None:
        from hebrew_workbench.engine.base import EngineFailure

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            worker = write_stub(root, "failing-worker", FAILING_WORKER)
            model = root / "small.safetensors"
            model.write_bytes(b"weights")
            document = root / "page.png"
            document.write_bytes(b"image")

            engine = WorkerEngine(worker, model)
            with self.assertRaises(EngineFailure) as caught:
                engine.recognize(document)
            self.assertIn("model file is missing", str(caught.exception))

    def test_the_message_of_the_worker_is_used(self) -> None:
        """The worker says what went wrong; the client says it too."""
        from hebrew_workbench.engine.base import EngineFailure

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            worker = write_stub(root, "reporting-worker", FAILING_WORKER_WITH_REPORT)
            model = root / "small.safetensors"
            model.write_bytes(b"weights")
            document = root / "page.png"
            document.write_bytes(b"image")

            engine = WorkerEngine(worker, model)
            with self.assertRaises(EngineFailure) as caught:
                engine.recognize(document)
            self.assertIn("the model file is missing", str(caught.exception))

    def test_the_callbacks_are_given_to_an_engine_that_wants_them(self) -> None:
        """The user can stop the work and sees what it is doing."""
        seen: dict = {}

        class Engine:
            name = "engine with callbacks"

            def available(self) -> bool:
                return True

            def recognize(self, path, progress=None, cancel=None):
                seen["progress"] = progress
                seen["cancel"] = cancel
                return OCRResult("שלום", self.name)

        messages: list[str] = []
        registry = EngineRegistry(Engine())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "page.png"
            path.write_bytes(b"image")
            registry.transcribe(path, progress=messages.append, cancel=lambda: False)
        self.assertIsNotNone(seen.get("progress"))
        self.assertIsNotNone(seen.get("cancel"))

    def test_an_engine_without_the_callbacks_still_works(self) -> None:
        """An adapter of the first version of the contract keeps working."""

        class OldEngine:
            name = "old adapter"

            def available(self) -> bool:
                return True

            def recognize(self, path) -> OCRResult:
                return OCRResult("שלום", self.name)

        registry = EngineRegistry(OldEngine())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "page.png"
            path.write_bytes(b"image")
            result = registry.transcribe(path, progress=lambda message: None)
        self.assertEqual(result.text, "שלום")

    def test_a_missing_worker_is_not_available(self) -> None:
        engine = WorkerEngine("does-not-exist.exe", "does-not-exist.safetensors")
        self.assertFalse(engine.available())
        with self.assertRaises(EngineUnavailable):
            engine.recognize("does-not-exist.png")


class WorkerManifestTests(unittest.TestCase):
    """The manifest of the worker names the model that it uses."""

    def test_mismatched_worker_engine_and_artifact_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "do not match"):
            WorkerEngine("worker.exe", "small.safetensors", engine="mishkefet")
        with self.assertRaisesRegex(ValueError, "do not match"):
            WorkerEngine("worker.exe", "model.pt", artifact_id="mishkefet-v1")

    def test_the_model_of_the_manifest_is_the_model_that_was_chosen(self) -> None:
        engine = WorkerEngine(
            "does-not-exist.exe",
            "does-not-exist.safetensors",
            artifact_id="kraken-ppocrv6-medium",
        )
        manifest = engine.manifest()
        self.assertEqual(manifest.model_id, "kraken-ppocrv6-medium")


if __name__ == "__main__":
    unittest.main()
