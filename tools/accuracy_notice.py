"""Print the measured accuracy of the engine as a note of the build.

The build page of a pull request should say how well the engine read
the corpus, so that the number is not only in a file.

    python tools/accuracy_notice.py --report ocr-accuracy.json

A report of a corpus that has no verified page says that the accuracy
is not verified, and does not publish a rate.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from hebrew_workbench.console import use_utf8  # noqa: E402


def summarise(report: dict) -> str:
    """One sentence about the measurement of a report."""
    corpus = report.get("corpus") or {}
    engines = report.get("engines") or []
    if not engines:
        return (
            f"the accuracy of the recognition on {corpus.get('name', 'the corpus')}"
            " is NOT verified: the corpus has no page with a verified transcript"
        )
    sentences = []
    for engine in engines:
        name = engine.get("model") or engine.get("engine")
        summary = engine.get("summary") or {}
        failures = engine.get("failures") or []
        if summary.get("cer") is None:
            if failures:
                # The engine failed: it is not the same thing as a
                # corpus without a verified transcript.
                sentences.append(
                    f"{name}: the engine failed on {len(failures)} pages"
                    + (f" ({failures[0].get('page', '?')})" if failures else "")
                )
            else:
                sentences.append(f"{name}: no verified page")
            continue
        if not engine.get("pages"):
            sentences.append(f"{name}: nothing to measure")
            continue
        sentences.append(
            f"{name}: "
            f"{engine.get('pages')} pages, "
            f"character error rate {summary.get('cer', 0) * 100:.1f}%, "
            f"word error rate {summary.get('wer', 0) * 100:.1f}%, "
            f"{summary.get('seconds_per_page', '?')} seconds per page"
            + (
                f", the engine failed on {len(failures)} pages"
                if failures
                else ""
            )
        )
    return "; ".join(sentences)


def main(argv: list[str] | None = None) -> int:
    # The console of Windows cannot write Hebrew in the code page of
    # the system, and the program would stop in the middle of a report
    # because of a letter.
    use_utf8()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="ocr-accuracy.json", help="report file")
    args = parser.parse_args(argv)

    path = pathlib.Path(args.report)
    if not path.is_file():
        print(f"there is no report at {path} yet")
        return 0

    report = json.loads(path.read_text(encoding="utf-8"))
    print(f"::notice title=Accuracy::{summarise(report)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
