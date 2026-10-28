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

NOTICE_PATH = Path(__file__).resolve().parents[1] / "tools" / "accuracy_notice.py"
NOTICE_SPEC = importlib.util.spec_from_file_location("accuracy_notice", NOTICE_PATH)
notice = importlib.util.module_from_spec(NOTICE_SPEC)
assert NOTICE_SPEC and NOTICE_SPEC.loader
NOTICE_SPEC.loader.exec_module(notice)


def load_notice():
    """The module of the notice of the build."""
    return notice


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


class ModernCorpusTests(unittest.TestCase):
    """The report of the modern corpus says when it is not verified."""

    REPORT = {
        "corpus": {
            "name": "Modern school handwriting",
            "target": "modern",
            "pages": 0,
            "pages_measured": 0,
            "verified": False,
        },
        "engines": [],
        "note": (
            "the corpus has no page with a verified transcript, so the "
            "accuracy of the recognition on this material is NOT verified"
        ),
    }

    def test_an_empty_corpus_is_written_as_not_verified(self) -> None:
        section = writer.build_section(self.REPORT)
        self.assertIn("not verified", section)
        self.assertNotIn("Character error rate | **", section)

    def test_the_note_of_the_report_is_shown(self) -> None:
        self.assertIn("NOT verified", writer.build_section(self.REPORT))


class SeveralEnginesTests(unittest.TestCase):
    """The engines are written as one table, so that they can be compared."""

    REPORT = {
        "corpus": {
            "name": "Modern school handwriting",
            "target": "modern",
            "pages": 2,
            "pages_measured": 2,
            "verified": True,
        },
        "engines": [
            {
                "engine": "kraken PP-OCRv6 (small)",
                "model": "kraken-ppocrv6-small",
                "pages": 2,
                "pages_seen": 2,
                "summary": {
                    "cer": 0.2,
                    "wer": 0.4,
                    "seconds_per_page": 12.5,
                    "characters_reference": 100,
                    "words_reference": 20,
                    "ground_truth_complete": True,
                    "pages_with_incomplete_ground_truth": [],
                    "pages_without_verification": [],
                },
                "results": [],
            },
            {
                "engine": "kraken PP-OCRv6 (medium)",
                "model": "kraken-ppocrv6-medium",
                "pages": 2,
                "pages_seen": 2,
                "summary": {
                    "cer": 0.15,
                    "wer": 0.3,
                    "seconds_per_page": 30.0,
                    "characters_reference": 100,
                    "words_reference": 20,
                    "ground_truth_complete": True,
                    "pages_with_incomplete_ground_truth": [],
                    "pages_without_verification": [],
                },
                "results": [],
            },
        ],
    }

    def test_every_engine_is_in_the_table(self) -> None:
        section = writer.build_section(self.REPORT)
        self.assertIn("kraken-ppocrv6-small", section)
        self.assertIn("kraken-ppocrv6-medium", section)

    def test_the_rates_of_the_engines_are_written(self) -> None:
        section = writer.build_section(self.REPORT)
        self.assertIn("20.0%", section)
        self.assertIn("15.0%", section)

    def test_the_measurement_says_that_no_correction_is_part_of_it(self) -> None:
        section = writer.build_section(self.REPORT)
        self.assertIn("no dictionary", section)




class NoVerifiedPageTests(unittest.TestCase):
    """An engine that ran, but no page that may be measured."""

    REPORT = {
        "corpus": {"name": "Modern school handwriting", "target": "modern", "pages": 2},
        "engines": [
            {
                "engine": "kraken",
                "model": "kraken-ppocrv6-small",
                "pages": 0,
                "pages_seen": 2,
                "summary": {"cer": None, "wer": None, "seconds_per_page": None},
                "results": [],
            }
        ],
    }

    def test_no_rate_is_published(self) -> None:
        section = writer.build_section(self.REPORT)
        self.assertIn("not verified", section)
        self.assertNotIn("0.0%", section)
        self.assertNotIn("Character error rate |", section)

    def test_the_notice_of_the_build_says_so(self) -> None:
        notice = load_notice()
        text = notice.summarise(self.REPORT)
        self.assertIn("no verified page", text)


