"""Look at the structure of the Pinkas corpus.

The script prints what the ground truth files really hold, so that a
measurement can be understood and not only believed.

    python tools/inspect_dataset.py --cache .cache/pinkas
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from xml.etree import ElementTree

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from hebrew_workbench.console import use_utf8  # noqa: E402

from tools.benchmark_ocr import (  # noqa: E402
    _line_text,
    _word_text,
    download_dataset,
    extract_dataset,
    find_pages,
    read_page_xml,
)


def count_tags(tree) -> dict[str, int]:
    counts: dict[str, int] = {}
    for element in tree.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        counts[tag] = counts.get(tag, 0) + 1
    return counts


def _tag(element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _points(element) -> list[tuple[float, float]]:
    """The points of the Coords of a line, when it has any."""
    for child in element:
        if _tag(child) != "Coords":
            continue
        points: list[tuple[float, float]] = []
        for point in child:
            if _tag(point) != "Point":
                continue
            try:
                points.append((float(point.get("x", "0")), float(point.get("y", "0"))))
            except (TypeError, ValueError):
                continue
        return points
    return []


def _top(points: list[tuple[float, float]]) -> float | None:
    """The place of the line on the page: the smallest y of its points."""
    if not points:
        return None
    return round(min(point[1] for point in points), 1)


def main(argv: list[str] | None = None) -> int:
    # The console of Windows cannot write Hebrew in the code page
    # of the system, and the program would stop in the middle of a
    # report because of a letter.
    use_utf8()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", help="folder with an extracted corpus")
    parser.add_argument("--cache", default=".cache/pinkas", help="download cache")
    parser.add_argument("--pages", type=int, default=2, help="how many pages to show")
    args = parser.parse_args(argv)

    if args.dataset:
        dataset_root = Path(args.dataset)
    else:
        cache = Path(args.cache)
        archive = download_dataset(cache)
        dataset_root = extract_dataset(archive, cache / "extracted")

    print(f"the corpus is in {dataset_root}")
    xml_files = sorted(dataset_root.rglob("*.xml"))
    print(f"there are {len(xml_files)} ground truth files")

    pairs = find_pages(dataset_root)
    print(f"there are {len(pairs)} pages with a ground truth")

    for image, xml_path in pairs[: max(1, args.pages)]:
        print("")
        print(f"--- {image.name}")
        tree = ElementTree.parse(xml_path)
        counts = count_tags(tree)
        interesting = {
            tag: number
            for tag, number in sorted(counts.items())
            if tag
            in {
                "Page",
                "TextRegion",
                "TextLine",
                "Word",
                "TextEquiv",
                "Unicode",
                "Image",
            }
        }
        print(f"    the file holds: {interesting}")
        text = read_page_xml(xml_path)
        lines = [line for line in text.splitlines() if line.strip()]
        print(f"    the text that is read: {len(text)} characters in {len(lines)} lines")
        print(f"    the first lines: {lines[:3]}")

        # The shape of a line, so that the structure is visible and not
        # only the result: the order of the children, the text of the
        # line itself and the words that are inside it.
        for element in tree.iter():
            if element.tag.rsplit("}", 1)[-1] != "TextLine":
                continue
            children = [child.tag.rsplit("}", 1)[-1] for child in element]
            print(f"    a line holds: {children}")
            print(f"    the text of that line: {_line_text(element)!r}")
            words = [
                _word_text(child)
                for child in element
                if child.tag.rsplit("}", 1)[-1] == "Word"
            ]
            print(f"    its words: {words[:8]}")
            break

        try:
            from PIL import Image

            with Image.open(image) as handle:
                print(f"    the image is {handle.width}x{handle.height} pixels")
        except Exception as exc:  # pragma: no cover - defensive
            print(f"    the image could not be opened: {exc!r}")

        # Where every line is on the page.  The order of the lines in
        # the file is the order of the reading, but it is worth seeing
        # it: when the file is not in the order of the page, every
        # measurement of the page is wrong.
        region = -1
        for element in tree.iter():
            tag = _tag(element)
            if tag == "TextRegion":
                region += 1
            if tag != "TextLine":
                continue
            text = _line_text(element)
            if not text:
                continue
            print(
                f"    line: region {region} at y={_top(_points(element))} "
                f"text={text[:48]!r}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
