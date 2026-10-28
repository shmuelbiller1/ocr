"""The registry of the plugins: what is there, and which one is active.

The registry gathers the plugins that come with the program and the
plugins that the user installed, reads the settings of the user, and
answers two questions: which plugins are there, and which one of them
is the active one for every kind.

The program works with no plugins at all: the registry then holds
nothing but the built-in plugins, and the parts of the program that
need a plugin say so.
"""

from __future__ import annotations

from pathlib import Path

from .base import (
    KIND_GRAMMAR,
    KIND_OCR,
    KIND_SPELLING,
    KIND_STYLE,
    KINDS,
    Plugin,
    PluginManifest,
)
from .builtin import BUILTIN_MANIFESTS
from .installer import PluginInstaller, read_manifest
from .loader import forget_modules, load_plugin
from .paths import plugins_directory
from .settings import PluginSettings

__all__ = ["PluginRegistry"]


class PluginRegistry:
    """Every plugin of the program, and the choice of the user."""

    def __init__(
        self,
        root: Path | None = None,
        settings_path: Path | None = None,
        load: bool = True,
    ) -> None:
        self.root = Path(root) if root is not None else plugins_directory()
        # The settings live next to the plugins, inside the folder of
        # the user.
        self.settings_path = (
            Path(settings_path)
            if settings_path is not None
            else self.root / "settings.json"
        )
        self.settings = PluginSettings.load(self.settings_path)
        self.plugins: list[Plugin] = []
        self.errors: list[str] = []
        # The folders of the plugins the user installed, so that their
        # code can be forgotten when the user replaces them.
        self._folders: dict[str, Path] = {}
        if load:
            self.load()

    # -- loading -----------------------------------------------------------
    def load(self) -> None:
        """Read every manifest and load the code of the plugins.

        The code of the plugins that the user installed is forgotten
        first, so that a plugin that was replaced is read again from
        the disk instead of from the cache of Python.
        """
        if self._folders:
            forget_modules(list(self._folders.values()))
        self._folders = {}
        self.plugins = []
        self.errors = []
        seen: set[str] = set()
        for manifest in BUILTIN_MANIFESTS:
            if manifest.id in seen:
                continue
            seen.add(manifest.id)
            self.plugins.append(self._load_one(manifest, []))
        installer = PluginInstaller(self.root)
        for folder in installer.installed_folders():
            try:
                manifest = read_manifest(folder)
            except Exception as exc:
                self.errors.append(f"{folder.name}: {exc}")
                continue
            if manifest.id in seen:
                self.errors.append(
                    f"the plugin {manifest.id} is already there and was not loaded twice"
                )
                continue
            seen.add(manifest.id)
            self._folders[manifest.id] = folder
            self.plugins.append(self._load_one(manifest, [folder]))

    def _load_one(self, manifest: PluginManifest, search_paths: list[Path]) -> Plugin:
        options = self._options_of(manifest)
        plugin = load_plugin(manifest, search_paths, options)
        if plugin.error:
            self.errors.append(f"{manifest.id}: {plugin.error}")
            return plugin
        self._apply_options(plugin, options)
        return plugin

    def _options_of(self, manifest: PluginManifest) -> dict:
        """The settings of a plugin: the manifest, and the choices on top.

        The choices of the user are put on top of the options of the
        manifest, and the result is given both to the constructor of the
        plugin and to its ``configure`` method.
        """
        options = dict(manifest.options or {})
        options.update(self.settings.options.get(manifest.id, {}))
        return options

    def _apply_options(self, plugin: Plugin, options: dict | None = None) -> None:
        """Give the plugin the settings of the manifest and the choices.

        The options of the manifest are the defaults of the plugin, and
        the choices of the user are put on top of them.  A plugin that
        has a ``configure`` method gets them, even when the user has
        not changed anything.
        """
        if options is None:
            options = self._options_of(plugin.manifest)
        if not options:
            return
        configure = getattr(plugin.object, "configure", None)
        if callable(configure):
            try:
                configure(dict(options))
            except Exception as exc:
                plugin.error = f"the settings of the plugin could not be used: {exc}"

    # -- what is there -----------------------------------------------------
    def get(self, plugin_id: str) -> Plugin | None:
        for plugin in self.plugins:
            if plugin.id == plugin_id:
                return plugin
        return None

    def by_kind(self, kind: str) -> list[Plugin]:
        """The plugins of one kind, e.g. the OCR engines."""
        return [plugin for plugin in self.plugins if plugin.kind == kind]

    def kinds(self) -> list[str]:
        return list(KINDS)

    def is_enabled(self, plugin_id: str) -> bool:
        """Is the plugin switched on?

        The choice of the user wins.  When the user did not say anything
        about this plugin, the manifest says whether it starts on.
        """
        plugin = self.get(plugin_id)
        if plugin is None:
            return False
        if plugin.error:
            return False
        if self.settings.is_enabled(plugin_id):
            return True
        if self.settings.is_disabled(plugin_id):
            return False
        return bool(plugin.manifest.enabled_by_default)

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        self.settings.set_enabled(plugin_id, enabled)
        self.save()

    # -- the active plugin of every kind ------------------------------------
    def active(self, kind: str) -> Plugin | None:
        """The plugin the user chose for this kind.

        When the user chose "no plugin" on purpose, nothing is
        returned, even when other plugins of this kind are switched
        on.
        """
        wanted = self.settings.active.get(kind)
        candidates = self.by_kind(kind)
        if wanted is not None:
            if not wanted:
                # The user chose that this kind has no plugin.
                return None
            for plugin in candidates:
                if plugin.id == wanted and self._can_be_used(plugin):
                    return plugin
        for plugin in candidates:
            if self._can_be_used(plugin):
                return plugin
        return None

    def without_plugin(self, kind: str) -> bool:
        """Did the user choose that this kind has no plugin at all?

        This is different from a choice that was not made yet: the
        program then works without a plugin of this kind on purpose.
        """
        wanted = self.settings.active.get(kind)
        return wanted is not None and not wanted

    def chosen(self, kind: str) -> Plugin | None:
        """The plugin the user chose for this kind.

        This is the plugin even when it cannot run right now - the
        model of the recognition is not installed yet, for example -
        because the user has to know which one he is preparing.
        """
        wanted = self.settings.active.get(kind)
        if wanted:
            for plugin in self.by_kind(kind):
                if plugin.id == wanted:
                    return plugin
        return None

    def _can_be_used(self, plugin: Plugin) -> bool:
        """Is the plugin switched on, and does it have something to give?

        A plugin whose code could not be built - the worker of the
        recognition when the model is not installed, for example - is
        not offered, so that the user is not shown an engine that
        cannot run.  A module of proposals that waits for a word list
        is still the module the user chose, so it is not put aside.
        """
        if plugin.object is None:
            return False
        if not self.is_enabled(plugin.id):
            return False
        if plugin.kind == KIND_OCR:
            return bool(plugin.available())
        return True

    def set_active(self, kind: str, plugin_id: str) -> None:
        """Choose the plugin of a kind.  An empty name means no plugin.

        The choice is kept as it is, so that the program knows that the
        user does not want a plugin of this kind, and not only that the
        user did not choose one yet.
        """
        self.settings.active[kind] = plugin_id or ""
        self.save()

    def kind_enabled(self, kind: str) -> bool:
        """Is the active plugin of this kind switched on?"""
        plugin = self.active(kind)
        if plugin is None:
            return False
        return self.is_enabled(plugin.id)

    def active_object(self, kind: str):
        """The object of the active plugin of a kind, or nothing."""
        plugin = self.active(kind)
        if plugin is None:
            return None
        return plugin.object

    # -- the OCR engine ----------------------------------------------------
    def ocr_engines(self) -> list[Plugin]:
        """The OCR plugins that can run right now."""
        engines = []
        for plugin in self.by_kind(KIND_OCR):
            if not self.is_enabled(plugin.id):
                continue
            if not plugin.available():
                continue
            engines.append(plugin)
        return engines

    def active_engine(self):
        """The engine the user chose, or nothing."""
        plugin = self.active(KIND_OCR)
        if plugin is None:
            return None
        return plugin.object

    # -- the modules of proposals ------------------------------------------
    def suggestion_modules(self) -> list:
        """The modules of proposals the user chose.

        A module that does not follow the contract of the program is
        left out, and not given to the program: a broken plugin may
        never stop the program from starting.
        """
        modules = []
        for kind in (KIND_SPELLING, KIND_GRAMMAR, KIND_STYLE):
            plugin = self.active(kind)
            if plugin is None:
                continue
            module = plugin.object
            if module is None:
                # A plugin that could not be built has no module.
                continue
            if not callable(getattr(module, "check", None)):
                self.errors.append(
                    f"{plugin.id}: the object is not a module of proposals"
                )
                continue
            # The attributes of the contract come from the manifest
            # when the plugin does not have them of its own.
            if not getattr(module, "kind", None):
                module.kind = kind
            if not getattr(module, "id", None):
                module.id = plugin.id
            if not hasattr(module, "enabled_by_default"):
                module.enabled_by_default = bool(
                    plugin.manifest.enabled_by_default
                )
            modules.append(module)
        return modules

    # -- keeping the settings ----------------------------------------------
    def save(self) -> None:
        """Write the choices of the user."""
        self.settings.save(self.settings_path)

    def set_option(self, plugin_id: str, key: str, value) -> None:
        self.settings.set_option(plugin_id, key, value)
        self.save()
        plugin = self.get(plugin_id)
        if plugin is not None:
            self._apply_options(plugin, self._options_of(plugin.manifest))

    # -- for the user -------------------------------------------------------
    def status(self) -> list[str]:
        """One line per plugin, for the user."""
        lines = []
        for plugin in self.plugins:
            state = "פעיל" if self.is_enabled(plugin.id) else "מושבת"
            if plugin.error:
                state = f"שגוי ({plugin.error})"
            elif not plugin.available() and plugin.kind == KIND_OCR:
                state = f"{state} (המודל אינו מותקן)"
            source = "נקבץ עם התוכנית" if plugin.builtin else "מותקן"
            lines.append(
                f"{plugin.name} [{plugin.kind}] {plugin.version} - {state} ({source})"
            )
        for error in self.errors:
            lines.append(f"שגיאה: {error}")
        return lines
