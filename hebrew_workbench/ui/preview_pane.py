"""The preview pane: shows the scanned page next to the transcription."""

from __future__ import annotations

import io
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..engine.photocraft_audit import (
    prepare_page_for_ocr,
    resolve_page_enhancement_enabled,
)
from ..preview.loader import DocumentPreview, PreviewError

__all__ = ["PreviewPane", "pil_to_qimage", "VIEW_MODES"]

BASE_RENDER_WIDTH = 1600
MINIMUM_ZOOM = 0.02
MAXIMUM_ZOOM = 8.0
VIEW_MODES = ("original", "processed", "compare")


def pil_to_qimage(image) -> QImage:
    """Convert a Pillow image into a standalone :class:`QImage`."""
    rgb = image.convert("RGB")
    data = rgb.tobytes("raw", "RGB")
    qimage = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format_RGB888)
    return qimage.copy()


class PreviewPane(QWidget):
    """Shows one document, one page at a time, completely offline."""

    view_mode_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._preview: DocumentPreview | None = None
        self._page = 1
        self._zoom = 1.0
        self._rotation = 0
        self._view_mode = "original"
        self._page_enhancement_enabled = True
        # Optional OCR-produced per-page cache: page_num -> (png_bytes|None, enhanced, enh_enabled)
        self._ocr_processed_pages: dict[int, tuple[bytes | None, bool, bool]] = {}
        # On-demand preview cache invalidated when document or enhancement setting changes
        self._live_processed_cache: dict[tuple[int, bool], tuple[Image.Image, bool, str]] = {}

        self.view = QGraphicsView(self)
        self.view.setRenderHints(self.view.renderHints())
        self.scene = QGraphicsScene(self)
        self.view.setScene(self.scene)
        self.view.setBackgroundBrush(Qt.darkGray)
        self.view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.view.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.status = QLabel("לא נבחר מסמך לתצוגה")
        self.status.setAlignment(Qt.AlignCenter)

        self._build_toolbar()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(self._toolbar)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.status)

    # -- toolbar -----------------------------------------------------------
    def _build_toolbar(self) -> None:
        self._toolbar = QHBoxLayout()
        self._toolbar.setSpacing(4)

        self.first_button = QPushButton("הראשון")
        self.first_button.setToolTip("מעבר לעמוד הראשון")
        self.first_button.clicked.connect(lambda: self.go_to_page(1))

        self.previous_button = QPushButton("הקודם")
        self.previous_button.setToolTip("מעבר לעמוד הקודם")
        self.previous_button.clicked.connect(lambda: self.go_to_page(self._page - 1))

        self.next_button = QPushButton("הבא")
        self.next_button.setToolTip("מעבר לעמוד הבא")
        self.next_button.clicked.connect(lambda: self.go_to_page(self._page + 1))

        self.last_button = QPushButton("אחרון")
        self.last_button.setToolTip("מעבר לעמוד האחרון")
        self.last_button.clicked.connect(lambda: self.go_to_page(self._page_count()))

        self.zoom_out_button = QPushButton("−")
        self.zoom_out_button.setToolTip("הקטנה")
        self.zoom_out_button.clicked.connect(lambda: self.set_zoom(self._zoom / 1.25))

        self.zoom_in_button = QPushButton("+")
        self.zoom_in_button.setToolTip("הגדלה")
        self.zoom_in_button.clicked.connect(lambda: self.set_zoom(self._zoom * 1.25))

        self.fit_button = QPushButton("התאמה")
        self.fit_button.setToolTip("התאמת העמוד לחלון")
        self.fit_button.clicked.connect(self.fit_to_window)

        self.actual_size_button = QPushButton("100%")
        self.actual_size_button.setToolTip("גודל אמיתי")
        self.actual_size_button.clicked.connect(lambda: self.set_zoom(1.0))

        self.rotate_left_button = QPushButton("סיבוב שמאלה")
        self.rotate_left_button.setToolTip("סיבוב העמוד לשמאל")
        self.rotate_left_button.clicked.connect(lambda: self.rotate(-90))

        self.rotate_right_button = QPushButton("סיבוב ימינה")
        self.rotate_right_button.setToolTip("סיבוב העמוד לימין")
        self.rotate_right_button.clicked.connect(lambda: self.rotate(90))

        self.page_label = QLabel("—")
        self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.setMinimumWidth(90)

        self.view_mode_box = QComboBox()
        self.view_mode_box.setToolTip(
            "מעבר בין התמונה המקורית, התמונה לאחר עיבוד מקדים, והשוואה זה לצד זה"
        )
        self.view_mode_box.addItem("תצוגה: מקור", "original")
        self.view_mode_box.addItem("תצוגה: לאחר עיבוד", "processed")
        self.view_mode_box.addItem("תצוגה: השוואה (מקור | מעובד)", "compare")
        self.view_mode_box.currentIndexChanged.connect(
            self._on_view_mode_combo_changed
        )

        for widget in (
            self.first_button,
            self.previous_button,
            self.next_button,
            self.last_button,
        ):
            self._toolbar.addWidget(widget)
        self._toolbar.addStretch(1)
        self._toolbar.addWidget(self.view_mode_box)
        for widget in (
            self.zoom_out_button,
            self.zoom_in_button,
            self.fit_button,
            self.actual_size_button,
            self.rotate_left_button,
            self.rotate_right_button,
            self.page_label,
        ):
            self._toolbar.addWidget(widget)

    # -- document handling -------------------------------------------------
    def set_document(self, path: str | None) -> None:
        """Show a different document (or clear the pane with ``None``)."""
        self.close_document()
        if not path:
            self._show_message("לא נבחר מסמך לתצוגה")
            return
        try:
            self._preview = DocumentPreview(path)
        except PreviewError as exc:
            self._show_message(str(exc))
            return
        self._page = 1
        self._rotation = 0
        self._render_page()

    def close_document(self) -> None:
        self._ocr_processed_pages = {}
        self._live_processed_cache = {}
        if self._preview is not None:
            self._preview.close()
            self._preview = None

    @property
    def view_mode(self) -> str:
        return self._view_mode

    def set_view_mode(self, mode: str) -> None:
        """Select ``'original'``, ``'processed'``, or ``'compare'``."""
        if mode not in VIEW_MODES:
            raise ValueError(f"Unknown preview view mode: {mode!r}")
        if mode == self._view_mode:
            return
        self._view_mode = mode
        idx = self.view_mode_box.findData(mode)
        if idx >= 0 and self.view_mode_box.currentIndex() != idx:
            self.view_mode_box.blockSignals(True)
            self.view_mode_box.setCurrentIndex(idx)
            self.view_mode_box.blockSignals(False)
        if self._preview is not None:
            self._render_page()
        self.view_mode_changed.emit(self._view_mode)

    def _on_view_mode_combo_changed(self, _index: int) -> None:
        chosen = str(self.view_mode_box.currentData() or "original")
        if chosen in VIEW_MODES and chosen != self._view_mode:
            self._view_mode = chosen
            if self._preview is not None:
                self._render_page()
            self.view_mode_changed.emit(self._view_mode)

    def set_page_enhancement_enabled(self, enabled: bool) -> None:
        """Inform the preview pane whether automatic page enhancement is active."""
        new_val = bool(enabled)
        if new_val != self._page_enhancement_enabled:
            self._page_enhancement_enabled = new_val
            if self._preview is not None and self._view_mode != "original":
                self._render_page()

    def set_processed_pages(
        self,
        pages_map: dict[int, tuple[bytes | None, bool, bool]] | None,
    ) -> None:
        """Supply OCR-produced processed page snapshots for exact visual comparison."""
        self._ocr_processed_pages = dict(pages_map or {})
        if self._preview is not None and self._view_mode != "original":
            self._render_page()

    def _resolve_processed_image(
        self, orig_image: Image.Image
    ) -> tuple[Image.Image, bool, str]:
        """Return ``(processed_pil, was_enhanced, detail_note)`` for ``self._page``."""
        eff_on = resolve_page_enhancement_enabled(self._page_enhancement_enabled)
        ocr_entry = self._ocr_processed_pages.get(self._page)
        if ocr_entry is not None:
            png_bytes, was_enh, ocr_eff_on = ocr_entry
            if ocr_eff_on == eff_on:
                if was_enh and png_bytes:
                    try:
                        im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
                        im.load()
                        return im, True, "בוצע שיפור סלקטיבי ב-OCR"
                    except Exception:
                        pass
                if not eff_on:
                    return orig_image, False, "שיפור דף אוטומטי: כבוי (ללא שינוי)"
                return orig_image, False, "הדף נקי — נשמר ללא שינוי פיקסלים"

        if not eff_on:
            return orig_image, False, "שיפור דף אוטומטי: כבוי (ללא שינוי)"

        cache_key = (self._page, eff_on)
        cached = self._live_processed_cache.get(cache_key)
        if cached is not None:
            return cached

        # 1. Fast in-process evaluation when worker vision packages are present
        try:
            prepared, audit = prepare_page_for_ocr(orig_image, enabled=True)
            if audit is not None:
                was_enh = bool(audit.needs_adjustment)
                note = (
                    "בוצע שיפור סלקטיבי"
                    if was_enh
                    else "הדף נקי — נשמר ללא שינוי פיקסלים"
                )
                res = (prepared.convert("RGB"), was_enh, note)
                self._live_processed_cache[cache_key] = res
                return res
        except Exception:
            pass

        # 2. Packaged Windows fallback via ocr-worker.exe when cv2 lives in worker
        from ..engine.worker import worker_path

        w_exe = worker_path()
        if w_exe is not None and w_exe.is_file():
            try:
                with tempfile.TemporaryDirectory(prefix="ocr-prev-") as td:
                    in_png = Path(td) / "in.png"
                    out_png = Path(td) / "out.png"
                    orig_image.convert("RGB").save(in_png, format="PNG")
                    proc = subprocess.run(
                        [
                            str(w_exe),
                            "--enhance-preview",
                            str(in_png),
                            "--output-preview",
                            str(out_png),
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=25,
                        check=False,
                    )
                    if proc.returncode == 0 and out_png.is_file():
                        im = Image.open(out_png).convert("RGB")
                        im.load()
                        meta_path = out_png.with_suffix(".json")
                        was_enh = False
                        if meta_path.is_file():
                            meta = json.loads(
                                meta_path.read_text(encoding="utf-8")
                            )
                            was_enh = bool(meta.get("enhanced", False))
                        note = (
                            "בוצע שיפור סלקטיבי"
                            if was_enh
                            else "הדף נקי — נשמר ללא שינוי פיקסלים"
                        )
                        res = (im, was_enh, note)
                        self._live_processed_cache[cache_key] = res
                        return res
            except Exception:
                pass

        return (
            orig_image,
            False,
            "תצוגת העיבוד המקדים תהיה זמינה לאחר התקנת רכיב הזיהוי",
        )

    @staticmethod
    def _compose_side_by_side(
        original: QPixmap, processed: QPixmap, gap: int = 16
    ) -> QPixmap:
        """Compose RTL side-by-side comparison: Right = Original, Left = Processed."""
        target_h = max(original.height(), processed.height(), 1)
        if original.height() != target_h and original.height() > 0:
            original = original.scaledToHeight(
                target_h, Qt.SmoothTransformation
            )
        if processed.height() != target_h and processed.height() > 0:
            processed = processed.scaledToHeight(
                target_h, Qt.SmoothTransformation
            )
        total_w = original.width() + gap + processed.width()
        canvas = QPixmap(max(1, total_w), target_h)
        canvas.fill(QColor(68, 68, 68))
        painter = QPainter(canvas)
        try:
            # Left half: Processed; Right half: Original (natural RTL reading order)
            painter.drawPixmap(0, 0, processed)
            painter.drawPixmap(processed.width() + gap, 0, original)
        finally:
            painter.end()
        return canvas

    def _page_count(self) -> int:
        return self._preview.page_count if self._preview else 0

    def _show_message(self, message: str) -> None:
        self.scene.clear()
        self.status.setText(message)

    # -- rendering ---------------------------------------------------------
    def go_to_page(self, number: int) -> None:
        if not self._preview:
            return
        number = max(1, min(number, self._preview.page_count))
        if number == self._page and self.scene.items():
            return
        self._page = number
        self._rotation = 0
        self._render_page()

    def set_zoom(self, factor: float) -> None:
        # The smallest zoom is small enough for a page that was fitted to
        # a small window, so that zooming out always makes the page
        # smaller.  A long page that was fitted to the window can be
        # smaller than that, and then the zoom may go further down, so
        # that zooming out does not make the page bigger.
        lowest = MINIMUM_ZOOM
        if self._zoom < MINIMUM_ZOOM:
            lowest = self._zoom
        self._zoom = max(lowest, min(MAXIMUM_ZOOM, factor))
        self._apply_zoom()

    def _apply_zoom(self) -> None:
        self.view.resetTransform()
        if self._zoom != 1.0:
            self.view.scale(self._zoom, self._zoom)
        self.view.centerOn(self.scene.itemsBoundingRect().center())

    def fit_to_window(self) -> None:
        self._zoom = 1.0
        self.view.resetTransform()
        self.view.fitInView(
            self.scene.itemsBoundingRect(), Qt.KeepAspectRatio
        )
        # The buttons of the zoom continue from the size that is shown
        # now, and not from the size of the original page.
        self._zoom = self._view_scale()

    def _view_scale(self) -> float:
        """The scale of the picture that is in the window."""
        transform = self.view.transform()
        horizontal = abs(transform.m11())
        vertical = abs(transform.m22())
        if horizontal <= 0 or vertical <= 0:
            return 1.0
        return (horizontal + vertical) / 2.0

    def rotate(self, degrees: int) -> None:
        self._rotation = (self._rotation + degrees) % 360
        self._render_page()

    def _render_page(self) -> None:
        if not self._preview:
            return
        try:
            page = self._preview.render(self._page, target_width=BASE_RENDER_WIDTH)
        except PreviewError as exc:
            self._show_message(str(exc))
            return
        orig_pixmap = QPixmap.fromImage(pil_to_qimage(page.image))
        if self._rotation:
            orig_pixmap = orig_pixmap.transformed(
                QTransform().rotate(self._rotation)
            )

        base_status = (
            f"עמוד {self._page} מתוך {self._preview.page_count} — {self._preview.path.name}"
        )
        if self._view_mode == "original":
            pixmap = orig_pixmap
            status_text = base_status
        else:
            proc_im, _was_enh, note = self._resolve_processed_image(page.image)
            proc_pixmap = QPixmap.fromImage(pil_to_qimage(proc_im))
            if self._rotation:
                proc_pixmap = proc_pixmap.transformed(
                    QTransform().rotate(self._rotation)
                )
            if self._view_mode == "processed":
                pixmap = proc_pixmap
                status_text = f"{base_status} | לאחר עיבוד ({note})"
            else:
                pixmap = self._compose_side_by_side(orig_pixmap, proc_pixmap)
                status_text = (
                    f"{base_status} | השוואה: מימין מקור, משמאל לאחר עיבוד ({note})"
                )

        self.scene.clear()
        self.scene.addPixmap(pixmap)
        self.scene.setSceneRect(self.scene.itemsBoundingRect())
        self._apply_zoom()
        self.status.setText(status_text)
        self.page_label.setText(f"{self._page} / {self._preview.page_count}")
        self._update_buttons()

    def _update_buttons(self) -> None:
        count = self._page_count()
        self.first_button.setEnabled(count > 1)
        self.previous_button.setEnabled(count > 1 and self._page > 1)
        self.next_button.setEnabled(count > 1 and self._page < count)
        self.last_button.setEnabled(count > 1)
