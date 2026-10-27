"""Tests for the pane of the proposals and for its use in the window."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

if sys.platform.startswith("linux"):
    # The machine that runs the tests has no screen.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hebrew_workbench.suggestions import KIND_GRAMMAR, Suggestion
from hebrew_workbench.ui.suggestions_pane import SuggestionsPane
from tests.qt_app import application  # noqa: E402


class SuggestionsPaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = application()
        self.pane = SuggestionsPane()

    def tearDown(self) -> None:
        self.pane.deleteLater()
        self.app.processEvents()

    def make_suggestion(self) -> Suggestion:
        return Suggestion(
            module=KIND_GRAMMAR,
            original=" ,",
            replacement=",",
            message="אין רווח לפני הפסיק",
            start=4,
            end=6,
        )

    def test_the_pane_shows_the_proposals(self) -> None:
        self.pane.show_suggestions([self.make_suggestion()])
        self.assertIn("1", self.pane.summary.text())

    def test_the_pane_says_when_there_are_no_proposals(self) -> None:
        self.pane.show_suggestions([])
        self.assertIn("אין", self.pane.summary.text())

    def test_the_pane_asks_to_undo(self) -> None:
        asked: list[bool] = []
        self.pane.undo_requested.connect(lambda: asked.append(True))
        self.pane.undo_button.setEnabled(True)
        self.pane.undo_button.click()
        self.assertEqual(asked, [True])


class WindowSuggestionsTests(unittest.TestCase):
    """The window applies a proposal only when the user accepts it."""

    def setUp(self) -> None:
        self.app = application()
        from hebrew_workbench.ui.main_window import MainWindow

        self.window = MainWindow()

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def sample_page(self) -> Path | None:
        from hebrew_workbench.resources import samples_directory

        samples = samples_directory()
        if samples is None:
            return None
        pages = sorted(samples.glob("scan_page_*.png"))
        return pages[0] if pages else None

    def add_document(self) -> None:
        page = self.sample_page()
        if page is None:
            self.skipTest("the sample pages are not available here")
        self.window.project.add(page)
        self.window._sync_document_list()
        self.window.doc_list.setCurrentRow(0)

    def make_suggestion(self) -> Suggestion:
        return Suggestion(
            module=KIND_GRAMMAR,
            original=" ,",
            replacement=",",
            message="אין רווח לפני הפסיק",
            start=4,
            end=6,
        )

    def test_checking_the_text_shows_the_proposals(self) -> None:
        self.add_document()
        self.window.editor.setPlainText("שלום , עולם")
        self.window.check_suggestions()
        self.assertEqual(len(self.window.suggestions.pending()), 1)
        self.assertFalse(self.window.suggestions_dock.isHidden())

    def test_accepting_a_proposal_changes_the_text_and_is_logged(self) -> None:
        self.add_document()
        self.window.editor.setPlainText("שלום , עולם")
        self.window.check_suggestions()
        self.window.accept_suggestion(self.window.suggestions.pending()[0])
        self.assertEqual(self.window.editor.toPlainText(), "שלום, עולם")
        self.assertEqual(len(self.window.project[0].changes), 1)

    def test_refusing_a_proposal_leaves_the_text_alone(self) -> None:
        self.add_document()
        self.window.editor.setPlainText("שלום , עולם")
        self.window.check_suggestions()
        self.window.refuse_suggestion(self.window.suggestions.pending()[0])
        self.assertEqual(self.window.editor.toPlainText(), "שלום , עולם")
        self.assertEqual(self.window.project[0].changes, [])

    def test_the_changes_can_be_undone(self) -> None:
        self.add_document()
        self.window.editor.setPlainText("שלום , עולם")
        self.window.check_suggestions()
        self.window.accept_suggestion(self.window.suggestions.pending()[0])
        self.assertEqual(self.window.editor.toPlainText(), "שלום, עולם")
        self.window.undo_all_changes()
        self.assertEqual(self.window.editor.toPlainText(), "שלום , עולם")
        self.assertEqual(self.window.project[0].changes, [])

    def test_the_spell_checker_needs_a_word_list(self) -> None:
        module = self.window.suggestion_modules.module("spelling")
        self.assertIsNotNone(module)
        self.assertFalse(module.available())
        with tempfile.TemporaryDirectory() as folder:
            words = Path(folder) / "words.txt"
            words.write_text("שלום\nעולם\n", encoding="utf-8")
            module.set_dictionary(words)
            self.assertTrue(module.available())
            proposals = module.check("זהו טקסט")
            self.assertTrue(proposals)


if __name__ == "__main__":
    unittest.main()
