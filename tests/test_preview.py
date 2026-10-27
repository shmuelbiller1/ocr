"""Tests for the offline document preview."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hebrew_workbench.preview import loader
from hebrew_workbench.preview.loader import DocumentPreview, PreviewError


def make_pdf_bytes(pages: int = 2) -> bytes:
    """Build a small, valid PDF with ``pages`` pages."""
    objects: list[bytes] = []
    page_ids = [3 + index for index in range(pages)]
    content_ids = [3 + pages + index for index in range(pages)]

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects.append(
        f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode("ascii")
    )
    for index, page_id in enumerate(page_ids):
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 120] "
                f"/Contents {content_ids[index]} 0 R >>"
            ).encode("ascii")
        )
    for content_id in content_ids:
        stream = b"BT /F1 18 Tf 20 60 Td (Sample page) Tj ET"
        objects.append(
            b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
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


class PreviewTests(unittest.TestCase):
    def test_image_has_one_page(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scan.png"
            Image.new("RGB", (64, 48), (255, 255, 255)).save(path)
            with DocumentPreview(path) as preview:
                self.assertEqual(preview.page_count, 1)
                page = preview.render(1)
                self.assertEqual(page.number, 1)
                self.assertEqual(page.image.size, (64, 48))

    def test_multipage_tiff_has_many_pages(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scan.tiff"
            frames = [Image.new("RGB", (32, 32), (index * 40, 0, 0)) for index in range(3)]
            frames[0].save(path, save_all=True, append_images=frames[1:])
            with DocumentPreview(path) as preview:
                self.assertEqual(preview.page_count, 3)
                self.assertEqual(preview.render(2).image.size, (32, 32))

    def test_pdf_is_rasterised(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scan.pdf"
            path.write_bytes(make_pdf_bytes(2))
            with DocumentPreview(path) as preview:
                self.assertTrue(preview.is_pdf)
                self.assertEqual(preview.page_count, 2)
                page = preview.render(2)
                self.assertEqual(page.number, 2)
                self.assertGreater(page.image.width, 0)

    def test_missing_file_is_reported(self) -> None:
        with self.assertRaises(PreviewError):
            DocumentPreview("this-file-does-not-exist.png")

    def test_unsupported_type_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "notes.docx"
            path.write_bytes(b"not a scan")
            with self.assertRaises(PreviewError):
                DocumentPreview(path)

    def test_broken_pdf_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "broken.pdf"
            path.write_bytes(b"this is not a pdf at all")
            with self.assertRaises(PreviewError):
                DocumentPreview(path)

    def test_oversized_file_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "huge.png"
            path.write_bytes(b"x" * 64)
            original = loader.MAX_FILE_BYTES
            loader.MAX_FILE_BYTES = 10
            try:
                with self.assertRaises(PreviewError):
                    DocumentPreview(path)
            finally:
                loader.MAX_FILE_BYTES = original

    def test_page_number_out_of_range(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scan.png"
            Image.new("RGB", (10, 10)).save(path)
            with DocumentPreview(path) as preview:
                with self.assertRaises(PreviewError):
                    preview.render(7)


class PreviewPaneTests(unittest.TestCase):
    """The widget that shows the page to the user."""

    def setUp(self) -> None:
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        self.app = QApplication.instance() or QApplication([])

    def test_pane_shows_a_page(self) -> None:
        from PIL import Image

        from hebrew_workbench.ui.preview_pane import PreviewPane

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scan.png"
            Image.new("RGB", (40, 30), (10, 10, 10)).save(path)
            pane = PreviewPane()
            pane.set_document(str(path))
            self.assertIn("1 / 1", pane.page_label.text())
            self.assertTrue(pane.scene.items())
            pane.close_document()

    def test_pane_reports_a_broken_document(self) -> None:
        from hebrew_workbench.ui.preview_pane import PreviewPane

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "broken.pdf"
            path.write_bytes(b"not a pdf")
            pane = PreviewPane()
            pane.set_document(str(path))
            self.assertFalse(pane.scene.items())
            self.assertIn("PDF", pane.status.text())
            pane.close_document()


if __name__ == "__main__":
    unittest.main()
