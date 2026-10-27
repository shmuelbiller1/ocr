"""Print the measured accuracy of the engine as a note of the build.

The build page of a pull request should say how well the engine read
the corpus, so that the number is not only in a file.

    python tools/accuracy_notice.py --report ocr-accuracy.json
"""

from __future__ import annotations

import argparse
import json
import pathlib


def summarise(report: dict) -> str:
    """One sentence about the measurement of a report."""
    summary = report.get("summary", {})
    return (
        f"the engine recognised {report.get('pages', 0)} pages, "
        f"character error rate {summary.get('cer', 0) * 100:.1f}%, "
        f"word error rate {summary.get('wer', 0) * 100:.1f}%"
    )


def main(argv: list[str] | None = None) -> int:
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
