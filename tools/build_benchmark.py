"""Check the corpus of the modern school handwriting and write its manifest.

The corpus of a folder is described in `corpus.json`; see
`benchmark/modern_school/README.md` for the rules of the pages and of
the transcripts.

The command checks that every page of the corpus has an image, a
transcript and a verification, and writes a manifest with the digest of
every image, so that the same pages are measured every time.

    python tools/build_benchmark.py --corpus benchmark/modern_school

The command does not fail when the corpus is empty or when a page was
not verified: it says so, and writes the manifest with what it found.
A corpus in which no page was verified is **not** a measurement of the
recognition, and the manifest says that as well.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from hebrew_workbench.console import use_utf8
from hebrew_workbench.benchmark.corpus import load_corpus  # noqa: E402

__all__ = ["build_manifest", "main"]

MANIFEST_FILE = "manifest.json"


def relative_to_the_corpus(corpus, path) -> str:
    """The path of a file of the corpus, as the corpus itself writes it.

    The path of the file and not only its name: two pages of the
    corpus may have the same name in two different folders, and a
    manifest that keeps only the name cannot tell them apart.
    """
    folder = getattr(corpus, "folder", None)
    if folder is None:
        return Path(path).name
    try:
        return str(Path(path).resolve().relative_to(Path(folder).resolve()))
    except ValueError:
        return Path(path).name


def build_manifest(corpus) -> dict:
    """The manifest of a corpus: what it holds, and what is missing."""
    pages = []
    for page in corpus.pages:
        pages.append(
            {
                "image": relative_to_the_corpus(corpus, page.image),
                "transcript": (
                    relative_to_the_corpus(corpus, page.transcript)
                    if page.transcript
                    else ""
                ),
                "sha256": page.digest(),
                "writer": page.writer,
                "date": page.date,
                "verified_by": list(page.verified_by),
                "verified": page.verified,
                "complete": page.complete,
                "lines": page.report.get("lines", 0),
                "characters": page.report.get("characters", 0),
                "notes": page.notes,
            }
        )
    measured = [
        page["image"] for page in pages if page["verified"] and page["complete"]
    ]
    return {
        "corpus": corpus.summary(),
        "pages": pages,
        "pages_measured": measured,
        "verified": bool(measured),
        "note": (
            "the pages that were measured have a transcript that was checked "
            "by somebody who is not the one who wrote it down"
            if measured
            else "no page of this corpus has a verified transcript, so the "
            "accuracy of the recognition on this material is NOT verified"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    # The console of Windows cannot write Hebrew in the code page
    # of the system, and the program would stop in the middle of a
    # report because of a letter.
    use_utf8()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        default="benchmark/modern_school",
        help="the folder of the corpus",
    )
    parser.add_argument(
        "--output",
        help="where the manifest is written (the folder of the corpus by default)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail when the corpus has an error or no verified page",
    )
    args = parser.parse_args(argv)

    folder = Path(args.corpus)
    corpus = load_corpus(folder)
    for error in corpus.errors:
        print(f"error: {error}", file=sys.stderr)

    manifest = build_manifest(corpus)
    target = (
        Path(args.output)
        if args.output
        else folder / MANIFEST_FILE
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    summary = manifest["corpus"]
    print(f"the corpus {summary['name'] or folder}: {summary['pages']} pages")
    for page in manifest["pages"]:
        state = "measured" if page["verified"] and page["complete"] else "not measured"
        print(
            f"  {page['image']}: {state}"
            + (f" - {page['lines']} lines" if page["lines"] else "")
        )
    print(manifest["note"])
    print(f"manifest written to {target}")

    if args.strict and (corpus.errors or not manifest["verified"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
