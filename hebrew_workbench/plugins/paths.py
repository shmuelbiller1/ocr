"""Where the plugins and the settings of the user live.

The program never writes into its own folder.  Everything that the
user adds goes into the data directory of the user, which on Windows is
``%LOCALAPPDATA%\\HebrewNotesWorkbench``.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "application_directory",
    "plugins_directory",
    "settings_file",
    "models_directory",
    "APPLICATION_NAME",
]


def _application_name() -> str:
    """The name of the folder of the program in the data directory.

    The name is the same on every system, so that a folder that was
    moved from one machine to another still works.
    """
    return "HebrewNotesWorkbench" if os.name == "nt" else "hebrew-notes-workbench"


APPLICATION_NAME = "HebrewNotesWorkbench"


def application_directory() -> Path:
    """The directory where the program keeps the data of the user."""
    override = os.environ.get("HEBREW_WORKBENCH_HOME")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / _application_name()
        return Path.home() / "AppData" / "Local" / _application_name()
    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base) / _application_name()
    return Path.home() / ".local" / "share" / _application_name()


def plugins_directory(root: Path | None = None) -> Path:
    """The folder where the installed plugins are kept."""
    base = Path(root) if root is not None else application_directory()
    return base / "plugins"


def settings_file(root: Path | None = None) -> Path:
    """The file where the choices of the user are kept.

    The root is the data directory of the program, so that the file is
    next to the folder of the plugins.
    """
    base = Path(root) if root is not None else application_directory()
    return base / "plugins" / "settings.json"


def models_directory(root: Path | None = None) -> Path:
    """The folder where the models of the engines are kept."""
    from ..engine.models import models_directory as engine_models_directory

    if root is None:
        return engine_models_directory()
    return Path(root) / "models"
