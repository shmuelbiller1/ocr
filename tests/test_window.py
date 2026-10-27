"""Tests for the main window: the documents and the text of every document."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

if sys.platform.startswith("linux"):
    # The machine that runs the tests has no screen.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hebrew_workbench.suggestions.session import AcceptedChange  # noqa: E402
from hebrew_workbench.ui.main_window import MainWindow  # noqa: E402
from tests.qt_app import application  # noqa: E402


class DocumentTextTests(unittest.TestCase):
    """Every document keeps its own text."""

    def setUp(self) -> None:
        self.app = application()
        self.window = MainWindow()
        self.pages = self.sample_pages()

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def sample_pages(self) -> list:
        from hebrew_workbench.resources import samples_directory

        samples = samples_directory()
        if samples is None:
            return []
        return sorted(samples.glob("scan_page_*.png"))

    def add_two_documents(self) -> None:
        if len(self.pages) < 2:
            self.skipTest("the sample pages are not available here")
        self.window.project.add(self.pages[0])
        self.window.project.add(self.pages[1])
        self.window._sync_document_list()
        self.window.doc_list.setCurrentRow(0)

    def test_the_text_of_a_document_is_kept_when_another_one_is_chosen(self) -> None:
        self.add_two_documents()
        first = self.window.project[0]
        second = self.window.project[1]

        self.window.editor.setPlainText("הטקסט של המסמך הראשון")
        self.assertEqual(first.transcription, "הטקסט של המסמך הראשון")

        self.window.doc_list.setCurrentRow(1)
        self.app.processEvents()

        # The text of the first document is still there, and the second
        # document did not get it.
        self.assertEqual(first.transcription, "הטקסט של המסמך הראשון")
        self.assertEqual(second.transcription, "")
        self.assertEqual(self.window.editor.toPlainText(), "")

    def test_the_text_comes_back_when_the_document_is_chosen_again(self) -> None:
        self.add_two_documents()
        self.window.editor.setPlainText("הטקסט של המסמך הראשון")
        self.window.doc_list.setCurrentRow(1)
        self.app.processEvents()
        self.window.doc_list.setCurrentRow(0)
        self.app.processEvents()
        self.assertEqual(self.window.editor.toPlainText(), "הטקסט של המסמך הראשון")

    def test_removing_a_document_clears_the_editor(self) -> None:
        self.add_two_documents()
        self.window.editor.setPlainText("הטקסט של המסמך הראשון")
        self.window.doc_list.setCurrentRow(1)
        self.app.processEvents()
        self.window.doc_list.clearSelection()
        self.window.doc_list.item(1).setSelected(True)
        self.window.remove_selected_documents()
        self.assertEqual(self.window.editor.toPlainText(), "")
        self.assertEqual(len(self.window.project), 1)

    def test_removing_another_document_keeps_the_text_of_the_shown_one(self) -> None:
        """The text of the shown document is not lost when another one goes."""
        self.add_two_documents()
        self.window.editor.setPlainText("הטקסט של המסמך הראשון")
        first = self.window.project[0]

        # The second document is removed, and the first one is shown.
        self.window.doc_list.clearSelection()
        self.window.doc_list.item(1).setSelected(True)
        self.window.remove_selected_documents()
        self.assertEqual(len(self.window.project), 1)
        self.assertEqual(first.transcription, "הטקסט של המסמך הראשון")

        # The text is not written over with the empty text of the editor.
        self.window.doc_list.setCurrentRow(0)
        self.app.processEvents()
        self.assertEqual(first.transcription, "הטקסט של המסמך הראשון")

    def test_the_result_of_the_recognition_stays_with_its_document(self) -> None:
        """A recognition that finishes after the user moved on is safe."""
        self.add_two_documents()
        first = self.window.project[0]
        second = self.window.project[1]

        class Result:
            text = "תוצאת הזיהוי"
            engine_name = "מנוע הבדיקה"
            duration_seconds = 1.5

        # The recognition of the first document is still running, and the
        # user moves to the second document.
        self.window.doc_list.setCurrentRow(1)
        self.app.processEvents()
        self.window.editor.setPlainText("הטקסט של המסמך השני")

        self.window._on_ocr_done(Result(), first)

        # The result belongs to the first document, and the editor of
        # the second one was left alone.
        self.assertEqual(first.transcription, "תוצאת הזיהוי")
        self.assertEqual(self.window.editor.toPlainText(), "הטקסט של המסמך השני")
        self.assertEqual(second.transcription, "הטקסט של המסמך השני")

    def test_the_recognition_clears_the_corrections_of_the_old_text(self) -> None:
        """The corrections of the old text do not belong to the new text."""
        self.add_two_documents()
        first = self.window.project[0]
        self.window.doc_list.setCurrentRow(0)
        self.app.processEvents()

        class Result:
            text = "תוצאת הזיהוי"
            engine_name = "מנוע הבדיקה"
            duration_seconds = 1.5

        # The document has corrections of an earlier text.
        first.changes = [
            {
                "module": "spelling",
                "original": "שלום ,",
                "replacement": "שלום,",
                "position": 0,
                "message": "",
            }
        ]
        self.window._on_ocr_done(Result(), first)

        self.assertEqual(first.changes, [])
        self.assertEqual(self.window.suggestions.accepted, [])
        self.assertEqual(self.window.suggestions.current_text, "תוצאת הזיהוי")
        self.assertFalse(self.window.suggestions.undo_available)

    def test_the_list_shows_the_document_that_is_in_the_editor(self) -> None:
        """After a removal the list and the editor show the same document."""
        self.add_two_documents()
        first = self.window.project[0]
        self.window.editor.setPlainText("הטקסט של המסמך הראשון")
        self.window.doc_list.setCurrentRow(0)
        self.app.processEvents()

        # The second document is removed, and the first one stays in
        # the editor.
        self.window.doc_list.clearSelection()
        self.window.doc_list.item(1).setSelected(True)
        self.window.remove_selected_documents()

        self.assertEqual(self.window.doc_list.currentRow(), 0)
        self.assertIs(self.window._shown_entry, first)

    def test_opening_another_project_forgets_the_old_one(self) -> None:
        """The proposals of one project are not offered in another."""
        self.add_two_documents()
        self.window.doc_list.setCurrentRow(0)
        self.app.processEvents()
        session = self.window.suggestions
        session.current_text = "שלום ,עולם"
        session.accepted.append(
            AcceptedChange("spelling", "שלום ,", "שלום,", 0, "")
        )
        self.assertTrue(session.undo_available)

        from hebrew_workbench.project import Project

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "work.hwproj"
            Project().save(path)
            self.assertTrue(self.window.load_project(path))
            # The old project is gone, and with it the proposals.
            self.assertEqual(len(self.window.project), 0)
            self.assertEqual(self.window.editor.toPlainText(), "")
            self.assertFalse(self.window.suggestions.undo_available)
            self.assertEqual(self.window.suggestions.pending(), [])


if __name__ == "__main__":
    unittest.main()
