"""Write the measured accuracy into the documentation.

    python tools/write_accuracy_results.py --report ocr-accuracy.json

The report of the benchmark is the only source of the numbers.  This
script puts them between the two markers of `docs/OCR_ACCURACY.md`, so
that the page always shows what was measured and not what somebody
remembered.

The script writes nothing when the report is missing, and it leaves the
file untouched when the numbers are already there.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BEGIN = "<!-- RESULTS:BEGIN -->"
END = "<!-- RESULTS:END -->"

REPO_ROOT = Path(__file__).resolve().parents[1]


def percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def build_section(report: dict) -> str:
    """The markdown of the results, taken from the report."""
    summary = report.get("summary") or {}
    corpus = report.get("corpus") or {}
    pages = report.get("results") or []

    lines = [
        BEGIN,
        "",
        f"Measured with {report.get('engine', 'the engine')} on"
        f" {report.get('pages', len(pages))} pages of"
        f" {corpus.get('name', 'the corpus')}:",
        "",
        "| | |",
        "| --- | --- |",
        f"| Character error rate | **{percent(summary.get('cer', 0.0))}** |",
        f"| Word error rate | **{percent(summary.get('wer', 0.0))}** |",
        f"| Seconds per page | {summary.get('seconds_per_page', '?')} |",
        f"| Pages | {report.get('pages', len(pages))} |",
        "",
    ]

    # The ground truth of a page has to be complete, or the page is not
    # a measurement of the recognition: the text that was not
    # transcribed would be counted as a mistake of the engine.
    incomplete = summary.get("pages_with_incomplete_ground_truth") or []
    if incomplete:
        lines += [
            "> **The ground truth of these pages is not complete, and they are"
            " not part of the rates above:** "
            + ", ".join(incomplete)
            + ".  Their numbers are in the table below, and they are not a"
            " measurement of the recognition.",
            "",
        ]

    if pages:
        lines += [
            "| Page | Characters in the ground truth | Character error rate | Word error rate | Seconds | Ground truth |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for page in pages:
            complete = (page.get("ground_truth") or {}).get("complete", True)
            lines.append(
                "| {page} | {chars} | {cer} | {wer} | {seconds} | {ground} |".format(
                    page=page.get("page", "?"),
                    chars=page.get("characters_reference", "?"),
                    cer=percent(page.get("cer", 0.0)),
                    wer=percent(page.get("wer", 0.0)),
                    seconds=page.get("seconds", "?"),
                    ground="complete" if complete else "**not complete**",
                )
            )
        lines.append("")

    lines += [
        "The numbers were produced by `tools/benchmark_ocr.py` in the"
        " `ocr-engine` job of the build, and the report they come from is"
        " uploaded as the artefact `ocr-accuracy-report`.",
        "",
        END,
    ]
    return "\n".join(lines)


def update_document(document: Path, section: str) -> bool:
    """Put the section between the markers.  Returns True when the file changed."""
    if not document.is_file():
        return False
    text = document.read_text(encoding="utf-8")
    if BEGIN in text and END in text:
        start = text.index(BEGIN)
        finish = text.index(END) + len(END)
        new_text = text[:start] + section + text[finish:]
    elif "<!-- RESULTS -->" in text:
        new_text = text.replace("<!-- RESULTS -->", section, 1)
    else:
        return False
    if new_text == text:
        return False
    document.write_text(new_text, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="ocr-accuracy.json")
    parser.add_argument(
        "--document", default=str(REPO_ROOT / "docs" / "OCR_ACCURACY.md")
    )
    args = parser.parse_args(argv)

    report_path = Path(args.report)
    if not report_path.is_file():
        print(f"no report: {report_path}", file=sys.stderr)
        return 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    document = Path(args.document)
    if update_document(document, build_section(report)):
        print(f"the results were written into {document}")
    else:
        print("the results are already in the document")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
