"""The preview pane: shows the scanned page next to the transcription."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap, QTransform
from PySide6.QtWidgets import (
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..preview.loader import DocumentPreview, PreviewError

__all__ = ["PreviewPane", "pil_to_qimage"]

BASE_RENDER_WIDTH = 1600
MINIMUM_ZOOM = 0.02
MAXIMUM_ZOOM = 8.0


def pil_to_qimage(image) -> QImage:
    """Convert a Pillow image into a standalone :class:`QImage`."""
    rgb = image.convert("RGB")
    data = rgb.tobytes("raw", "RGB")
    qimage = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format_RGB888)
    return qimage.copy()


class PreviewPane(QWidget):
    """Shows one document, one page at a time, completely offline."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._preview: DocumentPreview | None = None
        self._page = 1
        self._zoom = 1.0
        self._rotation = 0

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
        self.page_label.setMinimumWidth(110)

        for widget in (
            self.first_button,
            self.previous_button,
            self.next_button,
            self.last_button,
        ):
            self._toolbar.addWidget(widget)
        self._toolbar.addStretch(1)
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
        if self._preview is not None:
            self._preview.close()
            self._preview = None

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
        qimage = pil_to_qimage(page.image)
        pixmap = QPixmap.fromImage(qimage)
        if self._rotation:
            pixmap = pixmap.transformed(QTransform().rotate(self._rotation))
        self.scene.clear()
        self.scene.addPixmap(pixmap)
        self.scene.setSceneRect(self.scene.itemsBoundingRect())
        self._apply_zoom()
        self.status.setText(
            f"עמוד {self._page} מתוך {self._preview.page_count} — {self._preview.path.name}"
        )
        self.page_label.setText(f"{self._page} / {self._preview.page_count}")
        self._update_buttons()

    def _update_buttons(self) -> None:
        count = self._page_count()
        self.first_button.setEnabled(count > 1)
        self.previous_button.setEnabled(count > 1 and self._page > 1)
        self.next_button.setEnabled(count > 1 and self._page < count)
        self.last_button.setEnabled(count > 1)
