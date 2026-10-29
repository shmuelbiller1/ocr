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
from tests.qt_app import application, temporary_home  # noqa: E402


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

    def test_mishkefet_modes_are_explicit_persisted_and_not_globally_applied(self) -> None:
        active = self.dialog.active_boxes["ocr"]
        active.setCurrentIndex(active.findData("mishkefet-worker"))
        self.assertTrue(self.dialog.decoding_box.isEnabled())
        self.assertEqual(self.dialog.decoding_box.currentData(), "raw")
        self.dialog.decoding_box.setCurrentIndex(self.dialog.decoding_box.findData("assisted"))
        self.assertEqual(self.registry.settings.option("mishkefet-worker", "decoding_mode"), "assisted")
        self.assertIsNone(self.registry.settings.option("mishkefet", "decoding_mode"))
        active.setCurrentIndex(active.findData("kraken"))
        self.assertFalse(self.dialog.decoding_box.isEnabled())
        self.assertEqual(self.dialog.decoding_box.currentData(), "raw")
        active.setCurrentIndex(active.findData("mishkefet-worker"))
        self.assertEqual(self.dialog.decoding_box.currentData(), "assisted")

    def test_language_model_download_only_emits_on_explicit_request(self) -> None:
        requests = []
        self.dialog.install_decoding_requested.connect(lambda: requests.append(True))
        self.dialog.refresh()
        self.assertEqual(requests, [])
        self.dialog.install_decoding_button.click()
        self.assertEqual(requests, [True])

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
        # The first entry is "ללא": the choice that this kind has no
        # plugin at all.
        index = box.findData("")
        self.assertGreater(index, -1)
        box.setCurrentIndex(index)
        self.assertTrue(seen)
        self.assertEqual(self.registry.settings.active["grammar"], "")

    def test_the_list_shows_the_plugin_that_is_in_force(self) -> None:
        box = self.dialog.active_boxes["grammar"]
        current = self.registry.active("grammar")
        self.assertIsNotNone(current)
        self.assertEqual(box.currentData(), current.id)

    def test_the_choice_of_another_kind_is_not_changed(self) -> None:
        # The user chose the worker of the recognition, which cannot
        # run yet because the model is not installed.
        self.registry.set_active("ocr", "kraken-worker")
        box = self.dialog.active_boxes["grammar"]
        index = box.findData("grammar-hebrew")
        self.assertGreater(index, -1)
        box.setCurrentIndex(index)
        self.assertEqual(self.registry.settings.active.get("ocr"), "kraken-worker")

    def test_a_refresh_of_the_screen_does_not_replace_the_plugins(self) -> None:
        """A plugin that is read again is a new object, and the program
        that is running holds the old one.  The screen is only a
        screen: refreshing it does not read the plugins again."""
        before = list(self.registry.plugins)
        self.dialog.refresh()
        after = list(self.registry.plugins)
        self.assertEqual(len(before), len(after))
        for old, new in zip(before, after):
            self.assertIs(old, new)

    def test_switching_a_plugin_off_does_not_replace_the_plugins(self) -> None:
        before = list(self.registry.plugins)
        self.dialog.table.setCurrentCell(0, 0)
        self.dialog.toggle_plugin()
        after = list(self.registry.plugins)
        for old, new in zip(before, after):
            self.assertIs(old, new)


class WindowPluginTests(unittest.TestCase):
    """The window takes its engines and its modules from the plugins."""

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

    def test_the_choice_of_no_engine_is_kept(self) -> None:
        # The user chooses that the program has no engine at all: the
        # recognition is then not offered, and the choice is remembered.
        self.window.plugins.set_active("ocr", "")
        self.window._on_plugins_changed()
        # The engine of the registry is the one that says that there is
        # no engine, and the choice is remembered.
        self.assertFalse(self.window.registry.engine.available())
        self.assertEqual(self.window.plugins.settings.active.get("ocr"), "")
        # The program knows that this is a choice and not a missing
        # choice, and does not pick an engine on its own.
        self.assertTrue(self.window.plugins.without_plugin("ocr"))

    def test_when_every_module_is_off_there_are_no_modules_at_all(self) -> None:
        for plugin in self.window.plugins.by_kind("spelling"):
            self.window.plugins.set_enabled(plugin.id, False)
        for plugin in self.window.plugins.by_kind("grammar"):
            self.window.plugins.set_enabled(plugin.id, False)
        for plugin in self.window.plugins.by_kind("style"):
            self.window.plugins.set_enabled(plugin.id, False)
        self.window._on_plugins_changed()
        self.assertEqual(self.window.suggestion_modules.modules, [])
        self.assertEqual(self.window.suggestion_modules.check("שלום , עולם"), [])


if __name__ == "__main__":
    unittest.main()
