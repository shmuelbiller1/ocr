"""Tests for the bundled offline CC0-1.0 Hebrew spellchecker and OCR ranker."""

from __future__ import annotations

import gzip
import tempfile
import unittest
from pathlib import Path

from hebrew_workbench.suggestions import SpellingModule
from hebrew_workbench.suggestions.hebrew_lexicon import HebrewLexicon


class OfflineHebrewSpellingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.personal = Path(self.temp.name) / "personal.txt"
        self.module = SpellingModule(
            {"bundled": True, "personal_dictionary": str(self.personal)}
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_valid_modern_prefixed_rabbinic_and_maqaf_tokens_have_zero_false_flags(
        self,
    ) -> None:
        text = (
            'בס"ד ובירושלים למדנו מהתלמידים ע"פ רש"י ותוס\' '
            "סברא דאורייתא או דרבנן, שָׁלוֹם אל־הרך, צוהריים אונייה לעיתים לעתים "
            "וכו' English 2026."
        )
        self.assertEqual(self.module.check(text), [])

    def test_handwritten_ocr_confusions_and_runons_rank_exact_top1(self) -> None:
        text = "שלומ תלמיידים בירישלים המחכרת מםפר מהתלמירים ביתהספר"
        by_orig = {p.original: p for p in self.module.check(text)}
        expected = {
            "שלומ": "שלום",
            "תלמיידים": "תלמידים",
            "בירישלים": "בירושלים",
            "המחכרת": "המחברת",
            "מםפר": "מספר",
            "מהתלמירים": "מהתלמידים",
            "ביתהספר": "בית הספר",
        }
        self.assertEqual(set(by_orig), set(expected))
        for wrong, right in expected.items():
            prop = by_orig[wrong]
            self.assertEqual(
                prop.replacement,
                right,
                f"Expected top-1 {right!r} for {wrong!r}, got {prop.replacement!r} ({prop.alternatives})",
            )
            self.assertEqual(text[prop.start : prop.end], wrong)

    def test_personal_dictionary_persists_across_restarts(self) -> None:
        rare = "מונחמחקריחדשני"
        self.assertTrue(self.module.check(rare))
        self.assertTrue(self.module.keep_word(rare))
        self.assertEqual(self.module.check(rare), [])

        reloaded = SpellingModule(
            {"bundled": True, "personal_dictionary": str(self.personal)}
        )
        self.assertEqual(reloaded.check(rare), [])

    def test_corrupted_bundled_archive_fails_closed(self) -> None:
        bad_gz = Path(self.temp.name) / "bad.txt.gz"
        bad_gz.write_bytes(gzip.compress("שלום\n".encode("utf-8")))
        with self.assertRaises(ValueError):
            HebrewLexicon.load_bundled(bad_gz)

    def test_misspelling_before_closing_quote_keeps_quote_outside_span(self) -> None:
        sample = 'הוא אמר "התלמיריס".'
        proposals = self.module.check(sample)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].original, "התלמיריס")
        self.assertEqual(proposals[0].replacement, "התלמידים")
        self.assertEqual(sample[proposals[0].start : proposals[0].end], "התלמיריס")

    def test_missing_custom_dictionary_falls_back_to_bundled_lexicon(self) -> None:
        mod = SpellingModule(
            {
                "bundled": True,
                "dictionary": str(Path(self.temp.name) / "missing.dic"),
                "personal_dictionary": str(self.personal),
            }
        )
        self.assertTrue(mod.available())
        self.assertEqual(mod.check("התלמיריס")[0].replacement, "התלמידים")


if __name__ == "__main__":
    unittest.main()
