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


def make_plugin_folder(
    folder: Path, manifest: dict | None = None, code: str | None = None
) -> Path:
    """Write a plugin folder with a manifest and a module in it."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plugin.json").write_text(
        json.dumps(manifest or MANIFEST, ensure_ascii=False), encoding="utf-8"
    )
    (folder / "example_engine.py").write_text(
        code if code is not None else PLUGIN_CODE, encoding="utf-8"
    )
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
        # The plugins that come with the program are there, even when
        # the user has no folder of plugins at all.
        self.assertIsNotNone(registry.get("kraken"))
        self.assertIsNotNone(registry.get("spelling-hebrew"))

    def test_a_plugin_with_the_same_id_as_a_built_in_one_is_refused(self) -> None:
        source = make_plugin_folder(
            Path(self.temporary.name) / "source", {**MANIFEST, "id": "kraken"}
        )
        with self.assertRaises(PluginError):
            PluginInstaller(self.root).install_folder(source)
        registry = PluginRegistry(root=self.root)
        plugin = registry.get("kraken")
        self.assertTrue(plugin.builtin)
        self.assertEqual(len([p for p in registry.plugins if p.id == "kraken"]), 1)


class ActiveChoiceTests(unittest.TestCase):
    """The choice of the user is kept, even when it is "no plugin"."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "plugins"
        self.registry = PluginRegistry(root=self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_a_kind_without_a_choice_uses_the_first_plugin_that_is_on(self) -> None:
        self.assertIsNotNone(self.registry.active(KIND_GRAMMAR))

    def test_the_user_can_choose_that_a_kind_has_no_plugin(self) -> None:
        self.registry.set_active(KIND_GRAMMAR, "")
        self.assertIsNone(self.registry.active(KIND_GRAMMAR))
        self.assertEqual(self.registry.settings.active[KIND_GRAMMAR], "")

    def test_the_choice_of_no_plugin_survives_a_restart(self) -> None:
        self.registry.set_active(KIND_GRAMMAR, "")
        again = PluginRegistry(root=self.root)
        self.assertIsNone(again.active(KIND_GRAMMAR))

    def test_a_chosen_plugin_is_the_one_that_is_used(self) -> None:
        self.registry.set_active(KIND_GRAMMAR, "grammar-hebrew")
        self.assertEqual(self.registry.active(KIND_GRAMMAR).id, "grammar-hebrew")


class ReplacedPluginTests(unittest.TestCase):
    """A plugin that was replaced is read again, and not from the cache."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "plugins"
        self.source = Path(self.temporary.name) / "source"
        self.registry = PluginRegistry(root=self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_the_code_of_a_replaced_plugin_is_read_again(self) -> None:
        other = PLUGIN_CODE.replace("Example engine", "The second engine")
        make_plugin_folder(self.source, code=other)
        installer = PluginInstaller(self.root)
        installer.install_folder(self.source)
        self.registry.load()
        first = self.registry.get("example-engine")
        self.assertIsNotNone(first)
        self.assertEqual(first.object.name, "The second engine")

        # The same plugin, with other code, in the same session.
        make_plugin_folder(self.source, code=PLUGIN_CODE)
        installer.install_folder(self.source, overwrite=True)
        self.registry.load()
        second = self.registry.get("example-engine")
        self.assertIsNotNone(second)
        self.assertEqual(second.object.name, "Example engine")


class SuggestionModuleIdTests(unittest.TestCase):
    """A module with a name of its own still does the work of its kind."""

    def test_the_switch_of_a_module_is_by_its_kind(self) -> None:
        from hebrew_workbench.suggestions.base import SuggestionModule
        from hebrew_workbench.suggestions.registry import SuggestionRegistry

        class OtherGrammar(SuggestionModule):
            id = "other-grammar"
            kind = "grammar"
            name = "ניסוח אחר"

            def available(self):
                return True

            def check(self, text):
                return []

        registry = SuggestionRegistry([OtherGrammar()])
        registry.set_enabled("grammar", True)
        self.assertTrue(registry.is_enabled("grammar"))
        registry.set_enabled("grammar", False)
        self.assertFalse(registry.is_enabled("grammar"))


class DangerousIdentifierTests(unittest.TestCase):
    """An identifier may never lead outside of the folder of the plugins."""

    def test_the_identifier_of_a_folder_is_refused(self) -> None:
        for name in (".", ".."):
            with self.assertRaises(PluginError):
                PluginManifest.from_dict({**MANIFEST, "id": name})

    def test_the_installer_refuses_to_leave_its_folder(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            installer = PluginInstaller(Path(folder) / "plugins")
            for name in (".", ".."):
                with self.assertRaises(PluginError):
                    installer.plugin_folder(name)
                with self.assertRaises(PluginError):
                    installer.remove(name)


class IsolationTests(unittest.TestCase):
    """The code of a plugin does not take the place of anything else."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "plugins"
        self.source = Path(self.temporary.name) / "source"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _install(self, name: str, code: str) -> None:
        manifest = {**MANIFEST, "id": name, "entry": "example_engine:ExampleEngine"}
        folder = self.source / name
        make_plugin_folder(folder, manifest=manifest, code=code)
        PluginInstaller(self.root).install_folder(folder)

    def test_two_plugins_with_the_same_module_name_do_not_mix(self) -> None:
        self._install("first", PLUGIN_CODE.replace("Example engine", "The first one"))
        self._install("second", PLUGIN_CODE.replace("Example engine", "The second one"))
        registry = PluginRegistry(root=self.root)
        first = registry.get("first")
        second = registry.get("second")
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first.object.name, "The first one")
        self.assertEqual(second.object.name, "The second one")

    def test_a_file_of_a_plugin_does_not_hide_a_module_of_the_program(self) -> None:
        manifest = {**MANIFEST, "id": "shadow", "entry": "json:ExampleEngine"}
        folder = self.source / "shadow"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "plugin.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        (folder / "json.py").write_text(
            'raise RuntimeError("this file must not be imported")', encoding="utf-8"
        )
        PluginInstaller(self.root).install_folder(folder)
        registry = PluginRegistry(root=self.root)
        plugin = registry.get("shadow")
        self.assertIsNotNone(plugin)
        # The plugin could not be started, and the reason is clear; the
        # module `json` of the program still works.
        self.assertIsNone(plugin.object)
        self.assertTrue(plugin.error)
        import json as json_module

        self.assertEqual(json_module.dumps({"a": 1}), '{"a": 1}')


