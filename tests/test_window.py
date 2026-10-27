"""Tests for the main window: the documents and the text of every document."""

from __future__ import annotations

import os
import sys
import unittest

if sys.platform.startswith("linux"):
    # The machine that runs the tests has no screen.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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


if __name__ == "__main__":
    unittest.main()
