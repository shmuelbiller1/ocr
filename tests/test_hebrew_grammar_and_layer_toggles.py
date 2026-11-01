"""Regression tests for offline Hebrew grammar rules and 4-layer UI toggles."""

from __future__ import annotations

import os
import unittest

from hebrew_workbench.suggestions import KIND_STYLE, Suggestion, SuggestionModule
from hebrew_workbench.suggestions.grammar import GrammarModule


class HebrewGrammarRulesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.grammar = GrammarModule()

    def test_first_person_future_prefix_flags_yod_on_future_verbs(self) -> None:
        proposals = self.grammar.check("אני ילך מחר לבית הספר ואני לא יבוא מאוחר.")
        originals = [p.original for p in proposals]
        replacements = [p.replacement for p in proposals]
        self.assertEqual(originals, ["ילך", "יבוא"])
        self.assertEqual(replacements, ["אלך", "אבוא"])

    def test_first_person_future_prefix_ignores_present_participles_and_third_person(self) -> None:
        clean = (
            "אני יכול לעזור, אני יודע את התשובה, אני יושב בשורה הראשונה, "
            "והוא ילך מחר בבוקר."
        )
        self.assertEqual(self.grammar.check(clean), [])

    def test_construct_definite_article_moves_ha_to_nismakh(self) -> None:
        proposals = self.grammar.check("הגענו אל הבית ספר ופגשנו את העורך דין.")
        self.assertEqual(
            [(p.original, p.replacement) for p in proposals],
            [("הבית ספר", "בית הספר"), ("העורך דין", "עורך הדין")],
        )
        self.assertEqual(self.grammar.check("הגענו אל בית הספר ופגשנו את עורך הדין."), [])

    def test_numeral_gender_agreement_flags_clear_polarity_mismatches(self) -> None:
        proposals = self.grammar.check(
            "בכיתה יש שלושה בנות, חמש ילדים ועשרה דקות להפסקה."
        )
        self.assertEqual(
            [(p.original, p.replacement) for p in proposals],
            [
                ("שלושה", "שלוש"),
                ("חמש", "חמישה"),
                ("ועשרה", "ועשר"),
            ],
        )

    def test_numeral_gender_agreement_skips_valid_forms_and_unpointed_shmone(self) -> None:
        clean = "בכיתה יש שלוש בנות, חמישה ילדים, שמונה בנות ושמונה ילדים."
        self.assertEqual(self.grammar.check(clean), [])

    def test_demonstrative_agreement_flags_masculine_feminine_mismatch(self) -> None:
        proposals = self.grammar.check("הבעיה הזה מורכבת מאוד אבל המקום הזאת שקט.")
        self.assertEqual(
            [(p.original, p.replacement) for p in proposals],
            [("הזה", "הזאת"), ("הזאת", "הזה")],
        )
        self.assertEqual(self.grammar.check("הבעיה הזאת מורכבת אבל המקום הזה שקט."), [])

    def test_accidental_duplication_catches_echoes_and_keeps_hebrew_idioms(self) -> None:
        proposals = self.grammar.check("הספר מונח על על השולחן ופתוח בדף הדף הראשון.")
        self.assertEqual(
            [(p.original, p.replacement) for p in proposals],
            [("על על", "על"), ("בדף הדף", "בדף")],
        )
        idiomatic = "התקדמנו לאט לאט, יום יום, והתוצאה הייתה טובה מאוד מאוד וממש ממש ברורה."
        self.assertEqual(self.grammar.check(idiomatic), [])

    def test_bracket_inner_spaces_are_flagged(self) -> None:
        proposals = self.grammar.check("הערה קצרה ( בדיקה ) בסוגריים.")
        originals = [p.original for p in proposals]
        self.assertIn("( ", originals)
        self.assertIn(" )", originals)


def _qt_available() -> bool:
    try:
        from PySide6.QtWidgets import QApplication  # noqa: F401
        return True
    except Exception:
        return False