class UnavailablePluginTests(unittest.TestCase):
    """An engine that cannot run is not offered to the user."""

    UNUSABLE = """
class ExampleEngine:
    name = "Engine that cannot run"

    def __init__(self, options=None):
        self.options = dict(options or {})

    def available(self):
        return False
"""

    def test_an_engine_that_cannot_run_is_not_the_active_one(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "plugins"
            source = Path(folder) / "source"
            manifest = {**MANIFEST, "id": "unusable"}
            make_plugin_folder(source, manifest=manifest, code=self.UNUSABLE)
            PluginInstaller(root).install_folder(source)
            registry = PluginRegistry(root=root)
            plugin = registry.get("unusable")
            self.assertIsNotNone(plugin)
            self.assertFalse(plugin.available())
            # The engine that cannot run is not the one that is used,
            # whether another engine can run or not.
            active = registry.active("ocr")
            self.assertTrue(active is None or active.id != "unusable")

    def test_a_module_that_waits_for_a_word_list_is_still_the_chosen_one(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "plugins"
            registry = PluginRegistry(root=root)
            spelling = registry.active(KIND_SPELLING)
            self.assertIsNotNone(spelling)
            self.assertEqual(spelling.id, "spelling-hebrew")


class PackagePluginTests(unittest.TestCase):
    """A plugin that is a package, with an import from inside it."""

    def test_a_relative_import_inside_the_plugin_works(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "plugins"
            source = Path(folder) / "source" / "my_plugin"
            source.mkdir(parents=True)
            (source / "__init__.py").write_text("", encoding="utf-8")
            (source / "helper.py").write_text(
                'NAME = "the helper"\n', encoding="utf-8"
            )
            (source / "engine.py").write_text(
                "from .helper import NAME\n"
                "\n"
                "class Engine:\n"
                '    name = "Engine of the package"\n'
                "\n"
                "    def __init__(self, options=None):\n"
                "        self.options = dict(options or {})\n"
                "        self.helper = NAME\n"
                "\n"
                "    def available(self):\n"
                "        return True\n",
                encoding="utf-8",
            )
            manifest = {
                **MANIFEST,
                "id": "package-engine",
                "entry": "my_plugin.engine:Engine",
            }
            (Path(folder) / "source" / "plugin.json").write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
            )
            PluginInstaller(root).install_folder(Path(folder) / "source")
            registry = PluginRegistry(root=root)
            plugin = registry.get("package-engine")
            self.assertIsNotNone(plugin)
            self.assertEqual(plugin.error, "")
            self.assertIsNotNone(plugin.object)
            self.assertEqual(plugin.object.helper, "the helper")
            self.assertEqual(plugin.object.name, "Engine of the package")


class ManifestOptionTests(unittest.TestCase):
    """The options of the manifest reach the plugin."""

    CODE = """
class ExampleEngine:
    name = "Engine with options"

    def __init__(self):
        self.options = {}

    def available(self):
        return True

    def configure(self, options):
        self.options = dict(options)
"""

    def test_the_options_of_the_manifest_are_given_to_the_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "plugins"
            source = Path(folder) / "source"
            manifest = {**MANIFEST, "options": {"model_id": "a-model"}}
            make_plugin_folder(source, manifest=manifest, code=self.CODE)
            PluginInstaller(root).install_folder(source)
            registry = PluginRegistry(root=root)
            plugin = registry.get("example-engine")
            self.assertIsNotNone(plugin)
            self.assertEqual(plugin.error, "")
            self.assertEqual(plugin.object.options.get("model_id"), "a-model")

    def test_the_choice_of_the_user_is_on_top_of_the_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "plugins"
            source = Path(folder) / "source"
            manifest = {**MANIFEST, "options": {"model_id": "a-model"}}
            make_plugin_folder(source, manifest=manifest, code=self.CODE)
            PluginInstaller(root).install_folder(source)
            registry = PluginRegistry(root=root)
            registry.set_option("example-engine", "model_id", "another-model")
            plugin = registry.get("example-engine")
            self.assertEqual(plugin.object.options.get("model_id"), "another-model")


class PackageInitTests(unittest.TestCase):
    """The code of the package of a plugin runs when the plugin loads."""

    def test_the_code_of_the_package_of_the_plugin_runs(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "plugins"
            source = Path(folder) / "source" / "my_plugin"
            source.mkdir(parents=True)
            (source / "__init__.py").write_text(
                'READY = "the package is ready"\n', encoding="utf-8"
            )
            (source / "engine.py").write_text(
                "from . import READY\n"
                "\n"
                "class Engine:\n"
                '    name = "Engine of the package"\n'
                "\n"
                "    def __init__(self, options=None):\n"
                "        self.options = dict(options or {})\n"
                "        self.ready = READY\n"
                "\n"
                "    def available(self):\n"
                "        return True\n",
                encoding="utf-8",
            )
            manifest = {
                **MANIFEST,
                "id": "package-engine",
                "entry": "my_plugin.engine:Engine",
            }
            (Path(folder) / "source" / "plugin.json").write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
            )
            PluginInstaller(root).install_folder(Path(folder) / "source")
            registry = PluginRegistry(root=root)
            plugin = registry.get("package-engine")
            self.assertEqual(plugin.error, "")
            self.assertEqual(plugin.object.ready, "the package is ready")


class FolderNameTests(unittest.TestCase):
    """Two plugins with the same identifier in different folders are apart."""

    def test_the_name_of_the_package_includes_the_folder(self) -> None:
        from hebrew_workbench.plugins.loader import _private_name

        first = _private_name("engine", Path("/tmp/one"))
        second = _private_name("engine", Path("/tmp/two"))
        third = _private_name("other", Path("/tmp/one"))
        self.assertNotEqual(first, second)
        self.assertNotEqual(first, third)


class WithoutPluginTests(unittest.TestCase):
    """The choice of the user: no plugin of this kind at all."""

    def test_a_choice_that_was_not_made_is_not_a_choice_of_none(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            registry = PluginRegistry(root=Path(folder) / "plugins")
            self.assertFalse(registry.without_plugin("ocr"))
            registry.set_active("ocr", "")
            self.assertTrue(registry.without_plugin("ocr"))
            registry.set_active("ocr", "kraken")
            self.assertFalse(registry.without_plugin("ocr"))


class SavedOptionTests(unittest.TestCase):
    """The choices of the user reach the plugin that takes them."""

    CODE = """
class ExampleEngine:
    name = "Engine with options"

    def __init__(self, options=None):
        self.options = dict(options or {})

    def available(self):
        return True
"""

    def test_the_options_of_the_user_reach_the_constructor(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "plugins"
            source = Path(folder) / "source"
            manifest = {**MANIFEST, "options": {"model_id": "the-model"}}
            make_plugin_folder(source, manifest=manifest, code=self.CODE)
            installer = PluginInstaller(root)
            installer.install_folder(source)
            registry = PluginRegistry(root=root)
            registry.set_option("example-engine", "model_id", "another-model")
            # The plugin is built again with the choices of the user.
            registry.load()
            plugin = registry.get("example-engine")
            self.assertEqual(plugin.object.options.get("model_id"), "another-model")


class RefusedOptionTests(unittest.TestCase):
    """A plugin that does not accept a value does not keep it."""

    CODE = """
class ExampleEngine:
    name = "Engine with a strict setting"

    def __init__(self, options=None):
        self.options = dict(options or {})

    def available(self):
        return True

    def configure(self, options):
        if options.get("model_id") == "not-allowed":
            raise ValueError("this model is not allowed")
        self.options = dict(options)
"""

    def test_the_old_value_stays_when_the_plugin_refuses_the_new_one(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "plugins"
            source = Path(folder) / "source"
            manifest = {**MANIFEST, "options": {"model_id": "a-model"}}
            make_plugin_folder(source, manifest=manifest, code=self.CODE)
            PluginInstaller(root).install_folder(source)
            registry = PluginRegistry(root=root)
            accepted = registry.set_option("example-engine", "model_id", "another-model")
            self.assertTrue(accepted)
            refused = registry.set_option("example-engine", "model_id", "not-allowed")
            self.assertFalse(refused)
            plugin = registry.get("example-engine")
            # The value that was refused is not saved, and the old one
            # is still the one of the plugin.
            self.assertEqual(
                registry.settings.options["example-engine"]["model_id"],
                "another-model",
            )
            self.assertEqual(plugin.object.options.get("model_id"), "another-model")
            self.assertIn("not allowed", plugin.rejection)
            # The plugin itself works, and it is still the one that the
            # user chose.
            self.assertTrue(registry.is_enabled("example-engine"))


class PackageExportTests(unittest.TestCase):
    """A package that exports its engine loads without importing twice."""

    INIT = """
from .engine import DemoEngine

__all__ = ["DemoEngine"]
"""

    ENGINE = """
import builtins

if getattr(builtins, "_demo_engine_loaded", False):
    raise RuntimeError("the module of the engine was imported twice")

builtins._demo_engine_loaded = True


class DemoEngine:
    name = "Engine of a package"

    def __init__(self, options=None):
        self.options = dict(options or {})

    def available(self):
        return True
"""

    def test_the_engine_of_a_package_is_imported_once(self) -> None:
        import builtins

        if hasattr(builtins, "_demo_engine_loaded"):
            del builtins._demo_engine_loaded
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "plugins"
            source = Path(folder) / "source"
            package = source / "demo"
            package.mkdir(parents=True)
            manifest = {
                **MANIFEST,
                "id": "demo-engine",
                "entry": "demo.engine:DemoEngine",
            }
            (source / "plugin.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (package / "__init__.py").write_text(self.INIT, encoding="utf-8")
            (package / "engine.py").write_text(self.ENGINE, encoding="utf-8")
            PluginInstaller(root).install_folder(source)
            registry = PluginRegistry(root=root)
            plugin = registry.get("demo-engine")
            self.assertEqual(plugin.error, "")
            self.assertIsNotNone(plugin.object)
            self.assertEqual(plugin.object.name, "Engine of a package")


class NestedPackageTests(unittest.TestCase):
    """A plugin whose engine is in a package of a package."""

    INIT = """
from .sub.engine import DemoEngine

__all__ = ["DemoEngine"]
"""

    SUB_INIT = """
import builtins

if getattr(builtins, "_demo_sub_loaded", False):
    raise RuntimeError("the package of the engine was imported twice")

builtins._demo_sub_loaded = True
"""

    ENGINE = """
class DemoEngine:
    name = "Engine of a nested package"

    def __init__(self, options=None):
        self.options = dict(options or {})

    def available(self):
        return True
"""

    def test_the_engine_of_a_nested_package_is_imported_once(self) -> None:
        import builtins

        if hasattr(builtins, "_demo_sub_loaded"):
            del builtins._demo_sub_loaded
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "plugins"
            source = Path(folder) / "source"
            package = source / "demo"
            package.mkdir(parents=True)
            manifest = {
                **MANIFEST,
                "id": "demo-engine",
                "entry": "demo.sub.engine:DemoEngine",
            }
            (source / "plugin.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (package / "__init__.py").write_text(self.INIT, encoding="utf-8")
            sub = package / "sub"
            sub.mkdir()
            (sub / "__init__.py").write_text(self.SUB_INIT, encoding="utf-8")
            (sub / "engine.py").write_text(self.ENGINE, encoding="utf-8")
            PluginInstaller(root).install_folder(source)
            registry = PluginRegistry(root=root)
            plugin = registry.get("demo-engine")
            self.assertEqual(plugin.error, "")
            self.assertIsNotNone(plugin.object)


class PluginResourceTests(unittest.TestCase):
    """A plugin reads the files that come with it."""

    CODE = """
import importlib.resources

DATA = importlib.resources.files(__package__).joinpath("data.txt").read_text()


class DemoEngine:
    name = "Engine with a file of its own"

    def __init__(self, options=None):
        self.options = dict(options or {})
        self.data = DATA

    def available(self):
        return True
"""

    def test_a_plugin_can_read_the_files_that_come_with_it(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "plugins"
            source = Path(folder) / "source"
            source.mkdir(parents=True)
            manifest = {**MANIFEST, "id": "demo-engine", "entry": "demo:DemoEngine"}
            (source / "plugin.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (source / "data.txt").write_text("the data of the plugin", encoding="utf-8")
            (source / "demo.py").write_text(self.CODE, encoding="utf-8")
            PluginInstaller(root).install_folder(source)
            registry = PluginRegistry(root=root)
            plugin = registry.get("demo-engine")
            self.assertEqual(plugin.error, "")
            self.assertEqual(plugin.object.data, "the data of the plugin")


class EngineWithoutAvailabilityTests(unittest.TestCase):
    """An engine without `available` cannot be offered."""

    CODE = """
class DemoEngine:
    name = "Engine without a way to say that it can work"
"""

    def test_the_engine_is_not_offered(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "plugins"
            source = Path(folder) / "source"
            manifest = {**MANIFEST, "id": "demo-engine"}
            make_plugin_folder(source, manifest=manifest, code=self.CODE)
            PluginInstaller(root).install_folder(source)
            registry = PluginRegistry(root=root)
            plugin = registry.get("demo-engine")
            self.assertFalse(plugin.available())
            self.assertEqual(registry.ocr_engines(), [])


class ReservedIdentifierTests(unittest.TestCase):
    """The identifiers that the program keeps for itself."""

    def test_the_name_of_the_settings_file_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "plugins"
            source = Path(folder) / "source"
            manifest = {**MANIFEST, "id": "settings.json"}
            make_plugin_folder(source, manifest=manifest)
            with self.assertRaises(PluginError):
                PluginInstaller(root).install_folder(source)
            self.assertFalse((root / "settings.json").exists())


class ModuleKindTests(unittest.TestCase):
    """The kind of a module comes from the manifest of its plugin."""

    CODE = """
from hebrew_workbench.suggestions.base import SuggestionModule


class ExampleModule(SuggestionModule):
    def __init__(self, options=None):
        self.options = dict(options or {})

    def check(self, text):
        return []
"""

    def test_the_kind_of_the_manifest_is_the_kind_of_the_module(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "plugins"
            source = Path(folder) / "source"
            manifest = {**MANIFEST, "kind": "spelling", "id": "example-spelling"}
            make_plugin_folder(source, manifest=manifest, code=self.CODE)
            PluginInstaller(root).install_folder(source)
            registry = PluginRegistry(root=root)
            registry.set_active("spelling", "example-spelling")
            modules = registry.suggestion_modules()
        kinds = [module.kind for module in modules]
        self.assertIn("spelling", kinds)
        # The module of the plugin is the first one, and it has the
        # kind of the manifest and not the default of the base class.
        self.assertEqual(modules[0].kind, "spelling")


class BrokenModuleTests(unittest.TestCase):
    """A module that does not follow the contract is left out."""

    CODE = """
class ExampleEngine:
    name = "Not a module of proposals"

    def __init__(self, options=None):
        self.options = dict(options or {})
"""

    def test_a_module_without_check_is_not_given_to_the_program(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "plugins"
            source = Path(folder) / "source"
            manifest = {**MANIFEST, "kind": "grammar", "id": "broken-grammar"}
            make_plugin_folder(source, manifest=manifest, code=self.CODE)
            PluginInstaller(root).install_folder(source)
            registry = PluginRegistry(root=root)
            registry.set_active("grammar", "broken-grammar")
            modules = registry.suggestion_modules()
        # The module that does not follow the contract is left out; the
        # modules that do follow it are still there.
        self.assertNotIn("broken-grammar", [getattr(m, "id", "") for m in modules])
        self.assertEqual(
            [getattr(m, "id", "") for m in modules].count("broken-grammar"), 0
        )


if __name__ == "__main__":
    unittest.main()
