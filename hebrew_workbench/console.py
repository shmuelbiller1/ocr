"""Let the program write Hebrew text in the console of every system.

The console of Windows writes in a code page of the system, and Hebrew
is not in it.  A program that writes Hebrew there stops with an
error, and the build that measures the recognition would fail on a
letter and not on anything that is wrong with the measurement.

The streams are asked to write in UTF-8, and to leave out a character
that cannot be written, so that the writing of a report is never the
reason that the build stops.
"""

from __future__ import annotations

import sys

__all__ = ["use_utf8"]


def use_utf8() -> None:
    """Ask the console to write in UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            # The stream was replaced by something that cannot be
            # changed (a file of the test, for example).
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            # The stream does not allow it, and the program carries on
            # with the console as it is.
            pass
