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
from tests.qt_app import application, temporary_home  # noqa: E402


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

        self.home = temporary_home()
        self.window = MainWindow()

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.home.cleanup()

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

    def add_two_documents(self) -> None:
        from hebrew_workbench.resources import samples_directory

        samples = samples_directory()
        if samples is None:
            self.skipTest("the sample pages are not available here")
        pages = sorted(samples.glob("scan_page_*.png"))
        if len(pages) < 2:
            self.skipTest("the sample pages are not available here")
        self.window.project.add(pages[0])
        self.window.project.add(pages[1])
        self.window._sync_document_list()
        self.window.doc_list.setCurrentRow(0)

    def test_the_proposals_of_one_document_are_not_offered_for_another(self) -> None:
        """The proposals belong to the document they were made for."""
        self.add_two_documents()
        self.window.editor.setPlainText("שלום , עולם")
        self.window.check_suggestions()
        self.assertEqual(len(self.window.suggestions.pending()), 1)

        # The user moves to the other document.
        self.window.doc_list.setCurrentRow(1)
        self.app.processEvents()
        self.assertEqual(self.window.suggestions.pending(), [])

        # The proposal of the first document is not applied to the second.
        self.window.editor.setPlainText("טקסט של המסמך השני")
        stale = Suggestion(
            module=KIND_GRAMMAR,
            original=" ,",
            replacement=",",
            message="אין רווח לפני הפסיק",
            start=4,
            end=6,
        )
        self.window.accept_suggestion(stale)
        self.assertEqual(self.window.editor.toPlainText(), "טקסט של המסמך השני")

    def test_a_proposal_is_not_applied_when_the_text_was_changed_after_the_check(
        self,
    ) -> None:
        """What the user wrote after the check is not thrown away."""
        self.add_document()
        self.window.editor.setPlainText("שלום , עולם")
        self.window.check_suggestions()
        suggestion = self.window.suggestions.pending()[0]

        # The user writes something else before accepting.
        self.window.editor.setPlainText("שלום , עולם ועוד")
        self.window.accept_suggestion(suggestion)
        self.assertEqual(self.window.editor.toPlainText(), "שלום , עולם ועוד")

    def test_the_undo_is_still_there_after_a_new_check(self) -> None:
        self.add_document()
        self.window.editor.setPlainText("שלום , עולם")
        self.window.check_suggestions()
        self.window.accept_suggestion(self.window.suggestions.pending()[0])
        self.assertTrue(self.window.suggestions_pane.undo_button.isEnabled())

        # A new check does not take away the possibility to undo.
        self.window.check_suggestions()
        self.assertTrue(self.window.suggestions_pane.undo_button.isEnabled())

    def test_the_accepted_changes_come_back_when_the_project_is_opened(self) -> None:
        self.add_document()
        self.window.editor.setPlainText("שלום , עולם")
        self.window.check_suggestions()
        self.window.accept_suggestion(self.window.suggestions.pending()[0])
        self.assertEqual(len(self.window.project[0].changes), 1)

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "work.hwproj"
            self.window.project.save(path)

            from hebrew_workbench.ui.main_window import MainWindow

            other = MainWindow()
            try:
                other.project = type(self.window.project).load(path)
                other._sessions.clear()
                other._sync_document_list()
                other.doc_list.setCurrentRow(0)
                other.app = self.app
                self.app.processEvents()
                self.assertEqual(len(other.suggestions.accepted), 1)
                self.assertTrue(other.suggestions_pane.undo_button.isEnabled())
            finally:
                other.close()
                other.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
