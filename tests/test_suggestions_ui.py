"""Tests for the pane of the proposals and for its use in the window."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_the_proposals_are_cleared_when_the_word_list_changes(self) -> None:
        """The proposals of the old word list are not offered any more."""
        self.add_two_documents()

        # The first document has proposals.
        self.window.doc_list.setCurrentRow(0)
        self.app.processEvents()
        self.window.editor.setPlainText("שלום , עולם")
        self.window.check_suggestions()
        self.assertEqual(len(self.window.suggestions.pending()), 1)
        first = self.window.suggestions

        # The second document has proposals as well, and it is not the
        # one that is shown.
        self.window.doc_list.setCurrentRow(1)
        self.app.processEvents()
        self.window.editor.setPlainText("טקסט של המסמך השני , עולם")
        self.window.check_suggestions()
        other = self.window.suggestions
        self.assertEqual(len(other.pending()), 1)
        self.assertIsNot(first, other)

        # The user chooses another word list.
        with tempfile.TemporaryDirectory() as folder:
            words = Path(folder) / "words.txt"
            words.write_text("שלום\nעולם\n", encoding="utf-8")
            with mock.patch(
                "hebrew_workbench.ui.main_window.QFileDialog.getOpenFileName",
                return_value=(str(words), ""),
            ):
                self.window.choose_dictionary()

        # The proposals of the old word list are gone, in every
        # document and not only in the one that is shown.
        self.assertEqual(first.pending(), [])
        self.assertEqual(other.pending(), [])

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


class BulkActionsTests(unittest.TestCase):
    """The proposals of the document as a whole, and not one by one."""

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

    def add_document(self) -> None:
        from hebrew_workbench.resources import samples_directory

        samples = samples_directory()
        if samples is None:
            self.skipTest("the sample pages are not available here")
        pages = sorted(samples.glob("scan_page_*.png"))
        if not pages:
            self.skipTest("the sample pages are not available here")
        self.window.project.add(pages[0])
        self.window._sync_document_list()
        self.window.doc_list.setCurrentRow(0)

    def make_suggestions(self) -> None:
        """Two proposals in the text of the document."""
        self.add_document()
        self.window.editor.setPlainText("שלום ,עולם ועוד ,דבר")
        self.window.check_suggestions()
        self.assertGreaterEqual(len(self.window.suggestions.pending()), 2)

    def test_all_the_proposals_are_accepted_at_once(self) -> None:
        self.make_suggestions()
        before = len(self.window.suggestions.pending())
        self.window.accept_all_suggestions()
        self.assertEqual(self.window.suggestions.pending(), [])
        self.assertEqual(self.window.editor.toPlainText(), "שלום,עולם ועוד,דבר")
        self.assertGreater(before, 1)

    def test_all_the_proposals_are_refused_at_once(self) -> None:
        self.make_suggestions()
        self.window.refuse_all_suggestions()
        self.assertEqual(self.window.suggestions.pending(), [])
        self.assertEqual(self.window.editor.toPlainText(), "שלום ,עולם ועוד ,דבר")

    def test_the_proposals_that_were_marked_are_accepted(self) -> None:
        self.make_suggestions()
        rows = self.window.suggestions_pane._rows
        rows[0].checkbox.setChecked(True)
        marked = self.window.suggestions_pane.checked_suggestions()
        self.assertEqual(len(marked), 1)
        before = len(self.window.suggestions.pending())
        self.window.accept_selected_suggestions(marked)
        after = self.window.suggestions.pending()
        # The one that was marked is not waiting any more.
        self.assertNotIn(marked[0], after)
        self.assertLess(len(after), before)

    def test_the_proposals_that_were_marked_are_refused(self) -> None:
        self.make_suggestions()
        rows = self.window.suggestions_pane._rows
        rows[0].checkbox.setChecked(True)
        marked = self.window.suggestions_pane.checked_suggestions()
        before = len(self.window.suggestions.pending())
        self.window.refuse_selected_suggestions(marked)
        after = self.window.suggestions.pending()
        self.assertNotIn(marked[0], after)
        self.assertLess(len(after), before)

    def test_the_last_group_is_taken_back_as_one_action(self) -> None:
        self.make_suggestions()
        self.window.accept_all_suggestions()
        self.assertTrue(self.window.suggestions.has_batch)
        self.window.undo_last_batch()
        self.assertEqual(self.window.editor.toPlainText(), "שלום ,עולם ועוד ,דבר")
        self.assertFalse(self.window.suggestions.has_batch)

    def test_the_text_goes_back_to_what_the_recognition_gave(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        # The user is asked before the text he wrote is thrown away.
        original = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        self.addCleanup(lambda: setattr(QMessageBox, "question", original))

        self.add_document()
        self.window.editor.setPlainText("הטקסט של הזיהוי")
        self.window.project[0].original_transcription = "הטקסט של הזיהוי"
        self.window.editor.setPlainText("הטקסט של הזיהוי עם תיקון")
        self.window.restore_original_text()
        self.assertEqual(self.window.editor.toPlainText(), "הטקסט של הזיהוי")


class WordActionsTests(unittest.TestCase):
    """The actions that are done on one word in all its places."""

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

    def add_document(self) -> None:
        from hebrew_workbench.resources import samples_directory

        samples = samples_directory()
        if samples is None:
            self.skipTest("the sample pages are not available here")
        pages = sorted(samples.glob("scan_page_*.png"))
        if not pages:
            self.skipTest("the sample pages are not available here")
        self.window.project.add(pages[0])
        self.window._sync_document_list()
        self.window.doc_list.setCurrentRow(0)

    def make_word_suggestion(self, text: str, word: str):
        from hebrew_workbench.suggestions import Suggestion

        self.add_document()
        self.window.editor.setPlainText(text)
        self.window.check_suggestions()
        start = text.find(word)
        return Suggestion(
            module="spelling",
            original=word,
            replacement=word + "ים",
            message="אפשרות נוספת למילה",
            start=start,
            end=start + len(word),
            kind="word",
        )

    def test_the_word_is_changed_in_every_place_it_appears(self) -> None:
        suggestion = self.make_word_suggestion("ספר טוב ספר", "ספר")
        self.window.accept_every_occurrence(suggestion)
        self.assertEqual(self.window.editor.toPlainText(), "ספרים טוב ספרים")

    def test_the_places_can_be_taken_back_as_one_action(self) -> None:
        suggestion = self.make_word_suggestion("ספר טוב ספר", "ספר")
        self.window.accept_every_occurrence(suggestion)
        self.window.undo_last_batch()
        self.assertEqual(self.window.editor.toPlainText(), "ספר טוב ספר")

    def test_a_word_that_the_user_keeps_is_not_proposed_any_more(self) -> None:
        import tempfile
        from pathlib import Path

        suggestion = self.make_word_suggestion("מילה טובה", "מילה")
        module = self.window.suggestion_modules.module("spelling")
        if module is None:
            self.skipTest("the spelling module is not available here")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "words.txt"
            path.write_text("טובה\n", encoding="utf-8")
            module.set_dictionary(path)
            self.window.keep_word(suggestion)
            # The word is in the list of the user, and it is not
            # proposed again.
            self.assertIn("מילה", path.read_text(encoding="utf-8"))
            self.assertNotIn(
                "מילה",
                [item.original for item in self.window.suggestions.pending()],
            )


class BrokenPluginTests(unittest.TestCase):
    """A plugin that is in a fatal mistake is not used any more."""

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

    def add_document(self) -> None:
        from hebrew_workbench.resources import samples_directory

        samples = samples_directory()
        if samples is None:
            self.skipTest("the sample pages are not available here")
        pages = sorted(samples.glob("scan_page_*.png"))
        if not pages:
            self.skipTest("the sample pages are not available here")
        self.window.project.add(pages[0])
        self.window._sync_document_list()
        self.window.doc_list.setCurrentRow(0)

    def test_a_plugin_that_failed_is_not_called_any_more(self) -> None:
        """The window refreshes its modules when the setting was refused.

        The registry of the plugins does not use a plugin that is in a
        fatal mistake, and the window must not keep the old object of
        that plugin and call it.
        """
        self.add_document()
        self.window.editor.setPlainText("שלום , עולם")
        self.window.check_suggestions()
        self.assertTrue(self.window.suggestions.pending())

        # The plugin refuses the word list, and the old setting cannot
        # be put back either: the plugin is in a fatal mistake.
        plugin_id = self.window._spelling_plugin_id()
        plugin = self.window.plugins.get(plugin_id)
        self.assertIsNotNone(plugin)
        plugin.error = "the settings of the plugin could not be used"
        with tempfile.TemporaryDirectory() as folder:
            words = Path(folder) / "words.txt"
            words.write_text("שלום\n", encoding="utf-8")
            with mock.patch.object(
                self.window.plugins, "set_option", return_value=False
            ), mock.patch(
                "hebrew_workbench.ui.main_window.QMessageBox.warning"
            ), mock.patch(
                "hebrew_workbench.ui.main_window.QFileDialog.getOpenFileName",
                return_value=(str(words), ""),
            ):
                self.window.choose_dictionary()

        # The module of the broken plugin is not in the window any more,
        # and the proposals that it made are gone.
        self.assertIsNone(self.window.suggestion_modules.module("spelling"))
        self.assertEqual(self.window.suggestions.pending(), [])


class AlternativeTests(unittest.TestCase):
    """A wording that is chosen in the box is applied only when the
    user presses the button."""

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

    def add_document(self) -> None:
        from hebrew_workbench.resources import samples_directory

        samples = samples_directory()
        if samples is None:
            self.skipTest("the sample pages are not available here")
        pages = sorted(samples.glob("scan_page_*.png"))
        if not pages:
            self.skipTest("the sample pages are not available here")
        self.window.project.add(pages[0])
        self.window._sync_document_list()
        self.window.doc_list.setCurrentRow(0)

    def make_row(self):
        """A proposal with two other wordings."""
        suggestion = Suggestion(
            module=KIND_GRAMMAR,
            original="שלום",
            replacement="שדי",
            message="מילה אחרת",
            start=0,
            end=4,
            alternatives=("תחתונות", "משלום"),
        )
        from hebrew_workbench.ui.suggestions_pane import SuggestionRow

        row = SuggestionRow(suggestion)
        self.addCleanup(row.deleteLater)
        return row

    def test_choosing_a_wording_does_not_change_anything(self) -> None:
        row = self.make_row()
        chosen: list[tuple] = []
        row.alternative_chosen_requested.connect(
            lambda suggestion, text: chosen.append((suggestion, text))
        )
        # The user scrolls the box and chooses another wording.
        row.alternatives.setCurrentText("תחתונות")
        self.assertEqual(chosen, [])
        # The wording is applied when the button is pressed.
        row._accept_clicked()
        self.assertEqual(len(chosen), 1)
        self.assertEqual(chosen[0][1], "תחתונות")

    def test_the_button_accepts_the_proposal_when_no_was_chosen(self) -> None:
        row = self.make_row()
        accepted: list = []
        row.accept_requested.connect(lambda suggestion: accepted.append(suggestion))
        row._accept_clicked()
        self.assertEqual(len(accepted), 1)

    def test_the_original_proposal_is_not_waiting_after_an_alternative(self) -> None:
        self.add_document()
        self.window.editor.setPlainText("שלום")
        self.window.check_suggestions()
        session = self.window.suggestions
        suggestion = Suggestion(
            module=KIND_GRAMMAR,
            original="שלום",
            replacement="שדי",
            message="מילה אחרת",
            start=0,
            end=4,
            alternatives=("תחתונות",),
        )
        session.set_suggestions([suggestion], "שלום")
        self.window.accept_alternative(suggestion, "תחתונות")
        # The proposal that was offered is not waiting any more.
        self.assertEqual(session.pending(), [])


class UndoReportTests(unittest.TestCase):
    """The changes that could not be taken back are told to the user."""

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

    def add_document(self) -> None:
        from hebrew_workbench.resources import samples_directory

        samples = samples_directory()
        if samples is None:
            self.skipTest("the sample pages are not available here")
        pages = sorted(samples.glob("scan_page_*.png"))
        if not pages:
            self.skipTest("the sample pages are not available here")
        self.window.project.add(pages[0])
        self.window._sync_document_list()
        self.window.doc_list.setCurrentRow(0)

    def test_the_user_is_told_when_a_change_could_not_be_taken_back(self) -> None:
        self.add_document()
        self.window.editor.setPlainText("שלום ,עולם")
        self.window.check_suggestions()
        self.window.accept_all_suggestions()
        # The user writes something around the change.
        self.window.editor.setPlainText("שלום, עולם שלי")
        self.window.undo_last_batch()
        message = self.window.statusBar().currentMessage()
        self.assertIn("לא ניתן לבטל", message)


class ManualEditTests(unittest.TestCase):
    """What the user wrote is not thrown away without a question."""

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

    def add_document(self) -> None:
        from hebrew_workbench.resources import samples_directory

        samples = samples_directory()
        if samples is None:
            self.skipTest("the sample pages are not available here")
        pages = sorted(samples.glob("scan_page_*.png"))
        if not pages:
            self.skipTest("the sample pages are not available here")
        self.window.project.add(pages[0])
        self.window._sync_document_list()
        self.window.doc_list.setCurrentRow(0)

    def test_the_document_remembers_that_the_user_wrote_in_it(self) -> None:
        self.add_document()
        self.window.editor.setPlainText("טקסט")
        self.assertTrue(self.window.project[0].edited)

    def test_the_question_is_asked_after_the_proposals_were_checked(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        asked: list[bool] = []
        original = QMessageBox.question

        def question(*args, **kwargs):
            asked.append(True)
            return QMessageBox.No

        QMessageBox.question = staticmethod(question)
        self.addCleanup(lambda: setattr(QMessageBox, "question", original))

        self.add_document()
        self.window.project[0].original_transcription = "הטקסט של הזיהוי"
        # The user writes something by hand.
        self.window.editor.setPlainText("הטקסט של הזיהוי עם תיקון")
        # The proposals are checked again.
        self.window.check_suggestions()
        # Going back to the text of the recognition asks the user.
        self.window.restore_original_text()
        self.assertEqual(asked, [True])
        # The text of the user is still there.
        self.assertEqual(self.window.editor.toPlainText(), "הטקסט של הזיהוי עם תיקון")

    def test_the_project_keeps_what_the_user_wrote(self) -> None:
        import tempfile
        from hebrew_workbench.project import Project

        self.add_document()
        self.window.editor.setPlainText("טקסט")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "project.hwproj"
            self.window.project.save(path)
            project = Project.load(path)
            self.assertTrue(project[0].edited)
