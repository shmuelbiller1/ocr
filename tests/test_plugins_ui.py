"""Tests for the settings screen of the plugins."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

if sys.platform.startswith("linux"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hebrew_workbench.plugins import PluginRegistry
from hebrew_workbench.ui.settings_dialog import SettingsDialog
from tests.qt_app import application  # noqa: E402


class SettingsDialogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = application()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "plugins"
        self.registry = PluginRegistry(root=self.root)
        self.dialog = SettingsDialog(self.registry)

    def tearDown(self) -> None:
        self.dialog.close()
        self.dialog.deleteLater()
        self.app.processEvents()
        self.temporary.cleanup()

    def test_the_plugins_are_shown(self) -> None:
        names = [
            self.dialog.table.item(row, 0).text()
            for row in range(self.dialog.table.rowCount())
        ]
        self.assertTrue(names)
        self.assertIn("Kraken + PP-OCRv6 (in the program)", names)

    def test_every_kind_has_a_box_to_choose_the_active_plugin(self) -> None:
        self.assertIn("ocr", self.dialog.active_boxes)
        self.assertIn("spelling", self.dialog.active_boxes)
        self.assertIn("grammar", self.dialog.active_boxes)
        self.assertIn("style", self.dialog.active_boxes)

    def test_the_active_plugin_of_a_kind_can_be_chosen(self) -> None:
        box = self.dialog.active_boxes["ocr"]
        index = box.findData("kraken-worker")
        self.assertGreater(index, -1)
        box.setCurrentIndex(index)
        self.assertEqual(self.registry.settings.active["ocr"], "kraken-worker")

    def test_a_plugin_can_be_switched_off(self) -> None:
        self.dialog.table.setCurrentCell(0, 0)
        plugin_id = self.dialog.selected_plugin().id
        self.dialog.toggle_plugin()
        self.assertIn(plugin_id, self.registry.settings.disabled)
        self.assertFalse(self.registry.is_enabled(plugin_id))

    def test_the_dialog_reports_the_changes(self) -> None:
        seen: list[int] = []
        self.dialog.changed.connect(lambda: seen.append(1))
        box = self.dialog.active_boxes["grammar"]
        index = box.findData("grammar-hebrew")
        if index >= 0:
            box.setCurrentIndex(index)
        self.assertTrue(seen)


class WindowPluginTests(unittest.TestCase):
    """The window takes its engines and its modules from the plugins."""

    def setUp(self) -> None:
        self.app = application()
        from hebrew_workbench.ui.main_window import MainWindow

        self.window = MainWindow()

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_the_window_has_the_plugins(self) -> None:
        ids = {plugin.id for plugin in self.window.plugins.plugins}
        self.assertIn("kraken", ids)

    def test_the_window_has_a_button_to_the_settings_of_the_plugins(self) -> None:
        self.assertTrue(hasattr(self.window, "plugin_settings_action"))

    def test_the_modules_of_the_window_come_from_the_plugins(self) -> None:
        kinds = {
            module.kind for module in self.window.suggestion_modules.modules
        }
        self.assertIn("spelling", kinds)
        self.assertIn("grammar", kinds)

    def test_a_module_that_is_switched_off_gives_no_proposals(self) -> None:
        self.window.plugins.set_enabled("grammar-hebrew", False)
        self.window._on_plugins_changed()
        proposals = self.window.suggestion_modules.check("שלום , עולם")
        self.assertEqual(proposals, [])


if __name__ == "__main__":
    unittest.main()
