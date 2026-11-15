"""Paths that come from outside the program.

Every path that reaches the program from the outside - an argument of the
command line, the name of a file inside an archive, the job that the
recognition worker is handed - is resolved before it is used, and it is
used only when it stays inside one of the folders that the program is
allowed to touch.  A path that leaves those folders is refused: the
refusal is an error that is seen, and not a silent correction, because a
silent correction would hide the fact that the program was asked for
something else.

The question is asked in this one place so that the tools, the worker and
the recognition engine all ask it in the same way and get the same
answer.  Resolving the path first is what makes the answer true: it
removes the ``..`` of a crafted path and the links that point out of the
folder, so the comparison below is made on the place that is really
opened or written and not on the string that was typed.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class PathRefused(ValueError):
    """A path was outside every folder that the program may use."""


def repository_base() -> str:
    """The folder of the repository, with links resolved."""
    return os.path.realpath(str(REPO_ROOT))


def working_base() -> str:
    """The folder the program was started in, with links resolved."""
    return os.path.realpath(os.getcwd())


def temporary_base() -> str:
    """The folder of the temporary files, with links resolved."""
    return os.path.realpath(tempfile.gettempdir())


def default_bases() -> list[str]:
    """The folders a command line tool is allowed to read and write."""
    return [repository_base(), working_base(), temporary_base()]


def confine_path(raw: str | Path, *bases: str | Path) -> Path:
    """Resolve ``raw`` and return it only when it stays inside ``bases``.

    The comparison is made on the resolved path and on a prefix that ends
    with the separator, so a brother folder whose name begins with the
    same letters (``/work`` next to ``/workspace``) is not let in.
    """
    real = os.path.realpath(str(raw))
    for base in bases:
        prefix = os.path.realpath(str(base))
        if not prefix.endswith(os.sep):
            prefix = prefix + os.sep
        if real.startswith(prefix):
            return Path(real)
    allowed = ", ".join(str(base) for base in bases) or "no folder"
    raise PathRefused(
        f"the path {raw} is outside the folders that may be used ({allowed})"
    )
