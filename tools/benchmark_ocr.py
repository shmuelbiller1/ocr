"""Measure the accuracy of the handwriting engine on real pages.

The benchmark uses the **Pinkas dataset**: 30 pages of early modern
(1500-1800) European Jewish community records written in Hebrew and
Yiddish, with a ground truth transcription for every line.

* Authors: Irina Rabaev, Berat Kurar Barakat, Jihad El-Sana.
* Published as: *The Pinkas Dataset*, ICDAR 2019,
  Zenodo record 3569694, <https://doi.org/10.5281/zenodo.3569694>
* License: **CC-BY-4.0** (attribution required, commercial use allowed).
* Download: ``pinkas_dataset.zip``, 47.7 MB,
  md5 ``802f14fbdb400efab9cb0808c3620be8``.

The script downloads the corpus (unless a local copy is given), runs the
engine on the requested number of pages and writes a report with the
character error rate, the word error rate and the time per page.

    python tools/benchmark_ocr.py --model small.safetensors --pages 10
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
import unicodedata
import urllib.request
import zipfile
from pathlib import Path
from xml.etree import ElementTree

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

DATASET_URL = "https://zenodo.org/api/records/3569694/files/pinkas_dataset.zip/content"
DATASET_MD5 = "802f14fbdb400efab9cb0808c3620be8"
DATASET_SIZE = 47_699_110
DATASET_CITATION = (
    "Irina Rabaev, Berat Kurar Barakat, Jihad El-Sana, "
    '"The Pinkas Dataset", ICDAR 2019, https://doi.org/10.5281/zenodo.3569694'
)

# Hebrew vowel points and cantillation marks.
POINTS = re.compile(r"[֑-ֽֿׁ-ׂׄ-ׇ]")
SPACE = re.compile(r"\s+")


def normalise(text: str, keep_points: bool = False) -> str:
    """Normalise text the same way for the engine and for the ground truth."""
    text = unicodedata.normalize("NFC", text)
    if not keep_points:
        text = POINTS.sub("", text)
    text = text.replace("״", '"').replace("׳", "'")
    return SPACE.sub(" ", text).strip()


def levenshtein(first: list[str], second: list[str]) -> int:
    """Edit distance between two sequences."""
    if len(first) < len(second):
        first, second = second, first
    previous = list(range(len(second) + 1))
    for index1, item1 in enumerate(first, start=1):
        current = [index1]
        for index2, item2 in enumerate(second, start=1):
            insert = current[index2 - 1] + 1
            delete = previous[index2] + 1
            replace = previous[index2 - 1] + (item1 != item2)
            current.append(min(insert, delete, replace))
        previous = current
    return previous[-1]


def character_error_rate(reference: str, hypothesis: str) -> float:
    if not reference:
        return 0.0 if not hypothesis else 1.0
    distance = levenshtein(list(reference), list(hypothesis))
    return distance / len(reference)


def word_error_rate(reference: str, hypothesis: str) -> float:
    reference_words = reference.split()
    hypothesis_words = hypothesis.split()
    if not reference_words:
        return 0.0 if not hypothesis_words else 1.0
    distance = levenshtein(reference_words, hypothesis_words)
    return distance / len(reference_words)


def read_page_xml(path: Path) -> str:
    """The ground truth of a page: its lines, in reading order."""
    tree = ElementTree.parse(path)
    lines = []
    for line in tree.iter():
        tag = line.tag.rsplit("}", 1)[-1]
        if tag != "TextLine":
            continue
        for child in line:
            if child.tag.rsplit("}", 1)[-1] == "Unicode":
                text = (child.text or "").strip()
                if text:
                    lines.append(text)
                break
    return "\n".join(lines)


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="path to the recognition model")
    parser.add_argument("--dataset", help="folder with an extracted Pinkas dataset")
    parser.add_argument("--download", action="store_true", help="download the corpus first")
    parser.add_argument("--cache", default=".cache/pinkas", help="download cache folder")
    parser.add_argument("--pages", type=int, default=10, help="how many pages to recognise")
    parser.add_argument("--output", default="ocr-accuracy.json", help="report file")
    parser.add_argument("--timeout", type=float, default=1800.0)
    args = parser.parse_args(argv)

    model_path = Path(args.model)
    if not model_path.is_file():
        raise SystemExit(f"the model file was not found: {model_path}")

    if args.dataset:
        dataset_root = Path(args.dataset)
    else:
        cache = Path(args.cache)
        archive = download_dataset(cache)
        dataset_root = extract_dataset(archive, cache / "extracted")

    pairs = find_pages(dataset_root)
    if not pairs:
        raise SystemExit(f"no pages with ground truth were found in {dataset_root}")
    pairs = pairs[: max(1, args.pages)]

    from hebrew_workbench.engine.kraken_local import KrakenEngine

    engine = KrakenEngine(model_path, timeout_seconds=args.timeout)

    results = []
    for index, (image, xml_path) in enumerate(pairs, start=1):
        reference_raw = read_page_xml(xml_path)
        started = time.monotonic()
        print(f"[{index}/{len(pairs)}] recognising {image.name} ...", flush=True)
        recognised = engine.recognize(image)
        seconds = time.monotonic() - started

        reference = normalise(reference_raw)
        hypothesis = normalise(recognised.text)
        reference_points = normalise(reference_raw, keep_points=True)
        hypothesis_points = normalise(recognised.text, keep_points=True)

        results.append(
            {
                "page": image.name,
                "ground_truth_file": str(xml_path.relative_to(dataset_root)),
                "characters_reference": len(reference),
                "characters_hypothesis": len(hypothesis),
                "cer": round(character_error_rate(reference, hypothesis), 4),
                "cer_with_points": round(
                    character_error_rate(reference_points, hypothesis_points), 4
                ),
                "wer": round(word_error_rate(reference, hypothesis), 4),
                "seconds": round(seconds, 2),
            }
        )
        print(
            f"    CER {results[-1]['cer'] * 100:.1f}%  "
            f"WER {results[-1]['wer'] * 100:.1f}%  "
            f"{seconds:.1f}s",
            flush=True,
        )

    total_reference = sum(item["characters_reference"] for item in results)
    total_cer = sum(
        item["cer"] * item["characters_reference"] for item in results
    ) / max(1, total_reference)
    total_wer = sum(item["wer"] for item in results) / max(1, len(results))
    report = {
        "engine": engine.name,
        "model": str(model_path),
        "pages": len(results),
        "corpus": {
            "name": "The Pinkas Dataset",
            "citation": DATASET_CITATION,
            "license": "CC-BY-4.0",
            "url": "https://zenodo.org/records/3569694",
            "description": (
                "30 pages of early modern (1500-1800) European Jewish community "
                "records in Hebrew and Yiddish, with a line level ground truth."
            ),
        },
        "summary": {
            "cer": round(total_cer, 4),
            "wer": round(total_wer, 4),
            "seconds_per_page": round(
                sum(item["seconds"] for item in results) / max(1, len(results)), 2
            ),
        },
        "results": results,
    }
    Path(args.output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report["summary"], indent=2))
    print(f"report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
