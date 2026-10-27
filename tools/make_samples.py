"""Generate the sample pages that ship with the workbench.

The samples are **synthetic**: they are produced by this script, they
contain no real handwriting and no personal data, and they exist so that
a user (or a reviewer) can try the preview, the zoom, the rotation and the
page navigation without using real documents.

Run it with::

    python tools/make_samples.py

The files are written into ``samples/`` next to the repository root.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw

PAGE_WIDTH = 1240
PAGE_HEIGHT = 1754  # A4 at 150 dpi
MARGIN = 130
LINES = 22


def _ink_background(seed: int) -> Image.Image:
    """A slightly noisy, off-white page."""
    random.seed(seed)
    page = Image.new("L", (PAGE_WIDTH, PAGE_HEIGHT), 246)
    draw = ImageDraw.Draw(page)
    for _ in range(4000):
        x = random.randrange(PAGE_WIDTH)
        y = random.randrange(PAGE_HEIGHT)
        shade = random.randrange(225, 250)
        draw.point((x, y), fill=shade)
    return page.convert("RGB")


def _handwriting_like_lines(seed: int) -> Image.Image:
    """Draw strokes that look like handwriting without being any text."""
    random.seed(seed)
    page = _ink_background(seed)
    draw = ImageDraw.Draw(page)
    top = MARGIN + 90
    line_height = (PAGE_HEIGHT - 2 * MARGIN - 120) // LINES
    for index in range(LINES):
        y = top + index * line_height
        if random.random() < 0.18:  # an occasional short line, like a paragraph end
            x_end = MARGIN + random.randrange(200, 600)
        else:
            x_end = PAGE_WIDTH - MARGIN - random.randrange(0, 120)
        x = MARGIN
        while x < x_end:
            word_width = random.randrange(60, 190)
            points = []
            steps = max(6, word_width // 6)
            for step in range(steps + 1):
                px = x + word_width * step / steps
                py = y + random.uniform(-9, 9) + math.sin(step * 1.7) * 5
                points.append((px, py))
            if len(points) > 1:
                draw.line(points, fill=(24, 24, 30), width=random.choice([3, 3, 4]))
            x += word_width + random.randrange(18, 34)
    return page


def _pdf_bytes(pages: int) -> bytes:
    """A tiny, valid PDF with ``pages`` pages."""
    objects: list[bytes] = []
    page_ids = [3 + index for index in range(pages)]
    content_ids = [3 + pages + index for index in range(pages)]

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode("ascii"))
    for index, page_id in enumerate(page_ids):
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Contents {content_ids[index]} 0 R >>"
            ).encode("ascii")
        )
    for index, content_id in enumerate(content_ids):
        stream = (
            f"BT /F1 24 Tf 60 760 Td (Sample page {index + 1}) Tj ET\n"
            "0.85 0.85 0.85 rg 60 120 475 600 re f\n"
        ).encode("ascii")
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"

    xref_position = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_position}\n%%EOF\n"
    ).encode("ascii")
    return bytes(out)


HEBREW_SAMPLE = """זהוי טקסט לדוגמה, לבדיקת העורך והייצוא.

אפשר להקליד כאן טקסט עברי, לשנות אותו, לשמור אותו כקובץ טקסט או כמסמך Word,
ולהדפיס אותו. הכתב העברי מיושר לימין, בדיוק כמו שהוא נראה בדפוס.

שורה שלישית - הכל מקומי, ללא חיבור לאינטרנט.
"""


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    target = root / "samples"
    target.mkdir(parents=True, exist_ok=True)

    for index in (1, 2):
        page = _handwriting_like_lines(seed=20240101 + index)
        page.save(target / f"scan_page_{index}.png")

    (target / "two_pages.pdf").write_bytes(_pdf_bytes(2))
    (target / "sample_text_hebrew.txt").write_text(HEBREW_SAMPLE, encoding="utf-8-sig")

    print(f"wrote samples to {target}")
    for item in sorted(target.iterdir()):
        print(f"  {item.name} ({item.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
