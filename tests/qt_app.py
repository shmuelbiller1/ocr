"""The Qt application that the tests share.

Only one Qt application can exist in a process, so every test that
needs one asks for it here.
"""

from __future__ import annotations

import os
import sys

if sys.platform.startswith("linux"):
    # The machine that runs the tests has no screen.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402


def application() -> QApplication:
    """The Qt application of this process, made if it does not exist yet."""
    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication([])
