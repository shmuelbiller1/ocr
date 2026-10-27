"""Tests for the plugin system."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from hebrew_workbench.plugins import (
    KIND_GRAMMAR,
    KIND_OCR,
    KIND_SPELLING,
    KIND_STYLE,
    PluginError,
    PluginInstaller,
    PluginManifest,
    PluginRegistry,
    PluginSettings,
    read_manifest,
)

MANIFEST = {
    "id": "example-engine",
    "name": "מנוע לדוגמה",
    "version": "0.1.0",
    "kind": "ocr",
    "entry": "example_engine:ExampleEngine",
    "license": "MIT",
    "description": "מנוע קטן שנכתב לבדיקה",
}

PLUGIN_CODE = '''
class ExampleEngine:
    """A tiny engine, used by the tests."""

    name = "Example engine"

    def __init__(self, options=None):
        self.options = dict(options or {})

    def available(self):
        return True

    def manifest(self):
        return None
'''


def make_plugin_folder(folder: Path, manifest: dict | None = None) -> Path:
    """Write a plugin folder with a manifest and a module in it."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plugin.json").write_text(
        json.dumps(manifest or MANIFEST, ensure_ascii=False), encoding="utf-8"
    )
    (folder / "example_engine.py").write_text(PLUGIN_CODE, encoding="utf-8")
    return folder


