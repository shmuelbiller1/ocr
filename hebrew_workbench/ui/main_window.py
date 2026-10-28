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
from ..plugins import PluginRegistry
from ..project import PROJECT_SUFFIX, Project
from ..resources import samples_directory
from ..suggestions import SuggestionRegistry, SuggestionSession
from .preview_pane import PreviewPane
from .suggestions_pane import SuggestionsPane
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
        self.plugins = PluginRegistry()
        self.suggestion_modules = SuggestionRegistry()
        self.suggestions = SuggestionSession()
        # Every document has its own session of proposals, so that the
        # proposals of one document are never offered for another one.
        self._sessions: dict[str, SuggestionSession] = {}
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
        self._build_suggestions_dock()
        self._sync_document_list()
        self.refresh_engines()
        # The choices of the user about the modules of proposals are
        # read at once, and not only when the settings screen is
        # opened.
        self._refresh_suggestion_modules()

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

        self.plugin_settings_action = QAction("תוספים ומנועים...", self)
        self.plugin_settings_action.triggered.connect(self.open_plugin_settings)

        self.check_suggestions_action = QAction("בדיקת הצעות תיקון", self)
        self.check_suggestions_action.triggered.connect(self.check_suggestions)

        self.undo_changes_action = QAction("ביטול כל שינויי התיקון", self)
        self.undo_changes_action.triggered.connect(self.undo_all_changes)

        self.choose_dictionary_action = QAction("בחירת מילון לאיות...", self)
        self.choose_dictionary_action.triggered.connect(self.choose_dictionary)

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

        settings_menu = self.menuBar().addMenu("הגדרות")
        settings_menu.addAction(self.plugin_settings_action)

        suggestions_menu = self.menuBar().addMenu("הצעות תיקון")
        suggestions_menu.addAction(self.check_suggestions_action)
        suggestions_menu.addAction(self.undo_changes_action)
        suggestions_menu.addSeparator()
        suggestions_menu.addAction(self.choose_dictionary_action)

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

    def _build_suggestions_dock(self) -> None:
        """The pane with the proposals for corrections."""
        from PySide6.QtWidgets import QDockWidget

        self.suggestions_pane = SuggestionsPane(self)
        self.suggestions_pane.check_requested.connect(self.check_suggestions)
        self.suggestions_pane.undo_requested.connect(self.undo_all_changes)
        self.suggestions_pane.accept_requested.connect(self.accept_suggestion)
        self.suggestions_pane.refuse_requested.connect(self.refuse_suggestion)

        self.suggestions_dock = QDockWidget("הצעות תיקון", self)
        self.suggestions_dock.setObjectName("suggestions-dock")
        self.suggestions_dock.setWidget(self.suggestions_pane)
        self.suggestions_dock.setMinimumWidth(300)
        self.addDockWidget(Qt.RightDockWidgetArea, self.suggestions_dock)
        self.suggestions_dock.hide()

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
                self._sessions.pop(str(removed.path), None)
        self._sync_document_list()
        if self._shown_entry is not None and self._shown_entry not in self.project:
            self._shown_entry = None
        if self._shown_entry is not None:
            # The document that was shown is still there, so it stays in
            # the editor and its text is not lost.
            self._show_entry(self._shown_entry)
            # The list is built again, and the row of the document that
            # is shown is chosen again, so that the list and the editor
            # always show the same document.  The signals are held, so
            # that the editor is not loaded a second time.
            row = self.project.index_of(self._shown_entry.path)
            if row is not None:
                self.doc_list.blockSignals(True)
                self.doc_list.setCurrentRow(row)
                self.doc_list.blockSignals(False)
        else:
            self._clear_editor()
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
        self._sessions.clear()
        self._sync_document_list()
        self._clear_editor()
        self.statusBar().showMessage("הרשימה נוקתה. הקבצים על הדיסק לא נגעו.", 5000)

    def _on_document_selected(self, row: int) -> None:
        self._store_editor_text()
        if not (0 <= row < len(self.project)):
            self._clear_editor()
            return
        self._show_entry(self.project[row])

    def _show_entry(self, entry) -> None:
        """Show a document in the editor and in the preview.

        The proposals of the document come with it, so that they are
        never offered for a document they do not belong to.
        """
        self._loading = True
        self.editor.setPlainText(entry.transcription)
        self._loading = False
        self._shown_entry = entry
        self.suggestions = self._session_for(entry)
        self._refresh_suggestions(self.suggestions)
        self.doc_path_label.setText(entry.path)
        self.preview.set_document(entry.path)

    def _clear_editor(self) -> None:
        """Show an empty editor, with no document behind it.

        The document that was shown is forgotten, so that its text is
        not written over with the empty text of the editor.
        """
        self._loading = True
        self.editor.clear()
        self._loading = False
        self._shown_entry = None
        self.suggestions = SuggestionSession()
        self._refresh_suggestions(self.suggestions)
        self.doc_path_label.setText("לא נבחר מסמך")
        self.preview.set_document(None)

    def _session_for(self, entry) -> SuggestionSession:
        """The session of the proposals of a document.

        The session of a document that is opened for the first time is
        built from the corrections that were saved with the project, so
        that they can be taken back.
        """
        if entry is None:
            return SuggestionSession()
        key = str(entry.path)
        session = self._sessions.get(key)
        if session is None:
            session = SuggestionSession(entry.transcription)
            if entry.changes:
                session.restore_accepted(entry.changes)
            self._sessions[key] = session
        return session

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
        self.load_project(Path(path))

    def load_project(self, path: Path) -> bool:
        """Open a project file, and leave the old project behind.

        The sessions of the proposals belong to the documents of the
        project that is open, and they are forgotten when another
        project is opened.
        """
        try:
            project = Project.load(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "פתיחת הפרויקט", f"לא ניתן לפתוח: {exc}")
            return False
        self.project = project
        self._sessions.clear()
        self._sync_document_list()
        self._clear_editor()
        if len(self.project):
            self.doc_list.setCurrentRow(0)
        self.statusBar().showMessage(
            f"נפתח הפרויקט {Path(path).name} עם {len(self.project)} מסמכים.", 6000
        )
        return True

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
        if entry is not None:
            entry.transcription = result.text
            entry.engine_name = result.engine_name
            # The text of the document is new, and the corrections that
            # were made on the old text do not belong to it any more.
            # Their places are of no use, and a correction that is
            # looked for in the new text could be found in a place that
            # was never corrected.
            entry.changes = []
            self._sessions.pop(str(entry.path), None)
        if entry is not None and entry is self._shown_entry:
            # The document that was recognised is still the one that is
            # shown, so the editor may show the result.  When the user
            # moved to another document in the meantime, the result
            # stays with the document it belongs to, and the editor of
            # the other document is left alone.
            self._loading = True
            self._replace_editor_text(result.text)
            self._loading = False
            # The session of the document is new, because the text of
            # the document is new.
            self.suggestions = self._session_for(entry)
            self._refresh_suggestions(self.suggestions)
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

        # The model belongs to the OCR plugin the user chose.  The
        # plugin is used even when it cannot run yet, because the model
        # is what is missing.
        artifact_id = "kraken-ppocrv6-small"
        plugin = self.plugins.chosen("ocr") or self.plugins.active("ocr")
        if plugin is not None:
            # The options of the manifest and the choices of the user
            # together: the model that is installed has to be the model
            # that the engine waits for.
            options = self.plugins.options_of(plugin)
            artifact_id = str(options.get("model_id", artifact_id) or artifact_id)
        artifact = MODEL_ARTIFACTS.get(artifact_id)
        if artifact is None:
            QMessageBox.information(
                self,
                "התקנת מודל הזיהוי",
                f"התוסף {plugin.name if plugin else ''} אינו משתמש באחד "
                "מהמודלים שהתוכנית יודעת. יש להתקין את המודל לפי הוראות "
                "של יצרן התוסף.",
            )
            return
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
        """Look for engines that can run and update the registry.

        The engines are the OCR plugins the user has.  A plugin that is
        switched off, or whose model is not installed, is not offered.
        """
        self.plugins.load()
        # The load builds the plugins again, so the modules of proposals
        # of the window are the old ones and have to be looked at again.
        self._refresh_suggestion_modules()
        self.engines = []
        for plugin in self.plugins.ocr_engines():
            engine = plugin.object
            if engine is None:
                continue
            self.engines.append(engine)
        if self.engines and not self.plugins.without_plugin("ocr"):
            active = self.plugins.active_engine()
            chosen = active if active in self.engines else self.engines[0]
            self.registry = EngineRegistry(chosen)
        else:
            # No engine, or the user chose that this program has none:
            # the program works without a recognition, and says so.
            self.registry = EngineRegistry()
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
        for plugin in self.plugins.by_kind("ocr"):
            if plugin.object is engine:
                self.plugins.set_active("ocr", plugin.id)
                break
        self._update_engine_status()
        self._rebuild_engine_menu()
        self.statusBar().showMessage(f"נבחר מנוע הזיהוי: {getattr(engine, 'name', '')}", 5000)

    # -- the plugins ---------------------------------------------------------
    def open_plugin_settings(self) -> None:
        """Open the screen where the plugins are chosen."""
        from .settings_dialog import SettingsDialog

        dialog = SettingsDialog(self.plugins, self)
        dialog.changed.connect(self._on_plugins_changed)
        dialog.exec()
        # The dialog reads the plugins again, so the engines of the
        # window are old even when the user changed nothing.
        self._on_plugins_changed()

    def _on_plugins_changed(self) -> None:
        """The user changed the plugins: look at them again."""
        self.refresh_engines()
        self._refresh_suggestion_modules()

    def _refresh_suggestion_modules(self) -> None:
        """The modules of proposals come from the plugins as well."""
        modules = self.plugins.suggestion_modules()
        if not modules:
            # Every module of proposals was switched off: the program
            # must not keep the ones it had before.
            self.suggestion_modules = SuggestionRegistry([])
            return
        registry = SuggestionRegistry(modules)
        for kind in ("spelling", "grammar", "style"):
            registry.set_enabled(kind, self.plugins.kind_enabled(kind))
        self.suggestion_modules = registry
        # The settings of every plugin were given to it by the registry
        # when it was loaded, so the word list of the spelling is
        # already in place.

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

    # -- the proposals for corrections -------------------------------------
    def _refresh_suggestions(self, session: SuggestionSession) -> None:
        """Show the proposals of a session and what can be taken back."""
        self.suggestions_pane.show_suggestions(session.pending())
        self.suggestions_pane.set_undo_available(bool(session.accepted))

    def check_suggestions(self) -> None:
        """Ask the modules what they would change, and show the proposals."""
        entry = self._shown_entry
        if entry is None:
            QMessageBox.information(
                self, "הצעות תיקון", "יש לבחור מסמך לפני בדיקת הצעות."
            )
            return
        session = self._session_for(entry)
        self.suggestions = session
        text = self.editor.toPlainText()
        if not text.strip():
            session.set_suggestions([], text)
            self._refresh_suggestions(session)
            self.statusBar().showMessage("אין טקסט לבדיקה.", 5000)
            return
        proposals = self.suggestion_modules.check(text)
        session.set_suggestions(proposals, text)
        self._refresh_suggestions(session)
        self.suggestions_dock.show()
        if proposals:
            self.statusBar().showMessage(
                f"נמצאו {len(proposals)} הצעות. כל הצעה מתקבלת או נדחית בנפרד.",
                8000,
            )
        else:
            self.statusBar().showMessage("לא נמצאו הצעות לתיקון.", 5000)

    def accept_suggestion(self, suggestion) -> None:
        """Apply one proposal that the user accepted."""
        session = self.suggestions
        if session is not self._session_for(self._shown_entry):
            # The proposals belong to another document, and they are not
            # applied to this one.
            self.statusBar().showMessage(
                "ההצעות שייכות למסמך אחר, ולכן לא הוחלו.", 6000
            )
            return
        if self.editor.toPlainText() != session.current_text:
            # The user wrote something after the proposals were made, so
            # they no longer fit the text and applying them would throw
            # away what was written.
            self.statusBar().showMessage(
                "הטקסט השתנה אחרי הבדיקה, ולכן ההצעה לא הוחלה. יש לבדוק את ההצעות שוב.",
                8000,
            )
            self._refresh_suggestions(session)
            return
        outcome = session.accept(suggestion)
        if outcome is None:
            self.statusBar().showMessage(
                "ההצעה כבר אינה מתאימה לטקסט, ולכן לא הוחלה.", 6000
            )
            self._refresh_suggestions(session)
            return
        text, position = outcome
        self._loading = True
        self.editor.setPlainText(text)
        self._loading = False
        self._store_editor_text()
        self._refresh_suggestions(session)
        self._store_changes()
        self.statusBar().showMessage(
            f"ההצעה התקבלה. נשארו {len(session.pending())} הצעות.", 5000
        )

    def refuse_suggestion(self, suggestion) -> None:
        """The user does not want this proposal."""
        session = self.suggestions
        if session is not self._session_for(self._shown_entry):
            self.statusBar().showMessage(
                "ההצעות שייכות למסמך אחר, ולכן לא נדחו.", 6000
            )
            return
        session.refuse(suggestion)
        self._refresh_suggestions(session)
        self.statusBar().showMessage("ההצעה נדחתה. הטקסט לא השתנה.", 5000)

    def undo_all_changes(self) -> None:
        """Take back every correction that was accepted."""
        session = self.suggestions
        if session is not self._session_for(self._shown_entry):
            self.statusBar().showMessage(
                "ההצעות שייכות למסמך אחר, ולכן לא בוטלו.", 6000
            )
            return
        if not session.accepted:
            self.statusBar().showMessage("אין שינויים לביטול.", 5000)
            return
        # The corrections are taken back in the text that is in the
        # editor now, so that what the user wrote after them is kept.
        text = session.undo_all(self.editor.toPlainText())
        self._loading = True
        # The text is put in with the cursor and not with
        # `setPlainText`, so that the undo of the editor keeps working
        # and the user can take back a change that was wrong.
        self._replace_editor_text(text)
        self._loading = False
        self._store_editor_text()
        self._refresh_suggestions(session)
        self._store_changes()
        skipped = len(session.last_undo_skipped)
        if skipped:
            # A correction whose place could not be found is not taken
            # back, so that a text that was never corrected is not
            # changed.  The user is told about it.
            self.statusBar().showMessage(
                f"{skipped} שינויי תיקון לא ניתן לבטל, "
                "מפני שהטקסט שסביבם שונה.",
                8000,
            )
        else:
            self.statusBar().showMessage(
                "כל שינויי התיקון בוטלו. יש לבדוק את ההצעות שוב.",
                8000,
            )

    def _store_changes(self) -> None:
        """Keep the changes of the document that is open."""
        entry = self._shown_entry
        if entry is not None:
            entry.changes = self.suggestions.change_log()

    def _spelling_plugin_id(self) -> str:
        """The plugin that does the spelling, as the user chose it."""
        plugin = self.plugins.active("spelling")
        if plugin is not None:
            return plugin.id
        return "spelling-hebrew"

    def choose_dictionary(self) -> None:
        """Let the user point at a word list for the spelling module."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "בחירת מילון לבדיקת איות",
            "",
            "מילונים (*.dic *.txt *.lst);;כל הקבצים (*)",
        )
        if not path:
            return
        module = self.suggestion_modules.module("spelling")
        if module is None:
            return
        # The word list belongs to the spelling plugin, so that it is
        # remembered with it, and the proposals of the text that is
        # shown are looked for again.  A plugin of another maker gets
        # the word list through its own settings, and not through a
        # method of the program.
        self.plugins.set_option(self._spelling_plugin_id(), "dictionary", path)
        setter = getattr(module, "set_dictionary", None)
        if callable(setter):
            try:
                setter(path)
            except OSError as exc:
                QMessageBox.warning(
                    self, "בחירת מילון", f"לא ניתן לקרוא את המילון: {exc}"
                )
                return
        self._refresh_suggestions(self.suggestions)
        words = getattr(module, "word_count", "?")
        self.statusBar().showMessage(
            f"המילון של מודל האיות הוא עכשיו: {path} ({words} מילים)",
            8000,
        )

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
