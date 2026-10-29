"""Offline Hebrew-script transcription workbench.

The package is deliberately split into small pieces so that every
replaceable component (OCR engines, spelling, grammar and scholarly-style
processing) can be swapped without touching the user interface.

Design rules that the whole code base follows:

* The original scan is never modified.  Documents are opened read-only.
* An engine that cannot run must fail closed.  The application never
  shows invented text where a real transcription is expected.
* Nothing is uploaded, and nothing is downloaded behind the user's back.
* Suggested corrections are proposals, never automatic rewrites.
"""

from __future__ import annotations

__all__ = ["APP_NAME", "APP_ID", "__version__"]

APP_NAME = "Hebrew Notes Workbench"
APP_ID = "hebrew-workbench"

__version__ = "0.4.0"