class _SampleStyleModule(SuggestionModule):
    id = "sample-style"
    name = "בדיקת סגנון לדוגמה"
    kind = KIND_STYLE
    enabled_by_default = False

    def check(self, text: str) -> list[Suggestion]:
        idx = text.find("בגלל ש")
        if idx < 0:
            return []
        return [
            Suggestion(
                module=KIND_STYLE,
                original="בגלל ש",
                replacement="משום ש",
                message="העדפה סגנונית בלשון הספר",
                start=idx,
                end=idx + len("בגלל ש"),
            )
        ]


@unittest.skipUnless(_qt_available(), "PySide6 GUI runtime not available")
class LayerIndependenceUITests(unittest.TestCase):
    def setUp(self) -> None:
        from pathlib import Path
        from PIL import Image
        from hebrew_workbench.ui.main_window import MainWindow
        from tests.qt_app import application, temporary_home

        self.app = application()
        self.home = temporary_home()
        self._page = Path(self.home.name) / "page.png"
        Image.new("RGB", (60, 30), "white").save(self._page)
        self.window = MainWindow()
        self.window.project.add(self._page)
        self.window._sync_document_list()
        self.window.doc_list.setCurrentRow(0)

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.home.cleanup()

    def test_spelling_grammar_and_style_layers_toggle_independently_and_persist(self) -> None:
        from hebrew_workbench.ui.main_window import MainWindow

        pane = self.window.suggestions_pane
        # Default startup: spelling ON, grammar ON, style OFF.
        self.assertTrue(pane.spelling_toggle.isChecked())
        self.assertTrue(pane.grammar_toggle.isChecked())
        self.assertFalse(pane.style_toggle.isChecked())
        self.assertTrue(self.window.toggle_spelling_action.isChecked())
        self.assertTrue(self.window.toggle_grammar_action.isChecked())
        self.assertFalse(self.window.toggle_style_action.isChecked())

        # Mixed sample containing 1 spelling error ("התלמיריס") and 1 grammar error ("אני ילך").
        sample = "בגלל שהשיעור התחיל אני ילך עם התלמיריס לכיתה."
        self.window.editor.setPlainText(sample)
        self.window.check_suggestions()
        kinds_both = {s.module for s in self.window.suggestions.pending()}
        self.assertEqual(kinds_both, {"spelling", "grammar"})

        # Disable spelling -> only grammar remains.
        pane.spelling_toggle.setChecked(False)
        self.assertFalse(self.window.toggle_spelling_action.isChecked())
        kinds_grammar_only = {s.module for s in self.window.suggestions.pending()}
        self.assertEqual(kinds_grammar_only, {"grammar"})

        # Enable spelling and disable grammar -> only spelling remains.
        pane.spelling_toggle.setChecked(True)
        pane.grammar_toggle.setChecked(False)
        self.assertTrue(self.window.toggle_spelling_action.isChecked())
        self.assertFalse(self.window.toggle_grammar_action.isChecked())
        kinds_spelling_only = {s.module for s in self.window.suggestions.pending()}
        self.assertEqual(kinds_spelling_only, {"spelling"})

        # Register an active style module and verify style toggles independently.
        from hebrew_workbench.suggestions import SuggestionRegistry

        pane.spelling_toggle.setChecked(False)
        self.window.suggestion_modules = SuggestionRegistry([_SampleStyleModule()])
        self.window.suggestion_modules.set_enabled(KIND_STYLE, True)
        self.window.check_suggestions()
        self.assertEqual(
            {s.module for s in self.window.suggestions.pending()}, {"style"}
        )
        self.window.suggestion_modules.set_enabled(KIND_STYLE, False)
        self.window.check_suggestions()
        self.assertEqual(self.window.suggestions.pending(), [])

        # Toggle built-in style layer ON and verify plugin state persists across restart.
        pane.style_toggle.setChecked(True)
        second = MainWindow()
        try:
            self.assertFalse(second.suggestions_pane.spelling_toggle.isChecked())
            self.assertFalse(second.suggestions_pane.grammar_toggle.isChecked())
            self.assertTrue(second.suggestions_pane.style_toggle.isChecked())
        finally:
            second.close()
            second.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
