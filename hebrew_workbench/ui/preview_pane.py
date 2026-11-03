"""The preview pane: shows the scanned page next to the transcription."""

from __future__ import annotations

import io
import json
import subprocess
import tempfile
import threading
import time
from collections import OrderedDict
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QCoreApplication, QEventLoop, Qt, QThread, Signal
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
    encode_preview_png,
    prepare_page_for_ocr,
    resolve_page_enhancement_enabled,
)
from ..preview.loader import DocumentPreview, PreviewError

__all__ = [
    "PreviewPane",
    "pil_to_qimage",
    "VIEW_MODES",
    "MAX_LIVE_PREVIEW_CACHE_ENTRIES",
]

BASE_RENDER_WIDTH = 1600
MINIMUM_ZOOM = 0.02
MAXIMUM_ZOOM = 8.0
VIEW_MODES = ("original", "processed", "compare")
MAX_LIVE_PREVIEW_CACHE_ENTRIES = 4
WORKER_PREVIEW_TIMEOUT_SECONDS = 25.0


def pil_to_qimage(image) -> QImage:
    """Convert a Pillow image into a standalone :class:`QImage`."""
    rgb = image.convert("RGB")
    data = rgb.tobytes("raw", "RGB")
    qimage = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format_RGB888)
    return qimage.copy()


