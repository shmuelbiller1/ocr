"""The main application window.

The window is right-to-left because the workbench is meant for Hebrew
script.  Qt performs the bidirectional layout and the letter shaping, so
Hebrew is rendered the way it is written - not reversed as it would be in
a toolkit without bidi support.

The window deliberately keeps every action reversible:

* adding a document never touches the file on disk,
* removing a document only removes it from the workspace,
* the editor holds the *exact* text the user typed or the engine produced.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtPrintSupport import QPrinter, QPrintDialog, QPrintPreviewDialog
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QStyle,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__
from ..engine.registry import EngineRegistry
from ..exporting import ExportError, build_print_document, print_document, write_docx
from ..project import PROJECT_SUFFIX, Project
from ..resources import samples_directory
from .preview_pane import PreviewPane
from .tasks import TaskThread

__all__ = ["MainWindow", "run", "SUPPORTED_SUFFIXES"]

SUPPORTED_SUFFIXES = (".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")

#: Fonts that are known to carry Hebrew glyphs on Windows.  Qt silently
#: falls back to the next family when one is missing.
HEBREW_FONTS = ("David", "Segoe UI", "Arial", "Noto Sans Hebrew", "Times New Roman")

FILE_DIALOG_FILTER = (
    "Scanned pages (*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;"
    "PDF documents (*.pdf);;"
    "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;"
    "All files (*.*)"
)


class MainWindow(QMainWindow):
    """The single top level window of the workbench."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = Project()
        self.registry = EngineRegistry()
        self.engines: list = []
        self._shown_entry = None
        self._loading = False
        self.task: TaskThread | None = None

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1280, 820)
        self.setLayoutDirection(Qt.RightToLeft)

        self._build_central()
        self._build_actions()
        self._build_menu()
        self._build_toolbar()
        self._build_status_bar()
        self._sync_document_list()
        self.refresh_engines()

    # -- construction ------------------------------------------------------
    def _build_central(self) -> None:
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        self.doc_list = QListWidget()
        self.doc_list.setIconSize(QSize(20, 20))
        self.doc_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.doc_list.currentRowChanged.connect(self._on_document_selected)
        self.doc_list.setToolTip("מסמכים שנפתחו. הקבצים המקוריים אינם משתנים.")

        self.doc_path_label = QLabel("לא נבחר מסמך")
        self.doc_path_label.setWordWrap(True)
        self.doc_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.doc_path_label.setStyleSheet("color: #555;")

        add_button = QPushButton("הוספת מסמכים")
        add_button.clicked.connect(self.add_documents)
        remove_button = QPushButton("הסרת מסמך")
        remove_button.clicked.connect(self.remove_selected_documents)
        clear_button = QPushButton("ניקוי הרשימה")
        clear_button.clicked.connect(self.clear_documents)

        buttons = QHBoxLayout()
        buttons.addWidget(add_button)
        buttons.addWidget(remove_button)
        buttons.addWidget(clear_button)

        documents = QWidget()
        documents_layout = QVBoxLayout(documents)
        documents_layout.setContentsMargins(8, 8, 8, 8)
        documents_layout.addWidget(QLabel("<b>מסמכים</b>"))
        documents_layout.addWidget(self.doc_list, 1)
        documents_layout.addWidget(self.doc_path_label)
        documents_layout.addLayout(buttons)

        self.preview = PreviewPane()
        self.preview.setToolTip("תצוגה מקדימה של הדף הנבחר")

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            "הטקסט המוקלד מופיע כאן. אפשר להקליד או להדביק ידנית."
        )
        self.editor.setLayoutDirection(Qt.RightToLeft)
        self.editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.editor.setTabStopDistance(28)
        self.editor.setUndoRedoEnabled(True)
        self.editor.setFont(self._hebrew_font(14))
        self.editor.textChanged.connect(self._on_editor_changed)
        self.editor.setToolTip(
            "הטקסט המוקלד. המקור נשמר בנפרד ולא נדרס על ידי הצעות תיקון."
        )

        work = QSplitter(Qt.Vertical)
        work.setChildrenCollapsible(False)
        work.addWidget(self.preview)
        work.addWidget(self.editor)
        work.setStretchFactor(0, 3)
        work.setStretchFactor(1, 2)

        splitter.addWidget(documents)
        splitter.addWidget(work)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        self.setCentralWidget(splitter)

    def _build_actions(self) -> None:
        self.add_files_action = QAction("הוספת מסמכים...", self)
        self.add_files_action.setShortcut(QKeySequence.Open)
        self.add_files_action.triggered.connect(self.add_documents)

        self.add_folder_action = QAction("הוספת תיקייה...", self)
        self.add_folder_action.triggered.connect(self.add_folder)

        self.remove_action = QAction("הסרת מסמך נבחר", self)
        self.remove_action.setShortcut(QKeySequence.Delete)
        self.remove_action.triggered.connect(self.remove_selected_documents)

        self.clear_action = QAction("ניקוי הרשימה", self)
        self.clear_action.triggered.connect(self.clear_documents)

        self.run_ocr_action = QAction("הרצת OCR", self)
        self.run_ocr_action.setShortcut(QKeySequence("Ctrl+R"))
        self.run_ocr_action.triggered.connect(self.run_ocr)

        self.save_text_action = QAction("שמירת הטקסט...", self)
        self.save_text_action.setShortcut(QKeySequence("Ctrl+S"))
        self.save_text_action.triggered.connect(self.save_text)

        self.save_project_action = QAction("שמירת פרויקט...", self)
        self.save_project_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.save_project_action.triggered.connect(self.save_project)

        self.open_project_action = QAction("פתיחת פרויקט...", self)
        self.open_project_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self.open_project_action.triggered.connect(self.open_project)

        self.export_docx_action = QAction("ייצוא ל-Word (DOCX)...", self)
        self.export_docx_action.triggered.connect(self.export_docx)

        self.print_action = QAction("הדפסה...", self)
        self.print_action.setShortcut(QKeySequence("Ctrl+P"))
        self.print_action.triggered.connect(self.print_document)

        self.print_preview_action = QAction("תצוגה מקדימה להדפסה...", self)
        self.print_preview_action.triggered.connect(self.print_preview)

        self.print_pdf_action = QAction("שמירה כ-PDF להדפסה...", self)
        self.print_pdf_action.triggered.connect(self.print_to_pdf)

        self.engine_status_action = QAction("מצב המנועים...", self)
        self.engine_status_action.triggered.connect(self.show_engine_status)

        self.install_engine_action = QAction("התקנת מודל הזיהוי...", self)
        self.install_engine_action.triggered.connect(self.install_model)

        self.cancel_action = QAction("ביטול המשימה", self)
        self.cancel_action.triggered.connect(self.cancel_task)
        self.cancel_action.setEnabled(False)

        self.samples_action = QAction("פתיחת דוגמאות", self)
        self.samples_action.triggered.connect(self.open_samples)

        self.quit_action = QAction("יציאה", self)
        self.quit_action.setShortcut(QKeySequence.Quit)
        self.quit_action.triggered.connect(self.close)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("קובץ")
        file_menu.addAction(self.add_files_action)
        file_menu.addAction(self.add_folder_action)
        file_menu.addAction(self.samples_action)
        file_menu.addSeparator()
        file_menu.addAction(self.remove_action)
        file_menu.addAction(self.clear_action)
        file_menu.addSeparator()
        file_menu.addAction(self.open_project_action)
        file_menu.addAction(self.save_project_action)
        file_menu.addSeparator()
        file_menu.addAction(self.save_text_action)
        file_menu.addAction(self.export_docx_action)
        file_menu.addSeparator()
        file_menu.addAction(self.print_action)
        file_menu.addAction(self.print_preview_action)
        file_menu.addAction(self.print_pdf_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)

        tools_menu = self.menuBar().addMenu("כלים")
        tools_menu.addAction(self.run_ocr_action)
        tools_menu.addAction(self.cancel_action)
        tools_menu.addSeparator()
        self.engine_menu = tools_menu.addMenu("מנוע הזיהוי")
        tools_menu.addAction(self.install_engine_action)
        tools_menu.addAction(self.engine_status_action)

        help_menu = self.menuBar().addMenu("עזרה")
        about = QAction("אודות", self)
        about.triggered.connect(self.show_about)
        help_menu.addAction(about)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("כלים מרכזיים")
        toolbar.setObjectName("main-toolbar")
        toolbar.setIconSize(QSize(22, 22))
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        style = self.style()
        toolbar.addAction(self.add_files_action)
        toolbar.addAction(self.add_folder_action)
        toolbar.addSeparator()
        toolbar.addAction(self.run_ocr_action)
        toolbar.addSeparator()
        toolbar.addAction(self.save_text_action)
        toolbar.addAction(self.save_project_action)
        toolbar.addSeparator()
        toolbar.addAction(self.print_action)
        toolbar.addSeparator()
        toolbar.addAction(self.engine_status_action)
        self._refresh_toolbar_icons(style)

    def _refresh_toolbar_icons(self, style: QStyle) -> None:
        mapping = {
            self.add_files_action: QStyle.SP_DialogOpenButton,
            self.add_folder_action: QStyle.SP_DirOpenIcon,
            self.run_ocr_action: QStyle.SP_MediaPlay,
            self.save_text_action: QStyle.SP_DialogSaveButton,
            self.save_project_action: QStyle.SP_DriveHDIcon,
            self.print_action: QStyle.SP_DialogApplyButton,
            self.engine_status_action: QStyle.SP_FileDialogDetailedView,
        }
        for action, icon in mapping.items():
            action.setIcon(style.standardIcon(icon))

    def _build_status_bar(self) -> None:
        status = QStatusBar()
        self.setStatusBar(status)
        self.engine_label = QLabel("מנוע OCR: לא מותקן")
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(180)
        self.progress.setVisible(False)
        status.addWidget(self.engine_label, 1)
        status.addPermanentWidget(self.progress)

    # -- helpers -----------------------------------------------------------
    def _hebrew_font(self, size: int):
        from PySide6.QtGui import QFont

        font = QFont()
        font.setFamilies(list(HEBREW_FONTS))
        font.setPointSize(size)
        return font

    def _sync_document_list(self) -> None:
        self.doc_list.blockSignals(True)
        self.doc_list.clear()
        style = self.style()
        for entry in self.project:
            item = QListWidgetItem(entry.name)
            item.setToolTip(entry.path)
            item.setIcon(style.standardIcon(QStyle.SP_FileIcon))
            if not entry.exists:
                item.setToolTip(f"{entry.path}\n(הקובץ אינו נמצא במקום זה)")
            self.doc_list.addItem(item)
        self.doc_list.blockSignals(False)

    def _update_engine_status(self) -> None:
        available = self.registry.engine.available()
        self.engine_label.setText(
            f"מנוע OCR: {self.registry.engine.name}"
            + ("" if available else " — אין מנוע מותקן, לא בוצעה זיהוי")
        )

    def _current_entry(self):
        row = self.doc_list.currentRow()
        if 0 <= row < len(self.project):
            return self.project[row]
        return None

    def _current_text(self) -> str:
        entry = self._current_entry()
        if entry is not None:
            return entry.transcription
        return self.editor.toPlainText()

    # -- document handling -------------------------------------------------
    def add_documents(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "בחירת דפי סריקה", "", FILE_DIALOG_FILTER
        )
        if paths:
            self.add_paths(paths)

    def add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "בחירת תיקייה עם דפי סריקה")
        if not folder:
            return
        folder_path = Path(folder)
        files = sorted(p for p in folder_path.iterdir() if p.is_file())
        self.add_paths([str(p) for p in files])

    @staticmethod
    def samples_directory() -> Path | None:
        """Find the folder with the sample pages, if it is available."""
        return samples_directory()

    def open_samples(self) -> None:
        folder = self.samples_directory()
        if folder is None:
            QMessageBox.information(
                self,
                "דוגמאות",
                "תיקיית הדוגמאות לא נמצאה. היא נמצאת בתיקיית samples שבמקור היישום.",
            )
            return
        files = sorted(
            str(path)
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
        )
        if not files:
            QMessageBox.information(self, "דוגמאות", "בתיקיית הדוגמאות אין קבצים.")
            return
        self.add_paths(files)

    def add_paths(self, paths) -> None:
        added = 0
        first_added_row: int | None = None
        for item in paths:
            path = Path(item)
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            if not path.is_file():
                continue
            if self.project.index_of(path) is None:
                self.project.add(path)
                if first_added_row is None:
                    first_added_row = len(self.project) - 1
                added += 1
        if added:
            self._sync_document_list()
            self.statusBar().showMessage(
                f"נוספו {added} מסמכים. הקבצים המקוריים לא שונו.", 6000
            )
            if first_added_row is not None:
                self.doc_list.setCurrentRow(first_added_row)
        else:
            self.statusBar().showMessage("לא נוספו מסמכים חדשים.", 4000)

    def remove_selected_documents(self) -> None:
        rows = sorted((index.row() for index in self.doc_list.selectedIndexes()), reverse=True)
        if not rows:
            self.statusBar().showMessage("לא נבחר מסמך להסרה.", 4000)
            return
        for row in rows:
            if 0 <= row < len(self.project):
                removed = self.project.remove(row)
                if removed is self._shown_entry:
                    self._shown_entry = None
        self._sync_document_list()
        self._loading = True
        self.editor.clear()
        self._loading = False
        self.doc_path_label.setText("לא נבחר מסמך")
        self.preview.set_document(None)
        self.statusBar().showMessage(f"הוסרו {len(rows)} מסמכים מהרשימה.", 5000)

    def clear_documents(self) -> None:
        if not len(self.project):
            return
        answer = QMessageBox.question(
            self,
            "ניקוי הרשימה",
            "להסיר את כל המסמכים מהרשימה? הקבצים על הדיסק לא יימחקו.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.project.clear()
        self._shown_entry = None
        self._sync_document_list()
        self.preview.set_document(None)
        self._loading = True
        self.editor.clear()
        self._loading = False
        self.statusBar().showMessage("הרשימה נוקתה. הקבצים על הדיסק לא נגעו.", 5000)

    def _on_document_selected(self, row: int) -> None:
        self._store_editor_text()
        if not (0 <= row < len(self.project)):
            self._shown_entry = None
            self.editor.clear()
            self.doc_path_label.setText("לא נבחר מסמך")
            self.preview.set_document(None)
            return
        entry = self.project[row]
        self._loading = True
        self.editor.setPlainText(entry.transcription)
        self._loading = False
        self._shown_entry = entry
        self.doc_path_label.setText(entry.path)
        self.preview.set_document(entry.path)

    def _on_editor_changed(self) -> None:
        if self._loading:
            return
        self._store_editor_text()

    def _store_editor_text(self) -> None:
        """Save the text of the document that is in the editor.

        The document is the one that is *shown*, and not the one that is
        selected in the list: when the user moves to another document,
        the list has already changed, and the text of the old document
        would be written into the new one.
        """
        entry = self._shown_entry
        if entry is not None:
            entry.transcription = self.editor.toPlainText()

    # -- projects ----------------------------------------------------------
    def save_project(self) -> None:
        self._store_editor_text()
        suggested = "פרויקט" + PROJECT_SUFFIX
        if self.project.path:
            suggested = str(self.project.path)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "שמירת פרויקט",
            suggested,
            f"פרויקט העבודה (*{PROJECT_SUFFIX});;כל הקבצים (*.*)",
        )
        if not path:
            return
        try:
            saved = self.project.save(path)
        except OSError as exc:
            QMessageBox.warning(self, "שמירת הפרויקט", f"לא ניתן לשמור: {exc}")
            return
        self.statusBar().showMessage(f"הפרויקט נשמר: {saved}", 6000)

    def open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "פתיחת פרויקט",
            "",
            f"פרויקט העבודה (*{PROJECT_SUFFIX});;כל הקבצים (*.*)",
        )
        if not path:
            return
        try:
            project = Project.load(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "פתיחת הפרויקט", f"לא ניתן לפתוח: {exc}")
            return
        self.project = project
        self._shown_entry = None
        self._sync_document_list()
        self.preview.set_document(None)
        self._loading = True
        self.editor.clear()
        self._loading = False
        if len(self.project):
            self.doc_list.setCurrentRow(0)
        self.statusBar().showMessage(
            f"נפתח הפרויקט {Path(path).name} עם {len(self.project)} מסמכים.", 6000
        )

    # -- actions -----------------------------------------------------------
    def run_ocr(self) -> None:
        entry = self._current_entry()
        if entry is None:
            QMessageBox.information(self, "הרצת OCR", "יש לבחור מסמך לפני הרצת OCR.")
            return
        if self.task is not None and self.task.isRunning():
            QMessageBox.information(self, "הרצת OCR", "כבר מתבצעת משימה.")
            return
        if not self.registry.available():
            answer = QMessageBox.question(
                self,
                "OCR לא זמין",
                "לא מותקן מנוע זיהוי עבור עברית.\n\n"
                "האם להתקין כעת את מודל הזיהוי? "
                "ההתקנה מורידה קובץ מודל (כ-13MB) ובודקת את שלמותו.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer == QMessageBox.Yes:
                self.install_model()
            return

        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.cancel_action.setEnabled(True)
        self.run_ocr_action.setEnabled(False)

        def work(progress, cancel):
            return self.registry.transcribe(entry.file_path, progress=progress, cancel=cancel)

        self.task = TaskThread(work, self)
        self.task.progress.connect(self._on_task_progress)
        self.task.succeeded.connect(
            lambda result: self._on_ocr_done(result, entry)
        )
        self.task.failed.connect(self._on_task_failed)
        self.task.cancelled.connect(self._on_task_cancelled)
        self.task.finished.connect(self._on_task_finished)
        self.task.start()

    def _on_task_progress(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def _on_ocr_done(self, result, entry=None) -> None:
        if entry is None:
            entry = self._current_entry()
        self._loading = True
        self._replace_editor_text(result.text)
        self._loading = False
        if entry is not None:
            entry.transcription = result.text
            entry.engine_name = result.engine_name
        self.statusBar().showMessage(
            f"הזיהוי בוצע באמצעות {result.engine_name} ב-{result.duration_seconds:.1f} שניות. "
            "יש לבדוק כל שורה לפני הייצוא.",
            10000,
        )

    def _replace_editor_text(self, text: str) -> None:
        """Put a new text into the editor, in a way that can be undone.

        The user has to be able to take back a recognition result with
        the usual undo, so the text is replaced with a cursor and not
        with ``setPlainText``.
        """
        cursor = self.editor.textCursor()
        cursor.select(cursor.SelectionType.Document)
        cursor.insertText(text)

    def _on_task_cancelled(self) -> None:
        self.statusBar().showMessage("המשימה בוטלה. הטקסט נשאר כפי שהיה.", 6000)

    def _on_task_failed(self, message: str) -> None:
        self.statusBar().showMessage("המשימה לא הושלמה. הטקסט נשאר כפי שהיה.", 8000)
        QMessageBox.warning(self, "המשימה נכשלה", message)

    def _on_task_finished(self) -> None:
        self.progress.setVisible(False)
        self.progress.setRange(0, 1)
        self.cancel_action.setEnabled(False)
        self.run_ocr_action.setEnabled(True)
        self.task = None

    def cancel_task(self) -> None:
        if self.task is not None and self.task.isRunning():
            self.task.cancel()
            self.statusBar().showMessage("מבטלים את המשימה...", 4000)

    def install_model(self) -> None:
        """Download the recognition model after asking the user."""
        from ..engine.models import MODEL_ARTIFACTS, InstallError, install_artifact

        if self.task is not None and self.task.isRunning():
            QMessageBox.information(
                self, "התקנת מודל הזיהוי", "כבר מתבצעת משימה. אפשר לנסות שוב אחרי שהיא תסתיים."
            )
            return

        artifact = MODEL_ARTIFACTS["kraken-ppocrv6-small"]
        answer = QMessageBox.question(
            self,
            "התקנת מודל הזיהוי",
            f"{artifact.summary()}\n\n"
            "האם להוריד את המודל עכשיו?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return

        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.cancel_action.setEnabled(False)

        def work(progress, cancel):
            def report(done, total):
                if total:
                    progress(f"מוריד את המודל: {done * 100 // total}%")
                else:
                    progress(f"מוריד את המודל: {done // (1024 * 1024)}MB")

            return install_artifact(artifact, progress=report)

        self.task = TaskThread(work, self)
        self.task.progress.connect(self._on_task_progress)
        self.task.succeeded.connect(self._on_model_installed)
        self.task.failed.connect(self._on_task_failed)
        self.task.finished.connect(self._on_task_finished)
        self.task.start()

    def _on_model_installed(self, path) -> None:
        self.refresh_engines()
        self.statusBar().showMessage(f"המודל הותקן: {path}", 8000)
        QMessageBox.information(
            self,
            "המודל הותקן",
            f"המודל הותקן בהצלחה:\n{path}\n\n"
            "אפשר להריץ זיהוי עכשיו. יש לבדוק את התוצאה שורה שורה - "
            "הזיהוי אינו מושלם ואינו מחליף את בדיקת המורה.",
        )

    def refresh_engines(self) -> None:
        """Look for engines that can run and update the registry."""
        from ..engine.factory import detect_engines

        self.engines = detect_engines()
        if self.engines:
            self.registry = EngineRegistry(self.engines[0])
        self._update_engine_status()
        self._rebuild_engine_menu()

    def _rebuild_engine_menu(self) -> None:
        menu = getattr(self, "engine_menu", None)
        if menu is None:
            return
        menu.clear()
        if not self.engines:
            action = QAction("לא מותקן מנוע זיהוי", self)
            action.setEnabled(False)
            menu.addAction(action)
            return
        group = QActionGroup(self)
        for index, engine in enumerate(self.engines):
            action = QAction(getattr(engine, "name", f"מנוע {index + 1}"), self)
            action.setCheckable(True)
            action.setChecked(engine is self.registry.engine)
            action.triggered.connect(lambda _checked=False, e=engine: self.select_engine(e))
            group.addAction(action)
            menu.addAction(action)

    def select_engine(self, engine) -> None:
        self.registry = EngineRegistry(engine)
        self._update_engine_status()
        self._rebuild_engine_menu()
        self.statusBar().showMessage(f"נבחר מנוע הזיהוי: {getattr(engine, 'name', '')}", 5000)

    def save_text(self) -> None:
        content = self.editor.toPlainText()
        if not content.strip():
            QMessageBox.information(
                self,
                "שמירת הטקסט",
                "אין טקסט לשמירה. אפשר להקליד או להדביק טקסט לעורך.",
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "שמירת הטקסט", "תמלול.txt", "טקסט UTF-8 (*.txt);;כל הקבצים (*.*)"
        )
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != ".txt":
            target = target.with_suffix(".txt")
        try:
            write_txt(target, content)
        except ExportError as exc:
            QMessageBox.warning(self, "שמירת הטקסט", str(exc))
            return
        self.statusBar().showMessage(f"נשמר: {target}", 6000)

    def export_docx(self) -> None:
        content = self.editor.toPlainText()
        if not content.strip():
            QMessageBox.information(
                self, "ייצוא ל-Word", "אין טקסט לייצוא."
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "ייצוא ל-Word", "תמלול.docx", "מסמך Word (*.docx);;כל הקבצים (*.*)"
        )
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != ".docx":
            target = target.with_suffix(".docx")
        try:
            write_docx(target, content)
        except ExportError as exc:
            QMessageBox.warning(self, "ייצוא ל-Word", str(exc))
            return
        self.statusBar().showMessage(f"נוצר קובץ: {target}", 6000)

    # -- printing ----------------------------------------------------------
    def _printer(self) -> QPrinter:
        printer = QPrinter(QPrinter.HighResolution)
        printer.setDocName(APP_NAME)
        printer.setPageSize(QPrinter.A4)
        printer.setPageMargins(15, 15, 15, 15, QPrinter.Millimeter)
        printer.setFullPage(False)
        return printer

    def print_document(self) -> None:
        content = self.editor.toPlainText()
        if not content.strip():
            QMessageBox.information(self, "הדפסה", "אין טקסט להדפסה.")
            return
        printer = self._printer()
        dialog = QPrintDialog(printer, self)
        dialog.setWindowTitle("הדפסת התמלול")
        if dialog.exec() != QPrintDialog.Accepted:
            return
        try:
            print_document(build_print_document(content), printer)
        except ExportError as exc:
            QMessageBox.warning(self, "הדפסה", str(exc))
            return
        self.statusBar().showMessage("המסמך נשלח למדפסת.", 6000)

    def print_preview(self) -> None:
        content = self.editor.toPlainText()
        if not content.strip():
            QMessageBox.information(self, "תצוגה מקדימה", "אין טקסט להציג.")
            return
        printer = self._printer()
        dialog = QPrintPreviewDialog(printer, self)
        dialog.setWindowTitle("תצוגה מקדימה להדפסה")
        dialog.resize(900, 700)
        document = build_print_document(content)
        dialog.paintRequested.connect(lambda target: document.print_(target))
        dialog.exec()

    def print_to_pdf(self) -> None:
        content = self.editor.toPlainText()
        if not content.strip():
            QMessageBox.information(self, "שמירה כ-PDF", "אין טקסט לשמור.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "שמירה כ-PDF", "תמלול.pdf", "מסמך PDF (*.pdf);;כל הקבצים (*.*)"
        )
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != ".pdf":
            target = target.with_suffix(".pdf")
        printer = self._printer()
        printer.setOutputFileName(str(target))
        try:
            print_document(build_print_document(content), printer)
        except ExportError as exc:
            QMessageBox.warning(self, "שמירה כ-PDF", str(exc))
            return
        self.statusBar().showMessage(f"נוצר קובץ: {target}", 6000)

    def show_engine_status(self) -> None:
        QMessageBox.information(self, "מצב המנועים", self.registry.status())

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "אודות",
            f"<b>{APP_NAME}</b> {__version__}<br><br>"
            "יישום שולחני ללא חיבור לאינטרנט להפקת תמלול מסמכים בכתב יד.<br>"
            "המסמכים המקוריים אינם משתנים, והצעות תיקון מוצגות לבחירה בלבד.",
        )

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self.task is not None and self.task.isRunning():
            self.task.cancel()
            if not self.task.wait(3000):
                # The work did not stop.  The window stays open, so that
                # the user does not lose the text they wrote.
                self.statusBar().showMessage(
                    "המשימה עוד לא נעצרה. החלון נשאר פתוח.", 8000
                )
                event.ignore()
                return
        self._store_editor_text()
        self.preview.close_document()
        event.accept()


def run(argv: list[str] | None = None) -> int:
    """Start the graphical application."""
    app = QApplication.instance() or QApplication(argv or [])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_NAME)
    app.setLayoutDirection(Qt.RightToLeft)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run())
