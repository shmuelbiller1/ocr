"""Side-by-side diplomatic handwriting verification & school learning dialog.

Implements the two-stage school handwriting workflow:
1. **Stage 1 (this dialog — before grammar/style editing)**:
   Shows the scanned page side-by-side with each cropped handwritten line and
   its OCR reading. The user fixes ONLY OCR misreads so each line matches what
   was physically written in ink on the page (keeping the student's own
   wording, abbreviations, and spelling), explicitly ticks verified lines,
   confirms no grammar edits were made yet, and saves & trains the student's
   personal handwriting profile + the shared 50-student school corpus.
2. **Stage 2 (main editor — after Stage 1 saves)**:
   The verified diplomatic transcription is transferred to the main editor so
   the user never retypes fixes, and spelling/grammar/style suggestions can
   then be applied safely without polluting handwriting training data.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..engine.writer_adaptation import AdaptationReport, run_writer_training
from ..preview.loader import DocumentPreview, PreviewError
from ..project import DocumentEntry
from ..training.store import (
    SchoolLearningStore,
    VerifiedLineInput,
    WriterProfile,
    crop_line_from_page,
)
from .tasks import TaskThread

OCR_RENDER_DPI = 300


def _pil_to_qpixmap(image: Image.Image) -> QPixmap:
    rgb = image.convert("RGB")
    raw = rgb.tobytes("raw", "RGB")
    qimg = QImage(raw, rgb.width, rgb.height, rgb.width * 3, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


class _PageHighlightView(QLabel):
    """Displays a full page pixmap with an active line's bounding box highlighted."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._base_pixmap: QPixmap | None = None
        self._page_size_px: tuple[int, int] = (1, 1)
        self._highlight_box: tuple[float, float, float, float] | None = None
        self._display_scale: float = 1.0
        self.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

    def set_page_image(
        self, image: Image.Image, target_width: int = 520
    ) -> None:
        self._page_size_px = image.size
        src_pm = _pil_to_qpixmap(image)
        if src_pm.width() > 0:
            scaled = src_pm.scaledToWidth(
                max(260, target_width), Qt.SmoothTransformation
            )
            self._display_scale = scaled.width() / float(src_pm.width())
            self._base_pixmap = scaled
        else:
            self._display_scale = 1.0
            self._base_pixmap = src_pm
        self._redraw()

    def set_highlight_box(
        self, box: tuple[float, float, float, float] | None
    ) -> QRectF | None:
        self._highlight_box = box
        return self._redraw()

    def _redraw(self) -> QRectF | None:
        if self._base_pixmap is None or self._base_pixmap.isNull():
            self.clear()
            return None
        canvas = self._base_pixmap.copy()
        scaled_rect: QRectF | None = None
        if self._highlight_box is not None:
            x, y, w, h = self._highlight_box
            s = self._display_scale
            scaled_rect = QRectF(
                max(0.0, x * s - 4.0),
                max(0.0, y * s - 4.0),
                max(8.0, w * s + 8.0),
                max(8.0, h * s + 8.0),
            )
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.fillRect(scaled_rect, QColor(255, 210, 60, 65))
            pen = QPen(QColor(210, 115, 0), 2.5)
            painter.setPen(pen)
            painter.drawRoundedRect(scaled_rect, 4.0, 4.0)
            painter.end()
        self.setPixmap(canvas)
        return scaled_rect


