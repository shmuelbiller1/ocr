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
