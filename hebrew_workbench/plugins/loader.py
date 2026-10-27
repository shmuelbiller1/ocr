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

__all__ = ["load_object", "load_plugin"]


def _import(module_name: str, search_paths: list[Path]):
    for path in search_paths:
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)
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
