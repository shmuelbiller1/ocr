"""Tests for writing the measured accuracy into the documentation."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "write_accuracy_results.py"
SPEC = importlib.util.spec_from_file_location("write_accuracy_results", MODULE_PATH)
writer = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(writer)

REPORT = {
    "engine": "kraken",
    "model": "small.safetensors",
    "pages": 1,
    "corpus": {"name": "The Pinkas Dataset"},
    "summary": {"cer": 0.125, "wer": 0.4, "seconds_per_page": 12.5},
    "results": [
        {
            "page": "page_01.jpg",
            "characters_reference": 120,
            "cer": 0.125,
            "wer": 0.4,
            "seconds": 12.5,
        }
    ],
}


class AccuracyDocumentTests(unittest.TestCase):
    def test_the_numbers_of_the_report_are_written_into_the_document(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            document = Path(folder) / "OCR_ACCURACY.md"
            document.write_text(
                "# Title\n\n<!-- RESULTS -->\n\n## Next\n", encoding="utf-8"
            )
            self.assertTrue(writer.update_document(document, writer.build_section(REPORT)))
            text = document.read_text(encoding="utf-8")
            self.assertIn("12.5%", text)
            self.assertIn("40.0%", text)
            self.assertIn("page_01.jpg", text)
            self.assertIn("## Next", text)
            self.assertNotIn("<!-- RESULTS -->", text)

    def test_a_page_with_an_incomplete_ground_truth_is_named(self) -> None:
        """The numbers of a page that was not fully transcribed are marked."""
        report = json.loads(json.dumps(REPORT))
        report["pages"] = 1
        report["summary"]["pages_with_incomplete_ground_truth"] = ["page_02.jpg"]
        report["results"][0]["ground_truth"] = {"complete": False}
        section = writer.build_section(report)
        self.assertIn("page_02.jpg", section)
        self.assertIn("not complete", section)
        self.assertIn("are not part of the rates above", section)

    def test_a_complete_ground_truth_is_not_warned_about(self) -> None:
        section = writer.build_section(REPORT)
        self.assertNotIn("not part of the rates above", section)

    def test_writing_the_same_numbers_again_changes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            document = Path(folder) / "OCR_ACCURACY.md"
            document.write_text("# Title\n\n<!-- RESULTS -->\n", encoding="utf-8")
            writer.update_document(document, writer.build_section(REPORT))
            first = document.read_text(encoding="utf-8")
            self.assertFalse(writer.update_document(document, writer.build_section(REPORT)))
            self.assertEqual(document.read_text(encoding="utf-8"), first)

    def test_a_document_without_a_marker_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            document = Path(folder) / "OCR_ACCURACY.md"
            document.write_text("# Title\n", encoding="utf-8")
            self.assertFalse(writer.update_document(document, writer.build_section(REPORT)))
            self.assertEqual(document.read_text(encoding="utf-8"), "# Title\n")

    def test_the_report_of_the_benchmark_is_used_as_it_is(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "ocr-accuracy.json"
            report.write_text(json.dumps(REPORT, ensure_ascii=False), encoding="utf-8")
            document = Path(folder) / "OCR_ACCURACY.md"
            document.write_text("<!-- RESULTS -->\n", encoding="utf-8")
            self.assertEqual(
                writer.main(["--report", str(report), "--document", str(document)]), 0
            )
            self.assertIn("kraken", document.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
