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

from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QKeySequence, QTextOption
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
from ..project import Project

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
        self._loading = False

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1180, 780)
        self.setLayoutDirection(Qt.RightToLeft)

        self._build_central()
        self._build_actions()
        self._build_menu()
        self._build_toolbar()
        self._build_status_bar()
        self._sync_document_list()
        self._update_engine_status()

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

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.addWidget(QLabel("<b>מסמכים</b>"))
        left_layout.addWidget(self.doc_list, 1)
        left_layout.addWidget(self.doc_path_label)
        left_layout.addLayout(buttons)

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

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.addWidget(QLabel("<b>תמלול</b>"))
        right_layout.addWidget(self.editor, 1)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
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
        self.save_text_action.setShortcut(QKeySequence.Save)
        self.save_text_action.triggered.connect(self.save_text)

        self.engine_status_action = QAction("מצב המנועים...", self)
        self.engine_status_action.triggered.connect(self.show_engine_status)

        self.quit_action = QAction("יציאה", self)
        self.quit_action.setShortcut(QKeySequence.Quit)
        self.quit_action.triggered.connect(self.close)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("קובץ")
        file_menu.addAction(self.add_files_action)
        file_menu.addAction(self.add_folder_action)
        file_menu.addSeparator()
        file_menu.addAction(self.remove_action)
        file_menu.addAction(self.clear_action)
        file_menu.addSeparator()
        file_menu.addAction(self.save_text_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)

        tools_menu = self.menuBar().addMenu("כלים")
        tools_menu.addAction(self.run_ocr_action)
        tools_menu.addSeparator()
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
        toolbar.addSeparator()
        toolbar.addAction(self.engine_status_action)
        self._refresh_toolbar_icons(style)

    def _refresh_toolbar_icons(self, style: QStyle) -> None:
        mapping = {
            self.add_files_action: QStyle.SP_DialogOpenButton,
            self.add_folder_action: QStyle.SP_DirOpenIcon,
            self.run_ocr_action: QStyle.SP_MediaPlay,
            self.save_text_action: QStyle.SP_DialogSaveButton,
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
        self.run_ocr_action.setEnabled(True)

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
                self.project.remove(row)
        self._sync_document_list()
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
        self._sync_document_list()
        self.editor.clear()
        self.statusBar().showMessage("הרשימה נוקתה. הקבצים על הדיסק לא נגעו.", 5000)

    def _on_document_selected(self, row: int) -> None:
        self._store_editor_text()
        if not (0 <= row < len(self.project)):
            self.editor.clear()
            self.doc_path_label.setText("לא נבחר מסמך")
            return
        entry = self.project[row]
        self._loading = True
        self.editor.setPlainText(entry.transcription)
        self._loading = False
        self.doc_path_label.setText(entry.path)

    def _on_editor_changed(self) -> None:
        if self._loading:
            return
        self._store_editor_text()

    def _store_editor_text(self) -> None:
        row = self.doc_list.currentRow()
        if 0 <= row < len(self.project):
            self.project[row].transcription = self.editor.toPlainText()

    # -- actions -----------------------------------------------------------
    def run_ocr(self) -> None:
        row = self.doc_list.currentRow()
        if not (0 <= row < len(self.project)):
            QMessageBox.information(self, "הרצת OCR", "יש לבחור מסמך לפני הרצת OCR.")
            return
        entry = self.project[row]
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        try:
            result = self.registry.transcribe(entry.file_path)
        except Exception as exc:
            self.statusBar().showMessage("לא בוצעה זיהוי. הטקסט נשאר כפי שהיה.", 8000)
            QMessageBox.warning(self, "OCR לא זמין", str(exc))
            return
        finally:
            self.progress.setVisible(False)
            self.progress.setRange(0, 1)
        self._loading = True
        self.editor.setPlainText(result.text)
        self._loading = False
        self.project[row].transcription = result.text
        self.project[row].engine_name = result.engine_name
        self.statusBar().showMessage(
            f"הזיהוי בוצע באמצעות {result.engine_name}. יש לבדוק כל שורה לפני הייצוא.",
            8000,
        )

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
        target.write_text(content, encoding="utf-8-sig")
        self.statusBar().showMessage(f"נשמר: {target}", 6000)

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
        self._store_editor_text()
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