class _LineVerificationCard(QFrame):
    """One cropped handwritten line paired with its editable diplomatic text."""

    focused = Signal(int)
    state_changed = Signal()

    def __init__(
        self,
        *,
        page_number: int,
        line_index: int,
        crop_image: Image.Image,
        initial_text: str,
        ocr_text: str,
        confidence: float | None,
        box: tuple[float, float, float, float] | None,
        already_verified: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.page_number = page_number
        self.line_index = line_index
        self.crop_image = crop_image
        self.ocr_text = ocr_text
        self.confidence = confidence
        self.box = box
        self.setFrameShape(QFrame.StyledPanel)
        self.setLayoutDirection(Qt.RightToLeft)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # Header row: line index + confidence + verified / skip toggles
        header = QHBoxLayout()
        title = QLabel(f"<b>שורה {line_index + 1}</b>")
        header.addWidget(title)

        if confidence is not None:
            pct = int(round(float(confidence) * 100))
            conf_lbl = QLabel(
                f"ביטחון OCR: {pct}%"
                + (" (נמוך — לבדוק היטב)" if confidence < 0.85 else "")
            )
            if confidence < 0.85:
                conf_lbl.setStyleSheet(
                    "color: #9a4d00; font-weight: bold; background: #fff3cd; "
                    "padding: 1px 6px; border-radius: 3px;"
                )
            else:
                conf_lbl.setStyleSheet("color: #2f6b2f;")
            header.addWidget(conf_lbl)

        header.addStretch(1)

        self.verified_check = QCheckBox("✓ אומת כפי שנכתב")
        self.verified_check.setToolTip(
            "סמנו רק לאחר שבדקתם שהטקסט בשורה זו זהה בדיוק למה שכתוב בכתב היד (לפני עריכת דקדוק)."
        )
        self.verified_check.setChecked(bool(already_verified))

        self.skip_check = QCheckBox("דלג (מחוק / לא קריא)")
        self.skip_check.setToolTip("שורה מחוקה או שרבוט שאין ללמוד ממנו.")

        header.addWidget(self.verified_check)
        header.addWidget(self.skip_check)
        layout.addLayout(header)

        # Cropped handwritten line image
        self.crop_label = QLabel()
        self.crop_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        pm = _pil_to_qpixmap(crop_image)
        if pm.height() > 62:
            pm = pm.scaledToHeight(62, Qt.SmoothTransformation)
        elif pm.height() < 34 and pm.height() > 0:
            pm = pm.scaledToHeight(42, Qt.SmoothTransformation)
        if pm.width() > 640:
            pm = pm.scaledToWidth(640, Qt.SmoothTransformation)
        self.crop_label.setPixmap(pm)
        self.crop_label.setStyleSheet(
            "background: #fafafa; border: 1px solid #ddd; padding: 3px;"
        )
        layout.addWidget(self.crop_label)

        # Editable diplomatic text field
        self.text_edit = QLineEdit(initial_text)
        self.text_edit.setLayoutDirection(Qt.RightToLeft)
        self.text_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        font = QFont()
        font.setPointSize(13)
        self.text_edit.setFont(font)
        self.text_edit.setPlaceholderText("הקלידו בדיוק מה שכתוב בשורה זו בדף...")
        self.text_edit.installEventFilter(self)
        layout.addWidget(self.text_edit)

        self.text_edit.textEdited.connect(self._on_user_edited_text)
        self.verified_check.toggled.connect(self._on_verified_toggled)
        self.skip_check.toggled.connect(self._on_skip_toggled)
        self._refresh_card_style()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self.text_edit and event.type() == QEvent.FocusIn:
            self.focused.emit(self.line_index)
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.focused.emit(self.line_index)
        super().mousePressEvent(event)

    def _on_user_edited_text(self, _text: str) -> None:
        self.focused.emit(self.line_index)
        if not self.skip_check.isChecked() and self.text_edit.text().strip():
            self.verified_check.setChecked(True)
        self.state_changed.emit()

    def _on_verified_toggled(self, checked: bool) -> None:
        if checked and self.skip_check.isChecked():
            self.skip_check.setChecked(False)
        self._refresh_card_style()
        self.state_changed.emit()

    def _on_skip_toggled(self, skipped: bool) -> None:
        if skipped and self.verified_check.isChecked():
            self.verified_check.setChecked(False)
        self.text_edit.setEnabled(not skipped)
        self._refresh_card_style()
        self.state_changed.emit()

    def _refresh_card_style(self) -> None:
        if self.skip_check.isChecked():
            self.setStyleSheet(
                "QFrame { background: #f3f3f3; border: 1px dashed #bbb; border-radius: 5px; }"
            )
        elif self.verified_check.isChecked():
            self.setStyleSheet(
                "QFrame { background: #f2fbf4; border: 1px solid #6ab07a; border-radius: 5px; }"
            )
        else:
            self.setStyleSheet(
                "QFrame { background: #ffffff; border: 1px solid #d4d4d4; border-radius: 5px; }"
            )

    @property
    def is_verified_for_training(self) -> bool:
        return (
            self.verified_check.isChecked()
            and not self.skip_check.isChecked()
            and bool(self.text_edit.text().strip())
        )

    @property
    def diplomatic_text(self) -> str:
        return self.text_edit.text().strip()


class DiplomaticVerificationDialog(QDialog):
    """Side-by-side Stage-1 handwriting verification & student/school trainer."""

    def __init__(
        self,
        entry: DocumentEntry,
        store: SchoolLearningStore,
        *,
        initial_writer_id: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.entry = entry
        self.store = store
        self._train_task: TaskThread | None = None
        self.last_report: AdaptationReport | None = None
        self.saved_samples_count: int = 0
        self.selected_writer_id: str = (
            entry.writer_id or initial_writer_id or ""
        ).strip()
        self.updated_diplomatic_transcription: str | None = None

        self.setWindowTitle(
            f"שלב 1 — אימות כפי שנכתב ואימון כתב-יד ({entry.name})"
        )
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1220, 820)

        self._page_images: dict[int, Image.Image] = {}
        self._cards_by_page: dict[int, list[_LineVerificationCard]] = {}
        self._current_page_idx: int = 0
        self._page_numbers: list[int] = []

        self._build_ui()
        self._load_document_pages_and_lines()
        self._refresh_writer_combo(select_id=self.selected_writer_id)
        self._update_summary_and_buttons()

    # -- UI layout ---------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        # 1. Stage-1 non-grammar guardrail banner
        stage_banner = QFrame()
        stage_banner.setStyleSheet(
            "QFrame { background: #fff8e6; border: 1px solid #e0b84c; border-radius: 6px; }"
        )
        sb_layout = QVBoxLayout(stage_banner)
        sb_layout.setContentsMargins(10, 8, 10, 8)
        sb_title = QLabel(
            "<b>שלב 1 — אמתו בדיוק כפי שנכתב בדף (נא לא לערוך דקדוק, ניסוח או כתיב של הכותב עדיין!)</b>"
        )
        sb_title.setWordWrap(True)
        sb_body = QLabel(
            "השוו כל שורה מצולמת מכתב היד לטקסט שלצדה ותקנו <b>רק</b> שגיאות קריאה של ה-OCR כך שהטקסט יתאים "
            "אות-באות לדיו שבדף (כולל קיצורים או שגיאות כתיב של התלמיד). "
            "<b>אל תתקנו דקדוק או סגנון בשלב זה</b> — לאחר השמירה והלמידה הטקסט המתוקן יועבר לעורך הראשי "
            "ושם תוכלו להפעיל הצעות דקדוק ואיות (שלב 2) מבלי להקליד פעמיים!"
        )
        sb_body.setWordWrap(True)
        sb_layout.addWidget(sb_title)
        sb_layout.addWidget(sb_body)

        if self.entry.changes:
            grammar_warn = QLabel(
                "<span style='color:#9c2b00;'><b>שימו לב:</b> במסמך זה כבר הוחלו הצעות תיקון בעורך. "
                "כדי לא לזהם את אימון כתב-היד בתיקוני דקדוק, השורות להלן נטענו מהטקסט שלפני עריכת הדקדוק.</span>"
            )
            grammar_warn.setWordWrap(True)
            sb_layout.addWidget(grammar_warn)

        root.addWidget(stage_banner)

        # 2. Student / writer bar + 50-student school pool stats
        writer_bar = QHBoxLayout()
        writer_bar.addWidget(QLabel("<b>תלמיד / כותב:</b>"))
        self.writer_combo = QComboBox()
        self.writer_combo.setMinimumWidth(220)
        self.writer_combo.currentIndexChanged.connect(self._on_writer_changed)
        writer_bar.addWidget(self.writer_combo)

        self.add_writer_btn = QPushButton("+ תלמיד חדש...")
        self.add_writer_btn.clicked.connect(self._prompt_new_writer)
        writer_bar.addWidget(self.add_writer_btn)

        self.rename_writer_btn = QPushButton("שינוי שם...")
        self.rename_writer_btn.clicked.connect(self._prompt_rename_writer)
        writer_bar.addWidget(self.rename_writer_btn)

        writer_bar.addSpacing(12)
        self.school_stats_label = QLabel("")
        self.school_stats_label.setStyleSheet("color: #334;")
        writer_bar.addWidget(self.school_stats_label, 1)

        self.export_school_btn = QPushButton("ייצוא מאגר בית-ספרי (ZIP)...")
        self.export_school_btn.setToolTip(
            "ייצוא כל השורות המאומתות של כלל התלמידים בבית הספר לקובץ ZIP לאימון משותף."
        )
        self.export_school_btn.clicked.connect(self._export_school_zip)
        writer_bar.addWidget(self.export_school_btn)
        root.addLayout(writer_bar)

        # 3. Page selector + bulk actions bar
        page_bar = QHBoxLayout()
        self.prev_page_btn = QPushButton("עמוד קודם")
        self.prev_page_btn.clicked.connect(lambda: self._switch_page(-1))
        self.page_info_label = QLabel("עמוד 1 מתוך 1")
        self.next_page_btn = QPushButton("עמוד הבא")
        self.next_page_btn.clicked.connect(lambda: self._switch_page(1))
        page_bar.addWidget(self.prev_page_btn)
        page_bar.addWidget(self.page_info_label)
        page_bar.addWidget(self.next_page_btn)
        page_bar.addStretch(1)

        self.mark_all_page_btn = QPushButton("סמן את כל השורות בעמוד כאומתו")
        self.mark_all_page_btn.setToolTip(
            "השתמשו בכפתור זה רק לאחר שעברתם ובדקתם שכל השורות בעמוד תואמות לכתב היד."
        )
        self.mark_all_page_btn.clicked.connect(self._mark_all_current_page)
        self.unmark_all_page_btn = QPushButton("נקה סימונים בעמוד")
        self.unmark_all_page_btn.clicked.connect(self._unmark_all_current_page)
        page_bar.addWidget(self.mark_all_page_btn)
        page_bar.addWidget(self.unmark_all_page_btn)
        root.addLayout(page_bar)

        # 4. Main Side-by-Side Splitter: Full Scanned Page <-> Line-by-Line Cards
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Full page context pane
        page_pane = QWidget()
        page_pane_layout = QVBoxLayout(page_pane)
        page_pane_layout.setContentsMargins(0, 0, 0, 0)
        page_pane_layout.addWidget(
            QLabel("<b>דף כתב היד המלא (השורה הפעילה מודגשת):</b>")
        )
        self.page_scroll = QScrollArea()
        self.page_scroll.setWidgetResizable(True)
        self.page_view = _PageHighlightView()
        self.page_scroll.setWidget(self.page_view)
        page_pane_layout.addWidget(self.page_scroll, 1)

        # Line-by-line cards pane
        lines_pane = QWidget()
        lines_pane_layout = QVBoxLayout(lines_pane)
        lines_pane_layout.setContentsMargins(0, 0, 0, 0)
        lines_pane_layout.addWidget(
            QLabel("<b>שורות שזוהו בדף — השוואה ותיקון שורה-מול-שורה:</b>")
        )
        self.lines_scroll = QScrollArea()
        self.lines_scroll.setWidgetResizable(True)
        self.lines_container = QWidget()
        self.lines_layout = QVBoxLayout(self.lines_container)
        self.lines_layout.setContentsMargins(4, 4, 4, 4)
        self.lines_layout.setSpacing(8)
        self.lines_scroll.setWidget(self.lines_container)
        lines_pane_layout.addWidget(self.lines_scroll, 1)

        # In RTL layout, index 0 appears on the RIGHT (handwritten page) and index 1 on the LEFT (editable output)
        splitter.addWidget(page_pane)
        splitter.addWidget(lines_pane)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 7)
        root.addWidget(splitter, 1)

        # 5. Explicit safety confirmation gate & action buttons
        self.confirm_exact_checkbox = QCheckBox(
            'אני מאשר/ת שהשורות המסומנות ב-"אומת כפי שנכתב" נבדקו מול תמונת כתב היד '
            "ותוקנו כפי שנכתבו בדף (ללא עריכת דקדוק או ניסוח)."
        )
        self.confirm_exact_checkbox.setStyleSheet("font-weight: bold;")
        self.confirm_exact_checkbox.toggled.connect(
            self._update_summary_and_buttons
        )
        root.addWidget(self.confirm_exact_checkbox)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        root.addWidget(self.progress_bar)

        footer = QHBoxLayout()
        self.selection_summary_label = QLabel("")
        footer.addWidget(self.selection_summary_label, 1)

        self.cancel_btn = QPushButton("סגירה ללא שמירה")
        self.cancel_btn.clicked.connect(self.reject)
        self.save_and_train_btn = QPushButton("שמור שורות מאומתות ולמד כתב-יד")
        self.save_and_train_btn.setDefault(True)
        self.save_and_train_btn.setStyleSheet(
            "QPushButton:enabled { background: #1e6b3a; color: white; "
            "font-weight: bold; padding: 6px 14px; border-radius: 4px; }"
        )
        self.save_and_train_btn.clicked.connect(self._on_save_and_train_clicked)
        footer.addWidget(self.cancel_btn)
        footer.addWidget(self.save_and_train_btn)
        root.addLayout(footer)

    # -- loading pages & line crops ----------------------------------------
    def _load_document_pages_and_lines(self) -> None:
        if not self.entry.exists or not self.entry.recognized_pages:
            msg = QLabel(
                "למסמך זה עדיין אין נתוני שורות מזוהות.\n"
                "הריצו תחילה 'הרצת OCR' על המסמך ואז פתחו חלון זה לאימות שורה-מול-שורה."
            )
            msg.setWordWrap(True)
            msg.setStyleSheet("padding: 16px; color: #666;")
            self.lines_layout.addWidget(msg)
            self.lines_layout.addStretch(1)
            self.prev_page_btn.setEnabled(False)
            self.next_page_btn.setEnabled(False)
            self.mark_all_page_btn.setEnabled(False)
            self.unmark_all_page_btn.setEnabled(False)
            return

        # Choose safest baseline text per line before any Stage-2 grammar edits:
        # 1) previously verified samples in store for this writer+doc, else
        # 2) diplomatic_transcription if line counts match, else
        # 3) transcription (only when no grammar changes were applied and line count matches), else
        # 4) original OCR line text.
        total_box_lines = sum(
            len(p.get("lines", [])) for p in self.entry.recognized_pages
        )
        override_lines: list[str] | None = None
        if self.entry.diplomatic_transcription.strip():
            cand = [
                ln
                for ln in self.entry.diplomatic_transcription.splitlines()
                if ln.strip()
            ]
            if len(cand) == total_box_lines:
                override_lines = cand
        elif not self.entry.changes and self.entry.transcription.strip():
            cand = [
                ln for ln in self.entry.transcription.splitlines() if ln.strip()
            ]
            if len(cand) == total_box_lines:
                override_lines = cand

        saved_by_page_line: dict[tuple[int, int], str] = {}
        if self.selected_writer_id and self.store.get_writer(
            self.selected_writer_id
        ):
            doc_name = self.entry.name
            for smp in self.store.list_writer_samples(self.selected_writer_id):
                if smp.document_name == doc_name:
                    saved_by_page_line[(smp.page_number, smp.line_index)] = (
                        smp.diplomatic_text
                    )

        flat_cursor = 0
        try:
            with DocumentPreview(self.entry.file_path) as preview:
                for page_dict in self.entry.recognized_pages:
                    pnum = int(page_dict.get("number", 1))
                    if pnum < 1 or pnum > preview.page_count:
                        continue
                    rendered = preview.render(pnum, dpi=OCR_RENDER_DPI).image
                    self._page_images[pnum] = rendered
                    cards: list[_LineVerificationCard] = []
                    for l_idx, line_info in enumerate(page_dict.get("lines", [])):
                        ocr_txt = str(line_info.get("text", "") or "").strip()
                        conf = line_info.get("confidence")
                        raw_box = line_info.get("box")
                        box = (
                            tuple(float(v) for v in raw_box[:4])
                            if isinstance(raw_box, (list, tuple))
                            and len(raw_box) == 4
                            else None
                        )
                        if box is not None:
                            crop_im = crop_line_from_page(rendered, box)
                        else:
                            # Fallback strip if engine produced no bounding box
                            pw, ph = rendered.size
                            n_lines = max(1, len(page_dict.get("lines", [])))
                            y0 = int(ph * l_idx / n_lines)
                            y1 = max(y0 + 16, int(ph * (l_idx + 1) / n_lines))
                            crop_im = rendered.crop((0, y0, pw, min(ph, y1)))

                        already = (pnum, l_idx) in saved_by_page_line
                        if already:
                            init_txt = saved_by_page_line[(pnum, l_idx)]
                        elif override_lines is not None and flat_cursor < len(
                            override_lines
                        ):
                            init_txt = override_lines[flat_cursor]
                        else:
                            init_txt = ocr_txt
                        flat_cursor += 1

                        card = _LineVerificationCard(
                            page_number=pnum,
                            line_index=l_idx,
                            crop_image=crop_im,
                            initial_text=init_txt,
                            ocr_text=ocr_txt,
                            confidence=(
                                float(conf) if conf is not None else None
                            ),
                            box=box,
                            already_verified=already,
                        )
                        card.focused.connect(self._on_line_card_focused)
                        card.state_changed.connect(
                            self._update_summary_and_buttons
                        )
                        card.setVisible(False)
                        self.lines_layout.addWidget(card)
                        cards.append(card)
                    self._cards_by_page[pnum] = cards
                    self._page_numbers.append(pnum)
        except PreviewError as exc:
            err = QLabel(f"לא ניתן לטעון את תמונת המסמך: {exc}")
            err.setStyleSheet("color: #a00; padding: 12px;")
            self.lines_layout.addWidget(err)

        self.lines_layout.addStretch(1)
        if self._page_numbers:
            self._show_page_at_index(0)

    def _show_page_at_index(self, idx: int) -> None:
        if not self._page_numbers:
            return
        idx = max(0, min(len(self._page_numbers) - 1, idx))
        self._current_page_idx = idx
        active_pnum = self._page_numbers[idx]
        for pnum, cards in self._cards_by_page.items():
            vis = pnum == active_pnum
            for card in cards:
                card.setVisible(vis)
        page_im = self._page_images.get(active_pnum)
        if page_im is not None:
            self.page_view.set_page_image(page_im)
            first_cards = self._cards_by_page.get(active_pnum, [])
            if first_cards:
                self.page_view.set_highlight_box(first_cards[0].box)
        self.page_info_label.setText(
            f"עמוד {active_pnum} ({idx + 1} מתוך {len(self._page_numbers)})"
        )
        self.prev_page_btn.setEnabled(idx > 0)
        self.next_page_btn.setEnabled(idx < len(self._page_numbers) - 1)

    def _switch_page(self, delta: int) -> None:
        self._show_page_at_index(self._current_page_idx + delta)

    def _on_line_card_focused(self, line_index: int) -> None:
        if not self._page_numbers:
            return
        pnum = self._page_numbers[self._current_page_idx]
        cards = self._cards_by_page.get(pnum, [])
        if 0 <= line_index < len(cards):
            rect = self.page_view.set_highlight_box(cards[line_index].box)
            if rect is not None:
                center = rect.center()
                self.page_scroll.ensureVisible(
                    int(center.x()), int(center.y()), 80, 120
                )

    def _mark_all_current_page(self) -> None:
        if not self._page_numbers:
            return
        pnum = self._page_numbers[self._current_page_idx]
        for card in self._cards_by_page.get(pnum, []):
            if not card.skip_check.isChecked() and card.diplomatic_text:
                card.verified_check.setChecked(True)
        self._update_summary_and_buttons()

    def _unmark_all_current_page(self) -> None:
        if not self._page_numbers:
            return
        pnum = self._page_numbers[self._current_page_idx]
        for card in self._cards_by_page.get(pnum, []):
            card.verified_check.setChecked(False)
        self._update_summary_and_buttons()

    # -- student / writer management ---------------------------------------
    def _refresh_writer_combo(self, select_id: str = "") -> None:
        self.writer_combo.blockSignals(True)
        self.writer_combo.clear()
        self.writer_combo.addItem("— בחרו או הוסיפו תלמיד/כותב —", "")
        writers = self.store.list_writers()
        selected_idx = 0
        for idx, prof in enumerate(writers, start=1):
            badge = (
                f"{prof.name} ({prof.samples_count} שורות"
                + (f", סיבוב #{prof.active_round}" if prof.active_round else "")
                + ")"
            )
            self.writer_combo.addItem(badge, prof.writer_id)
            if prof.writer_id == select_id:
                selected_idx = idx
        self.writer_combo.setCurrentIndex(selected_idx)
        self.writer_combo.blockSignals(False)
        self.selected_writer_id = str(self.writer_combo.currentData() or "")
        self.rename_writer_btn.setEnabled(bool(self.selected_writer_id))
        self._refresh_school_stats_label()

    def _on_writer_changed(self, _idx: int) -> None:
        self.selected_writer_id = str(self.writer_combo.currentData() or "")
        self.rename_writer_btn.setEnabled(bool(self.selected_writer_id))
        self._refresh_school_stats_label()
        self._update_summary_and_buttons()

    def _prompt_new_writer(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            "הוספת תלמיד / כותב חדש",
            "שם התלמיד או הכותב (למשל: יוסף כהן / שיעור א׳ — דוד):",
        )
        if not ok or not name.strip():
            return
        try:
            prof = self.store.create_writer(name.strip())
        except ValueError as exc:
            QMessageBox.warning(self, "הוספת תלמיד", str(exc))
            return
        self._refresh_writer_combo(select_id=prof.writer_id)
        self._update_summary_and_buttons()

    def _prompt_rename_writer(self) -> None:
        if not self.selected_writer_id:
            return
        prof = self.store.get_writer(self.selected_writer_id)
        if prof is None:
            return
        name, ok = QInputDialog.getText(
            self,
            "שינוי שם תלמיד",
            "שם מעודכן:",
            text=prof.name,
        )
        if not ok or not name.strip():
            return
        try:
            updated = self.store.rename_writer(prof.writer_id, name.strip())
        except (ValueError, KeyError) as exc:
            QMessageBox.warning(self, "שינוי שם", str(exc))
            return
        self._refresh_writer_combo(select_id=updated.writer_id)

    def _refresh_school_stats_label(self) -> None:
        summary = self.store.school_summary()
        prof: WriterProfile | None = (
            self.store.get_writer(self.selected_writer_id)
            if self.selected_writer_id
            else None
        )
        personal_part = (
            f"תלמיד נבחר: {prof.name} ({prof.samples_count} שורות, סיבוב #{prof.active_round})  |  "
            if prof is not None
            else ""
        )
        self.school_stats_label.setText(
            f"{personal_part}מאגר בית-ספרי: {summary['writers_count']} תלמידים · "
            f"{summary['verified_lines_count']} שורות מאומתות · "
            f"{summary['shared_vocab_words']} מילים משותפות"
        )

    def _export_school_zip(self) -> None:
        summary = self.store.school_summary()
        if summary["verified_lines_count"] == 0:
            QMessageBox.information(
                self,
                "ייצוא מאגר בית-ספרי",
                "המאגר הבית-ספרי עדיין ריק. אמתו ושמרו שורות תחילה.",
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "ייצוא מאגר בית-ספרי לאימון (ZIP)",
            "school-handwriting-corpus.zip",
            "ארכיון ZIP (*.zip)",
        )
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != ".zip":
            target = target.with_suffix(".zip")
        try:
            saved = self.store.export_school_dataset_zip(target)
        except OSError as exc:
            QMessageBox.warning(self, "ייצוא מאגר בית-ספרי", str(exc))
            return
        QMessageBox.information(
            self,
            "ייצוא הושלם",
            f"המאגר הבית-ספרי יוצא בהצלחה אל:\n{saved}\n\n"
            f"({summary['writers_count']} תלמידים, {summary['verified_lines_count']} שורות מאומתות).",
        )

    # -- summary, validation & async training ------------------------------
    def _all_cards(self) -> list[_LineVerificationCard]:
        out: list[_LineVerificationCard] = []
        for pnum in self._page_numbers:
            out.extend(self._cards_by_page.get(pnum, []))
        return out

    def verified_cards(self) -> list[_LineVerificationCard]:
        return [c for c in self._all_cards() if c.is_verified_for_training]

    def _update_summary_and_buttons(self) -> None:
        all_cards = self._all_cards()
        verified = self.verified_cards()
        skipped = sum(1 for c in all_cards if c.skip_check.isChecked())
        self.selection_summary_label.setText(
            f"מסומנות לאימון: {len(verified)} מתוך {len(all_cards)} שורות"
            + (f" ({skipped} דולגו)" if skipped else "")
        )
        busy = self._train_task is not None and self._train_task.isRunning()
        can_save = (
            not busy
            and bool(verified)
            and self.confirm_exact_checkbox.isChecked()
        )
        self.save_and_train_btn.setEnabled(can_save)

    def _assemble_diplomatic_transcription(self) -> str:
        lines: list[str] = []
        for card in self._all_cards():
            if card.skip_check.isChecked():
                continue
            txt = card.diplomatic_text
            if txt:
                lines.append(txt)
        return "\n".join(lines)

    def _on_save_and_train_clicked(self) -> None:
        verified = self.verified_cards()
        if not verified:
            QMessageBox.information(
                self,
                "אימות שורות",
                "יש לסמן לפחות שורה אחת ב-'✓ אומת כפי שנכתב'.",
            )
            return
        if not self.confirm_exact_checkbox.isChecked():
            QMessageBox.information(
                self,
                "אישור אימות",
                "יש לאשר בתחתית החלון שהשורות המסומנות נבדקו כפי שנכתבו בדף לפני עריכת דקדוק.",
            )
            return
        if not self.selected_writer_id:
            self._prompt_new_writer()
            if not self.selected_writer_id:
                return

        inputs = [
            VerifiedLineInput(
                crop_image=card.crop_image,
                diplomatic_text=card.diplomatic_text,
                page_number=card.page_number,
                line_index=card.line_index,
                box=card.box,
                ocr_text=card.ocr_text,
                ocr_confidence=card.confidence,
                verified_exact_as_written=True,
                grammar_unedited_confirmed=True,
            )
            for card in verified
        ]
        try:
            saved = self.store.record_verified_lines(
                self.selected_writer_id, self.entry.file_path, inputs
            )
        except Exception as exc:
            QMessageBox.warning(self, "שמירת שורות מאומתות", str(exc))
            return

        self.saved_samples_count = len(saved)
        self.updated_diplomatic_transcription = (
            self._assemble_diplomatic_transcription()
        )
        writer_id = self.selected_writer_id
        store_root = self.store.root

        self.progress_bar.setVisible(True)
        self.save_and_train_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.selection_summary_label.setText(
            f"נשמרו {len(saved)} שורות מאומתות. מעדכן פרופיל כתב-יד אישי ומילון בית-ספרי..."
        )

        def work(_progress, _cancel):
            return run_writer_training(writer_id, store_root=store_root)

        self._train_task = TaskThread(work, self)
        self._train_task.succeeded.connect(self._on_training_succeeded)
        self._train_task.failed.connect(self._on_training_failed)
        self._train_task.finished.connect(self._on_training_finished)
        self._train_task.start()

    def _on_training_succeeded(self, report: AdaptationReport) -> None:
        self.last_report = report
        self._refresh_school_stats_label()
        self.accept()

    def _on_training_failed(self, message: str) -> None:
        QMessageBox.warning(
            self,
            "אימון פרופיל כתב-יד",
            f"השורות המאומתות נשמרו במאגר בהצלחה ({self.saved_samples_count} שורות), "
            f"אך עדכון המודל האישי נתקל בשגיאה:\n{message}",
        )
        self.accept()

    def _on_training_finished(self) -> None:
        self.progress_bar.setVisible(False)
        self.cancel_btn.setEnabled(True)
        self._train_task = None

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._train_task is not None and self._train_task.isRunning():
            self._train_task.cancel()
            if not self._train_task.wait(2500):
                event.ignore()
                return
        super().closeEvent(event)
