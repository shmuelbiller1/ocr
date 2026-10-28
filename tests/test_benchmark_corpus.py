"""Tests for the corpora that the accuracy is measured on."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hebrew_workbench.benchmark.corpus import (
    Corpus,
    Page,
    load_corpus,
    pinkas_pages,
    read_transcript,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def write_corpus(folder: Path, pages: list[dict]) -> Path:
    """Write a corpus folder with the given pages."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "corpus.json").write_text(
        json.dumps(
            {
                "name": "A corpus of the tests",
                "description": "Pages of the tests, not real pages.",
                "target": "modern",
                "license": "the tests",
                "pages": pages,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return folder


class TranscriptTests(unittest.TestCase):
    def test_a_text_file_is_read_line_by_line(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "page.txt"
            path.write_text("שלום עולם\nמה שלום\n", encoding="utf-8")
            text, report = read_transcript(path)
        self.assertEqual(text, "שלום עולם\nמה שלום")
        self.assertEqual(report["lines"], 2)
        self.assertTrue(report["complete"])

    def test_an_empty_transcript_is_not_complete(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "page.txt"
            path.write_text("\n\n", encoding="utf-8")
            _text, report = read_transcript(path)
        self.assertFalse(report["complete"])


class CorpusTests(unittest.TestCase):
    def test_a_page_with_a_verified_transcript_is_measured(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "corpus"
            (root / "pages").mkdir(parents=True)
            (root / "transcripts").mkdir(parents=True)
            (root / "pages" / "page1.jpg").write_bytes(b"not a real picture")
            (root / "transcripts" / "page1.txt").write_text(
                "שלום עולם\n", encoding="utf-8"
            )
            write_corpus(
                root,
                [
                    {
                        "image": "pages/page1.jpg",
                        "transcript": "transcripts/page1.txt",
                        "writer": "7a-01",
                        "verified_by": ["the teacher"],
                    }
                ],
            )
            corpus = load_corpus(root)
        self.assertEqual(corpus.errors, [])
        self.assertEqual(len(corpus.pages), 1)
        self.assertTrue(corpus.verified)
        self.assertEqual(len(corpus.measured_pages), 1)
        self.assertEqual(corpus.pages[0].text, "שלום עולם")
        self.assertEqual(corpus.pages[0].writer, "7a-01")

    def test_a_page_without_a_verification_is_not_measured(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "corpus"
            (root / "pages").mkdir(parents=True)
            (root / "transcripts").mkdir(parents=True)
            (root / "pages" / "page1.jpg").write_bytes(b"not a real picture")
            (root / "transcripts" / "page1.txt").write_text(
                "שלום עולם\n", encoding="utf-8"
            )
            write_corpus(
                root,
                [
                    {
                        "image": "pages/page1.jpg",
                        "transcript": "transcripts/page1.txt",
                    }
                ],
            )
            corpus = load_corpus(root)
        self.assertFalse(corpus.verified)
        self.assertEqual(corpus.measured_pages, [])
        self.assertEqual(corpus.summary()["pages_without_verification"], ["page1.jpg"])

    def test_a_page_without_an_image_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = write_corpus(
                Path(folder) / "corpus", [{"image": "pages/nothing.jpg"}]
            )
            corpus = load_corpus(root)
        self.assertTrue(corpus.errors)
        self.assertFalse(corpus.verified)

    def test_a_folder_without_a_description_is_not_a_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            corpus = load_corpus(Path(folder))
        self.assertTrue(corpus.errors)
        self.assertEqual(corpus.pages, [])


class ModernSchoolCorpusTests(unittest.TestCase):
    """The corpus of the modern school handwriting is honest about itself."""

    def test_the_corpus_of_the_school_exists(self) -> None:
        folder = REPO_ROOT / "benchmark" / "modern_school"
        self.assertTrue(folder.is_dir())
        self.assertTrue((folder / "corpus.json").is_file())
        self.assertTrue((folder / "README.md").is_file())

    def test_the_corpus_of_the_school_says_that_it_is_not_verified(self) -> None:
        folder = REPO_ROOT / "benchmark" / "modern_school"
        corpus = load_corpus(folder)
        self.assertEqual(corpus.errors, [])
        self.assertEqual(corpus.target, "modern")
        if not corpus.pages:
            # There is no genuine material yet: the corpus has to say
            # that the accuracy is not verified, and not pretend that it
            # is.
            self.assertFalse(corpus.verified)
            self.assertEqual(corpus.measured_pages, [])
        else:
            self.assertTrue(corpus.verified)

    def test_the_pinkas_corpus_is_a_diagnostic_one(self) -> None:
        self.assertEqual(Corpus(target="historical").target, "historical")
        # The pages of the Pinkas dataset carry the verification of the
        # dataset itself.
        self.assertEqual(pinkas_pages(Path("/nowhere")), [])


class UnreadableLineTests(unittest.TestCase):
    """A line that could not be read is missing from the ground truth."""

    def test_a_page_with_an_unreadable_line_is_not_measured(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "transcripts").mkdir()
            transcript = root / "transcripts" / "page.txt"
            transcript.write_text("שלום עולם\n[?]\n", encoding="utf-8")
            text, report = read_transcript(transcript)
        self.assertIn("שלום עולם", text)
        self.assertFalse(report["complete"])
        self.assertEqual(report["lines_unreadable"], 1)


class EngineFolderTests(unittest.TestCase):
    """The models are looked for in the folder that is given."""

    def test_the_model_of_the_folder_that_is_given_is_found(self) -> None:
        from tools.benchmark_ocr import resolve_engines

        with tempfile.TemporaryDirectory() as folder:
            models = Path(folder) / "models"
            models.mkdir()
            (models / "small.safetensors").write_bytes(b"not a real model")
            engines, warnings = resolve_engines(
                ["kraken-ppocrv6-small"], models
            )
            self.assertEqual(warnings, [])
            self.assertEqual(len(engines), 1)
            self.assertEqual(engines[0][1], "kraken-ppocrv6-small")

    def test_a_model_that_is_not_there_is_not_measured(self) -> None:
        from tools.benchmark_ocr import resolve_engines

        with tempfile.TemporaryDirectory() as folder:
            models = Path(folder) / "models"
            models.mkdir()
            engines, warnings = resolve_engines(
                ["kraken-ppocrv6-small", "kraken-ppocrv6-medium"], models
            )
            self.assertEqual(engines, [])
            self.assertEqual(len(warnings), 2)
            self.assertIn("not installed", warnings[0])

    def test_a_model_that_is_not_known_is_not_measured(self) -> None:
        from tools.benchmark_ocr import resolve_engines

        with tempfile.TemporaryDirectory() as folder:
            engines, warnings = resolve_engines(["no-such-model"], Path(folder))
            self.assertEqual(engines, [])
            self.assertIn("not known to the program", warnings[0])


class EngineFailureTests(unittest.TestCase):
    """A broken engine does not stop the measurement of the others."""

    def test_the_failure_of_an_engine_is_named_and_the_run_goes_on(self) -> None:
        from tools.benchmark_ocr import run_engine

        class BrokenEngine:
            name = "The broken engine"

            def recognize(self, image):
                raise RuntimeError("the engine is not installed")

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "transcripts").mkdir()
            transcript = root / "transcripts" / "page.txt"
            transcript.write_text("שלום עולם\n", encoding="utf-8")
            page = Page(
                image=root / "page.png",
                transcript=transcript,
                text="שלום עולם",
                report={"complete": True},
                verified_by=["the teacher"],
            )
            report = run_engine(BrokenEngine(), [page], label="broken")
        self.assertEqual(report["results"], [])
        self.assertEqual(len(report["failures"]), 1)
        self.assertIn("the engine is not installed", report["failures"][0]["error"])
        # No rate is published, and not a rate of zero.
        self.assertIsNone(report["summary"]["cer"])
        self.assertFalse(report["summary"]["measured"])