class FirstWorkingEngineTests(unittest.TestCase):
    """The engine that is written first is the first engine that worked."""

    REPORT = {
        "corpus": {
            "name": "The Pinkas Dataset",
            "target": "historical",
            "pages": 2,
            "pages_measured": 2,
            "verified": True,
        },
        "measured_corpus_pages": 2,
        "engines": [
            {
                "engine": "the engine that failed",
                "model": "kraken-ppocrv6-small",
                "pages": 0,
                "pages_seen": 2,
                "summary": {
                    "cer": None,
                    "wer": None,
                    "seconds_per_page": None,
                },
                "results": [],
            },
            {
                "engine": "the engine that worked",
                "model": "kraken-ppocrv6-medium",
                "pages": 2,
                "pages_seen": 2,
                "summary": {
                    "cer": 0.15,
                    "wer": 0.3,
                    "seconds_per_page": 30.0,
                    "characters_reference": 100,
                    "words_reference": 20,
                },
                "results": [],
            },
        ],
    }

    def test_the_rate_of_the_engine_that_worked_is_written(self) -> None:
        section = writer.build_section(self.REPORT)
        self.assertIn("15.0%", section)
        self.assertNotIn("not verified", section)

    def test_the_engine_that_failed_is_not_the_headline(self) -> None:
        section = writer.build_section(self.REPORT)
        head = section.split("###")[0]
        self.assertNotIn("the engine that failed", head)


class MissingDocumentTests(unittest.TestCase):
    """A document that is not there does not make the build fail."""

    def test_the_tool_says_that_the_document_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "ocr-accuracy.json"
            report.write_text(json.dumps(REPORT, ensure_ascii=False), encoding="utf-8")
            missing = Path(folder) / "no-such-document.md"
            self.assertEqual(
                writer.main(
                    ["--report", str(report), "--document", str(missing)]
                ),
                1,
            )


class EngineFailureTests(unittest.TestCase):
    """A failure of an engine is not the same as a missing transcript."""

    REPORT = {
        "corpus": {
            "name": "The Pinkas Dataset",
            "target": "historical",
            "pages": 5,
            "pages_measured": 5,
            "verified": True,
        },
        "measured_corpus_pages": 5,
        "engines": [
            {
                "engine": "the engine that failed",
                "model": "kraken-ppocrv6-small",
                "pages": 0,
                "pages_seen": 5,
                "summary": {
                    "cer": None,
                    "wer": None,
                    "seconds_per_page": None,
                },
                "results": [],
                "failures": [
                    {"page": "page_01.jpg", "error": "RuntimeError: no model"}
                ],
            },
            {
                "engine": "the engine that worked",
                "model": "kraken-ppocrv6-medium",
                "pages": 4,
                "pages_seen": 5,
                "summary": {
                    "cer": 0.15,
                    "wer": 0.3,
                    "seconds_per_page": 30.0,
                    "characters_reference": 100,
                    "words_reference": 20,
                },
                "results": [],
                "failures": [],
            },
        ],
    }

    def test_the_results_of_the_engine_that_worked_are_kept(self) -> None:
        section = writer.build_section(self.REPORT)
        self.assertIn("15.0%", section)
        self.assertNotIn("not verified", section)

    def test_the_failure_of_the_engine_is_named(self) -> None:
        section = writer.build_section(self.REPORT)
        self.assertIn("page_01.jpg", section)
        self.assertIn("failed", section)

    def test_the_notice_of_the_build_tells_the_failure_and_the_result(self) -> None:
        text = notice.summarise(self.REPORT)
        self.assertIn("failed", text)
        self.assertIn("15.0%", text)


class CorpusSizeTests(unittest.TestCase):
    """The size of the corpus and the number of the pages that were
    measured are two different numbers, and the report keeps them
    apart."""

    def _report(self) -> dict:
        return {
            "corpus": {
                "name": "The Pinkas Dataset",
                "target": "historical",
                "pages": 30,
                "pages_measured": 4,
            },
            "pages_read": 5,
            "measured_corpus_pages": 4,
            "engines": [
                {
                    "engine": "kraken PP-OCRv6 (Apache-2.0)",
                    "model": "kraken-ppocrv6-small",
                    "pages": 4,
                    "pages_seen": 4,
                    "summary": {
                        "cer": 0.576,
                        "wer": 0.9375,
                        "seconds_per_page": 22.4,
                        "characters_reference": 10798,
                        "words_reference": 2176,
                        "pages_measured": 4,
                        "measured": True,
                    },
                    "failures": [],
                }
            ],
        }

    def test_the_report_says_how_much_of_the_corpus_was_read(self) -> None:
        text = writer.build_section(self._report())
        self.assertIn("The corpus holds 30 pages.", text)
        self.assertIn("The build chose 5 of them", text)
        self.assertIn("4 of them could be measured", text)

    def test_the_rate_is_not_written_as_a_rate_of_the_whole_corpus(self) -> None:
        text = writer.build_section(self._report())
        self.assertIn("it is not a rate of the whole corpus", text)

    def test_a_corpus_that_was_measured_whole_says_nothing_of_the_sort(self) -> None:
        report = self._report()
        report["corpus"]["pages_measured"] = 30
        report["pages_read"] = 30
        report["measured_corpus_pages"] = 30
        text = writer.build_section(report)
        self.assertNotIn("it is not a rate of the whole corpus", text)


