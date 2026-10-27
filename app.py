"""Launcher for the Hebrew Notes Workbench.

Usage::

    python app.py                 # start the desktop application
    python app.py --selftest      # run the built-in checks and exit
    python app.py --version       # print the version

``--selftest`` is what the Windows build job runs against the packaged
executable, so that "the .exe was produced" and "the .exe starts" are two
separate, verified facts.
"""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="app.py",
        description="Offline Hebrew-script transcription workbench.",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="run the built-in checks (used by the packaging job) and exit",
    )
    parser.add_argument(
        "--selftest-report",
        metavar="PATH",
        help="write the self-test results as JSON to PATH",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="print the version and exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.version:
        from hebrew_workbench import __version__

        print(__version__)
        return 0

    if args.selftest:
        from hebrew_workbench.selftest import main as selftest_main

        return selftest_main(args.selftest_report)

    from hebrew_workbench.ui.main_window import run

    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
