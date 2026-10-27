"""The Qt application that the tests share.

Only one Qt application can exist in a process, so every test that
needs one asks for it here.
"""

from __future__ import annotations

import os
import sys
import tempfile

if sys.platform.startswith("linux"):
    # The machine that runs the tests has no screen.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# The tests must not read or write the data of the user, so the
# plugins and their settings go into a temporary folder.
os.environ.setdefault(
    "HEBREW_WORKBENCH_HOME", tempfile.mkdtemp(prefix="hebrew-workbench-tests-")
)

from PySide6.QtWidgets import QApplication  # noqa: E402


def application() -> QApplication:
    """The Qt application of this process, made if it does not exist yet."""
    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication([])


def temporary_home() -> tempfile.TemporaryDirectory:
    """A data folder of its own for one test.

    The tests must not read or write the data of the user, and one test
    must not change what another test finds.  Every test that opens the
    window therefore gets a folder of its own, and the folder is thrown
    away at the end of the test.
    """
    folder = tempfile.TemporaryDirectory(prefix="hebrew-workbench-home-")
    os.environ["HEBREW_WORKBENCH_HOME"] = folder.name
    return folder
