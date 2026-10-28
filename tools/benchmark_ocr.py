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

from hebrew_workbench.console import use_utf8

# The console of Windows cannot write Hebrew in the code page of the
# system, and the program would stop in the middle of a report because
# of a letter.  The console is asked to write in UTF-8 as soon as the
# tool is loaded, so that every place that writes text is safe.
use_utf8()
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
    "summarise",
    "measured_pages_of",
    "compare_on_the_same_pages",
    "check_against_the_manifest",
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


def measure(engine, page: Page, name: str = "") -> dict | None:
    """Recognise one page and compare the result with its ground truth.

    ``None`` is returned when the page has no ground truth, because such
    a page cannot be measured.

    The name of the page is the path of the image in the corpus and not
    only its name: two pages of the corpus may have the same name in
    two different folders, and the measurement has to tell them apart.
    """
    if not name:
        name = page.image.name
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
        "page": name,
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


def summarise(results: list[dict]) -> dict:
    """The rate of an engine over the pages that it really measured.

    Only the pages whose ground truth is complete and was verified by
    somebody else are counted: the rate of the errors of an engine
    against a ground truth that is not there is not a measurement.

    The rate of the whole corpus is the sum of the errors over the
    whole corpus, and not the average of the rates of the pages: a page
    with few words would otherwise count as much as a page with many.
    """
    incomplete = [
        item["page"]
        for item in results
        if not item["ground_truth"].get("complete", False)
    ]
    unverified = [item["page"] for item in results if not item.get("verified_by")]
    measured_pages = [
        item
        for item in results
        if item["ground_truth"].get("complete", False) and item.get("verified_by")
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
        "cer": None if total_cer is None else round(total_cer, 4),
        "wer": None if total_wer is None else round(total_wer, 4),
        "seconds_per_page": None if seconds is None else round(seconds, 2),
        "characters_reference": total_reference,
        "words_reference": total_words,
        "pages_measured": len(measured_pages),
        "ground_truth_complete": not incomplete,
        "pages_with_incomplete_ground_truth": incomplete,
        "pages_without_verification": unverified,
        # The rate is only a measurement when the ground truth was
        # verified; without it the number is not published.
        "measured": bool(measured_pages),
    }


def pages_that_may_be_measured(pages: list[Page]) -> int:
    """The number of the pages whose ground truth may be measured.

    A page whose transcript could not be read, or whose transcript was
    not checked by somebody else, is not a measurement: the engine
    would be blamed for a text that is not there.
    """
    return len([page for page in pages if page.complete and page.verified])


def measured_pages_of(report: dict) -> set[str]:
    """The names of the pages that an engine really measured."""
    return {
        item["page"]
        for item in report.get("results", [])
        if item.get("ground_truth", {}).get("complete", False)
        and item.get("verified_by")
    }


def _key_of(report: dict) -> str:
    """The name that tells one measurement from another.

    It is the model that was measured, because two models of the same
    engine have the same name.
    """
    return str(report.get("model") or report.get("engine", ""))


def compare_on_the_same_pages(reports: list[dict]) -> dict:
    """Compare the engines on the pages that every engine measured.

    A rate that was measured on other pages than the rate of another
    engine is not a comparison.  The pages that every engine measured
    are therefore the pages the engines are compared on, and the rate
    of every engine is computed over those pages.

    The pages that one of the engines did not read are named, so that
    a report with fewer pages than the corpus has is not taken for a
    report of a smaller corpus.
    """
    if not reports:
        return {"pages": [], "engines": [], "pages_outside_the_comparison": {}}
    # The reports are told apart by the model that was measured.  Two
    # models of the same engine have the same name, and a comparison
    # that keeps only one of them is not a comparison.
    pages_of = {
        _key_of(report): measured_pages_of(report) for report in reports
    }
    common = set.intersection(*pages_of.values())
    outside = {
        name: sorted(pages - common) for name, pages in pages_of.items()
    }
    engines = []
    for report in reports:
        name = str(report.get("engine", ""))
        results = [
            item for item in report.get("results", []) if item["page"] in common
        ]
        engines.append(
            {
                "engine": name,
                "model": report.get("model", ""),
                "summary": summarise(results),
            }
        )
    return {
        "pages": sorted(common),
        "engines": engines,
        "pages_outside_the_comparison": outside,
    }