class LeftOutPagesTests(unittest.TestCase):
    """A page that was left out of the measurement is named in the
    report."""

    def _report(self) -> dict:
        return {
            "corpus": {
                "name": "The Pinkas Dataset",
                "target": "historical",
                "pages": 30,
                "pages_measured": 4,
            },
            "pages_read": 5,
            "measured_corpus_pages": 4,
            "engines": [
                {
                    "engine": "kraken PP-OCRv6 (Apache-2.0)",
                    "model": "kraken-ppocrv6-small",
                    "pages": 4,
                    "pages_seen": 4,
                    "summary": {
                        "cer": 0.576,
                        "wer": 0.9375,
                        "seconds_per_page": 22.4,
                        "characters_reference": 10798,
                        "words_reference": 2176,
                        "pages_measured": 4,
                        "measured": True,
                    },
                    "failures": [],
                    "left_out": [
                        {"page": "Page 113_1.jpg", "reason": "there is no ground truth"}
                    ],
                }
            ],
        }

    def test_the_page_that_was_left_out_is_named(self) -> None:
        text = writer.build_section(self._report())
        self.assertIn("Page 113_1.jpg", text)
        self.assertIn("left out of the measurement", text)

    def test_a_report_without_a_page_that_was_left_out_says_nothing(self) -> None:
        report = self._report()
        report["engines"][0]["left_out"] = []
        text = writer.build_section(report)
        self.assertNotIn("left out of the measurement", text)


class FailedEnginesTests(unittest.TestCase):
    """The engines that failed are named, also when there is no rate."""

    def _report(self) -> dict:
        return {
            "corpus": {
                "name": "The Pinkas Dataset",
                "target": "historical",
                "pages": 30,
                "pages_measured": 4,
            },
            "pages_read": 5,
            "measured_corpus_pages": 4,
            "engines": [
                {
                    "engine": "kraken PP-OCRv6 (Apache-2.0)",
                    "model": "kraken-ppocrv6-small",
                    "pages": 0,
                    "pages_seen": 0,
                    "summary": {
                        "cer": None,
                        "wer": None,
                        "seconds_per_page": None,
                        "pages_measured": 0,
                        "measured": False,
                    },
                    "failures": [
                        {"page": "Page 105_1.jpg", "error": "the model is missing"}
                    ],
                }
            ],
        }

    def test_the_engine_that_failed_is_named(self) -> None:
        text = writer.build_section(self._report())
        self.assertIn("kraken-ppocrv6-small", text)
        self.assertIn("Page 105_1.jpg", text)
        self.assertIn("failed on 1", text)

    def test_the_rate_is_not_published(self) -> None:
        text = writer.build_section(self._report())
        self.assertIn("is not verified", text)


class SelectedAndMeasuredTests(unittest.TestCase):
    """The pages that were chosen and the pages that were measured are
    two numbers, and the report keeps them apart."""

    def test_the_report_says_how_many_pages_were_measured(self) -> None:
        report = {
            "corpus": {
                "name": "The Pinkas Dataset",
                "target": "historical",
                "pages": 30,
                "pages_measured": 4,
            },
            "pages_read": 5,
            "measured_corpus_pages": 4,
            "engines": [
                {
                    "engine": "kraken PP-OCRv6 (Apache-2.0)",
                    "model": "kraken-ppocrv6-small",
                    "pages": 3,
                    "pages_seen": 4,
                    "summary": {
                        "cer": 0.576,
                        "wer": 0.9375,
                        "seconds_per_page": 22.4,
                        "characters_reference": 10798,
                        "words_reference": 2176,
                        "pages_measured": 3,
                        "measured": True,
                    },
                    "failures": [],
                }
            ],
        }
        text = writer.build_section(report)
        self.assertIn("The build chose 5 of them", text)
        self.assertIn("The rate above is of the 3 pages that were measured", text)


if __name__ == "__main__":
    unittest.main()
