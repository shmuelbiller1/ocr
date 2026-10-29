"""The settings screen: the plugins that are there, and which one is used.

The screen shows every plugin the program knows: the ones that came
with it and the ones the user installed.  For every plugin the user can
see the version, the licence and whether it is switched on, and the
user can install a new plugin, remove one, or choose which plugin of
each kind is the active one.

Nothing here is required: the program works with no plugins at all.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..plugins import KIND_NAMES, PluginError, PluginInstaller, PluginRegistry

__all__ = ["SettingsDialog"]


class SettingsDialog(QDialog):
    """The screen where the user chooses the plugins of the program."""

    #: Emitted when the plugins were changed and the program has to
    #: look at them again.
    changed = Signal()
    install_decoding_requested = Signal()

    def __init__(self, registry: PluginRegistry, parent=None) -> None:
        super().__init__(parent)
        self.registry = registry
        self.installer = PluginInstaller(registry.root)
        self.setWindowTitle("הגדרות - תוספים ומנועים")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(760, 520)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["תוסף", "סוג", "גרסה", "רישיון", "מצב", "מקור"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        self.active_boxes: dict[str, QComboBox] = {}
        form = QFormLayout()
        for kind, name in KIND_NAMES.items():
            box = QComboBox()
            box.currentIndexChanged.connect(
                lambda _index, name=kind: self._on_active_changed(name)
            )
            self.active_boxes[kind] = box
            form.addRow(name, box)

        self.decoding_box = QComboBox()
        self.decoding_box.addItem("Raw / בסיסי — ללא מודל שפה", "raw")
        self.decoding_box.addItem("Beam 12 + 3 scales — ללא מודל שפה (ניסיוני)", "beam")
        self.decoding_box.addItem("Assisted — Beam 12 + 3 scales + מודלי שפה (ניסיוני)", "assisted")
        self.decoding_box.currentIndexChanged.connect(self._on_decoding_changed)
        form.addRow("Mishkefet: פענוח", self.decoding_box)
        self.install_decoding_button = QPushButton("התקנת מודלי השפה האופציונליים (32 MB)...")
        self.install_decoding_button.clicked.connect(self.install_decoding_requested.emit)
        self.remove_decoding_button = QPushButton("הסרת מודלי השפה האופציונליים...")
        self.remove_decoding_button.clicked.connect(self._remove_decoding_models)
        self.decoding_hint = QLabel(
            "Raw נשמר תמיד. פענוח מסייע מוצג בנפרד ואינו מחליף טקסט בלי אישור. "
            "מודלי שפה עלולים לשנות קיצורים ומונחים נדירים. השיפור על הדפים שלך לא אומת. "
            "מודלי השפה: CC-BY-NC-SA-4.0, שימוש לא מסחרי; מותקנים בנפרד.")
        self.decoding_hint.setWordWrap(True)

        buttons = QHBoxLayout()
        self.install_folder_button = QPushButton("התקנה מתיקייה...")
        self.install_folder_button.clicked.connect(self.install_from_folder)
        self.install_zip_button = QPushButton("התקנה מקובץ ZIP...")
        self.install_zip_button.clicked.connect(self.install_from_zip)
        self.remove_button = QPushButton("הסרת התוסף")
        self.remove_button.clicked.connect(self.remove_plugin)
        self.toggle_button = QPushButton("כיבוי/הפעלה")
        self.toggle_button.clicked.connect(self.toggle_plugin)
        for button in (
            self.install_folder_button,
            self.install_zip_button,
            self.remove_button,
            self.toggle_button,
        ):
            buttons.addWidget(button)

        self.hint = QLabel(
            "התוספים נשמרים בתיקיית הנתונים של התוכנית. ניתן להוסיף מנוע עברי "
            "אחר בלי לשנות את התוכנית."
        )
        self.hint.setWordWrap(True)

        close_box = QDialogButtonBox(QDialogButtonBox.Close)
        close_box.rejected.connect(self.reject)
        close_box.accepted.connect(self.accept)

        layout = QVBoxLayout()
        layout.addWidget(self.table)
        layout.addLayout(form)
        layout.addWidget(self.decoding_hint)
        layout.addWidget(self.install_decoding_button)
        layout.addWidget(self.remove_decoding_button)
        layout.addLayout(buttons)
        layout.addWidget(self.hint)
        layout.addWidget(close_box)
        self.setLayout(layout)

        self.refresh()

    # -- showing -----------------------------------------------------------
    def refresh(self) -> None:
        """Show the plugins that are there.

        This is a refresh of the *screen* and nothing more: the plugins
        are not read again, because a plugin that is read again is a new
        object, and the program that is running holds the old one.  The
        registry is read again when the set of the plugins really
        changes, when a plugin is installed or when one is removed.
        """
        self.table.setRowCount(0)
        for plugin in self.registry.plugins:
            row = self.table.rowCount()
            self.table.insertRow(row)
            state = "פעיל" if self.registry.is_enabled(plugin.id) else "מושבת"
            if plugin.error:
                state = "שגוי"
            values = [
                plugin.name,
                KIND_NAMES.get(plugin.kind, plugin.kind),
                plugin.version,
                plugin.license or "-",
                state,
                "נקבץ עם התוכנית" if plugin.builtin else "מותקן",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if plugin.error:
                    item.setToolTip(plugin.error)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()

        for kind, box in self.active_boxes.items():
            box.blockSignals(True)
            box.clear()
            box.addItem("ללא", "")
            for plugin in self.registry.by_kind(kind):
                box.addItem(plugin.name, plugin.id)
            # The list shows the choice of the user, even when the
            # plugin of that kind cannot run right now.  When there is
            # no choice yet, the plugin that is in force is shown.
            saved = self.registry.settings.active.get(kind)
            if saved is None:
                current = self.registry.active(kind)
                active = current.id if current is not None else ""
            else:
                active = saved
            index = box.findData(active)
            if index < 0:
                index = 0
            box.setCurrentIndex(index)
            box.blockSignals(False)

        plugin = self.registry.chosen("ocr") or self.registry.active("ocr")
        is_mishkefet = plugin is not None and plugin.id in ("mishkefet", "mishkefet-worker")
        self.decoding_box.blockSignals(True)
        self.decoding_box.setEnabled(is_mishkefet)
        mode = self.registry.options_of(plugin).get("decoding_mode", "raw") if is_mishkefet else "raw"
        self.decoding_box.setCurrentIndex(max(0, self.decoding_box.findData(mode)))
        self.decoding_box.blockSignals(False)

    def _on_decoding_changed(self, _index: int) -> None:
        plugin = self.registry.chosen("ocr") or self.registry.active("ocr")
        if plugin is None or plugin.id not in ("mishkefet", "mishkefet-worker"):
            return
        parent = self.parent()
        if getattr(parent, "task", None) is not None:
            QMessageBox.information(self, "פענוח", "יש להמתין לסיום המשימה לפני שינוי המצב.")
            self.refresh()
            return
        if not self.registry.set_option(plugin.id, "decoding_mode", self.decoding_box.currentData()):
            QMessageBox.warning(self, "פענוח", plugin.rejection or "לא ניתן לשנות את המצב.")
        else:
            self.changed.emit()
        self.refresh()

    def _remove_decoding_models(self) -> None:
        from ..engine.models import models_directory
        from ..engine.mishkefet_decoding import DECODING_ARTIFACTS
        if getattr(self.parent(), "task", None) is not None:
            QMessageBox.information(self, "הסרה", "יש להמתין לסיום המשימה.")
            return
        if QMessageBox.question(self, "הסרת מודלי השפה",
                                "להסיר רק את שני מודלי השפה? מודל הזיהוי והמסמכים יישארו.",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            for artifact in DECODING_ARTIFACTS.values():
                (models_directory() / artifact.filename).unlink(missing_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "הסרה", str(exc))
            return
        self.changed.emit()
        self.refresh()

    # -- the active plugin of every kind ------------------------------------
    def _on_active_changed(self, kind: str) -> None:
        """The user chose another plugin for this kind.

        Only this kind is saved: the other kinds keep the choice the
        user made, even when the plugin of that kind cannot run right
        now.
        """
        box = self.active_boxes.get(kind)
        if box is None:
            return
        self.registry.set_active(kind, box.currentData() or "")
        self.changed.emit()
        self.refresh()

    # -- installing ---------------------------------------------------------
    def install_from_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "בחירת תיקיית התוסף", ""
        )
        if not folder:
            return
        self._install(Path(folder))

    def install_from_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "בחירת קובץ התוסף", "", "קבצי ZIP (*.zip);;כל הקבצים (*)"
        )
        if not path:
            return
        self._install(Path(path))

    def _install(self, source: Path) -> None:
        try:
            if source.is_file():
                manifest = self.installer.install_zip(source)
            else:
                manifest = self.installer.install_folder(source)
        except PluginError as exc:
            QMessageBox.warning(self, "התקנת התוסף", str(exc))
            return
        except OSError as exc:
            QMessageBox.warning(self, "התקנת התוסף", f"לא ניתן להתקין: {exc}")
            return
        self.registry.load()
        self.refresh()
        self.changed.emit()
        QMessageBox.information(
            self,
            "התוסף הותקן",
            f"התוסף {manifest.name} ({manifest.id}) הותקן.\n"
            f"הרישיון: {manifest.license or 'לא צוין'}",
        )

    # -- removing and switching ---------------------------------------------
    def selected_plugin(self):
        """The plugin the user chose in the table, if there is one."""
        model = self.table.selectionModel()
        rows = model.selectedRows() if model is not None else []
        row = rows[0].row() if rows else self.table.currentRow()
        if row < 0 or row >= len(self.registry.plugins):
            return None
        return self.registry.plugins[row]

    def remove_plugin(self) -> None:
        plugin = self.selected_plugin()
        if plugin is None:
            QMessageBox.information(self, "הסרת התוסף", "יש לבחור תוסף תחילה.")
            return
        if plugin.builtin:
            QMessageBox.information(
                self,
                "הסרת התוסף",
                "אי אפשר להסיר תוסף שמגיע עם התוכנית. אפשר לכבות אותו, "
                "ואז התוכנית עובדת בלעדיו.",
            )
            return
        answer = QMessageBox.question(
            self,
            "הסרת התוסף",
            f"להסיר את התוסף {plugin.name}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.installer.remove(plugin.id)
        except PluginError as exc:
            QMessageBox.warning(self, "הסרת התוסף", str(exc))
            return
        except OSError as exc:
            QMessageBox.warning(
                self, "הסרת התוסף", f"לא ניתן להסיר את התוסף: {exc}"
            )
            return
        # The plugin is gone: the choices that were about it are gone
        # too, so that a plugin with the same name that is installed
        # later starts switched on.
        self.registry.settings.enabled.discard(plugin.id)
        self.registry.settings.disabled.discard(plugin.id)
        self.registry.settings.options.pop(plugin.id, None)
        self.registry.settings.active = {
            key: value
            for key, value in self.registry.settings.active.items()
            if value != plugin.id
        }
        self.registry.save()
        self.registry.load()
        self.refresh()
        self.changed.emit()

    def toggle_plugin(self) -> None:
        plugin = self.selected_plugin()
        if plugin is None:
            QMessageBox.information(self, "כיבוי והפעלה", "יש לבחור תוסף תחילה.")
            return
        self.registry.set_enabled(plugin.id, not self.registry.is_enabled(plugin.id))
        self.refresh()
        self.changed.emit()
