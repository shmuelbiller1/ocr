"""Tests for the accuracy measuring helpers."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "benchmark_ocr.py"
SPEC = importlib.util.spec_from_file_location("benchmark_ocr", MODULE_PATH)
benchmark = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(benchmark)


class AccuracyTests(unittest.TestCase):
    def test_character_error_rate_of_equal_text_is_zero(self) -> None:
        self.assertEqual(benchmark.character_error_rate("שלום", "שלום"), 0.0)

    def test_character_error_rate_counts_edits(self) -> None:
        # one wrong character out of four
        self.assertAlmostEqual(benchmark.character_error_rate("שלום", "שלופ"), 0.25)

    def test_character_error_rate_of_empty_reference(self) -> None:
        self.assertEqual(benchmark.character_error_rate("", ""), 0.0)
        self.assertEqual(benchmark.character_error_rate("", "שלום"), 1.0)

    def test_word_error_rate(self) -> None:
        self.assertEqual(benchmark.word_error_rate("שלום עולם", "שלום עולם"), 0.0)
        self.assertAlmostEqual(benchmark.word_error_rate("שלום עולם", "שלום עולפ"), 0.5)

    def test_normalisation_removes_vowel_points_and_keeps_letters(self) -> None:
        self.assertEqual(benchmark.normalise("שָׁלוֹם"), "שלום")
        self.assertNotEqual(benchmark.normalise("שָׁלוֹם", keep_points=True), "שלום")

    def test_normalisation_collapses_whitespace(self) -> None:
        self.assertEqual(benchmark.normalise("שלום   עולם\n"), "שלום עולם")

    def test_page_xml_is_read_line_by_line(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15">
          <Page>
            <TextRegion>
              <TextLine id="l1"><Unicode>שלום</Unicode></TextLine>
              <TextLine id="l2"><Unicode>עולם</Unicode></TextLine>
            </TextRegion>
          </Page>
        </PcGts>
        """
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "page.xml"
            path.write_text(xml, encoding="utf-8")
            self.assertEqual(benchmark.read_page_xml(path), "שלום\nעולם")

    def test_the_text_of_a_line_is_found_inside_a_text_equiv(self) -> None:
        """The text of a line sits deeper than the direct children."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15">
          <Page>
            <TextRegion>
              <TextLine id="line_1">
                <TextEquiv>
                  <Unicode>שלום</Unicode>
                </TextEquiv>
              </TextLine>
            </TextRegion>
          </Page>
        </PcGts>
        """
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "page.xml"
            path.write_text(xml, encoding="utf-8")
            self.assertEqual(benchmark.read_page_xml(path), "שלום")

    def test_the_text_of_a_line_is_not_the_text_of_its_first_word(self) -> None:
        """A line has a text of its own, next to the texts of its words.

        This is the shape of the Pinkas corpus: every line holds the
        text of the whole line and, beside it, the words of the line.
        """
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2018-07-15">
          <Page>
            <TextRegion>
              <TextLine id="l0">
                <Coords points="1,2 3,4"/>
                <TextEquiv><Unicode>דיא ע"י צלין</Unicode></TextEquiv>
                <Word id="w0"><TextEquiv><Unicode>דיא</Unicode></TextEquiv></Word>
                <Word id="w1"><TextEquiv><Unicode>ע"י</Unicode></TextEquiv></Word>
                <Word id="w2"><TextEquiv><Unicode>צלין</Unicode></TextEquiv></Word>
              </TextLine>
            </TextRegion>
          </Page>
        </PcGts>
        """
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "page.xml"
            path.write_text(xml, encoding="utf-8")
            self.assertEqual(benchmark.read_page_xml(path), 'דיא ע"י צלין')

    def test_the_words_of_a_line_are_joined_when_the_line_has_no_text(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2018-07-15">
          <Page>
            <TextRegion>
              <TextLine id="l0">
                <TextEquiv><Unicode/></TextEquiv>
                <Word id="w0"><TextEquiv><Unicode>דיא</Unicode></TextEquiv></Word>
                <Word id="w1"><TextEquiv><Unicode>צלין</Unicode></TextEquiv></Word>
              </TextLine>
            </TextRegion>
          </Page>
        </PcGts>
        """
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "page.xml"
            path.write_text(xml, encoding="utf-8")
            self.assertEqual(benchmark.read_page_xml(path), "דיא צלין")

    def test_a_page_without_a_ground_truth_is_not_measured(self) -> None:
        class Engine:
            def recognize(self, image):  # noqa: N802 - the name of the engine
                raise AssertionError("the page should not be recognised")

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "page.jpg"
            image.write_bytes(b"image")
            xml = root / "page.xml"
            xml.write_text(
                "<PcGts><Page><TextRegion><TextLine>"
                "</TextLine></TextRegion></Page></PcGts>",
                encoding="utf-8",
            )
            self.assertIsNone(benchmark.measure_page(Engine(), image, xml, root))

    def test_a_page_is_measured_against_its_ground_truth(self) -> None:
        class Engine:
            def recognize(self, image):  # noqa: N802 - the name of the engine
                class Result:
                    text = "שלום"

                return Result()

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "page.jpg"
            image.write_bytes(b"image")
            xml = root / "page.xml"
            xml.write_text(
                "<PcGts><Page><TextRegion><TextLine>"
                "<TextEquiv><Unicode>שלום</Unicode></TextEquiv>"
                "</TextLine></TextRegion></Page></PcGts>",
                encoding="utf-8",
            )
            measured = benchmark.measure_page(Engine(), image, xml, root)
            self.assertIsNotNone(measured)
            self.assertEqual(measured["cer"], 0.0)
            self.assertEqual(measured["wer"], 0.0)

    def test_pages_are_paired_with_their_ground_truth(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "page.xml").write_text("<PcGts/>", encoding="utf-8")
            (root / "page.jpg").write_bytes(b"jpg")
            (root / "lonely.xml").write_text("<PcGts/>", encoding="utf-8")
            pairs = benchmark.find_pages(root)
            self.assertEqual(len(pairs), 1)
            self.assertEqual(pairs[0][0].name, "page.jpg")

    def test_the_number_of_the_words_is_recorded(self) -> None:
        """The rate of the corpus needs the number of the words."""

        class Result:
            text = "שלום עולם"

        class Engine:
            def recognize(self, image):  # noqa: N802 - the name of the engine
                return Result()

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "page.jpg"
            image.write_bytes(b"jpg")
            xml = root / "page.xml"
            xml.write_text(
                "<PcGts><Page><TextRegion><TextLine>"
                "<TextEquiv><Unicode>שלום עולם</Unicode></TextEquiv>"
                "</TextLine></TextRegion></Page></PcGts>",
                encoding="utf-8",
            )
            measured = benchmark.measure_page(Engine(), image, xml, root)
            self.assertIsNotNone(measured)
            self.assertEqual(measured["words_reference"], 2)
            self.assertEqual(measured["word_errors"], 0)

    def test_the_report_of_the_ground_truth_says_what_the_file_holds(self) -> None:
        """A measurement says whether the ground truth was complete."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            xml = root / "page.xml"
            xml.write_text(
                "<PcGts><Page><TextRegion>"
                "<TextLine><Word><TextEquiv><Unicode>שלום</Unicode></TextEquiv></Word>"
                "</TextLine>"
                "<TextLine><TextEquiv><Unicode>עולם</Unicode></TextEquiv></TextLine>"
                "<TextLine></TextLine>"
                "</TextRegion></Page></PcGts>",
                encoding="utf-8",
            )
            text, report = benchmark.ground_truth_of(xml)
            self.assertEqual(text, "שלום\nעולם")
            self.assertEqual(report["lines"], 3)
            self.assertEqual(report["lines_with_text"], 2)
            self.assertEqual(report["lines_from_words"], 1)
            self.assertEqual(report["words"], 1)
            # One line has no text at all, so the ground truth of this
            # page is not complete.
            self.assertFalse(report["complete"])

    def test_a_line_that_is_only_half_transcribed_is_not_complete(self) -> None:
        """A word without a text would be counted as a mistake."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            xml = root / "page.xml"
            xml.write_text(
                "<PcGts><Page><TextRegion><TextLine>"
                "<Word><TextEquiv><Unicode>שלום</Unicode></TextEquiv></Word>"
                "<Word></Word>"
                "</TextLine></TextRegion></Page></PcGts>",
                encoding="utf-8",
            )
            text, report = benchmark.ground_truth_of(xml)
            self.assertEqual(text, "שלום")
            self.assertEqual(report["lines_from_words"], 1)
            self.assertEqual(report["words"], 2)
            self.assertEqual(report["words_with_text"], 1)
            self.assertFalse(report["complete"])

    def test_the_rate_of_the_words_of_the_corpus_weighs_the_pages(self) -> None:
        """A page with few words does not count as much as a page with many."""
        results = [
            {"wer": 1.0, "words_reference": 1, "word_errors": 1},
            {"wer": 0.0, "words_reference": 100, "word_errors": 0},
        ]
        total_words = sum(item["words_reference"] for item in results)
        total_wer = sum(item["word_errors"] for item in results) / total_words
        self.assertAlmostEqual(total_wer, 0.0099, places=4)


