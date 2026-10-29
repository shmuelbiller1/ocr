"""Tests for the main window: the documents and the text of every document."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

if sys.platform.startswith("linux"):
    # The machine that runs the tests has no screen.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hebrew_workbench.engine.registry import EngineRegistry  # noqa: E402
from hebrew_workbench.suggestions.session import AcceptedChange  # noqa: E402
from hebrew_workbench.ui.main_window import MainWindow  # noqa: E402
from tests.qt_app import application, temporary_home  # noqa: E402


class DocumentTextTests(unittest.TestCase):
    """Every document keeps its own text."""

    def setUp(self) -> None:
        self.app = application()
        self.home = temporary_home()
        self.window = MainWindow()
        self.pages = self.sample_pages()

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.home.cleanup()

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

    def test_assisted_output_is_reviewed_and_never_auto_applied(self) -> None:
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        from hebrew_workbench.engine.base import OCRResult
        self.add_two_documents()
        entry = self.window.project[0]
        result = OCRResult("raw original", "Mishkefet", assisted_text="assisted alternative",
                           decoding_mode="assisted")
        self.window._on_ocr_done(result, entry)
        self.assertEqual(self.window.editor.toPlainText(), "raw original")
        self.assertEqual(entry.original_transcription, "raw original")
        self.assertEqual(self.window.assisted_reading.toPlainText(), "assisted alternative")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
            self.window.use_assisted_reading()
        self.assertEqual(self.window.editor.toPlainText(), "raw original")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            self.window.use_assisted_reading()
        self.assertEqual(self.window.editor.toPlainText(), "assisted alternative")
        self.assertEqual(entry.original_transcription, "raw original")
        self.window.editor.undo()
        self.assertEqual(self.window.editor.toPlainText(), "raw original")
        self.window.doc_list.setCurrentRow(1)
        self.assertEqual(self.window.assisted_reading.toPlainText(), "")
        self.window.doc_list.setCurrentRow(0)
        self.assertEqual(self.window.assisted_reading.toPlainText(), "assisted alternative")

    def test_assisted_apply_cannot_modify_the_recognizing_document(self) -> None:
        self.add_two_documents()
        entry = self.window.project[0]
        entry.assisted_transcription = "alternative"
        self.window.editor.setPlainText("manual")
        self.window._recognizing_entry = entry
        self.window.use_assisted_reading()
        self.assertEqual(self.window.editor.toPlainText(), "manual")
        self.window._recognizing_entry = None

    def test_only_the_document_being_recognized_is_read_only(self) -> None:
        self.add_two_documents()
        self.window._recognizing_entry = self.window.project[0]
        self.window._show_entry(self.window.project[0])
        self.assertTrue(self.window.editor.isReadOnly())
        self.window.doc_list.setCurrentRow(1)
        self.assertFalse(self.window.editor.isReadOnly())
        self.window.doc_list.setCurrentRow(0)
        self.assertTrue(self.window.editor.isReadOnly())
        self.window._on_task_finished()
        self.assertFalse(self.window.editor.isReadOnly())

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




class UnsavedWorkTests(unittest.TestCase):
    """The program asks before it throws the work of the user away."""

    def setUp(self) -> None:
        self.app = application()
        self.home = temporary_home()
        self.window = MainWindow()

    def tearDown(self) -> None:
        self.window.close()

    def answer_the_question(self, answer) -> list:
        from PySide6.QtWidgets import QMessageBox

        asked = []

        def question(*args, **kwargs):
            asked.append(args[1] if len(args) > 1 else "")
            return answer

        original = QMessageBox.question
        QMessageBox.question = staticmethod(question)
        self.addCleanup(lambda: setattr(QMessageBox, "question", original))
        return asked

    def test_the_user_is_asked_before_the_window_is_closed(self) -> None:
        """The text of the user is not in a project file, and the
        program has to ask before it is lost."""
        self.window.editor.setPlainText("מה שהמשתמש הקליד")
        asked = self.answer_the_question(self.no())
        self.window.close()
        self.assertTrue(asked)

    def test_the_window_stays_open_when_the_user_refuses(self) -> None:
        self.window.editor.setPlainText("מה שהמשתמש הקליד")
        self.answer_the_question(self.no())
        self.window.show()
        self.window.close()
        self.assertTrue(self.window.isVisible())

    def test_the_result_of_the_recognition_is_work_that_was_not_saved(self) -> None:
        """The program puts the text of the recognition in the editor,
        and it is not in a project file."""

        class Result:
            text = "תוצאת הזיהוי"
            engine_name = "מנוע הבדיקה"
            duration_seconds = 1.5

        self.window.project.add(Path(__file__))
        self.window._sync_document_list()
        self.window.doc_list.setCurrentRow(0)
        self.window._on_ocr_done(Result(), self.window.project[0])
        self.assertTrue(self.window.project.dirty)
        asked = self.answer_the_question(self.no())
        self.window.close()
        self.assertTrue(asked)

    def test_the_text_without_a_document_is_not_in_the_project(self) -> None:
        """The text that the user typed without choosing a document is
        not in the file of the project, and the program asks about it."""
        from PySide6.QtWidgets import QFileDialog

        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "the-project.hwb"
            original = QFileDialog.getSaveFileName
            QFileDialog.getSaveFileName = staticmethod(
                lambda *args, **kwargs: (str(target), "")
            )
            self.addCleanup(
                lambda: setattr(QFileDialog, "getSaveFileName", original)
            )
            self.window.editor.setPlainText("מה שהמשתמש הקליד")
            self.window.save_project()
        self.assertTrue(self.window.project.dirty)
        asked = self.answer_the_question(self.no())
        self.window.close()
        self.assertTrue(asked)

    def test_nothing_is_asked_when_the_work_was_saved(self) -> None:
        """The text is in a project file, and there is nothing to lose."""
        with tempfile.TemporaryDirectory() as folder:
            self.window.editor.setPlainText("מה שהמשתמש הקליד")
            self.window.project.save(Path(folder) / "the-project.hwb")
        asked = self.answer_the_question(self.no())
        self.window.close()
        self.assertFalse(asked)

    def test_the_work_is_not_asked_about_when_the_window_is_empty(self) -> None:
        asked = self.answer_the_question(self.no())
        self.window.close()
        self.assertFalse(asked)

    @staticmethod
    def no():
        from PySide6.QtWidgets import QMessageBox

        return QMessageBox.No


class ExportOverwriteTests(unittest.TestCase):
    """The question of the overwrite is asked about the file that is
    really written."""

    def setUp(self) -> None:
        self.app = application()
        self.home = temporary_home()
        self.window = MainWindow()
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def tearDown(self) -> None:
        self.window.close()

    def answer_the_question(self, answer) -> list:
        from PySide6.QtWidgets import QMessageBox

        asked = []

        def question(*args, **kwargs):
            asked.append(args[1] if len(args) > 1 else "")
            return answer

        original = QMessageBox.question
        QMessageBox.question = staticmethod(question)
        self.addCleanup(lambda: setattr(QMessageBox, "question", original))
        return asked

    @staticmethod
    def no():
        from PySide6.QtWidgets import QMessageBox

        return QMessageBox.No

    def test_a_file_that_is_there_is_not_replaced_without_a_question(self) -> None:
        target = Path(self.folder.name) / "notes.txt"
        target.write_text("the text of another transcription", encoding="utf-8")
        chosen = Path(self.folder.name) / "notes.md"
        asked = self.answer_the_question(self.no())
        allowed = self.window._ask_before_replacing(target, chosen, "שמירת הטקסט")
        self.assertTrue(asked)
        self.assertFalse(allowed)
        self.assertEqual(
            target.read_text(encoding="utf-8"), "the text of another transcription"
        )

    def test_a_file_that_is_not_there_is_written_without_a_question(self) -> None:
        target = Path(self.folder.name) / "notes.txt"
        chosen = Path(self.folder.name) / "notes.md"
        asked = self.answer_the_question(self.no())
        allowed = self.window._ask_before_replacing(target, chosen, "שמירת הטקסט")
        self.assertFalse(asked)
        self.assertTrue(allowed)

    def test_the_file_that_is_written_is_the_one_that_was_asked_about(self) -> None:
        """The name of the file changes after the dialog was closed, and
        the question is about the file that is really written."""
        from PySide6.QtWidgets import QFileDialog

        target = Path(self.folder.name) / "notes.txt"
        target.write_text("the text of another transcription", encoding="utf-8")
        chosen = Path(self.folder.name) / "notes.md"
        original = QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName = staticmethod(
            lambda *args, **kwargs: (str(chosen), "")
        )
        self.addCleanup(lambda: setattr(QFileDialog, "getSaveFileName", original))
        self.window.editor.setPlainText("מה שהמשתמש הקליד")
        self.answer_the_question(self.no())
        self.window.save_text()
        # The user refused, and the file that was there is as it was.
        self.assertEqual(
            target.read_text(encoding="utf-8"), "the text of another transcription"
        )


class ExportToPdfTests(unittest.TestCase):
    """The PDF is written to the file that is really written."""

    def setUp(self) -> None:
        self.app = application()
        self.home = temporary_home()
        self.window = MainWindow()
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def tearDown(self) -> None:
        self.window.close()

    def test_the_user_is_asked_before_a_pdf_that_is_there_is_replaced(self) -> None:
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        target = Path(self.folder.name) / "notes.pdf"
        target.write_bytes(b"the old pdf")
        chosen = Path(self.folder.name) / "notes"
        original_dialog = QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName = staticmethod(
            lambda *args, **kwargs: (str(chosen), "")
        )
        self.addCleanup(
            lambda: setattr(QFileDialog, "getSaveFileName", original_dialog)
        )
        asked = []

        def question(*args, **kwargs):
            asked.append(args[1] if len(args) > 1 else "")
            return QMessageBox.No

        original_question = QMessageBox.question
        QMessageBox.question = staticmethod(question)
        self.addCleanup(lambda: setattr(QMessageBox, "question", original_question))
        self.window.editor.setPlainText("מה שהמשתמש הקליד")
        self.window.print_to_pdf()
        self.assertTrue(asked)
        # The file that was there is as it was.
        self.assertEqual(target.read_bytes(), b"the old pdf")


class OriginalTextTests(unittest.TestCase):
    """The text as the recognition gave it is kept, so it can be found again."""

    def setUp(self) -> None:
        self.app = application()
        self.home = temporary_home()
        self.window = MainWindow()

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.home.cleanup()

    def add_document(self):
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
        return self.window.project[0]

    @staticmethod
    def yes() -> object:
        from PySide6.QtWidgets import QMessageBox

        return QMessageBox.Yes

    @staticmethod
    def no() -> object:
        from PySide6.QtWidgets import QMessageBox

        return QMessageBox.No

    def answer_the_question(self, answer) -> list:
        """Answer the question of the program without a window of its own."""
        from PySide6.QtWidgets import QMessageBox

        asked = []

        def question(*args, **kwargs):
            asked.append(args[1] if len(args) > 1 else "")
            return answer

        original = QMessageBox.question
        QMessageBox.question = staticmethod(question)
        self.addCleanup(lambda: setattr(QMessageBox, "question", original))
        return asked

    def test_the_recognition_keeps_the_text_it_gave(self) -> None:
        entry = self.add_document()

        class Result:
            text = "תוצאת הזיהוי"
            engine_name = "מנוע הבדיקה"
            duration_seconds = 1.5

        self.window._on_ocr_done(Result(), entry)
        self.assertEqual(entry.original_transcription, "תוצאת הזיהוי")

    def test_the_text_can_go_back_to_what_the_recognition_gave(self) -> None:
        entry = self.add_document()

        class Result:
            text = "תוצאת הזיהוי"
            engine_name = "מנוע הבדיקה"
            duration_seconds = 1.5

        self.window._on_ocr_done(Result(), entry)
        # The user changes the text in the editor.
        self.window.editor.setPlainText("תוצאת הזיהוי עם תיקון של המשתמש")
        self.answer_the_question(self.yes())
        self.window.restore_original_text()
        self.assertEqual(self.window.editor.toPlainText(), "תוצאת הזיהוי")

    def test_the_user_is_asked_before_the_text_he_wrote_is_thrown_away(self) -> None:
        """Going back to the original text takes away what was typed."""
        entry = self.add_document()

        class Result:
            text = "תוצאת הזיהוי"
            engine_name = "מנוע הבדיקה"
            duration_seconds = 1.5

        self.window._on_ocr_done(Result(), entry)
        self.window.editor.setPlainText("מה שהמשתמש הקליד")
        asked = self.answer_the_question(self.no())
        self.window.restore_original_text()
        # The user refused, and the text of the editor is as it was.
        self.assertTrue(asked)
        self.assertEqual(self.window.editor.toPlainText(), "מה שהמשתמש הקליד")

    def test_there_is_nothing_to_go_back_to_before_the_recognition(self) -> None:
        self.add_document()
        self.window.editor.setPlainText("טקסט שהמשתמש הקליד")
        self.window.restore_original_text()
        # The text of the editor is not changed, because there is no
        # original text yet.
        self.assertEqual(self.window.editor.toPlainText(), "טקסט שהמשתמש הקליד")


class TheEditorDuringTheRecognitionTests(unittest.TestCase):
    """While the recognition runs, the editor is closed.

    The result of the recognition replaces the text of the editor, and
    what the user writes in the meantime would be lost without a word.
    """

    def setUp(self) -> None:
        self.app = application()
        self.home = temporary_home()
        self.window = MainWindow()
        from hebrew_workbench.resources import samples_directory

        samples = samples_directory()
        pages = sorted(samples.glob("scan_page_*.png")) if samples else []
        if not pages:
            self.skipTest("the sample pages are not available here")
        self.window.project.add(pages[0])
        self.window._sync_document_list()
        self.window.doc_list.setCurrentRow(0)

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.home.cleanup()

    def test_the_editor_is_closed_while_the_recognition_runs(self) -> None:
        release = threading.Event()

        class Result:
            text = "תוצאת הזיהוי"
            engine_name = "מנוע הבדיקה"
            duration_seconds = 0.1

        class Engine:
            name = "מנוע הבדיקה"

            def available(self) -> bool:
                return True

            def recognize(self, file_path, progress=None, cancel=None):
                release.wait(20)
                return Result()

        self.window.registry = EngineRegistry(Engine())
        self.window.run_ocr()
        # The editor is closed while the recognition runs.
        self.assertTrue(self.window.editor.isReadOnly())
        release.set()
        deadline = time.monotonic() + 20
        while self.window.task is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.05)
        # And it is open again when the recognition is over.
        self.assertFalse(self.window.editor.isReadOnly())


if __name__ == "__main__":
    unittest.main()
