"""Tests for the replaceable OCR engine contract."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hebrew_workbench.engine.base import EngineUnavailable, OCRResult
from hebrew_workbench.engine.registry import EngineRegistry


class EngineContractTests(unittest.TestCase):
    def test_disabled_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "example.png"
            path.write_bytes(b"sample")
            with self.assertRaises(EngineUnavailable):
                EngineRegistry().transcribe(path)

    def test_replaceable_engine(self) -> None:
        class ExampleAdapter:
            name = "Test adapter"

            def available(self) -> bool:
                return True

            def recognize(self, file_path: Path) -> OCRResult:
                return OCRResult("שלום", self.name)

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "example.png"
            path.write_bytes(b"sample")
            result = EngineRegistry(ExampleAdapter()).transcribe(path)
            self.assertEqual(result.text, "שלום")
            self.assertEqual(result.engine_name, "Test adapter")

    def test_missing_file_not_processed(self) -> None:
        with self.assertRaises(FileNotFoundError):
            EngineRegistry().transcribe("this-file-does-not-exist.jpg")

    def test_disabled_engine_never_returns_text(self) -> None:
        """A disabled engine must raise instead of returning anything."""
        from hebrew_workbench.engine.registry import DisabledEngine

        engine = DisabledEngine()
        self.assertFalse(engine.available())
        with self.assertRaises(EngineUnavailable):
            engine.recognize(Path("whatever.png"))

    def test_result_is_immutable(self) -> None:
        result = OCRResult("שלום", "engine")
        with self.assertRaises(Exception):
            result.text = "changed"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
