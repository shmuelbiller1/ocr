"""Locating the files that ship with the application.

The workbench is packaged as a single executable.  PyInstaller unpacks
such a build into a temporary folder, so the location of the bundled data
depends on how the application was started.  Everything that needs the
sample pages asks this module instead of guessing.
"""

from __future__ import annotations

import sys
from pathlib import Path

__all__ = ["bundle_root", "samples_directory"]


def bundle_root() -> Path:
    """The folder that holds the files bundled with the application."""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle)
    return Path(__file__).resolve().parent


def samples_directory() -> Path | None:
    """Return the folder with the sample pages, or ``None``."""
    candidates = [
        bundle_root() / "samples",
        Path(sys.executable).resolve().parent / "samples",
        Path(__file__).resolve().parents[1] / "samples",
        Path.cwd() / "samples",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None
