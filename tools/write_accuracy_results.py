"""Write the measured accuracy into the documentation.

    python tools/write_accuracy_results.py --report ocr-accuracy.json

The report of the benchmark is the only source of the numbers.  This
script puts them between the two markers of `docs/OCR_ACCURACY.md`, so
that the page always shows what was measured and not what somebody
remembered.

The report may hold the measurements of several engines, and they are
written as one table, so that the engines can be compared with one
another.  A corpus in which no page has a verified transcript is
written as **not verified**, and no rate is published for it.

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
sys.path.insert(0, str(REPO_ROOT))

from hebrew_workbench.console import use_utf8  # noqa: E402


def percent(value) -> str:
    """A rate, or the words that say that there is no rate."""
    if value is None:
        return "not measured"
    return f"{value * 100:.1f}%"


def engine_rows(report: dict) -> list[dict]:
    """The measurements of the report, one for every engine."""
    engines = report.get("engines")
    if isinstance(engines, list) and engines:
        return [engine for engine in engines if isinstance(engine, dict)]
    # The older shape of the report: one engine at the top.
    if report.get("summary"):
        return [
            {
                "engine": report.get("engine", "the engine"),
                "model": report.get("model", ""),
                "pages": report.get("pages", 0),
                "pages_seen": report.get("pages_seen", 0),
                "summary": report.get("summary", {}),
                "results": report.get("results", []),
            }
        ]
    return []


def build_section(report: dict, begin: str = BEGIN, end: str = END) -> str:
    """The markdown of the results, taken from the report."""
    corpus = report.get("corpus") or {}
    engines = engine_rows(report)
    target = corpus.get("target", "modern")
    pages_seen = corpus.get("pages", 0)
    measured_corpus = corpus.get("pages_measured", 0)

    lines = [begin, ""]

    if not engines:
        # Nothing was measured: the corpus has no verified page, and
        # the accuracy of the recognition on it is not verified.
        lines += [
            f"**The accuracy of the recognition on"
            f" {corpus.get('name', 'this corpus')} is not verified.**",
            "",
            f"The corpus holds {pages_seen} pages, and none of them has a"
            " transcript that was checked by somebody who is not the one who"
            " wrote it down.  Without such a transcript there is nothing to"
            " measure, and no rate is published here.",
            "",
        ]
        if report.get("note"):
            lines += [f"> {report['note']}", ""]
        lines += [
            "The tools that build the corpus and that measure the engines on"
            " it are ready: see `docs/MODERN_SCHOOL_BENCHMARK.md`.",
            "",
            end,
        ]
        return "\n".join(lines)

    # The engine that is written first is the first engine that was
    # really measured: an engine that failed has no rate, and it is not
    # written as if it had one.
    first = next(
        (
            engine
            for engine in engines
            if engine.get("summary", {}).get("cer") is not None
        ),
        None,
    )
    if first is None:
        # The engines ran, but none of them read a page that may be
        # measured: there is no rate to publish.
        lines += [
            f"**The accuracy of the recognition on"
            f" {corpus.get('name', 'this corpus')} is not verified.**",
            "",
        ]
        if report.get("measured_corpus_pages"):
            lines += [
                f"The corpus holds {pages_seen} pages, and"
                f" {report['measured_corpus_pages']} of them may be measured, but"
                " the engines did not read one of them.  Without a result there"
                " is nothing to measure, and no rate is published here.",
                "",
            ]
        else:
            lines += [
                f"The corpus holds {pages_seen} pages, and none of them has a"
                " transcript that was checked by somebody who is not the one who"
                " wrote it down.  Without such a transcript there is nothing to"
                " measure, and no rate is published here.",
                "",
            ]
        # The engines that failed are named: a failure of an engine is
        # a fact about that engine, and it is not hidden by the fact
        # that there is no rate.
        for engine in engines:
            failures = engine.get("failures") or []
            if not failures:
                continue
            names = ", ".join(str(item.get("page", "?")) for item in failures)
            lines += [
                f"> **{engine.get('model') or engine.get('engine', 'the engine')}"
                f" failed on {len(failures)} of the pages it was given:**"
                f" {names}.",
                "",
            ]
        if report.get("note"):
            lines += [f"> {report['note']}", ""]
        lines += [
            "The tools that build the corpus and that measure the engines on"
            " it are ready: see `docs/MODERN_SCHOOL_BENCHMARK.md`.",
            "",
            end,
        ]
        return "\n".join(lines)
    summary = first.get("summary", {})
    lines += [
        f"Measured with {first.get('engine', 'the engine')} on"
        f" {first.get('pages', 0)} pages of"
        f" {corpus.get('name', 'the corpus')}:",
        "",
        "| | |",
        "| --- | --- |",
        f"| Character error rate | **{percent(summary.get('cer', 0.0))}** |",
        f"| Word error rate | **{percent(summary.get('wer', 0.0))}** |",
        f"| Seconds per page | {summary.get('seconds_per_page', '?')} |",
        f"| Pages measured | {first.get('pages', 0)} |",
        f"| Pages seen | {first.get('pages_seen', 0)} |",
        f"| Characters of the ground truth | {summary.get('characters_reference', '?')} |",
        f"| Words of the ground truth | {summary.get('words_reference', '?')} |",
        "",
    ]

    # How much of the corpus was really measured: a corpus of thirty
    # pages of which four were read is not a corpus of four pages, and
    # the report says which is which.
    if pages_seen and measured_corpus and measured_corpus < pages_seen:
        lines += [
            f"The corpus holds {pages_seen} pages.  The build chose"
            f" {report.get('pages_read', measured_corpus)} of them, and"
            f" {measured_corpus} of them could be measured.  The rate above"
            f" is of the {first.get('pages', 0)} pages that were measured, and it"
            " is not a rate of the whole corpus.",
            "",
        ]

    # The failures of an engine are named: a rate that is of the pages
    # the engine read is not a rate of the corpus, and it is not
    # written as if it were one.
    failures = first.get("failures") or []
    if failures:
        names = ", ".join(str(item.get("page", "?")) for item in failures)
        lines += [
            "> **The engine failed on {count} of the pages it was given:**"
            " {names}.  The rate above is of the pages it read, and it is not"
            " a rate of the whole corpus.".format(
                count=len(failures), names=names
            ),
            "",
        ]

    # The pages that were left out are named: a report with fewer pages
    # than the corpus has is not a report of a smaller corpus.
    left_out = first.get("left_out") or []
    if left_out:
        names = ", ".join(str(item.get("page", "?")) for item in left_out)
        lines += [
            f"> **{len(left_out)} of the pages were left out of the"
            f" measurement:** {names}.  There is no ground truth to compare"
            " them with, and the rate above is not a rate of those pages.",
            "",
        ]

    if len(engines) > 1:
        # The engines are compared on the pages that every engine
        # measured.  A rate that was measured on other pages than the
        # rate of another engine is not a comparison.
        comparison = report.get("comparison") or {}
        compared = comparison.get("engines") or []
        outside = comparison.get("pages_outside_the_comparison") or {}
        missed = sorted({page for pages in outside.values() for page in pages})
        lines += [
            "### The engines on the same pages",
            "",
        ]
        if missed:
            lines += [
                "The engines are compared on the pages that **every** engine"
                " measured: "
                f"{len(comparison.get('pages', []))} pages.  These pages were not"
                " measured by every engine: "
                + ", ".join(missed)
                + ".  A rate that was measured on other pages than the rate of"
                " another engine is not a comparison, and it is not written as"
                " one.",
                "",
            ]
        else:
            lines += [
                "Every engine was measured on the **same** pages.",
                "",
            ]
        lines += [
            "The rate of the"
            " errors is what decides which engine is the better one; the time"
            " that a teacher needs to correct the text is the other half of the"
            " decision, and it is measured with the people of the school.",
            "",
            "| Engine | Character error rate | Word error rate | Seconds per page | Pages |",
            "| --- | --- | --- | --- | --- |",
        ]
        for engine in compared or engines:
            engine_summary = engine.get("summary", {})
            lines.append(
                "| {name} | {cer} | {wer} | {seconds} | {pages} |".format(
                    name=engine.get("model") or engine.get("engine", "the engine"),
                    cer=percent(engine_summary.get("cer", 0.0)),
                    wer=percent(engine_summary.get("wer", 0.0)),
                    seconds=engine_summary.get("seconds_per_page", "?"),
                    pages=engine_summary.get(
                        "pages_measured", engine.get("pages", 0)
                    ),
                )
            )
        lines.append("")

        broken = [
            (engine.get("model") or engine.get("engine", "the engine"),
             engine.get("failures") or [])
            for engine in engines
            if engine.get("failures")
        ]
        if broken:
            lines += [
                "**The engines that failed:**",
                "",
            ]
            for name, items in broken:
                pages = ", ".join(str(item.get("page", "?")) for item in items)
                lines.append(f"* {name} failed on {pages}.")
            lines += [
                "",
                "The comparison above is of the pages that every engine read."
                " A rate that is of other pages than the rate of another engine"
                " is not a comparison, and it is not written as one.",
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

    unverified = summary.get("pages_without_verification") or []
    if unverified:
        lines += [
            "> **The transcript of these pages was not verified, and they are"
            " not part of the rates above:** "
            + ", ".join(unverified)
            + ".",
            "",
        ]

    pages = first.get("results") or []
    if pages:
        lines += [
            "| Page | Characters in the ground truth | Character error rate | Word error rate | Seconds | Ground truth |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for page in pages:
            complete = (page.get("ground_truth") or {}).get("complete", True)
            verified = bool(page.get("verified_by"))
            state = "complete" if complete else "**not complete**"
            if not verified:
                state = "**not verified**"
            lines.append(
                "| {page} | {chars} | {cer} | {wer} | {seconds} | {ground} |".format(
                    page=page.get("page", "?"),
                    chars=page.get("characters_reference", "?"),
                    cer=percent(page.get("cer", 0.0)),
                    wer=percent(page.get("wer", 0.0)),
                    seconds=page.get("seconds", "?"),
                    ground=state,
                )
            )
        lines.append("")

    if target == "modern":
        lines += [
            "These pages are the material the program is made for.  The rate"
            " is the rate of the raw recognition: no dictionary, no language"
            " model and no proposal of the spelling, of the grammar or of the"
            " scholarly style is part of it.",
            "",
        ]
    else:
        lines += [
            "These pages are the *diagnostic* corpus of the old handwriting."
            " They are not the material the program is made for, and they do"
            " not decide which engine is the better one.",
            "",
        ]

    lines += [
        "The numbers were produced by `tools/benchmark_ocr.py` in the"
        " `ocr-engine` job of the build, and the report they come from is"
        " uploaded as the artefact `ocr-accuracy-report`.",
        "",
        end,
    ]
    return "\n".join(lines)


def update_document(
    document: Path, section: str, begin: str = BEGIN, end: str = END
) -> bool:
    """Put the section between the markers.  Returns True when the file changed."""
    if not document.is_file():
        return False
    text = document.read_text(encoding="utf-8")
    if begin in text and end in text:
        start = text.index(begin)
        finish = text.index(end) + len(end)
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
    # The console of Windows cannot write Hebrew in the code page of
    # the system, and the program would stop in the middle of a report
    # because of a letter.
    use_utf8()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="ocr-accuracy.json")
    parser.add_argument(
        "--document", default=str(REPO_ROOT / "docs" / "OCR_ACCURACY.md")
    )
    parser.add_argument(
        "--begin",
        default=BEGIN,
        help="the marker where the section begins",
    )
    parser.add_argument(
        "--end",
        default=END,
        help="the marker where the section ends",
    )
    args = parser.parse_args(argv)

    report_path = Path(args.report)
    if not report_path.is_file():
        print(f"no report: {report_path}", file=sys.stderr)
        return 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    document = Path(args.document)
    if not document.is_file():
        # The document is not there: the build must not fail with a
        # traceback, and it must say what is missing.
        print(f"the document {document} is not there", file=sys.stderr)
        return 1
    section = build_section(report, begin=args.begin, end=args.end)
    if update_document(document, section, begin=args.begin, end=args.end):
        print(f"the results were written into {document}")
    elif args.begin not in document.read_text(encoding="utf-8"):
        print(
            f"the document {document} has no marker {args.begin}, "
            "nothing was written"
        )
    else:
        print("the results are already in the document")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