def _compute_live_preview_payload(
    orig_image: Image.Image,
    *,
    cancel_event: threading.Event | None = None,
    proc_holder: dict[str, object] | None = None,
    proc_lock: threading.Lock | None = None,
    worker_timeout: float = WORKER_PREVIEW_TIMEOUT_SECONDS,
) -> tuple[bytes | None, bool, str]:
    """Compute ``(png_bytes_or_none, was_enhanced, detail_note)`` off the GUI thread.

    Clean pages and fallbacks return ``png_bytes=None`` so the caller reuses the
    already-rendered original pixmap without duplicating uncompressed pixels in RAM.
    """
    if cancel_event is not None and cancel_event.is_set():
        return None, False, "העיבוד המקדים בוטל"

    # 1. Fast in-process evaluation when vision packages (numpy/cv2) are present
    try:
        prepared, audit = prepare_page_for_ocr(orig_image, enabled=True)
        if audit is not None:
            was_enh = bool(audit.needs_adjustment)
            if was_enh:
                png_bytes = encode_preview_png(prepared.convert("RGB"))
                return png_bytes, True, "בוצע שיפור סלקטיבי"
            return None, False, "הדף נקי — נשמר ללא שינוי פיקסלים"
    except Exception:
        pass

    if cancel_event is not None and cancel_event.is_set():
        return None, False, "העיבוד המקדים בוטל"

    # 2. Packaged Windows fallback via ocr-worker.exe when cv2 lives in worker
    from ..engine.worker import worker_path

    w_exe = worker_path()
    if w_exe is not None and w_exe.is_file():
        try:
            with tempfile.TemporaryDirectory(prefix="ocr-prev-") as td:
                in_png = Path(td) / "in.png"
                out_png = Path(td) / "out.png"
                orig_image.convert("RGB").save(in_png, format="PNG")
                if cancel_event is not None and cancel_event.is_set():
                    return None, False, "העיבוד המקדים בוטל"
                proc = subprocess.Popen(
                    [
                        str(w_exe),
                        "--enhance-preview",
                        str(in_png),
                        "--output-preview",
                        str(out_png),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if proc_holder is not None and proc_lock is not None:
                    with proc_lock:
                        proc_holder["proc"] = proc
                        if cancel_event is not None and cancel_event.is_set():
                            try:
                                proc.kill()
                            except OSError:
                                pass
                try:
                    proc.communicate(timeout=worker_timeout)
                except subprocess.TimeoutExpired:
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    proc.wait()
                    return (
                        None,
                        False,
                        "חריגה מזמן הקצוב להכנת התצוגה המעובדת — מוצג המקור",
                    )
                finally:
                    if proc_holder is not None and proc_lock is not None:
                        with proc_lock:
                            proc_holder["proc"] = None

                if cancel_event is not None and cancel_event.is_set():
                    return None, False, "העיבוד המקדים בוטל"

                if proc.returncode == 0 and out_png.is_file():
                    meta_path = out_png.with_suffix(".json")
                    was_enh = False
                    if meta_path.is_file():
                        meta = json.loads(meta_path.read_text(encoding="utf-8"))
                        was_enh = bool(meta.get("enhanced", False))
                    if was_enh:
                        png_bytes = out_png.read_bytes()
                        # Validate readable image before caching
                        im = Image.open(io.BytesIO(png_bytes))
                        im.load()
                        return png_bytes, True, "בוצע שיפור סלקטיבי"
                    return None, False, "הדף נקי — נשמר ללא שינוי פיקסלים"
                return (
                    None,
                    False,
                    "לא ניתן להפיק תצוגה מעובדת לעמוד זה — מוצג המקור",
                )
        except Exception:
            return (
                None,
                False,
                "לא ניתן להפיק תצוגה מעובדת לעמוד זה — מוצג המקור",
            )

    return (
        None,
        False,
        "תצוגת העיבוד המקדים תהיה זמינה לאחר התקנת רכיב הזיהוי",
    )


_ACTIVE_PREVIEW_THREADS: set[_PreviewEnhanceThread] = set()


class _PreviewEnhanceThread(QThread):
    """Background worker that resolves processed-page previews off the GUI thread."""

    result_ready = Signal(int, int, bool, object, bool, str)

    def __init__(
        self,
        doc_token: int,
        page_number: int,
        eff_on: bool,
        orig_image: Image.Image,
        worker_timeout: float = WORKER_PREVIEW_TIMEOUT_SECONDS,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.doc_token = doc_token
        self.page_number = page_number
        self.eff_on = eff_on
        self._orig_image = orig_image
        self._worker_timeout = worker_timeout
        self._cancel_event = threading.Event()
        self._proc_lock = threading.Lock()
        self._proc_holder: dict[str, object] = {"proc": None}

    def cancel(self) -> None:
        self._cancel_event.set()
        with self._proc_lock:
            proc = self._proc_holder.get("proc")
            if isinstance(proc, subprocess.Popen):
                try:
                    proc.kill()
                except OSError:
                    pass

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def run(self) -> None:
        png_bytes, was_enh, note = _compute_live_preview_payload(
            self._orig_image,
            cancel_event=self._cancel_event,
            proc_holder=self._proc_holder,
            proc_lock=self._proc_lock,
            worker_timeout=self._worker_timeout,
        )
        if not self._cancel_event.is_set():
            self.result_ready.emit(
                self.doc_token,
                self.page_number,
                self.eff_on,
                png_bytes,
                was_enh,
                note,
            )


class PreviewPane(QWidget):
    """Shows one document, one page at a time, completely offline."""

    view_mode_changed = Signal(str)
    preview_enhancement_finished = Signal(int, bool)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        max_cache_entries: int = MAX_LIVE_PREVIEW_CACHE_ENTRIES,
        worker_timeout: float = WORKER_PREVIEW_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(parent)
        self._preview: DocumentPreview | None = None
        self._doc_token = 0
        self._page = 1
        self._zoom = 1.0
        self._rotation = 0
        self._view_mode = "original"
        self._page_enhancement_enabled = True
        self._max_cache_entries = max(1, int(max_cache_entries))
        self._worker_timeout = float(worker_timeout)
        # Optional OCR-produced per-page cache: page_num -> (png_bytes|None, enhanced, enh_enabled)
        self._ocr_processed_pages: dict[int, tuple[bytes | None, bool, bool]] = {}
        # Bounded LRU on-demand preview cache: (page_num, eff_on) -> (png_bytes|None, was_enh, note)
        self._live_processed_cache: OrderedDict[
            tuple[int, bool], tuple[bytes | None, bool, str]
        ] = OrderedDict()
        self._enhance_thread: _PreviewEnhanceThread | None = None
        self._retired_threads: list[_PreviewEnhanceThread] = []

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
    def set_document(
        self,
        path: str | None,
        *,
        processed_pages: dict[int, tuple[bytes | None, bool, bool]] | None = None,
    ) -> None:
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
        self._ocr_processed_pages = dict(processed_pages or {})
        self._page = 1
        self._rotation = 0
        self._render_page()

    def close_document(self) -> None:
        self._doc_token += 1
        self._cancel_pending_enhancement(wait_ms=250)
        self._ocr_processed_pages = {}
        self._live_processed_cache.clear()
        if self._preview is not None:
            self._preview.close()
            self._preview = None

    def shutdown_threads(self, timeout_ms: int = 3000) -> bool:
        """Cancel and wait for active and retired preview threads before shutdown."""
        deadline = time.monotonic() + max(0.01, timeout_ms / 1000.0)
        self._cancel_pending_enhancement(wait_ms=0)
        for t in list(self._retired_threads):
            t.cancel()
        while True:
            running = [
                t
                for t in list(self._retired_threads)
                if t.isRunning()
            ]
            if self._enhance_thread is not None and self._enhance_thread.isRunning():
                running.append(self._enhance_thread)
            if not running:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            QCoreApplication.processEvents(QEventLoop.AllEvents, 20)
            slice_ms = min(25, max(1, int(remaining * 1000)))
            for t in running:
                if t.isRunning():
                    t.wait(slice_ms)
        for t in list(self._retired_threads):
            if not t.isRunning():
                self._cleanup_retired_thread(t)
        return True

    def closeEvent(self, event) -> None:  # noqa: N802
        self.shutdown_threads(2000)
        super().closeEvent(event)

    @property
    def is_enhancing_preview(self) -> bool:
        return self._enhance_thread is not None and self._enhance_thread.isRunning()

    def wait_for_pending_enhancement(self, timeout_ms: int = 5000) -> bool:
        """Pump Qt events until any active preview-enhancement thread finishes."""
        deadline = time.monotonic() + max(0.01, timeout_ms / 1000.0)
        while True:
            thread = self._enhance_thread
            if thread is None or not thread.isRunning():
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            QCoreApplication.processEvents(QEventLoop.AllEvents, 25)
            thread = self._enhance_thread
            if thread is not None and thread.isRunning():
                thread.wait(min(25, max(1, int(remaining * 1000))))
        QCoreApplication.processEvents(QEventLoop.AllEvents, 25)
        return self._enhance_thread is None or not self._enhance_thread.isRunning()

    def _cancel_pending_enhancement(self, *, wait_ms: int = 0) -> None:
        thread = self._enhance_thread
        if thread is None:
            return
        self._enhance_thread = None
        thread.cancel()
        if thread.isRunning():
            if wait_ms > 0 and thread.wait(wait_ms):
                _ACTIVE_PREVIEW_THREADS.discard(thread)
                thread.deleteLater()
            else:
                self._retired_threads.append(thread)
                thread.finished.connect(
                    lambda t=thread: self._cleanup_retired_thread(t)
                )
        else:
            _ACTIVE_PREVIEW_THREADS.discard(thread)
            thread.deleteLater()

    def _cleanup_retired_thread(self, thread: _PreviewEnhanceThread) -> None:
        if thread in self._retired_threads:
            self._retired_threads.remove(thread)
        _ACTIVE_PREVIEW_THREADS.discard(thread)
        thread.deleteLater()

    def _cache_put(
        self,
        key: tuple[int, bool],
        value: tuple[bytes | None, bool, str],
    ) -> None:
        if key in self._live_processed_cache:
            self._live_processed_cache.move_to_end(key)
        self._live_processed_cache[key] = value
        while len(self._live_processed_cache) > self._max_cache_entries:
            self._live_processed_cache.popitem(last=False)

    def _cache_get(
        self, key: tuple[int, bool]
    ) -> tuple[bytes | None, bool, str] | None:
        val = self._live_processed_cache.get(key)
        if val is not None:
            self._live_processed_cache.move_to_end(key)
        return val

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
        if mode == "original":
            self._cancel_pending_enhancement()
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
            if chosen == "original":
                self._cancel_pending_enhancement()
            if self._preview is not None:
                self._render_page()
            self.view_mode_changed.emit(self._view_mode)

    def set_page_enhancement_enabled(self, enabled: bool) -> None:
        """Inform the preview pane whether automatic page enhancement is active."""
        new_val = bool(enabled)
        if new_val != self._page_enhancement_enabled:
            self._page_enhancement_enabled = new_val
            if not new_val:
                self._cancel_pending_enhancement()
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

    @staticmethod
    def _decode_png_to_pixmap(
        png_bytes: bytes | None, fallback_pixmap: QPixmap, rotation: int
    ) -> QPixmap:
        if not png_bytes:
            return fallback_pixmap
        try:
            im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
            im.load()
            px = QPixmap.fromImage(pil_to_qimage(im))
            if rotation:
                px = px.transformed(QTransform().rotate(rotation))
            return px
        except Exception:
            return fallback_pixmap

    def _resolve_cached_or_schedule(
        self, orig_image: Image.Image, orig_pixmap: QPixmap
    ) -> tuple[QPixmap, str]:
        """Return ``(proc_pixmap, detail_note)`` immediately without blocking the GUI."""
        eff_on = resolve_page_enhancement_enabled(self._page_enhancement_enabled)
        ocr_entry = self._ocr_processed_pages.get(self._page)
        if ocr_entry is not None:
            png_bytes, was_enh, ocr_eff_on = ocr_entry
            if ocr_eff_on == eff_on:
                if was_enh and png_bytes:
                    px = self._decode_png_to_pixmap(
                        png_bytes, orig_pixmap, self._rotation
                    )
                    return px, "בוצע שיפור סלקטיבי ב-OCR"
                if not eff_on:
                    return orig_pixmap, "שיפור דף אוטומטי: כבוי (ללא שינוי)"
                return orig_pixmap, "הדף נקי — נשמר ללא שינוי פיקסלים"

        if not eff_on:
            return orig_pixmap, "שיפור דף אוטומטי: כבוי (ללא שינוי)"

        cache_key = (self._page, eff_on)
        cached = self._cache_get(cache_key)
        if cached is not None:
            png_bytes, was_enh, note = cached
            if was_enh and png_bytes:
                px = self._decode_png_to_pixmap(
                    png_bytes, orig_pixmap, self._rotation
                )
                return px, note
            return orig_pixmap, note

        self._ensure_async_enhancement(self._doc_token, self._page, eff_on, orig_image)
        return orig_pixmap, "מכין תצוגה מעובדת ברקע..."

    def _ensure_async_enhancement(
        self,
        doc_token: int,
        page_number: int,
        eff_on: bool,
        orig_image: Image.Image,
    ) -> None:
        cur = self._enhance_thread
        if (
            cur is not None
            and cur.isRunning()
            and not cur.cancelled
            and cur.doc_token == doc_token
            and cur.page_number == page_number
            and cur.eff_on == eff_on
        ):
            return
        self._cancel_pending_enhancement()
        thread = _PreviewEnhanceThread(
            doc_token=doc_token,
            page_number=page_number,
            eff_on=eff_on,
            orig_image=orig_image.copy(),
            worker_timeout=self._worker_timeout,
            parent=None,
        )
        _ACTIVE_PREVIEW_THREADS.add(thread)
        thread.result_ready.connect(self._on_async_enhancement_ready)
        thread.finished.connect(
            lambda t=thread: self._on_async_thread_finished(t)
        )
        self._enhance_thread = thread
        thread.start()

    def _on_async_thread_finished(self, thread: _PreviewEnhanceThread) -> None:
        _ACTIVE_PREVIEW_THREADS.discard(thread)
        if self._enhance_thread is thread:
            self._enhance_thread = None
            thread.deleteLater()

    def _on_async_enhancement_ready(
        self,
        doc_token: int,
        page_number: int,
        eff_on: bool,
        png_bytes: object,
        was_enh: bool,
        note: str,
    ) -> None:
        if doc_token != self._doc_token or self._preview is None:
            return
        payload_bytes = png_bytes if isinstance(png_bytes, bytes) else None
        self._cache_put((page_number, eff_on), (payload_bytes, bool(was_enh), note))
        if (
            self._page == page_number
            and self._view_mode != "original"
            and resolve_page_enhancement_enabled(self._page_enhancement_enabled)
            == eff_on
        ):
            self._render_page()
        self.preview_enhancement_finished.emit(page_number, bool(was_enh))

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
            proc_pixmap, note = self._resolve_cached_or_schedule(
                page.image, orig_pixmap
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