def _name_of_the_page(corpus_folder: Path | None, image: Path) -> str:
    """The name of a page in a measurement: the path in the corpus."""
    if corpus_folder is None:
        return Path(image).name
    return _name_in_the_corpus(corpus_folder, image)


def _name_in_the_corpus(corpus_folder: Path, image: Path) -> str:
    """The name of a page in the corpus: the path and not only the name.

    Two pages of the corpus may have the same name in two different
    folders, and the manifest tells them apart by their path.
    """
    folder = Path(corpus_folder)
    try:
        # The path is written with slashes and not with the separator
        # of the system, so that the manifest of a corpus is the same
        # everywhere.
        # The links of the file are not followed: a page that is
        # linked from outside of the corpus keeps the place it has in
        # the corpus, and two pages that are linked from two folders
        # are two pages.
        return Path(image).absolute().relative_to(folder.absolute()).as_posix()
    except ValueError:
        return Path(image).name


def check_against_the_manifest(corpus_folder: Path, pages: list[Page]) -> list[str]:
    """Check that the images are the ones that the manifest holds.

    The measurement has to be of the same pages every time, and the
    manifest holds the digest of every image.  When an image was
    changed, the measurement is of a different corpus than the one
    that was built, and it is not published.

    A corpus without a manifest is not checked: there is nothing to
    check it against.
    """
    manifest_path = Path(corpus_folder) / "manifest.json"
    if not manifest_path.is_file():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"the manifest of the corpus could not be read: {exc}")
    digests = {
        str(entry.get("image", "")): str(entry.get("sha256", ""))
        for entry in manifest.get("pages", [])
    }
    changed = []
    missing = []
    names = []
    for page in pages:
        name = _name_in_the_corpus(corpus_folder, page.image)
        names.append(name)
        expected = digests.get(name)
        if not expected:
            # The page is not in the manifest: the manifest was made
            # for another corpus, and the measurement would not be the
            # measurement of the corpus that was built.
            missing.append(name)
            continue
        if page.digest() != expected:
            changed.append(name)
    # The pages of the manifest that are not in the corpus any more.
    gone = [name for name in digests if name not in names]
    if changed or missing or gone:
        what = []
        if changed:
            what.append(
                "the image of these pages is not the one that the manifest holds: "
                + ", ".join(sorted(changed))
            )
        if missing:
            what.append(
                "these pages are not in the manifest: " + ", ".join(sorted(missing))
            )
        if gone:
            what.append(
                "these pages of the manifest are not in the corpus any more: "
                + ", ".join(sorted(gone))
            )
        raise SystemExit(
            ". ".join(what)
            + ". The measurement was not published, because it would not be "
            "the measurement of the corpus. Run tools/build_benchmark.py to "
            "write a manifest of the pages that are there now."
        )
    return changed


