"""Loading the code of a plugin.

The manifest says where the code is: ``package.module:Name``.  The
loader imports it and hands back the object.  The object of an OCR
plugin has to implement the contract of :mod:`hebrew_workbench.engine`,
and the object of a module of proposals has to implement the contract
of :mod:`hebrew_workbench.suggestions`.

The code of a plugin is read from the folder of the plugin, under a name
of its own, so that two plugins cannot take each other's place, and so
that a file of a plugin cannot take the place of a module of the
program.  A plugin that cannot be loaded is reported with the reason,
and the program carries on without it.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import sys
import types
from pathlib import Path

from .base import PluginError, PluginManifest

__all__ = ["load_object", "load_plugin", "forget_modules"]

#: The name a plugin module is given, so that it does not share the
#: name space of the program with the other plugins.
PRIVATE_PREFIX = "_hebrew_workbench_plugin_"


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


def forget_modules(folders: list[Path]) -> list[str]:
    """Drop the modules of these folders from the import cache.

    When the user removes a plugin and installs another one with the
    same name, Python would hand back the old code from its cache.  The
    modules of the folder are therefore forgotten, and the next load
    reads the code that is on the disk now.
    """
    forgotten: list[str] = []
    for name in list(sys.modules):
        module = sys.modules.get(name)
        file_name = getattr(module, "__file__", None)
        if not file_name:
            continue
        if _belongs_to(folders, file_name):
            del sys.modules[name]
            forgotten.append(name)
    return forgotten


def _module_file(folder: Path, module_name: str) -> tuple[Path, bool] | None:
    """Where the module of the plugin is: a file, or a package."""
    parts = [part for part in module_name.split(".") if part]
    if not parts:
        return None
    base = folder.joinpath(*parts)
    file_path = base.with_name(base.name + ".py")
    if file_path.is_file():
        return file_path, False
    package = base / "__init__.py"
    if package.is_file():
        return package, True
    return None


def _private_name(plugin_id: str, folder: Path) -> str:
    """The name of the package that holds the code of the plugin.

    The name is built from a digest of the identifier of the plugin and
    of the folder it lives in: two plugins whose identifiers look alike
    - ``my-engine`` and ``my_engine`` - therefore never share a
    package, and never share the modules inside it.
    """
    try:
        place = str(Path(folder).resolve())
    except OSError:
        place = str(folder)
    digest = hashlib.sha256(f"{plugin_id}\0{place}".encode("utf-8")).hexdigest()[:20]
    return PRIVATE_PREFIX + digest


def _make_package(name: str, folder: Path) -> None:
    """Make a package of the plugin, so that relative imports work."""
    module = types.ModuleType(name)
    module.__path__ = [str(folder)]
    module.__package__ = name
    sys.modules[name] = module


def _run_package(name: str, file_path: Path) -> None:
    """Read the ``__init__.py`` of a package of the plugin.

    The code of the package has to run, because a plugin may put
    something in it that the rest of the plugin needs.
    """
    try:
        spec = importlib.util.spec_from_file_location(
            name, file_path, submodule_search_locations=[str(file_path.parent)]
        )
    except (ImportError, ValueError) as exc:
        raise PluginError(f"the package {name} could not be prepared: {exc}") from exc
    if spec is None or spec.loader is None:
        raise PluginError(f"the package {name} could not be prepared")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # the plugin may raise anything
        sys.modules.pop(name, None)
        raise PluginError(f"the package {name} could not be imported: {exc}") from exc


def _import_from_folder(module_name: str, folder: Path, plugin_id: str):
    """Read the module of the plugin from its own folder.

    The code of the plugin is given a package of its own, so that it
    does not take the place of another plugin, and so that a file of a
    plugin cannot take the place of a module of the program.  The
    packages of the plugin are made first, so that a relative import
    inside the plugin - ``from .helper import NAME`` - works.
    """
    parts = [part for part in module_name.split(".") if part]
    if not parts:
        raise PluginError(f"the module {module_name} has no name")

    root = _private_name(plugin_id, folder)
    _make_package(root, folder)
    current = root
    for number, part in enumerate(parts[:-1], start=1):
        current = f"{current}.{part}"
        place = folder.joinpath(*parts[:number])
        init = place / "__init__.py"
        if init.is_file():
            _run_package(current, init)
        else:
            _make_package(current, place)

    found = _module_file(folder, module_name)
    if found is None:
        raise PluginError(
            f"the module {module_name} is not in the folder of the plugin"
        )
    file_path, is_package = found
    name = f"{root}.{module_name}"
    try:
        spec = importlib.util.spec_from_file_location(
            name,
            file_path,
            submodule_search_locations=[str(file_path.parent)] if is_package else None,
        )
    except (ImportError, ValueError) as exc:
        raise PluginError(f"the module {module_name} could not be prepared: {exc}") from exc
    if spec is None or spec.loader is None:
        raise PluginError(f"the module {module_name} could not be prepared")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # the plugin may raise anything
        sys.modules.pop(name, None)
        raise PluginError(f"the module {module_name} could not be imported: {exc}") from exc
    return module


def _import(module_name: str, search_paths: list[Path], plugin_id: str = ""):
    """Import the module of the plugin."""
    if not search_paths:
        # A plugin that comes with the program: the usual import.
        try:
            return importlib.import_module(module_name)
        except Exception as exc:  # the plugin may raise anything
            raise PluginError(
                f"the module {module_name} could not be imported: {exc}"
            ) from exc

    # The folder of the plugin is added at the end of the path, so that
    # a file of a plugin cannot take the place of a module of the
    # program.
    for path in search_paths:
        text = str(path)
        if text not in sys.path:
            sys.path.append(text)
    return _import_from_folder(module_name, search_paths[0], plugin_id)


def _build(attribute, manifest: PluginManifest, options: dict | None = None):
    """Turn the entry point into an object.

    The options of the manifest, with the choices of the user on top of
    them, are given to the plugin that takes them, so that a plugin
    whose settings are in its constructor works as well as one that
    has a ``configure`` method.
    """
    settings = dict(options if options is not None else manifest.options)
    if isinstance(attribute, type):
        try:
            return attribute(options=settings)
        except TypeError:
            return attribute()
    if callable(attribute):
        try:
            return attribute(options=settings)
        except TypeError:
            try:
                return attribute(settings)
            except TypeError:
                return attribute()
    return attribute


def load_object(
    manifest: PluginManifest,
    search_paths: list[Path] | None = None,
    options: dict | None = None,
):
    """Load the object of a plugin.

    Raises:
        PluginError: when the plugin cannot be loaded.
    """
    module_name, _, attribute_name = manifest.entry.partition(":")
    module = _import(module_name, list(search_paths or []), manifest.id)
    try:
        attribute = getattr(module, attribute_name)
    except AttributeError as exc:
        raise PluginError(
            f"{manifest.entry} does not exist in {module_name}"
        ) from exc
    try:
        return _build(attribute, manifest, options)
    except Exception as exc:
        raise PluginError(f"{manifest.id} could not be started: {exc}") from exc


def load_plugin(
    manifest: PluginManifest,
    search_paths: list[Path] | None = None,
    options: dict | None = None,
):
    """Load a plugin and give back the object, or the reason it failed."""
    from .base import Plugin

    try:
        return Plugin(
            manifest=manifest,
            object=load_object(manifest, search_paths, options),
        )
    except PluginError as exc:
        return Plugin(manifest=manifest, object=None, error=str(exc))
    except Exception as exc:
        return Plugin(
            manifest=manifest, object=None, error=f"the plugin failed: {exc}"
        )
