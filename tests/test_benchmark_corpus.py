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
    read_page_xml_report,
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


class IncompleteGroundTruthTests(unittest.TestCase):
    """A page whose ground truth is not there is not a measurement."""

    def test_a_page_without_a_transcript_is_not_complete(self) -> None:
        page = Page(image=Path("page.png"))
        self.assertFalse(page.complete)

    def test_a_page_with_an_empty_report_is_not_complete(self) -> None:
        page = Page(image=Path("page.png"), report={})
        self.assertFalse(page.complete)

    def test_a_corpus_with_a_page_without_a_transcript_is_not_verified(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "pages").mkdir()
            (root / "transcripts").mkdir()
            (root / "pages" / "p1.png").write_bytes(b"png")
            (root / "transcripts" / "p1.txt").write_text(
                "שלום עולם\n", encoding="utf-8"
            )
            write_corpus(
                root,
                [
                    {
                        "image": "pages/p1.png",
                        "transcript": "transcripts/p1.txt",
                        "verified_by": ["teacher"],
                    },
                    {
                        "image": "pages/p2.png",
                        "transcript": "transcripts/p2.txt",
                        "verified_by": ["teacher"],
                    },
                ],
            )
            corpus = load_corpus(root)
        # The second page has no image and no transcript, and so it is
        # not a measurement: the corpus as a whole is not verified.
        self.assertFalse(corpus.verified)
        self.assertEqual(len(corpus.measured_pages), 1)

    def test_the_name_of_one_checker_may_be_given_as_a_string(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "pages").mkdir()
            (root / "transcripts").mkdir()
            (root / "pages" / "p1.png").write_bytes(b"png")
            (root / "transcripts" / "p1.txt").write_text(
                "שלום עולם\n", encoding="utf-8"
            )
            write_corpus(
                root,
                [
                    {
                        "image": "pages/p1.png",
                        "transcript": "transcripts/p1.txt",
                        "verified_by": "teacher",
                    }
                ],
            )
            corpus = load_corpus(root)
        self.assertEqual(corpus.pages[0].verified_by, ["teacher"])
        self.assertTrue(corpus.pages[0].verified)

    def test_a_blank_name_is_not_a_name(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "pages").mkdir()
            (root / "transcripts").mkdir()
            (root / "pages" / "p1.png").write_bytes(b"png")
            (root / "transcripts" / "p1.txt").write_text(
                "שלום עולם\n", encoding="utf-8"
            )
            write_corpus(
                root,
                [
                    {
                        "image": "pages/p1.png",
                        "transcript": "transcripts/p1.txt",
                        "verified_by": ["  ", "teacher"],
                    }
                ],
            )
            corpus = load_corpus(root)
        self.assertEqual(corpus.pages[0].verified_by, ["teacher"])


class UnreadableXmlTests(unittest.TestCase):
    """The mark of a line that could not be read is honoured in the XML form."""

    def make_xml(self, folder: Path, text: str) -> Path:
        path = folder / "page.xml"
        path.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15">
  <Page>
    <TextRegion>
      <TextLine>
        <TextEquiv><Unicode>{text}</Unicode></TextEquiv>
      </TextLine>
    </TextRegion>
  </Page>