def run_engine(
    engine,
    pages: list[Page],
    label: str = "",
    corpus_folder: Path | None = None,
) -> dict:
    """Measure one engine on the given pages.

    The pages that are not verified, or whose ground truth is not
    complete, are left out of the rate of the corpus and are named in
    the report.

    Every page is named by its path in the corpus, so that two pages
    with the same name in two folders are two different pages.
    """
    results = []
    failures = []
    left_out = []
    for index, page in enumerate(pages, start=1):
        name = _name_of_the_page(corpus_folder, page.image)
        print(f"[{index}/{len(pages)}] recognising {name} ...", flush=True)
        try:
            measured = measure(engine, page, name=name)
        except Exception as exc:
            # A failure of the engine on one page does not stop the
            # measurement of the other pages, and it does not stop the
            # other engines: every engine is measured on the same
            # pages, and one of them that is broken is a fact about that
            # engine and not about the others.
            message = f"{type(exc).__name__}: {exc}"
            print(f"    the engine failed on this page: {message}", flush=True)
            failures.append({"page": name, "error": message})
            continue
        if measured is None:
            # The page was read, but there is nothing to compare it
            # with.  It is named, so that a report with fewer pages
            # than the corpus has is not taken for a report of a
            # smaller corpus.
            print("    no ground truth, the page is left out", flush=True)
            left_out.append(
                {"page": name, "reason": "there is no ground truth"}
            )
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

    summary = summarise(results)

    return {
        "engine": getattr(engine, "name", label or "the engine"),
        "model": label,
        "pages": summary["pages_measured"],
        "pages_seen": len(results),
        "summary": summary,
        "results": results,
        # The pages on which the engine failed.  They are named, so
        # that a report with fewer pages than the corpus has is not
        # taken for a report of a smaller corpus.
        "failures": failures,
        # The pages that were left out because there was no ground
        # truth to compare them with.
        "left_out": left_out,
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
            (
                _kraken_engine()(
                    model_path, artifact_id=identifier, timeout_seconds=timeout
                ),
                identifier,
            )
        )
    return engines, warnings


def main(argv: list[str] | None = None) -> int:
    # The console of Windows cannot write Hebrew in the code page
    # of the system, and the program would stop in the middle of a
    # report because of a letter.
    use_utf8()
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
        # Only the pages that may be measured: a page whose transcript
        # was not checked by somebody else, or whose transcript could
        # not be read, is not a measurement.
        pages = corpus.measured_pages
        description = corpus.summary()
        # The images have to be the ones that the manifest holds, so
        # that every build measures the same corpus.
        check_against_the_manifest(Path(args.corpus), corpus.pages)
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
            # The number of the pages that were measured is not known
            # yet: it is set after the pages were chosen.
            "pages_measured": 0,
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
    if args.pinkas:
        # The limit of the number of the pages is for the diagnostic
        # corpus alone: the corpus of the school is measured with all
        # of the pages that may be measured.
        pages = pages[: max(1, args.pages)]

    # The number of the pages that were read is not the number of the
    # pages that were measured: a page whose ground truth is not
    # complete is not a measurement, and a corpus of thirty pages of
    # which four were read is not a corpus of four pages.
    pages_read = len(pages)
    pages_measured = pages_that_may_be_measured(pages)
    description["pages_measured"] = pages_measured

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
        # The number of the pages that were read, and the number of
        # the pages of the corpus that may be measured.  They are not
        # the same: a page whose ground truth is not complete is not a
        # measurement.  The number of the pages that an engine read is
        # a fact about that engine, and it is in its own part of the
        # report.
        "pages_read": pages_read,
        "measured_corpus_pages": pages_measured,
        "engines": [],
    }
    # The folder of the corpus: the pages are named by their path in
    # it, so that two pages with the same name are two pages.
    folder = Path(args.corpus) if args.corpus else None
    for engine, label in engines:
        print(f"=== the engine {label} ===", flush=True)
        report["engines"].append(
            run_engine(engine, pages, label=label, corpus_folder=folder)
        )

    # The engines are compared on the pages that every engine measured.
    report["comparison"] = compare_on_the_same_pages(report["engines"])

    Path(args.output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report["engines"][-1]["summary"], indent=2))
    if not report["engines"][-1]["summary"].get("measured"):
        if report["measured_corpus_pages"]:
            # The corpus has pages that may be measured, and the engine
            # did not read one of them: the fault is in the engine, and
            # it is said so.
            print(
                "the corpus has pages that may be measured, but the engine "
                "did not read one of them. No rate is published."
            )
        else:
            print(
                "no page of this corpus has a verified transcript, so no rate "
                "is published"
            )
    print(f"report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
