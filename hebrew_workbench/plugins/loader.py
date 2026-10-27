"""Loading the code of a plugin.

The manifest says where the code is: ``package.module:Name``.  The
loader imports it and hands back the object.  The object of an OCR
plugin has to implement the contract of :mod:`hebrew_workbench.engine`,
and the object of a module of proposals has to implement the contract
of :mod:`hebrew_workbench.suggestions`.

A plugin that cannot be loaded is reported with the reason, and the
program carries on without it.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from .base import PluginError, PluginManifest

__all__ = ["load_object", "load_plugin", "forget_modules"]


def _belongs_to(paths: list[Path], file_name: str | None) -> bool:
    """Is this file inside one of these folders?"""
    if not file_name:
        return False
    try:
        path = str(Path(file_name).resolve())
    except OSError:
        return False
    for folder in paths:
        try:
            root = str(Path(folder).resolve())
        except OSError:
            continue
        if path.startswith(root):
            return True
    return False


def _import(module_name: str, search_paths: list[Path]):
    for path in search_paths:
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)
    # A module of the same name may already be in the cache of Python:
    # from another plugin, or from an earlier version of this one.  The
    # code of a plugin has to come from its own folder, so the cached
    # module is dropped when it comes from somewhere else.
    existing = sys.modules.get(module_name)
    if existing is not None and not _belongs_to(search_paths, getattr(existing, "__file__", None)):
        del sys.modules[module_name]
    try:
        return importlib.import_module(module_name)
    except Exception as exc:  # the plugin may raise anything
        raise PluginError(f"the module {module_name} could not be imported: {exc}") from exc


def _build(attribute, manifest: PluginManifest):
    """Turn the entry point into an object."""
    if isinstance(attribute, type):
        try:
            return attribute(options=dict(manifest.options))
        except TypeError:
            return attribute()
    if callable(attribute):
        try:
            return attribute(options=dict(manifest.options))
        except TypeError:
            try:
                return attribute(dict(manifest.options))
            except TypeError:
                return attribute()
    return attribute


def forget_modules(folders: list[Path]) -> list[str]:
    """Drop the modules of these folders from the import cache.

    When the user removes a plugin and installs another one with the
    same name, Python would hand back the old code from its cache.  The
    modules of the folder are therefore forgotten, and the next load
    reads the code that is on the disk now.
    """
    roots = []
    for folder in folders:
        try:
            roots.append(str(Path(folder).resolve()))
        except OSError:
            continue
    forgotten: list[str] = []
    for name in list(sys.modules):
        module = sys.modules.get(name)
        file_name = getattr(module, "__file__", None)
        if not file_name:
            continue
        try:
            path = str(Path(file_name).resolve())
        except OSError:
            continue
        if any(path.startswith(root) for root in roots):
            del sys.modules[name]
            forgotten.append(name)
    return forgotten


def load_object(
    manifest: PluginManifest, search_paths: list[Path] | None = None
):
    """Load the object of a plugin.

    Raises:
        PluginError: when the plugin cannot be loaded.
    """
    module_name, _, attribute_name = manifest.entry.partition(":")
    module = _import(module_name, list(search_paths or []))
    try:
        attribute = getattr(module, attribute_name)
    except AttributeError as exc:
        raise PluginError(
            f"{manifest.entry} does not exist in {module_name}"
        ) from exc
    try:
        return _build(attribute, manifest)
    except Exception as exc:
        raise PluginError(f"{manifest.id} could not be started: {exc}") from exc


def load_plugin(
    manifest: PluginManifest, search_paths: list[Path] | None = None
):
    """Load a plugin and give back the object, or the reason it failed."""
    from .base import Plugin

    try:
        return Plugin(manifest=manifest, object=load_object(manifest, search_paths))
    except PluginError as exc:
        return Plugin(manifest=manifest, object=None, error=str(exc))
    except Exception as exc:
        return Plugin(
            manifest=manifest, object=None, error=f"the plugin failed: {exc}"
        )