</PcGts>
""".format(text=text),
            encoding="utf-8",
        )
        return path

    def test_a_line_that_could_not_be_read_makes_the_page_not_complete(self) -> None:
        from hebrew_workbench.benchmark.corpus import read_page_xml_report

        with tempfile.TemporaryDirectory() as folder:
            path = self.make_xml(Path(folder), "שלום [?] עולם")
            _text, report = read_page_xml_report(path)
        self.assertFalse(report["complete"])
        self.assertEqual(report["lines_unreadable"], 1)

    def test_a_page_that_was_read_is_complete(self) -> None:
        from hebrew_workbench.benchmark.corpus import read_page_xml_report

        with tempfile.TemporaryDirectory() as folder:
            path = self.make_xml(Path(folder), "שלום עולם")
            _text, report = read_page_xml_report(path)
        self.assertTrue(report["complete"])
        self.assertEqual(report["lines_unreadable"], 0)


def make_result(
    page: str,
    cer: float = 0.2,
    characters: int = 100,
    words: int = 20,
    word_errors: int = 4,
    seconds: float = 1.0,
    complete: bool = True,
    verified: bool = True,
) -> dict:
    """One page that was measured, as the report holds it."""
    return {
        "page": page,
        "ground_truth": {"complete": complete},
        "verified_by": ["teacher"] if verified else [],
        "cer": cer,
        "wer": 0.5,
        "characters_reference": characters,
        "words_reference": words,
        "word_errors": word_errors,
        "seconds": seconds,
    }


class SharedPagesTests(unittest.TestCase):
    """The engines are compared on the pages that every engine measured."""

    def test_the_common_pages_are_the_ones_the_engines_are_compared_on(self) -> None:
        from tools.benchmark_ocr import compare_on_the_same_pages

        first = {
            "engine": "the small model",
            "model": "kraken-ppocrv6-small",
            "results": [
                make_result("p1.png", cer=0.2, characters=100, words=20, word_errors=4),
                make_result("p2.png", cer=0.6, characters=100, words=20, word_errors=12),
            ],
        }
        second = {
            "engine": "the medium model",
            "model": "kraken-ppocrv6-medium",
            "results": [
                make_result("p1.png", cer=0.1, characters=100, words=20, word_errors=2),
            ],
        }
        comparison = compare_on_the_same_pages([first, second])

        self.assertEqual(comparison["pages"], ["p1.png"])
        # The rate of every engine is the rate on the common pages only.
        for engine in comparison["engines"]:
            self.assertEqual(engine["summary"]["pages_measured"], 1)
            self.assertEqual(engine["summary"]["cer"], 0.2 if "small" in engine["model"] else 0.1)
        # The page that one of the engines did not read is named.
        self.assertEqual(
            comparison["pages_outside_the_comparison"]["the small model"], ["p2.png"]
        )

    def test_a_page_that_was_not_verified_is_not_a_measurement(self) -> None:
        from tools.benchmark_ocr import measured_pages_of, summarise

        results = [
            make_result("p1.png"),
            make_result("p2.png", verified=False),
        ]
        summary = summarise(results)
        self.assertEqual(summary["pages_measured"], 1)
        self.assertEqual(summary["cer"], 0.2)
        self.assertEqual(summary["pages_without_verification"], ["p2.png"])
        self.assertEqual(measured_pages_of({"results": results}), {"p1.png"})

    def test_a_page_whose_ground_truth_is_not_complete_is_not_a_measurement(self) -> None:
        from tools.benchmark_ocr import summarise

        results = [
            make_result("p1.png"),
            make_result("p2.png", complete=False),
        ]
        summary = summarise(results)
        self.assertEqual(summary["pages_measured"], 1)
        self.assertEqual(summary["pages_with_incomplete_ground_truth"], ["p2.png"])

    def test_there_is_no_rate_when_no_page_may_be_measured(self) -> None:
        from tools.benchmark_ocr import summarise

        summary = summarise([make_result("p1.png", verified=False)])
        self.assertIsNone(summary["cer"])
        self.assertIsNone(summary["wer"])
        self.assertFalse(summary["measured"])


class ManifestTests(unittest.TestCase):
    """The images of the corpus are the ones that the manifest holds."""

    def make_corpus(self, folder: Path) -> Path:
        root = Path(folder)
        (root / "pages").mkdir(parents=True)
        (root / "transcripts").mkdir()
        (root / "pages" / "p1.png").write_bytes(b"the image of the page")
        (root / "transcripts" / "p1.txt").write_text(
            "שלום עולם\n", encoding="utf-8"
        )
        write_corpus(
            root,
            [
                {
                    "image": "pages/p1.png",
                    "transcript": "transcripts/p1.txt",
                    "verified_by": ["teacher"],
                }
            ],
        )
        return root

    def test_a_corpus_without_a_manifest_is_not_checked(self) -> None:
        from tools.benchmark_ocr import check_against_the_manifest

        with tempfile.TemporaryDirectory() as folder:
            root = self.make_corpus(Path(folder))
            corpus = load_corpus(root)
            self.assertEqual(check_against_the_manifest(root, corpus.pages), [])

    def test_the_image_that_the_manifest_holds_is_accepted(self) -> None:
        from tools.benchmark_ocr import check_against_the_manifest

        with tempfile.TemporaryDirectory() as folder:
            root = self.make_corpus(Path(folder))
            corpus = load_corpus(root)
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "pages": [
                            {
                                "image": "p1.png",
                                "sha256": corpus.pages[0].digest(),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(check_against_the_manifest(root, corpus.pages), [])

    def test_an_image_that_was_changed_is_not_measured(self) -> None:
        from tools.benchmark_ocr import check_against_the_manifest

        with tempfile.TemporaryDirectory() as folder:
            root = self.make_corpus(Path(folder))
            corpus = load_corpus(root)
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "pages": [
                            {
                                "image": "p1.png",
                                "sha256": "the digest of another image",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit) as caught:
                check_against_the_manifest(root, corpus.pages)
            self.assertIn("p1.png", str(caught.exception))


class EmptyXmlTests(unittest.TestCase):
    """A file of the XML form without a line of text is not a ground
    truth, in the same way as a plain text file without a line."""

    def _write(self, folder: Path, body: str) -> Path:
        path = folder / "page.xml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_a_file_without_any_line_is_not_complete(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = self._write(
                Path(folder),
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15">'
                "<Page><TextRegion></TextRegion></Page></PcGts>",
            )
            text, report = read_page_xml_report(path)
            self.assertEqual(text, "")
            self.assertFalse(report["complete"])

    def test_a_line_without_text_is_not_complete(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = self._write(
                Path(folder),
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15">'
                "<Page><TextRegion>"
                '<TextLine id="l1"></TextLine>'
                "</TextRegion></Page></PcGts>",
            )
            text, report = read_page_xml_report(path)
            self.assertEqual(text, "")
            self.assertFalse(report["complete"])

    def test_a_file_with_text_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = self._write(
                Path(folder),
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15">'
                "<Page><TextRegion>"
                '<TextLine id="l1"><Unicode>שלום</Unicode></TextLine>'
                "</TextRegion></Page></PcGts>",
            )
            text, report = read_page_xml_report(path)
            self.assertEqual(text, "שלום")
            self.assertTrue(report["complete"])


class LeftOutPageTests(unittest.TestCase):
    """A page without a ground truth is left out of the measurement and
    it is named."""

    def test_a_page_without_a_ground_truth_is_named(self) -> None:
        from tools.benchmark_ocr import run_engine

        class Engine:
            name = "the engine"

            def recognize(self, image):
                class Result:
                    text = "שלום עולם"

                return Result()

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            good = Page(
                image=root / "good.png",
                transcript=root / "good.txt",
                text="שלום עולם",
                report={"complete": True},
                verified_by=["the teacher"],
            )
            empty = Page(
                image=root / "empty.png",
                transcript=root / "empty.txt",
                text="",
                report={"complete": False},
                verified_by=["the teacher"],
            )
            report = run_engine(Engine(), [good, empty], label="the model")
        self.assertEqual(len(report["results"]), 1)
        self.assertEqual(len(report["left_out"]), 1)
        self.assertEqual(report["left_out"][0]["page"], "empty.png")
        self.assertIn("ground truth", report["left_out"][0]["reason"])
        self.assertEqual(report["failures"], [])
