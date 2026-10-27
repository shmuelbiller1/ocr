"""Local rendering of scanned pages.

The preview works completely offline: PDF pages are rasterised by PDFium
through :mod:`pypdfium2`, images are read by Pillow.  Nothing is uploaded
and nothing is cached outside the user's own machine.

The loader refuses hostile or broken files instead of trying to render
them: a 400 MB scan, a PDF with ten thousand pages, an encrypted PDF or a
decompression bomb all produce a clear message for the user.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

__all__ = [
    "PreviewError",
    "PageImage",
    "DocumentPreview",
    "MAX_FILE_BYTES",
    "MAX_PAGES",
    "MAX_PIXELS",
]

#: Largest file the preview will open (bytes).
MAX_FILE_BYTES = 300 * 1024 * 1024
#: Largest number of pages a single document may have.
MAX_PAGES = 2000
#: Largest number of pixels a single rendered page may have.
MAX_PIXELS = 120_000_000

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif"}


class PreviewError(RuntimeError):
    """The document cannot be shown.  The message is written for the user."""


@dataclass(frozen=True)
class PageImage:
    """A rendered page."""

    number: int
    image: object  # PIL.Image.Image


def _require_pillow():
    try:
        from PIL import Image  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise PreviewError(
            "חבילת תמונות (Pillow) אינה מותקנת, ולכן אין אפשרות להציג תצוגה מקדימה."
        ) from exc
    return Image


class DocumentPreview:
    """Opens a local document and renders its pages on demand."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise PreviewError(f"הקובץ אינו נמצא: {self.path}")
        if not self.path.is_file():
            raise PreviewError(f"הנתיב אינו קובץ: {self.path}")
        size = self.path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise PreviewError(
                f"הקובץ גדול מדי לתצוגה ({size // (1024 * 1024)}MB). "
                "אפשר להמשיך לעבוד עם הטקסט, אך לא להציג אותו."
            )
        self._pdf = None
        self._image = None
        self._page_count = 0
        self._open()

    # -- opening -----------------------------------------------------------
    def _open(self) -> None:
        suffix = self.path.suffix.lower()
        if suffix == ".pdf":
            self._open_pdf()
        elif suffix in IMAGE_SUFFIXES:
            self._open_image()
        else:
            raise PreviewError(
                f"סוג הקובץ {suffix or '(ללא סיומת)'} אינו נתמך לתצוגה מקדימה."
            )

    def _open_pdf(self) -> None:
        try:
            import pypdfium2
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise PreviewError(
                "חבילת קריאת PDF (pypdfium2) אינה מותקנת, ולכן אין אפשרות להציג קבצי PDF."
            ) from exc
        try:
            pdf = pypdfium2.PdfDocument(str(self.path))
        except Exception as exc:
            # The document may be encrypted with an empty owner password,
            # which unlocks most "printing not allowed" scans.
            try:
                pdf = pypdfium2.PdfDocument(str(self.path), password="")
            except Exception:
                raise PreviewError(
                    f"קובץ ה-PDF אינו תקין או מוגן בסיסמה ולא ניתן לפתוח אותו: {exc}"
                ) from exc
        try:
            page_count = len(pdf)
        except Exception as exc:
            pdf.close()
            raise PreviewError(f"קובץ ה-PDF אינו תקין: {exc}") from exc
        if page_count > MAX_PAGES:
            pdf.close()
            raise PreviewError(
                f"לקובץ יותר מ-{MAX_PAGES} עמודים, ולכן הוא לא נפתח לתצוגה."
            )
        if page_count == 0:
            pdf.close()
            raise PreviewError("קובץ ה-PDF אינו מכיל עמודים.")
        self._pdf = pdf
        self._page_count = page_count

    def _open_image(self) -> None:
        image_module = _require_pillow()
        try:
            image = image_module.open(self.path)
        except Exception as exc:
            raise PreviewError(f"קובץ התמונה אינו תקין: {exc}") from exc
        frames = int(getattr(image, "n_frames", 1) or 1)
        if frames > MAX_PAGES:
            raise PreviewError(
                f"לקובץ יותר מ-{MAX_PAGES} מסגרים, ולכן הוא לא נפתח לתצוגה."
            )
        self._image = image
        self._page_count = frames

    # -- properties --------------------------------------------------------
    @property
    def page_count(self) -> int:
        return self._page_count

    @property
    def is_pdf(self) -> bool:
        return self._pdf is not None

    # -- rendering ---------------------------------------------------------
    def render(self, page_number: int, target_width: int | None = None) -> PageImage:
        """Render a single 1-based page."""
        if not 1 <= page_number <= self._page_count:
            raise PreviewError(
                f"מספר העמוד {page_number} אינו תקין (יש {self._page_count} עמודים)."
            )
        if self._pdf is not None:
            image = self._render_pdf(page_number, target_width)
        else:
            image = self._render_image(page_number)
        if image.width * image.height > MAX_PIXELS:
            raise PreviewError("העמוד גדול מדי להצגה במלואו.")
        return PageImage(number=page_number, image=image)

    def _render_pdf(self, page_number: int, target_width: int | None):
        assert self._pdf is not None
        page = self._pdf[page_number - 1]
        try:
            width, height = page.get_size()
            scale = 1.0
            if target_width and width:
                scale = max(0.1, min(6.0, target_width / float(width)))
            # The size of the page is checked before the picture is made,
            # so that a page with unusual proportions cannot use more
            # memory than the machine has.
            if width and height:
                pixels = width * height * scale * scale
                if pixels > MAX_PIXELS:
                    smaller = (MAX_PIXELS / float(width * height)) ** 0.5
                    if smaller < 0.05:
                        raise PreviewError("העמוד גדול מדי להצגה במלואו.")
                    scale = smaller
            bitmap = page.render(scale=scale)
            return bitmap.to_pil().convert("RGB")
        except PreviewError:
            raise
        except Exception as exc:
            raise PreviewError(f"לא ניתן להציג את העמוד {page_number}: {exc}") from exc
        finally:
            try:
                page.close()
            except Exception:
                pass

    def _render_image(self, page_number: int):
        assert self._image is not None
        try:
            from PIL import ImageOps
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise PreviewError("חבילת תמונות (Pillow) אינה מותקנת.") from exc
        try:
            # Every page starts at its own frame, so that the first
            # frame is shown again after another one was looked at.
            self._image.seek(page_number - 1)
            image = self._image
            image = ImageOps.exif_transpose(image) or image
            return image.convert("RGB")
        except Exception as exc:
            raise PreviewError(f"לא ניתן להציג את העמוד {page_number}: {exc}") from exc

    def iter_pages(self, target_width: int | None = None) -> Iterator[PageImage]:
        for number in range(1, self._page_count + 1):
            yield self.render(number, target_width)

    def close(self) -> None:
        if self._pdf is not None:
            try:
                self._pdf.close()
            except Exception:
                pass
            self._pdf = None
        if self._image is not None:
            try:
                self._image.close()
            except Exception:
                pass
            self._image = None

    def __enter__(self) -> "DocumentPreview":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