if __name__ == "__main__":
    unittest.main()


class PageNamesTests(unittest.TestCase):
    """Two pages of the corpus may have the same name."""

    class Engine:
        """An engine that reads every page the same way."""

        name = "the engine"

        def __init__(self, text: str = "שלום") -> None:
            self.text = text

        def recognize(self, image):  # noqa: N802 - the name of the engine
            class Result:
                text = ""

            result = Result()
            result.text = self.text
            return result

    def make_page(self, folder: Path, name: str, text: str) -> object:
        from hebrew_workbench.benchmark.corpus import Page

        image = folder / name
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(b"image")
        transcript = image.with_suffix(".txt")
        transcript.write_text(text, encoding="utf-8")
        return Page(
            image=image,
            transcript=transcript,
            text=text,
            report={"complete": True},
            writer="the writer",
            verified_by=["the reader"],
        )

    def test_two_pages_with_the_same_name_are_two_pages(self) -> None:
        """The pages of two folders may have the same name, and the
        measurement has to tell them apart."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = self.make_page(root / "class_a", "page.jpg", "שלום")
            second = self.make_page(root / "class_b", "page.jpg", "עולם")
            report = benchmark.run_engine(
                self.Engine(),
                [first, second],
                corpus_folder=root,
            )
            names = [item["page"] for item in report["results"]]
            self.assertEqual(len(names), 2)
            self.assertEqual(sorted(names), ["class_a/page.jpg", "class_b/page.jpg"])

    def test_a_page_that_is_linked_keeps_its_place_in_the_corpus(self) -> None:
        """A page that is linked from outside of the corpus is still a
        page of the corpus, and it keeps the place it has in it."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            outside = root / "outside"
            outside.mkdir()
            (outside / "page.jpg").write_bytes(b"image")
            linked = root / "class_a"
            linked.mkdir()
            try:
                (linked / "page.jpg").symlink_to(outside / "page.jpg")
            except (OSError, NotImplementedError):
                self.skipTest("the machine cannot make a link")
            page = self.make_page(linked, "page.jpg", "שלום")
            report = benchmark.run_engine(
                self.Engine(), [page], corpus_folder=root
            )
            self.assertEqual(
                [item["page"] for item in report["results"]], ["class_a/page.jpg"]
            )

    def test_a_corpus_that_is_a_link_keeps_the_names_of_its_pages(self) -> None:
        """The folder of the corpus may be a link, and the pages of the
        corpus keep their names."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            real = root / "the-real-corpus"
            real.mkdir()
            link = root / "the-corpus"
            try:
                link.symlink_to(real)
            except (OSError, NotImplementedError):
                self.skipTest("the machine cannot make a link")
            page = self.make_page(real, "page.jpg", "שלום")
            report = benchmark.run_engine(
                self.Engine(), [page], corpus_folder=link
            )
            self.assertEqual(
                [item["page"] for item in report["results"]], ["page.jpg"]
            )

    def test_the_comparison_of_two_engines_is_of_the_same_pages(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = self.make_page(root / "class_a", "page.jpg", "שלום")
            second = self.make_page(root / "class_b", "page.jpg", "עולם")
            one = benchmark.run_engine(
                self.Engine("שלום"),
                [first, second],
                label="the first engine",
                corpus_folder=root,
            )
            two = benchmark.run_engine(
                self.Engine("עולם"),
                [second],
                label="the second engine",
                corpus_folder=root,
            )
            comparison = benchmark.compare_on_the_same_pages([one, two])
            self.assertEqual(comparison["pages"], ["class_b/page.jpg"])
            self.assertEqual(
                comparison["pages_outside_the_comparison"]["the first engine"],
                ["class_a/page.jpg"],
            )


class MeasuredPagesTests(unittest.TestCase):
    """The number of the pages that may be measured is not the number of
    the pages of the corpus."""

    def _page(self, name: str, complete: bool, verified: bool) -> benchmark.Page:
        page = benchmark.Page(image=Path(name))
        page.report = {"complete": complete}
        page.verified_by = ["a teacher"] if verified else []
        return page

    def test_a_page_that_is_complete_and_verified_is_measured(self) -> None:
        pages = [self._page("a.jpg", True, True)]
        self.assertEqual(benchmark.pages_that_may_be_measured(pages), 1)

    def test_a_page_whose_ground_truth_is_not_complete_is_not_measured(self) -> None:
        pages = [self._page("a.jpg", False, True)]
        self.assertEqual(benchmark.pages_that_may_be_measured(pages), 0)

    def test_a_page_that_was_not_verified_is_not_measured(self) -> None:
        pages = [self._page("a.jpg", True, False)]
        self.assertEqual(benchmark.pages_that_may_be_measured(pages), 0)

    def test_the_pages_of_the_corpus_are_not_all_measured(self) -> None:
        pages = [
            self._page("a.jpg", True, True),
            self._page("b.jpg", False, True),
            self._page("c.jpg", True, False),
        ]
        self.assertEqual(benchmark.pages_that_may_be_measured(pages), 1)


class ConsoleTests(unittest.TestCase):
    """The console of Windows writes in a code page of the system, and
    Hebrew is not in it."""

    def test_the_console_can_write_hebrew(self) -> None:
        import io
        import sys

        from hebrew_workbench.console import use_utf8

        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        original = sys.stdout
        sys.stdout = stream
        try:
            use_utf8()
            print("שלום עולם")
            stream.flush()
            written = stream.buffer.getvalue()
        finally:
            sys.stdout = original
        self.assertIn("שלום עולם", written.decode("utf-8"))

    def test_a_stream_that_cannot_be_changed_is_not_an_error(self) -> None:
        from hebrew_workbench.console import use_utf8

        class Stream:
            """A stream without the way to change it."""

        # The function does nothing with the streams of the program, and
        # it does not stop when a stream cannot be changed.
        use_utf8()
