"""The settings of a child process.

A benchmark measures an engine in a child process, so that the memory of
one engine is measured without the memory of the others.  The child is
this same program, and it could be given its work on the command line -
but a command line is a place where a value is not only passed, it is
also read by everything that looks at the process, and it is easy to
build one by putting strings together.

So the child is given a **file**: the parent writes what it wants into a
folder it made itself, and the command line holds nothing but the name of
the program and the name of that file.  What comes back out of the file
is read like any other input - a path from it is confined before it is
used - and no value that a user typed is ever put into a command line.
"""

from __future__ import annotations

import json
from pathlib import Path

from hebrew_workbench.safe_paths import confine_path, default_bases

#: The name of the file of settings inside the folder of the child.
SETTINGS_NAME = "child-settings.json"


def write_child_settings(folder: str | Path, settings: dict) -> Path:
    """Write the *settings* of a child into *folder* and return the file.

    The folder is the one the parent made for this child, so the file is
    written where nothing else is - and it is confined here as well, so
    that a caller that forgot to ask cannot write one outside of it.
    """
    target = confine_path(Path(folder) / SETTINGS_NAME, *default_bases())
    target.write_text(  # NOSONAR (S8707): target was confined above
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return target


def read_child_settings(path: str | Path) -> dict:
    """The settings a child was given, as they were written.

    A file that is not there, that is not readable, or that does not hold
    an object gives nothing: the child then runs with what it was told on
    its own command line, which is the answer a user expects.
    """
    try:
        target = confine_path(path, *default_bases())
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def apply_child_settings(args, path: str | Path | None) -> None:
    """Put the settings of the file at *path* into the parsed *args*.

    Only the names the parser already knows are taken, so a file cannot
    add an argument that the program does not have.
    """
    if not path:
        return
    known = vars(args)
    for name, value in read_child_settings(path).items():
        if name in known:
            known[name] = value
