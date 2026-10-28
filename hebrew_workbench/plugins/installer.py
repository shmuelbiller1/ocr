"""Adding a plugin to the program, and taking it away again.

A plugin is a folder with a ``plugin.json`` in it.  It can be given to
the program as a folder or as a ZIP file.  The installer checks the
manifest before anything is copied, and it never writes outside of the
plugins folder of the user.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from .base import PluginError, PluginManifest
from .builtin import BUILTIN_MANIFESTS
from .manifest import MANIFEST_NAME
from .paths import plugins_directory

#: The identifiers that the program keeps for itself.  A plugin with
#: one of them would take the place of the settings of the plugins.
RESERVED_IDS = frozenset({"settings.json", "settings"})

__all__ = ["PluginInstaller", "read_manifest"]


def read_manifest(folder: Path) -> PluginManifest:
    """Read the manifest of a plugin folder."""
    path = Path(folder) / MANIFEST_NAME
    if not path.is_file():
        raise PluginError(f"the folder has no {MANIFEST_NAME} in it")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise PluginError(f"the {MANIFEST_NAME} is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise PluginError(f"the {MANIFEST_NAME} could not be read: {exc}") from exc
    return PluginManifest.from_dict(data)


class PluginInstaller:
    """Installs and removes the plugins of the user."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else plugins_directory()

    # -- the folder of a plugin --------------------------------------------
    def plugin_folder(self, plugin_id: str) -> Path:
        """Where the plugin of this identifier lives.

        The folder has to be inside the folder of the plugins: an
        identifier such as ``..`` must never lead outside of it.
        """
        folder = self.root / plugin_id
        try:
            root = self.root.resolve()
            resolved = folder.resolve()
        except OSError:
            resolved = folder
            root = self.root
        if resolved == root or root not in resolved.parents:
            raise PluginError(
                f"the identifier {plugin_id!r} leads outside of the folder "
                "of the plugins"
            )
        return folder

    def installed_folders(self) -> list[Path]:
        """Every folder in the plugins directory that holds a manifest."""
        if not self.root.is_dir():
            return []
        folders = []
        for child in sorted(self.root.iterdir()):
            if not child.is_dir():
                continue
            if (child / MANIFEST_NAME).is_file():
                folders.append(child)
        return folders

    def installed(self) -> list[PluginManifest]:
        """The manifests of the installed plugins."""
        manifests = []
        for folder in self.installed_folders():
            try:
                manifests.append(read_manifest(folder))
            except PluginError:
                continue
        return manifests

    # -- installing --------------------------------------------------------
    def install_folder(self, source: Path, overwrite: bool = False) -> PluginManifest:
        """Install a plugin from a folder.

        The folder is copied, so that the original files are not touched.
        """
        source = Path(source)
        if not source.is_dir():
            raise PluginError(f"{source} is not a folder")
        manifest = read_manifest(source)
        if manifest.id in {item.id for item in BUILTIN_MANIFESTS}:
            raise PluginError(
                f"the identifier {manifest.id!r} belongs to a plugin that "
                "comes with the program"
            )
        if manifest.id.lower() in RESERVED_IDS:
            raise PluginError(
                f"the identifier {manifest.id!r} is reserved by the program"
            )
        target = self.plugin_folder(manifest.id)
        if target.exists():
            if not overwrite:
                raise PluginError(
                    f"the plugin {manifest.id} is already installed; "
                    "remove it first or ask to replace it"
                )
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
        return manifest

    def install_zip(self, archive: Path, overwrite: bool = False) -> PluginManifest:
        """Install a plugin from a ZIP file."""
        archive = Path(archive)
        if not archive.is_file():
            raise PluginError(f"{archive} is not a file")
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            self._extract(archive, folder)
            source = self._find_root(folder)
            return self.install_folder(source, overwrite=overwrite)

    def _extract(self, archive: Path, target: Path) -> None:
        """Unpack a ZIP file, without letting it write outside the folder."""
        try:
            handle = zipfile.ZipFile(archive)
        except zipfile.BadZipFile as exc:
            raise PluginError(f"the file is not a ZIP file: {exc}") from exc
        with handle:
            root = target.resolve()
            for member in handle.infolist():
                name = member.filename
                if name.startswith("/") or ".." in Path(name).parts:
                    raise PluginError(
                        f"the archive holds a file outside of it: {name}"
                    )
                destination = (root / name).resolve()
                if not str(destination).startswith(str(root)):
                    raise PluginError(
                        f"the archive holds a file outside of it: {name}"
                    )
            handle.extractall(target)

    def _find_root(self, folder: Path) -> Path:
        """Find the folder that holds the manifest."""
        if (folder / MANIFEST_NAME).is_file():
            return folder
        for child in sorted(folder.iterdir()):
            if child.is_dir() and (child / MANIFEST_NAME).is_file():
                return child
        raise PluginError(f"the archive has no {MANIFEST_NAME} in it")

    # -- removing ----------------------------------------------------------
    def remove(self, plugin_id: str) -> bool:
        """Remove an installed plugin.  Built-in plugins stay."""
        target = self.plugin_folder(plugin_id)
        if not target.is_dir():
            return False
        try:
            shutil.rmtree(target)
        except OSError as exc:
            raise PluginError(
                f"the plugin {plugin_id} could not be removed: {exc}"
            ) from exc
        return True
