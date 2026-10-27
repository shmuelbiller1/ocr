"""The plugins of the program.

A plugin is a part of the program that the user can add, take away, or
leave out:

* an OCR engine - the recognition of a Hebrew handwriting;
* a module of proposals - the spelling, the grammar, or the scholarly
  style.

The program does not know the plugins in advance.  It reads the
manifests of the plugins, loads the entry points, and lets the user
choose in the settings screen which one of them is the active one.  A
better Hebrew engine can therefore be added later without changing the
code of the program.
"""

from __future__ import annotations

from .base import (
    KIND_GRAMMAR,
    KIND_OCR,
    KIND_SPELLING,
    KIND_STYLE,
    KIND_NAMES,
    KINDS,
    Plugin,
    PluginError,
    PluginManifest,
)
from .builtin import BUILTIN_MANIFESTS, builtin_manifests
from .installer import PluginInstaller, read_manifest
from .loader import load_object, load_plugin
from .manifest import MANIFEST_NAME
from .paths import application_directory, plugins_directory, settings_file
from .registry import PluginRegistry
from .settings import PluginSettings

__all__ = [
    "BUILTIN_MANIFESTS",
    "KINDS",
    "KIND_GRAMMAR",
    "KIND_NAMES",
    "KIND_OCR",
    "KIND_SPELLING",
    "KIND_STYLE",
    "MANIFEST_NAME",
    "Plugin",
    "PluginError",
    "PluginInstaller",
    "PluginManifest",
    "PluginRegistry",
    "PluginSettings",
    "application_directory",
    "builtin_manifests",
    "load_object",
    "load_plugin",
    "plugins_directory",
    "read_manifest",
    "settings_file",
]
