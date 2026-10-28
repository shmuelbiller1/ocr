"""Measure the accuracy of the handwriting engine on real pages.

The corpus that matters is the **modern school handwriting**: pages
written by students in class, with a transcript of every page that was
checked by somebody who is not the one who wrote it down.  That corpus
lives in `benchmark/modern_school` and is described in
`docs/MODERN_SCHOOL_BENCHMARK.md`.

The **Pinkas dataset** is kept as a *diagnostic* corpus: 30 pages of
early modern (1500-1800) European Jewish community records written in
Hebrew and Yiddish, with a ground truth transcription for every line.
It shows that the engine reads old handwriting as well, but it is not
the material the program is made for, and it does not decide which
engine is the better one.

* Authors: Irina Rabaev, Berat Kurar Barakat, Jihad El-Sana.
* Published as: *The Pinkas Dataset*, ICDAR 2019,
  Zenodo record 3569694, <https://doi.org/10.5281/zenodo.3569694>
* License: **CC-BY-4.0** (attribution required, commercial use allowed).
* Download: ``pinkas_dataset.zip``, 47.7 MB,
  md5 ``802f14fbdb400efab9cb0808c3620be8``.

Every engine is measured on the **same** pages, so that the engines
can be compared with one another.  The measurement is of the raw
recognition: no dictionary, no language model and no proposal of the
spelling, of the grammar or of the scholarly style is ever part of it.

    python tools/benchmark_ocr.py --corpus benchmark/modern_school \
        --engines kraken-ppocrv6-small kraken-ppocrv6-medium
    python tools/benchmark_ocr.py --pinkas --pages 10 \
        --engines kraken-ppocrv6-small
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from hebrew_workbench.benchmark.corpus import (  # noqa: E402
    Corpus,
    Page,
    load_corpus,
    pinkas_pages,
    read_page_xml_report,
)
from hebrew_workbench.benchmark.metrics import (  # noqa: E402
    character_error_rate,
    levenshtein,
    normalise,
    word_error_rate,
)

__all__ = [
    "normalise",
    "levenshtein",
    "character_error_rate",
    "word_error_rate",
    "read_page_xml",
    "ground_truth_of",
    "find_pages",
    "measure_page",
    "measure",
    "run_engine",
    "resolve_engines",
    "main",
]

DATASET_URL = "https://zenodo.org/api/records/3569694/files/pinkas_dataset.zip/content"
DATASET_MD5 = "802f14fbdb400efab9cb0808c3620be8"
DATASET_SIZE = 47_699_110
DATASET_CITATION = (
    "Irina Rabaev, Berat Kurar Barakat, Jihad El-Sana, "
    '"The Pinkas Dataset", ICDAR 2019, https://doi.org/10.5281/zenodo.3569694'
)


def read_page_xml(path: Path) -> str:
    """The ground truth of a page in the PAGE XML form: its lines."""
    text, _report = read_page_xml_report(Path(path))
    return text


def ground_truth_of(path: Path) -> tuple[str, dict]:
    """The ground truth of a page, and what the file really holds."""
    from hebrew_workbench.benchmark.corpus import read_transcript

    return read_transcript(Path(path))


def download_dataset(target: Path) -> Path:
    """Download and verify the Pinkas dataset."""
    target.mkdir(parents=True, exist_ok=True)
    archive = target / "pinkas_dataset.zip"
    if archive.exists() and hashlib.md5(archive.read_bytes()).hexdigest() == DATASET_MD5:
        return archive
    print(f"downloading {DATASET_URL}")
    with urllib.request.urlopen(DATASET_URL, timeout=600) as response:
        data = response.read()
    digest = hashlib.md5(data).hexdigest()
    if digest != DATASET_MD5:
        raise SystemExit(
            f"the downloaded corpus does not match the published md5 ({digest}). "
            "It was not used."
        )
    archive.write_bytes(data)
    return archive


def extract_dataset(archive: Path, target: Path) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(target)
    return target


def find_pages(root: Path) -> list[tuple[Path, Path]]:
    """Pair every page image with its ground truth file."""
    pairs = []
    for xml_path in sorted(root.rglob("*.xml")):
        page = xml_path.with_suffix(".jpg")
        if not page.exists():
            page = xml_path.with_suffix(".png")
        if page.exists():
            pairs.append((page, xml_path))
    return pairs


def measure(engine, page: Page) -> dict | None:
    """Recognise one page and compare the result with its ground truth.

    ``None`` is returned when the page has no ground truth, because such
    a page cannot be measured.
    """
    reference_raw = page.text
    if not reference_raw.strip():
        return None

    started = time.monotonic()
    recognised = engine.recognize(page.image)
    seconds = time.monotonic() - started

    reference = normalise(reference_raw)
    hypothesis = normalise(recognised.text)
    reference_points = normalise(reference_raw, keep_points=True)
    hypothesis_points = normalise(recognised.text, keep_points=True)
    reference_words = reference.split()
    hypothesis_words = hypothesis.split()

    return {
        "page": page.image.name,
        "ground_truth_file": str(page.transcript or ""),
        "writer": page.writer,
        "verified_by": list(page.verified_by),
        # What the file of the ground truth really holds, so that the
        # measurement can be understood and not only believed.
        "ground_truth": dict(page.report),
        "characters_reference": len(reference),
        "characters_hypothesis": len(hypothesis),
        "cer": round(character_error_rate(reference, hypothesis), 4),
        "cer_with_points": round(
            character_error_rate(reference_points, hypothesis_points), 4
        ),
        "wer": round(word_error_rate(reference, hypothesis), 4),
        # The number of the words of the ground truth and the number of
        # the words that were not read right.  The error rate of the
        # whole corpus is the sum of these over the whole corpus, and
        # not the average of the rates of the pages: a page with few
        # words would otherwise count as much as a page with many.
        "words_reference": len(reference_words),
        "word_errors": levenshtein(reference_words, hypothesis_words),
        "seconds": round(seconds, 2),
        # A short piece of both texts, so that a report that says
        # "the error rate is 1200%" can be looked at and understood.
        "reference_sample": reference[:200],
        "hypothesis_sample": hypothesis[:200],
        # The first lines of both sides, one by one, so that a
        # difference between the two can be seen and not only counted.
        "reference_lines_sample": [
            line[:70] for line in reference_raw.splitlines() if line.strip()
        ][:4],
        "hypothesis_lines_sample": [
            line[:70] for line in recognised.text.splitlines() if line.strip()
        ][:4],
        # The lines are counted before the text is normalised, because
        # the normalisation turns every line into one long line.
        "lines_reference": len(
            [line for line in reference_raw.splitlines() if line.strip()]
        ),
        "lines_hypothesis": len(
            [line for line in recognised.text.splitlines() if line.strip()]
        ),
    }


def measure_page(
    engine,
    image: Path,
    xml_path: Path,
    dataset_root: Path,
) -> dict | None:
    """Recognise a page and compare the result with its ground truth.

    This is the older way of calling the measurement, with the image
    and the file of the ground truth given directly.
    """
    page = Page(image=Path(image), transcript=Path(xml_path))
    try:
        text, report = ground_truth_of(Path(xml_path))
    except (OSError, ValueError):
        return None
    page.text = text
    page.report = report
    return measure(engine, page)


def run_engine(engine, pages: list[Page], label: str = "") -> dict:
    """Measure one engine on the given pages.

    The pages that are not verified, or whose ground truth is not
    complete, are left out of the rate of the corpus and are named in
    the report.
    """
    results = []
    failures = []
    for index, page in enumerate(pages, start=1):
        print(f"[{index}/{len(pages)}] recognising {page.image.name} ...", flush=True)
        try:
            measured = measure(engine, page)
        except Exception as exc:
            # A failure of the engine on one page does not stop the
            # measurement of the other pages, and it does not stop the
            # other engines: every engine is measured on the same
            # pages, and one of them that is broken is a fact about that
            # engine and not about the others.
            message = f"{type(exc).__name__}: {exc}"
            print(f"    the engine failed on this page: {message}", flush=True)
            failures.append({"page": page.image.name, "error": message})
            continue
        if measured is None:
            print("    no ground truth, the page is left out", flush=True)
            continue
        results.append(measured)
        print(
            f"    CER {measured['cer'] * 100:.1f}%  "
            f"WER {measured['wer'] * 100:.1f}%  "
            f"{measured['seconds']:.1f}s",
            flush=True,
        )
        print(
            f"    lines: {measured['lines_reference']} in the ground truth, "
            f"{measured['lines_hypothesis']} in the result",
            flush=True,
        )
        print(f"    ground truth: {measured['reference_sample']}", flush=True)
        print(f"    recognised:   {measured['hypothesis_sample']}", flush=True)

    if not results and not failures:
        raise SystemExit("no page with a ground truth was found in the corpus")

    incomplete = [
        item["page"] for item in results if not item["ground_truth"].get("complete", True)
    ]
    unverified = [item["page"] for item in results if not item.get("verified_by")]
    measured_pages = [
        item
        for item in results
        if item["ground_truth"].get("complete", True) and item.get("verified_by")
    ]
    if measured_pages:
        total_reference = sum(item["characters_reference"] for item in measured_pages)
        total_cer = (
            sum(
                item["cer"] * item["characters_reference"]
                for item in measured_pages
            )
            / max(1, total_reference)
        )
        total_words = sum(item["words_reference"] for item in measured_pages)
        total_wer = sum(item["word_errors"] for item in measured_pages) / max(
            1, total_words
        )
        seconds = sum(item["seconds"] for item in measured_pages) / len(measured_pages)
    else:
        # There is no page that may be measured: there is no rate, and
        # not a rate of zero.
        total_reference = 0
        total_words = 0
        total_cer = None
        total_wer = None
        seconds = None

    return {
        "engine": getattr(engine, "name", label or "the engine"),
        "model": label,
        "pages": len(measured_pages),
        "pages_seen": len(results),
        "summary": {
            "cer": None if total_cer is None else round(total_cer, 4),
            "wer": None if total_wer is None else round(total_wer, 4),
            "seconds_per_page": None if seconds is None else round(seconds, 2),
            "characters_reference": total_reference,
            "words_reference": total_words,
            "ground_truth_complete": not incomplete,
            "pages_with_incomplete_ground_truth": incomplete,
            "pages_without_verification": unverified,
            # The rate is only a measurement when the ground truth was
            # verified; without it the number is not published.
            "measured": bool(measured_pages),
        },
        "results": results,
        # The pages on which the engine failed.  They are named, so
        # that a report with fewer pages than the corpus has is not
        # taken for a report of a smaller corpus.
        "failures": failures,
    }


def _kraken_engine():
    """The class of the engine, imported only when it is needed.

    The engine is imported lazily, so that the tools that only look at
    the corpora work even where kraken is not installed.
    """
    from hebrew_workbench.engine.kraken_local import KrakenEngine

    return KrakenEngine


def resolve_engines(model_ids: list[str], models_folder: Path, timeout: float = 1800.0):
    """The engines to measure, and the reasons for the ones that are left out.

    The models are looked for in the folder that is given, so that a
    build can measure the models it downloaded itself, and not only the
    ones that the program keeps for the user.

    ``kraken`` is imported only when an engine is really made, so that
    this function works where the engine is not installed.
    """
    from hebrew_workbench.engine.models import MODEL_ARTIFACTS

    engines = []
    warnings = []
    for identifier in model_ids:
        artifact = MODEL_ARTIFACTS.get(identifier)
        if artifact is None:
            warnings.append(f"the model {identifier} is not known to the program")
            continue
        model_path = models_folder / artifact.filename
        if not model_path.is_file():
            warnings.append(
                f"the model {identifier} is not installed ({model_path}), "
                "it was not measured"
            )
            continue
        engines.append(
            (_kraken_engine()(model_path, timeout_seconds=timeout), identifier)
        )
    return engines, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        help="folder of a corpus with a corpus.json in it (the modern school pages)",
    )
    parser.add_argument(
        "--pinkas",
        action="store_true",
        help="use the Pinkas dataset, the diagnostic corpus of the old handwriting",
    )
    parser.add_argument(
        "--engines",
        nargs="+",
        default=[],
        help="the models to measure, e.g. kraken-ppocrv6-small kraken-ppocrv6-medium",
    )
    parser.add_argument("--model", help="path to one recognition model file")
    parser.add_argument(
        "--models",
        help=(
            "folder where the model files are, when they are not in the "
            "folder of the program"
        ),
    )
    parser.add_argument("--dataset", help="folder with an extracted Pinkas dataset")
    parser.add_argument("--download", action="store_true", help="download the corpus first")
    parser.add_argument("--cache", default=".cache/pinkas", help="download cache folder")
    parser.add_argument("--pages", type=int, default=10, help="how many pages to recognise")
    parser.add_argument("--output", default="ocr-accuracy.json", help="report file")
    parser.add_argument("--timeout", type=float, default=1800.0)
    args = parser.parse_args(argv)

    if not args.corpus and not args.pinkas:
        raise SystemExit(
            "a corpus is needed: --corpus for the modern school pages, "
            "--pinkas for the diagnostic corpus of the old handwriting"
        )

    # -- the corpus ---------------------------------------------------------
    if args.corpus:
        corpus = load_corpus(Path(args.corpus))
        for error in corpus.errors:
            print(f"warning: {error}", file=sys.stderr)
        pages = corpus.pages
        description = corpus.summary()
    else:
        if args.dataset:
            dataset_root = Path(args.dataset)
        else:
            cache = Path(args.cache)
            archive = download_dataset(cache)
            dataset_root = extract_dataset(archive, cache / "extracted")
        pages = pinkas_pages(dataset_root)
        description = {
            "name": "The Pinkas Dataset",
            "target": "historical",
            "citation": DATASET_CITATION,
            "license": "CC-BY-4.0",
            "url": "https://zenodo.org/records/3569694",
            "description": (
                "30 pages of early modern (1500-1800) European Jewish community "
                "records in Hebrew and Yiddish, with a line level ground truth. "
                "A diagnostic corpus: it is not the material the program is made for."
            ),
            "pages": len(pages),
            "pages_measured": len(pages),
            "verified": False,
        }
        corpus = Corpus(
            name=description["name"],
            description=description["description"],
            target="historical",
            license=description["license"],
            citation=description["citation"],
            url=description["url"],
            pages=pages,
        )

    if not pages:
        # An empty corpus is not a failure: it means that the accuracy
        # of the recognition on this material is not verified, and the
        # report says so.
        report = {
            "corpus": description,
            "measurement": {
                "what_is_measured": "the raw recognition of the engine",
                "no_corrections": (
                    "the proposals of the spelling, of the grammar and of the "
                    "scholarly style are not part of the measurement"
                ),
            },
            "engines": [],
            "note": (
                "the corpus has no page with a verified transcript, so the "
                "accuracy of the recognition on this material is NOT verified"
            ),
        }
        Path(args.output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(report["note"])
        print(f"report written to {args.output}")
        return 0
    pages = pages[: max(1, args.pages)]

    # -- the engines --------------------------------------------------------
    from hebrew_workbench.engine.models import models_directory

    model_ids = list(args.engines)
    if args.model:
        model_ids = []

    engines = []
    if args.model:
        engines.append(
            (
                _kraken_engine()(Path(args.model), timeout_seconds=args.timeout),
                str(args.model),
            )
        )
    else:
        models_folder = Path(args.models) if args.models else models_directory()
        engines, warnings = resolve_engines(
            model_ids, models_folder, timeout=args.timeout
        )
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
    if not engines:
        raise SystemExit(
            "no engine to measure: give --engines with the models that are "
            "installed, or --model with the path of a model file"
        )

    # -- the measurement ----------------------------------------------------
    report = {
        "corpus": description,
        "measurement": {
            "what_is_measured": "the raw recognition of the engine",
            "no_corrections": (
                "the proposals of the spelling, of the grammar and of the "
                "scholarly style are not part of the measurement"
            ),
        },
        "engines": [],
    }
    for engine, label in engines:
        print(f"=== the engine {label} ===", flush=True)
        report["engines"].append(run_engine(engine, pages, label=label))

    Path(args.output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report["engines"][-1]["summary"], indent=2))
    if not report["engines"][-1]["summary"].get("measured"):
        print(
            "no page of this corpus has a verified transcript, so no rate "
            "is published"
        )
    print(f"report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