class ManifestTests(unittest.TestCase):
    def test_a_manifest_is_read(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = make_plugin_folder(Path(folder))
            manifest = read_manifest(path)
        self.assertEqual(manifest.id, "example-engine")
        self.assertEqual(manifest.kind, KIND_OCR)
        self.assertEqual(manifest.license, "MIT")

    def test_a_manifest_without_the_needed_fields_is_refused(self) -> None:
        with self.assertRaises(PluginError):
            PluginManifest.from_dict({"id": "x", "name": "y"})

    def test_an_identifier_with_a_path_in_it_is_refused(self) -> None:
        with self.assertRaises(PluginError):
            PluginManifest.from_dict({**MANIFEST, "id": "../evil"})

    def test_a_kind_that_is_not_known_is_refused(self) -> None:
        with self.assertRaises(PluginError):
            PluginManifest.from_dict({**MANIFEST, "kind": "something-else"})

    def test_an_entry_without_a_colon_is_refused(self) -> None:
        with self.assertRaises(PluginError):
            PluginManifest.from_dict({**MANIFEST, "entry": "example_engine"})


class InstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "plugins"
        self.installer = PluginInstaller(self.root)
        self.source = make_plugin_folder(Path(self.temporary.name) / "source")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_a_plugin_is_installed_from_a_folder(self) -> None:
        manifest = self.installer.install_folder(self.source)
        self.assertEqual(manifest.id, "example-engine")
        self.assertTrue((self.root / "example-engine" / "plugin.json").is_file())

    def test_the_original_files_are_not_touched(self) -> None:
        self.installer.install_folder(self.source)
        self.assertTrue((self.source / "plugin.json").is_file())

    def test_a_plugin_that_is_already_there_is_not_replaced_by_accident(self) -> None:
        self.installer.install_folder(self.source)
        with self.assertRaises(PluginError):
            self.installer.install_folder(self.source)

    def test_a_plugin_can_be_installed_again_on_purpose(self) -> None:
        self.installer.install_folder(self.source)
        manifest = self.installer.install_folder(self.source, overwrite=True)
        self.assertEqual(manifest.id, "example-engine")

    def test_a_plugin_is_installed_from_a_zip_file(self) -> None:
        archive = Path(self.temporary.name) / "plugin.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.write(self.source / "plugin.json", "plugin.json")
            handle.write(self.source / "example_engine.py", "example_engine.py")
        manifest = self.installer.install_zip(archive)
        self.assertEqual(manifest.id, "example-engine")

    def test_a_zip_that_holds_a_file_outside_of_itself_is_refused(self) -> None:
        archive = Path(self.temporary.name) / "evil.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("../evil.py", "print('hello')")
        with self.assertRaises(PluginError):
            self.installer.install_zip(archive)

    def test_a_plugin_is_removed(self) -> None:
        self.installer.install_folder(self.source)
        self.assertTrue(self.installer.remove("example-engine"))
        self.assertFalse((self.root / "example-engine").exists())

    def test_a_built_in_plugin_is_not_removed_by_the_installer(self) -> None:
        # The installer only touches the folder of the user; the built-in
        # plugins are not in it.
        self.assertFalse(self.installer.remove("kraken"))


class SettingsTests(unittest.TestCase):
    def test_the_settings_are_written_and_read_back(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            settings = PluginSettings.load(path)
            settings.set_active = None  # not part of the settings
            settings.active["ocr"] = "example"
            settings.set_enabled("example", True)
            settings.set_option("example", "dictionary", "/tmp/words.txt")
            settings.save(path)
            again = PluginSettings.load(path)
        self.assertEqual(again.active["ocr"], "example")
        self.assertTrue(again.is_enabled("example"))
        self.assertEqual(again.option("example", "dictionary"), "/tmp/words.txt")

    def test_a_broken_settings_file_does_not_stop_the_program(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text("{not json", encoding="utf-8")
            settings = PluginSettings.load(path)
        self.assertEqual(settings.active, {})


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "plugins"
        self.registry = PluginRegistry(root=self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_the_built_in_plugins_are_there(self) -> None:
        ids = {plugin.id for plugin in self.registry.plugins}
        self.assertIn("kraken", ids)
        self.assertIn("spelling-hebrew", ids)
        self.assertIn("grammar-hebrew", ids)
        self.assertIn("style-leshon-ha-sefer", ids)

    def test_the_style_plugin_starts_switched_off(self) -> None:
        self.assertFalse(self.registry.is_enabled("style-leshon-ha-sefer"))

    def test_the_grammar_and_the_spelling_start_switched_on(self) -> None:
        self.assertTrue(self.registry.is_enabled("grammar-hebrew"))
        self.assertTrue(self.registry.is_enabled("spelling-hebrew"))

    def test_a_plugin_can_be_switched_off_and_on_again(self) -> None:
        self.registry.set_enabled("grammar-hebrew", False)
        self.assertFalse(self.registry.is_enabled("grammar-hebrew"))
        self.registry.set_enabled("grammar-hebrew", True)
        self.assertTrue(self.registry.is_enabled("grammar-hebrew"))

    def test_the_choice_of_the_user_is_kept(self) -> None:
        self.registry.set_active(KIND_OCR, "kraken")
        again = PluginRegistry(root=self.root)
        self.assertEqual(again.settings.active[KIND_OCR], "kraken")

    def test_an_installed_plugin_is_found_and_can_be_used(self) -> None:
        source = make_plugin_folder(Path(self.temporary.name) / "source")
        PluginInstaller(self.root).install_folder(source)
        registry = PluginRegistry(root=self.root)
        plugin = registry.get("example-engine")
        self.assertIsNotNone(plugin)
        self.assertEqual(plugin.error, "")
        self.assertTrue(plugin.available())
        self.assertEqual(plugin.object.name, "Example engine")

    def test_a_broken_plugin_is_reported_and_does_not_stop_the_others(self) -> None:
        folder = self.root / "broken"
        folder.mkdir(parents=True)
        (folder / "plugin.json").write_text(
            json.dumps({**MANIFEST, "id": "broken", "entry": "nothing:here"}),
            encoding="utf-8",
        )
        registry = PluginRegistry(root=self.root)
        self.assertTrue(registry.errors)
        self.assertIsNotNone(registry.get("grammar-hebrew"))
        self.assertIsNone(registry.get("broken").object)

    def test_the_modules_of_the_proposals_come_from_the_plugins(self) -> None:
        modules = self.registry.suggestion_modules()
        kinds = {module.kind for module in modules}
        self.assertIn(KIND_SPELLING, kinds)
        self.assertIn(KIND_GRAMMAR, kinds)

    def test_the_program_works_without_a_plugins_folder(self) -> None:
        root = Path(self.temporary.name) / "nothing-here"
        registry = PluginRegistry(root=root)
        self.assertTrue(registry.plugins)
        self.assertEqual(registry.errors, [])
        self.assertEqual(registry.active(KIND_OCR).id, "kraken")

    def test_a_plugin_with_the_same_id_as_a_built_in_one_does_not_win(self) -> None:
        source = make_plugin_folder(
            Path(self.temporary.name) / "source", {**MANIFEST, "id": "kraken"}
        )
        PluginInstaller(self.root).install_folder(source)
        registry = PluginRegistry(root=self.root)
        plugin = registry.get("kraken")
        self.assertTrue(plugin.builtin)
        self.assertEqual(len([p for p in registry.plugins if p.id == "kraken"]), 1)


if __name__ == "__main__":
    unittest.main()
