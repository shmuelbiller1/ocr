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
from .loader import load_plugin
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
        if load:
            self.load()

    # -- loading -----------------------------------------------------------
    def load(self) -> None:
        """Read every manifest and load the code of the plugins."""
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
            self.plugins.append(self._load_one(manifest, [folder]))

    def _load_one(self, manifest: PluginManifest, search_paths: list[Path]) -> Plugin:
        plugin = load_plugin(manifest, search_paths)
        if plugin.error:
            self.errors.append(f"{manifest.id}: {plugin.error}")
            return plugin
        self._apply_options(plugin)
        return plugin

    def _apply_options(self, plugin: Plugin) -> None:
        """Give the plugin the settings the user chose for it."""
        options = self.settings.options.get(plugin.id)
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
        """The plugin the user chose for this kind."""
        wanted = self.settings.active.get(kind)
        candidates = self.by_kind(kind)
        if wanted:
            for plugin in candidates:
                if plugin.id == wanted and self.is_enabled(plugin.id):
                    return plugin
        for plugin in candidates:
            if self.is_enabled(plugin.id):
                return plugin
        return None

    def set_active(self, kind: str, plugin_id: str) -> None:
        """Choose the plugin of a kind."""
        if plugin_id:
            self.settings.active[kind] = plugin_id
        else:
            self.settings.active.pop(kind, None)
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
        """The modules of proposals the user chose."""
        modules = []
        for kind in (KIND_SPELLING, KIND_GRAMMAR, KIND_STYLE):
            plugin = self.active(kind)
            if plugin is None:
                continue
            modules.append(plugin.object)
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
            self._apply_options(plugin)

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
