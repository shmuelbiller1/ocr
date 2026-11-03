"""Stage-A side-by-side diplomatic verification, vocabulary admin & adapter rollback UI.

Key guarantees:
1. **Stage A (exact transcription) strictly separated from Stage B (grammar/style)**:
   Users compare the original scanned page and per-line crops against the OCR
   output and record what was physically written on paper before any optional
   spelling/grammar/style suggestions.
2. **Never auto-verifies edited or saved lines**:
   Editing a line or clicking "Save Draft Progress" keeps its status as
   ``not_reviewed`` unless the reviewer explicitly marks it ``verified``
   (via the ``✓ אמת`` button, status selector, or ``Ctrl+Enter`` shortcut).
   Lines marked ``uncertain`` (or containing ``[?]``) are saved locally so work
   is never lost, and are strictly excluded from training.
3. **Bounded memory for 8 GB RAM Windows PCs**:
   Renders only the active page (2-page LRU) instead of loading entire multi-page
   PDFs into RAM at once.
4. **Full local control**:
   Includes student profile creation/renaming/deletion, General/Unknown base-model
   mode, adapter version history with one-click rollback, opt-in administrator
   vocabulary approval, local backup/restore, and privacy-safe (anonymized by
   default) ZIP export for external/online GPU training.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
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
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..engine.writer_adaptation import (
    AdaptationReport,
    import_external_adapter_npz,
    run_writer_training,
)
from ..preview.loader import DocumentPreview, PreviewError
from ..project import DocumentEntry
from ..training.store import (
    STATUS_NOT_REVIEWED,
    STATUS_SKIPPED,
    STATUS_UNCERTAIN,
    STATUS_VERIFIED,
    VOCAB_APPROVED,
    VOCAB_PENDING,
    SchoolLearningStore,
    VerifiedLineInput,
    WriterProfile,
    crop_line_from_page,
)
from .tasks import TaskThread

OCR_RENDER_DPI = 300
MAX_RENDERED_PAGE_CACHE = 2

_STATUS_LABELS: tuple[tuple[str, str], ...] = (
    (STATUS_NOT_REVIEWED, "לא נבדק (טיוטה)"),
    (STATUS_VERIFIED, "✓ אומת כפי שנכתב"),
    (STATUS_UNCERTAIN, "? מסופק (אות לא ברורה)"),
    (STATUS_SKIPPED, "דלג (מחוק / לא קריא)"),
)


def _pil_to_qpixmap(image: Image.Image) -> QPixmap:
    rgb = image.convert("RGB")
    raw = rgb.tobytes("raw", "RGB")
    qimg = QImage(raw, rgb.width, rgb.height, rgb.width * 3, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


def _boxes_match(
    box_a: tuple[float, float, float, float] | None,
    box_b: tuple[float, float, float, float] | None,
    tol: float = 16.0,
) -> bool:
    if box_a is None and box_b is None:
        return True
    if box_a is None or box_b is None:
        return False
    return all(abs(float(a) - float(b)) <= tol for a, b in zip(box_a, box_b))


def _apply_page_skew(image: Image.Image, skew_degrees: float) -> Image.Image:
    """Match ``segment_page``'s deskewed coordinate frame when boxes come from skewed scans."""
    if abs(float(skew_degrees or 0.0)) <= 1e-3:
        return image
    rgb = image.convert("RGB")
    return rgb.rotate(
        float(skew_degrees), resample=Image.BICUBIC, fillcolor=(255, 255, 255)
    )


@dataclass
class _DraftLineState:
    """Lightweight in-memory state per line across all pages (no PIL image retained)."""

    page_number: int
    line_index: int
    ocr_text: str
    diplomatic_text: str
    review_status: str = STATUS_NOT_REVIEWED
    confidence: float | None = None
    box: tuple[float, float, float, float] | None = None
    engine_name: str = ""
    engine_version: str = ""
    model_id: str = ""
    model_sha256: str = ""
    decoding_mode: str = "raw"
    preprocessing: dict = field(default_factory=dict)
    confirmed_verified_writer_id: str | None = None
    confirmed_verified_text: str | None = None
    confirmed_verified_box: tuple[float, float, float, float] | None = None

    @property
    def is_verified_for_training(self) -> bool:
        return (
            self.review_status == STATUS_VERIFIED
            and bool(self.diplomatic_text.strip())
            and "[?]" not in self.diplomatic_text
        )


class _PageHighlightView(QLabel):
    """Displays the active page scan with the selected line's bounding box highlighted."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._base_pixmap: QPixmap | None = None
        self._highlight_box: tuple[float, float, float, float] | None = None
        self._display_scale: float = 1.0
        self.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

    def set_page_image(
        self, image: Image.Image, target_width: int = 520
    ) -> None:
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
            painter.fillRect(scaled_rect, QColor(255, 210, 60, 68))
            pen = QPen(QColor(210, 115, 0), 2.5)
            painter.setPen(pen)
            painter.drawRoundedRect(scaled_rect, 4.0, 4.0)
            painter.end()
        self.setPixmap(canvas)
        return scaled_rect


class _LineVerificationCard(QFrame):
    """Widget for one line on the currently visible page."""

    focused = Signal(int)
    state_changed = Signal()
    verify_and_advance_requested = Signal(int)
    uncertain_and_advance_requested = Signal(int)
    move_line_requested = Signal(int, int)

    def __init__(
        self,
        state: _DraftLineState,
        crop_image: Image.Image,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.state = state
        self.page_number = state.page_number
        self.line_index = state.line_index
        self.box = state.box
        self.setFrameShape(QFrame.StyledPanel)
        self.setLayoutDirection(Qt.RightToLeft)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.addWidget(QLabel(f"<b>שורה {self.line_index + 1}</b>"))

        if state.confidence is not None:
            pct = int(round(float(state.confidence) * 100))
            conf_lbl = QLabel(
                f"ביטחון OCR: {pct}%"
                + (" (נמוך — בדקו היטב)" if state.confidence < 0.85 else "")
            )
            if state.confidence < 0.85:
                conf_lbl.setStyleSheet(
                    "color: #9a4d00; font-weight: bold; background: #fff3cd; "
                    "padding: 1px 6px; border-radius: 3px;"
                )
            else:
                conf_lbl.setStyleSheet("color: #2f6b2f;")
            header.addWidget(conf_lbl)

        header.addStretch(1)

        self.quick_verify_btn = QPushButton("✓ אמת והמשך (Ctrl+Enter)")
        self.quick_verify_btn.setToolTip(
            "אישור ששורה זו נבדקה ותואמת בדיוק למה שנכתב בדף, ומעבר לשורה הבאה."
        )
        self.quick_verify_btn.clicked.connect(
            lambda: self.verify_and_advance_requested.emit(self.line_index)
        )
        header.addWidget(self.quick_verify_btn)

        self.quick_uncertain_btn = QPushButton("? מסופק (Alt+U)")
        self.quick_uncertain_btn.setToolTip(
            "סימון שאות אחת או יותר בשורה אינה ודאית (נשמר מקומית אך לא משמש לאימון)."
        )
        self.quick_uncertain_btn.clicked.connect(
            lambda: self.uncertain_and_advance_requested.emit(self.line_index)
        )
        header.addWidget(self.quick_uncertain_btn)

        self.status_combo = QComboBox()
        for code, label in _STATUS_LABELS:
            self.status_combo.addItem(label, code)
        idx = self.status_combo.findData(state.review_status)
        self.status_combo.setCurrentIndex(max(0, idx))
        header.addWidget(self.status_combo)
        layout.addLayout(header)

        # Compatibility checkboxes synchronized with explicit 4-state status
        self.verified_check = QCheckBox("✓ אומת כפי שנכתב")
        self.verified_check.setVisible(False)
        self.verified_check.setChecked(state.review_status == STATUS_VERIFIED)
        self.skip_check = QCheckBox("דלג (מחוק / לא קריא)")
        self.skip_check.setVisible(False)
        self.skip_check.setChecked(state.review_status == STATUS_SKIPPED)
        layout.addWidget(self.verified_check)
        layout.addWidget(self.skip_check)

        # Cropped handwritten line image (pixmap only — PIL image released)
        self.crop_label = QLabel()
        self.crop_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        pm = _pil_to_qpixmap(crop_image)
        if pm.height() > 62:
            pm = pm.scaledToHeight(62, Qt.SmoothTransformation)
        elif 0 < pm.height() < 34:
            pm = pm.scaledToHeight(42, Qt.SmoothTransformation)
        if pm.width() > 640:
            pm = pm.scaledToWidth(640, Qt.SmoothTransformation)
        self.crop_label.setPixmap(pm)
        self.crop_label.setStyleSheet(
            "background: #fafafa; border: 1px solid #ddd; padding: 3px;"
        )
        layout.addWidget(self.crop_label)

        self.text_edit = QLineEdit(state.diplomatic_text)
        self.text_edit.setLayoutDirection(Qt.RightToLeft)
        self.text_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        font = QFont()
        font.setPointSize(13)
        self.text_edit.setFont(font)
        self.text_edit.setPlaceholderText("הטקסט כפי שנכתב בשורה זו בדף...")
        self.text_edit.installEventFilter(self)
        self.text_edit.setEnabled(state.review_status != STATUS_SKIPPED)
        layout.addWidget(self.text_edit)

        self.text_edit.textEdited.connect(self._on_user_edited_text)
        self.status_combo.currentIndexChanged.connect(self._on_status_combo_changed)
        self.verified_check.toggled.connect(self._on_verified_check_toggled)
        self.skip_check.toggled.connect(self._on_skip_check_toggled)
        self._refresh_card_style()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self.text_edit:
            if event.type() == QEvent.FocusIn:
                self.focused.emit(self.line_index)
            elif event.type() == QEvent.KeyPress:
                mods = event.modifiers()
                key = event.key()
                if key in (Qt.Key_Return, Qt.Key_Enter) and (
                    mods & (Qt.ControlModifier | Qt.AltModifier)
                ):
                    self.verify_and_advance_requested.emit(self.line_index)
                    return True
                if key == Qt.Key_U and (mods & Qt.AltModifier):
                    self.uncertain_and_advance_requested.emit(self.line_index)
                    return True
                if key == Qt.Key_Down and (mods & Qt.AltModifier):
                    self.move_line_requested.emit(self.line_index, 1)
                    return True
                if key == Qt.Key_Up and (mods & Qt.AltModifier):
                    self.move_line_requested.emit(self.line_index, -1)
                    return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.focused.emit(self.line_index)
        super().mousePressEvent(event)

    def _on_user_edited_text(self, text: str) -> None:
        """Editing NEVER auto-marks a line verified; typing '[?]' marks uncertain."""
        self.focused.emit(self.line_index)
        self.state.diplomatic_text = text
        if "[?]" in text and self.state.review_status == STATUS_VERIFIED:
            self.set_review_status(STATUS_UNCERTAIN)
            return
        self.state_changed.emit()

    def set_review_status(self, status: str) -> None:
        txt = self.text_edit.text().strip()
        self.state.diplomatic_text = self.text_edit.text()
        if status == STATUS_VERIFIED and ("[?]" in txt or not txt):
            status = STATUS_UNCERTAIN if "[?]" in txt else STATUS_NOT_REVIEWED
        self.state.review_status = status

        self.status_combo.blockSignals(True)
        idx = self.status_combo.findData(status)
        if idx >= 0:
            self.status_combo.setCurrentIndex(idx)
        self.status_combo.blockSignals(False)

        self.verified_check.blockSignals(True)
        self.verified_check.setChecked(status == STATUS_VERIFIED)
        self.verified_check.blockSignals(False)

        self.skip_check.blockSignals(True)
        self.skip_check.setChecked(status == STATUS_SKIPPED)
        self.skip_check.blockSignals(False)

        self.text_edit.setEnabled(status != STATUS_SKIPPED)
        self._refresh_card_style()
        self.state_changed.emit()

    def _on_status_combo_changed(self, _idx: int) -> None:
        code = str(self.status_combo.currentData() or STATUS_NOT_REVIEWED)
        self.set_review_status(code)

    def _on_verified_check_toggled(self, checked: bool) -> None:
        if checked:
            self.set_review_status(STATUS_VERIFIED)
        elif self.state.review_status == STATUS_VERIFIED:
            self.set_review_status(STATUS_NOT_REVIEWED)

    def _on_skip_check_toggled(self, skipped: bool) -> None:
        if skipped:
            self.set_review_status(STATUS_SKIPPED)
        elif self.state.review_status == STATUS_SKIPPED:
            self.set_review_status(STATUS_NOT_REVIEWED)

    def _refresh_card_style(self) -> None:
        st = self.state.review_status
        if st == STATUS_SKIPPED:
            self.setStyleSheet(
                "QFrame { background: #f3f3f3; border: 1px dashed #bbb; border-radius: 5px; }"
            )
        elif st == STATUS_VERIFIED:
            self.setStyleSheet(
                "QFrame { background: #f2fbf4; border: 1px solid #6ab07a; border-radius: 5px; }"
            )
        elif st == STATUS_UNCERTAIN:
            self.setStyleSheet(
                "QFrame { background: #fff9eb; border: 1px solid #e0a800; border-radius: 5px; }"
            )
        else:
            self.setStyleSheet(
                "QFrame { background: #ffffff; border: 1px solid #d4d4d4; border-radius: 5px; }"
            )

    @property
    def review_status(self) -> str:
        return self.state.review_status

    @property
    def is_verified_for_training(self) -> bool:
        self.state.diplomatic_text = self.text_edit.text()
        return self.state.is_verified_for_training

    @property
    def diplomatic_text(self) -> str:
        return self.text_edit.text().strip()


class SchoolVocabularyDialog(QDialog):
    """Administrator review/approval dialog for opt-in school-wide shared vocabulary."""

    def __init__(
        self, store: SchoolLearningStore, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("ניהול ואישור מילון בית-ספרי משותף (מנהל)")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(720, 520)

        layout = QVBoxLayout(self)
        info = QLabel(
            "רק מונחים וקיצורים שאושרו במפורש על-ידי מנהל משותפים בין התלמידים לשיפור "
            "פענוח והצעות איות. שמות פרטיים, טיוטות או שגיאות כתיב של תלמידים לעולם אינם "
            "מתווספים אוטומטית ללא אישור."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.sharing_check = QCheckBox(
            "הפעל שימוש ואיסוף מועמדים למילון בית-ספרי משותף (Opt-in)"
        )
        self.sharing_check.setChecked(self.store.vocab_sharing_enabled())
        self.sharing_check.toggled.connect(self._on_sharing_toggled)
        layout.addWidget(self.sharing_check)

        lists_row = QHBoxLayout()

        # Pending candidates column
        pending_col = QVBoxLayout()
        pending_col.addWidget(QLabel("<b>מועמדים להמתנת אישור (מתוך שורות מאומתות):</b>"))
        self.pending_list = QListWidget()
        pending_col.addWidget(self.pending_list, 1)
        p_btns = QHBoxLayout()
        self.approve_btn = QPushButton("✓ אשר מונח נבחר")
        self.approve_btn.clicked.connect(self._approve_selected)
        self.reject_btn = QPushButton("דחה מונח")
        self.reject_btn.clicked.connect(self._reject_selected)
        p_btns.addWidget(self.approve_btn)
        p_btns.addWidget(self.reject_btn)
        pending_col.addLayout(p_btns)

        # Approved terms column
        approved_col = QVBoxLayout()
        approved_col.addWidget(QLabel("<b>מונחים וקיצורים מאושרים במילון הבית-ספרי:</b>"))
        self.approved_list = QListWidget()
        approved_col.addWidget(self.approved_list, 1)
        a_btns = QHBoxLayout()
        self.add_manual_btn = QPushButton("+ הוסף ואשר מונח...")
        self.add_manual_btn.clicked.connect(self._add_manual_term)
        self.remove_approved_btn = QPushButton("הסר מהמילון המשותף")
        self.remove_approved_btn.clicked.connect(self._remove_selected_approved)
        a_btns.addWidget(self.add_manual_btn)
        a_btns.addWidget(self.remove_approved_btn)
        approved_col.addLayout(a_btns)

        lists_row.addLayout(pending_col, 1)
        lists_row.addLayout(approved_col, 1)
        layout.addLayout(lists_row, 1)

        close_btn = QPushButton("סגירה")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignLeft)
        self._refresh_lists()

    def _on_sharing_toggled(self, checked: bool) -> None:
        self.store.set_vocab_sharing_enabled(checked)
        self._refresh_lists()

    def _refresh_lists(self) -> None:
        self.pending_list.clear()
        for entry in self.store.list_vocab_terms(status=VOCAB_PENDING):
            item = QListWidgetItem(
                f"{entry.term}  ({entry.occurrences} מופעים, {entry.writers_count} כותבים)"
            )
            item.setData(Qt.UserRole, entry.term)
            self.pending_list.addItem(item)

        self.approved_list.clear()
        for entry in self.store.list_vocab_terms(status=VOCAB_APPROVED):
            item = QListWidgetItem(f"{entry.term}  ({entry.occurrences} מופעים)")
            item.setData(Qt.UserRole, entry.term)
            self.approved_list.addItem(item)

    def _approve_selected(self) -> None:
        item = self.pending_list.currentItem()
        if item is None:
            return
        term = str(item.data(Qt.UserRole))
        self.store.approve_vocab_term(
            term, enable_sharing=self.sharing_check.isChecked() or True
        )
        self.sharing_check.setChecked(self.store.vocab_sharing_enabled())
        self._refresh_lists()

    def _reject_selected(self) -> None:
        item = self.pending_list.currentItem()
        if item is None:
            return
        self.store.reject_vocab_term(str(item.data(Qt.UserRole)))
        self._refresh_lists()

    def _add_manual_term(self) -> None:
        term, ok = QInputDialog.getText(
            self,
            "הוספת מונח או קיצור בית-ספרי",
            'הקלידו מילה או ראשי-תיבות (למשל: שמעתתין / מהרשד"ם):',
        )
        if not ok or not term.strip():
            return
        try:
            self.store.approve_vocab_term(term.strip(), enable_sharing=True)
        except ValueError as exc:
            QMessageBox.warning(self, "הוספת מונח", str(exc))
            return
        self.sharing_check.setChecked(self.store.vocab_sharing_enabled())
        self._refresh_lists()

    def _remove_selected_approved(self) -> None:
        item = self.approved_list.currentItem()
        if item is None:
            return
        self.store.remove_vocab_term(str(item.data(Qt.UserRole)))
        self._refresh_lists()


class AdapterHistoryDialog(QDialog):
    """Displays per-student adapter version history and one-click rollback."""

    def __init__(
        self,
        store: SchoolLearningStore,
        writer_id: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.writer_id = writer_id
        self.rolled_back = False
        prof = store.get_writer(writer_id)
        name = prof.name if prof else writer_id
        self.setWindowTitle(f"היסטוריית גרסאות ושחזור (Rollback) — {name}")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(620, 400)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "בחרו גרסה קודמת או את מודל הבסיס המקורי ולחצו על 'הפעל גרסה נבחרת' לשחזור מיידי בלחיצה אחת:"
            )
        )
        self.version_list = QListWidget()
        layout.addWidget(self.version_list, 1)

        btns = QHBoxLayout()
        self.rollback_prev_btn = QPushButton("שחזור מהיר לגרסה הקודמת")
        self.rollback_prev_btn.clicked.connect(self._rollback_one_step)
        self.activate_selected_btn = QPushButton("הפעל גרסה נבחרת")
        self.activate_selected_btn.clicked.connect(self._activate_selected)
        self.import_external_btn = QPushButton("ייבוא מתאם מאומן (.npz)...")
        self.import_external_btn.setToolTip(
            "ייבוא מתאם אישי שאומן במחשב חיצוני/מקוון (נבדק ללא pickle עם אפשרות שחזור בלחיצה אחת)."
        )
        self.import_external_btn.clicked.connect(self._import_external_npz)
        close_btn = QPushButton("סגירה")
        close_btn.clicked.connect(self.accept)
        btns.addWidget(self.rollback_prev_btn)
        btns.addWidget(self.activate_selected_btn)
        btns.addWidget(self.import_external_btn)
        btns.addStretch(1)
        btns.addWidget(close_btn)
        layout.addLayout(btns)
        self._populate()

    def _populate(self) -> None:
        self.version_list.clear()
        prof = self.store.get_writer(self.writer_id)
        active_round = prof.active_round if prof else 0

        base_item = QListWidgetItem(
            "מודל בסיס מקורי (ללא התאמה אישית — סיבוב #0)"
            + ("  [פעיל כעת]" if active_round == 0 else "")
        )
        base_item.setData(Qt.UserRole, 0)
        self.version_list.addItem(base_item)

        for ver in self.store.list_adapter_versions(self.writer_id):
            cer_str = ""
            proven = (
                ver.held_out_cer_before is not None
                and ver.held_out_cer_after is not None
                and ver.held_out_cer_after <= ver.held_out_cer_before + 1e-6
            )
            if (
                ver.held_out_cer_before is not None
                and ver.held_out_cer_after is not None
            ):
                cer_str = (
                    f" | בקרה CER: {ver.held_out_cer_before * 100:.1f}% → "
                    f"{ver.held_out_cer_after * 100:.1f}%"
                )
            state_tag = (
                "  [פעילה כעת]"
                if ver.is_active
                else ("" if proven else "  [לא הופעלה — ללא שיפור מוכח בבקרה]")
            )
            txt = (
                f"גרסה #{ver.round_number} ({ver.created_at}) — "
                f"{ver.train_samples} אימון, {ver.held_out_samples} בקרה{cer_str}{state_tag}"
            )
            item = QListWidgetItem(txt)
            item.setData(Qt.UserRole, ver.round_number)
            self.version_list.addItem(item)
        self.rollback_prev_btn.setEnabled(active_round > 0)

    def _rollback_one_step(self) -> None:
        self.store.rollback_writer_adapter(self.writer_id, target_round=None)
        self.rolled_back = True
        self._populate()

    def _activate_selected(self) -> None:
        item = self.version_list.currentItem()
        if item is None:
            return
        target_round = int(item.data(Qt.UserRole))
        try:
            self.store.rollback_writer_adapter(
                self.writer_id, target_round=target_round
            )
        except Exception as exc:
            QMessageBox.warning(self, "הפעלת גרסת מתאם", str(exc))
            return
        self.rolled_back = True
        self._populate()

    def _import_external_npz(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "ייבוא מתאם כתב-יד מאומן (.npz)",
            "",
            "קובץ מתאם NumPy (*.npz)",
        )
        if not path:
            return
        try:
            report = import_external_adapter_npz(
                self.writer_id, path, store_root=self.store.root
            )
        except Exception as exc:
            QMessageBox.warning(self, "ייבוא מתאם (.npz)", str(exc))
            return
        if report.accepted:
            self.rolled_back = True
        self._populate()
        QMessageBox.information(
            self,
            "ייבוא מתאם (.npz)",
            report.message,
        )


class DiplomaticVerificationDialog(QDialog):
    """Stage-A side-by-side handwriting verification & local school trainer."""

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
        self.committed_writer_id: str = self.selected_writer_id
        self.updated_diplomatic_transcription: str | None = None

        self.setWindowTitle(
            f"שלב א׳ — אימות כתב-יד מדויק לפני עריכת דקדוק ({entry.name})"
        )
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1260, 840)

        self._rendered_page_lru: OrderedDict[int, Image.Image] = OrderedDict()
        self._page_skew_by_num: dict[int, float] = {}
        self._states_by_page: dict[int, list[_DraftLineState]] = {}
        self._active_page_cards: list[_LineVerificationCard] = []
        self._current_page_idx: int = 0
        self._page_numbers: list[int] = []

        self._build_ui()
        self._init_line_states_from_entry()
        self._refresh_writer_combo(select_id=self.selected_writer_id)
        if self._page_numbers:
            self._show_page_at_index(0)
        self._update_summary_and_buttons()

    # -- UI layout ---------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(7)

        # 1. Stage-A banner
        stage_banner = QFrame()
        stage_banner.setStyleSheet(
            "QFrame { background: #fff8e6; border: 1px solid #e0b84c; border-radius: 6px; }"
        )
        sb_layout = QVBoxLayout(stage_banner)
        sb_layout.setContentsMargins(10, 7, 10, 7)
        sb_title = QLabel(
            "<b>שלב א׳ — אמתו בדיוק כפי שנכתב בדף (לפני תיקוני איות, דקדוק או סגנון!)</b>"
        )
        sb_title.setWordWrap(True)
        sb_body = QLabel(
            "תקנו רק שגיאות קריאה של ה-OCR כך שהשורה תתאים <b>אות-באות</b> לדיו שבדף (כולל קיצורים או שגיאות כתיב במקור). "
            "עריכת טקסט או שמירת טיוטה <b>אינה</b> מסמנת שורה כמאומתת מעצמה — לחצו <b>✓ אמת והמשך (Ctrl+Enter)</b> רק על שורות שבדקתם בוודאות, "
            "או <b>? מסופק (Alt+U)</b> כשאחת האותיות לא ברורה. בשלב ב׳ בעורך הראשי תוכלו לשפר איות ודקדוק מבלי לפגוע בנתוני האימון!"
        )
        sb_body.setWordWrap(True)
        sb_layout.addWidget(sb_title)
        sb_layout.addWidget(sb_body)

        if self.entry.changes:
            grammar_warn = QLabel(
                "<span style='color:#9c2b00;'><b>הגנת שלב א׳ פעילה:</b> במסמך זה כבר הוחלו תיקוני שפה בעורך (שלב ב׳). "
                "השורות כאן נטענו מהגרסה הדיפלומטית המקורית שלפני תיקוני הדקדוק כדי לא לזהם את אימון כתב-היד.</span>"
            )
            grammar_warn.setWordWrap(True)
            sb_layout.addWidget(grammar_warn)

        root.addWidget(stage_banner)

        # 2. Student profile & local admin bar
        writer_bar = QHBoxLayout()
        writer_bar.addWidget(QLabel("<b>תלמיד / כותב:</b>"))
        self.writer_combo = QComboBox()
        self.writer_combo.setMinimumWidth(235)
        self.writer_combo.currentIndexChanged.connect(self._on_writer_changed)
        writer_bar.addWidget(self.writer_combo)

        self.add_writer_btn = QPushButton("+ תלמיד...")
        self.add_writer_btn.clicked.connect(self._prompt_new_writer)
        writer_bar.addWidget(self.add_writer_btn)

        self.rename_writer_btn = QPushButton("שינוי שם...")
        self.rename_writer_btn.clicked.connect(self._prompt_rename_writer)
        writer_bar.addWidget(self.rename_writer_btn)

        self.delete_writer_btn = QPushButton("מחיקת פרופיל...")
        self.delete_writer_btn.clicked.connect(self._prompt_delete_writer)
        writer_bar.addWidget(self.delete_writer_btn)

        self.rollback_btn = QPushButton("גרסאות / שחזור...")
        self.rollback_btn.setToolTip(
            "צפייה בהיסטוריית המתאמים האישיים ושחזור בלחיצה אחת לגרסה קודמת או למודל הבסיס."
        )
        self.rollback_btn.clicked.connect(self._open_adapter_history)
        writer_bar.addWidget(self.rollback_btn)

        writer_bar.addSpacing(8)
        self.vocab_admin_btn = QPushButton("מילון משותף (מנהל)...")
        self.vocab_admin_btn.clicked.connect(self._open_vocab_admin)
        writer_bar.addWidget(self.vocab_admin_btn)

        self.export_school_btn = QPushButton("ייצוא לאימון אונליין (ZIP)...")
        self.export_school_btn.clicked.connect(self._export_school_zip)
        writer_bar.addWidget(self.export_school_btn)

        self.backup_btn = QPushButton("גיבוי/שחזור...")
        self.backup_btn.clicked.connect(self._prompt_backup_or_restore)
        writer_bar.addWidget(self.backup_btn)
        root.addLayout(writer_bar)

        self.school_stats_label = QLabel("")
        self.school_stats_label.setStyleSheet("color: #334;")
        root.addWidget(self.school_stats_label)

        # 3. Page navigation & page-level helpers
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

        self.mark_all_page_btn = QPushButton("אמת את כל השורות בעמוד לאחר בדיקה")
        self.mark_all_page_btn.setToolTip(
            "מסמן כ-'אומת' את כל השורות התקינות בעמוד זה (מדלג על שורות עם '[?]' או מחוקות)."
        )
        self.mark_all_page_btn.clicked.connect(self._mark_all_current_page)
        self.unmark_all_page_btn = QPushButton("החזר עמוד ל-'לא נבדק'")
        self.unmark_all_page_btn.clicked.connect(self._unmark_all_current_page)
        page_bar.addWidget(self.mark_all_page_btn)
        page_bar.addWidget(self.unmark_all_page_btn)
        root.addLayout(page_bar)

        # 4. Side-by-Side Splitter (RTL: Right = Original Page Scan, Left = Line Cards)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        page_pane = QWidget()
        page_pane_layout = QVBoxLayout(page_pane)
        page_pane_layout.setContentsMargins(0, 0, 0, 0)
        page_pane_layout.addWidget(
            QLabel("<b>דף כתב היד המקורי (מיקום השורה הפעילה מודגש):</b>")
        )
        self.page_scroll = QScrollArea()
        self.page_scroll.setWidgetResizable(True)
        self.page_view = _PageHighlightView()
        self.page_scroll.setWidget(self.page_view)
        page_pane_layout.addWidget(self.page_scroll, 1)

        lines_pane = QWidget()
        lines_pane_layout = QVBoxLayout(lines_pane)
        lines_pane_layout.setContentsMargins(0, 0, 0, 0)
        lines_pane_layout.addWidget(
            QLabel(
                "<b>שורות הדף (קיצורי מקלדת: Ctrl+Enter = אמת והמשך · Alt+U = מסופק · Alt+↓/↑ = מעבר שורה):</b>"
            )
        )
        self.lines_scroll = QScrollArea()
        self.lines_scroll.setWidgetResizable(True)
        self.lines_container = QWidget()
        self.lines_layout = QVBoxLayout(self.lines_container)
        self.lines_layout.setContentsMargins(4, 4, 4, 4)
        self.lines_layout.setSpacing(8)
        self.lines_scroll.setWidget(self.lines_container)
        lines_pane_layout.addWidget(self.lines_scroll, 1)

        splitter.addWidget(page_pane)
        splitter.addWidget(lines_pane)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 7)
        root.addWidget(splitter, 1)

        # 5. Stage-A confirmation gate & separate Draft-Save vs Train actions
        self.confirm_exact_checkbox = QCheckBox(
            'אני מאשר/ת שהשורות שסומנו ב-"✓ אומת כפי שנכתב" נבדקו מול הסריקה המקורית '
            "ותואמות בדיוק למה שנכתב בדף (לפני תיקוני איות, דקדוק או סגנון)."
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

        self.save_draft_btn = QPushButton("שמור התקדמות מקומית (ללא אימון)")
        self.save_draft_btn.setToolTip(
            "שומר מקומית את כל תיקוני הטיוטה, השורות המסופקות והשורות המאומתות — מבלי לסמן שורות ערוכות כמאומתות."
        )
        self.save_draft_btn.clicked.connect(self._on_save_draft_clicked)

        self.save_and_train_btn = QPushButton(
            "שמור שורות מאומתות ובדוק התאמה אישית"
        )
        self.save_and_train_btn.setDefault(True)
        self.save_and_train_btn.setStyleSheet(
            "QPushButton:enabled { background: #1e6b3a; color: white; "
            "font-weight: bold; padding: 6px 14px; border-radius: 4px; }"
        )
        self.save_and_train_btn.clicked.connect(self._on_save_and_train_clicked)

        footer.addWidget(self.cancel_btn)
        footer.addWidget(self.save_draft_btn)
        footer.addWidget(self.save_and_train_btn)
        root.addLayout(footer)

        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._on_save_draft_clicked)

    # -- lightweight state initialization & bounded-RAM page rendering -----
    def _init_line_states_from_entry(self) -> None:
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
            self.save_draft_btn.setEnabled(False)
            return

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

        saved_map = self.store.list_document_lines(
            self.selected_writer_id, self.entry.file_path
        )

        flat_cursor = 0
        for page_dict in self.entry.recognized_pages:
            pnum = int(page_dict.get("number", 1))
            skew_deg = float(page_dict.get("skew_degrees", 0.0) or 0.0)
            self._page_skew_by_num[pnum] = skew_deg
            page_preproc = {
                "page_enhancement_enabled": bool(
                    page_dict.get("enhancement_enabled", True)
                ),
                "page_enhanced": bool(page_dict.get("enhanced", False)),
                "skew_degrees": skew_deg,
                "stroke_variant": str(
                    page_dict.get("stroke_variant", "original")
                ),
                "render_dpi": OCR_RENDER_DPI,
            }
            p_states: list[_DraftLineState] = []
            for l_idx, line_info in enumerate(page_dict.get("lines", [])):
                ocr_txt = str(line_info.get("text", "") or "").strip()
                conf = line_info.get("confidence")
                raw_box = line_info.get("box")
                box = (
                    tuple(float(v) for v in raw_box[:4])
                    if isinstance(raw_box, (list, tuple)) and len(raw_box) == 4
                    else None
                )
                saved_rec = saved_map.get((pnum, l_idx))
                conf_wid: str | None = None
                conf_txt: str | None = None
                conf_box: tuple[float, float, float, float] | None = None
                if saved_rec is not None and _boxes_match(saved_rec.box, box):
                    init_txt = saved_rec.diplomatic_text
                    init_status = saved_rec.review_status
                    if saved_rec.review_status == STATUS_VERIFIED:
                        conf_wid = self.selected_writer_id
                        conf_txt = saved_rec.diplomatic_text.strip()
                        conf_box = box
                elif override_lines is not None and flat_cursor < len(
                    override_lines
                ):
                    init_txt = override_lines[flat_cursor]
                    init_status = (
                        STATUS_UNCERTAIN
                        if "[?]" in init_txt
                        else STATUS_NOT_REVIEWED
                    )
                else:
                    init_txt = ocr_txt
                    init_status = (
                        STATUS_UNCERTAIN
                        if "[?]" in init_txt
                        else STATUS_NOT_REVIEWED
                    )
                flat_cursor += 1

                p_states.append(
                    _DraftLineState(
                        page_number=pnum,
                        line_index=l_idx,
                        ocr_text=ocr_txt,
                        diplomatic_text=init_txt,
                        review_status=init_status,
                        confidence=float(conf) if conf is not None else None,
                        box=box,
                        engine_name=str(
                            page_dict.get("engine_name")
                            or self.entry.engine_name
                            or ""
                        ),
                        engine_version=str(
                            page_dict.get("engine_version") or ""
                        ),
                        model_id=str(page_dict.get("model_id") or ""),
                        model_sha256=str(page_dict.get("model_sha256") or ""),
                        decoding_mode=str(
                            page_dict.get("decoding_mode")
                            or self.entry.decoding_mode
                            or "raw"
                        ),
                        preprocessing=dict(page_preproc),
                        confirmed_verified_writer_id=conf_wid,
                        confirmed_verified_text=conf_txt,
                        confirmed_verified_box=conf_box,
                    )
                )
            self._states_by_page[pnum] = p_states
            self._page_numbers.append(pnum)

    def _render_single_page_bounded(self, pnum: int) -> Image.Image | None:
        """Render one page from the original scan with a strict 2-page LRU bound."""
        if pnum in self._rendered_page_lru:
            self._rendered_page_lru.move_to_end(pnum)
            return self._rendered_page_lru[pnum]
        try:
            with DocumentPreview(self.entry.file_path) as preview:
                if pnum < 1 or pnum > preview.page_count:
                    return None
                rendered = _apply_page_skew(
                    preview.render(pnum, dpi=OCR_RENDER_DPI).image,
                    self._page_skew_by_num.get(pnum, 0.0),
                )
        except PreviewError:
            return None
        self._rendered_page_lru[pnum] = rendered
        while len(self._rendered_page_lru) > MAX_RENDERED_PAGE_CACHE:
            self._rendered_page_lru.popitem(last=False)
        return rendered

    def _clear_active_page_cards(self) -> None:
        self._sync_active_cards_into_states()
        self._active_page_cards.clear()
        while self.lines_layout.count():
            item = self.lines_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _sync_active_cards_into_states(self) -> None:
        for card in self._active_page_cards:
            card.state.diplomatic_text = card.text_edit.text()

    def _show_page_at_index(self, idx: int) -> None:
        if not self._page_numbers:
            return
        idx = max(0, min(len(self._page_numbers) - 1, idx))
        self._clear_active_page_cards()
        self._current_page_idx = idx
        active_pnum = self._page_numbers[idx]
        rendered = self._render_single_page_bounded(active_pnum)

        states = self._states_by_page.get(active_pnum, [])
        if rendered is not None:
            self.page_view.set_page_image(rendered)
            pw, ph = rendered.size
            n_lines = max(1, len(states))
            for st in states:
                if st.box is not None:
                    crop_im = crop_line_from_page(rendered, st.box)
                else:
                    y0 = int(ph * st.line_index / n_lines)
                    y1 = max(y0 + 16, int(ph * (st.line_index + 1) / n_lines))
                    crop_im = rendered.crop((0, y0, pw, min(ph, y1)))
                card = _LineVerificationCard(st, crop_im, self.lines_container)
                card.focused.connect(self._on_line_card_focused)
                card.state_changed.connect(self._update_summary_and_buttons)
                card.verify_and_advance_requested.connect(
                    self._on_verify_and_advance
                )
                card.uncertain_and_advance_requested.connect(
                    self._on_uncertain_and_advance
                )
                card.move_line_requested.connect(self._on_move_line)
                self.lines_layout.addWidget(card)
                self._active_page_cards.append(card)
            if self._active_page_cards:
                self.page_view.set_highlight_box(self._active_page_cards[0].box)
        self.lines_layout.addStretch(1)
        self.page_info_label.setText(
            f"עמוד {active_pnum} ({idx + 1} מתוך {len(self._page_numbers)})"
        )
        self.prev_page_btn.setEnabled(idx > 0)
        self.next_page_btn.setEnabled(idx < len(self._page_numbers) - 1)
        self._update_summary_and_buttons()

    def _switch_page(self, delta: int) -> None:
        self._show_page_at_index(self._current_page_idx + delta)

    def _on_line_card_focused(self, line_index: int) -> None:
        if 0 <= line_index < len(self._active_page_cards):
            card = self._active_page_cards[line_index]
            rect = self.page_view.set_highlight_box(card.box)
            if rect is not None:
                center = rect.center()
                self.page_scroll.ensureVisible(
                    int(center.x()), int(center.y()), 80, 120
                )

    def _on_verify_and_advance(self, line_index: int) -> None:
        if 0 <= line_index < len(self._active_page_cards):
            self._active_page_cards[line_index].set_review_status(STATUS_VERIFIED)
            self._on_move_line(line_index, 1)

    def _on_uncertain_and_advance(self, line_index: int) -> None:
        if 0 <= line_index < len(self._active_page_cards):
            self._active_page_cards[line_index].set_review_status(
                STATUS_UNCERTAIN
            )
            self._on_move_line(line_index, 1)

    def _on_move_line(self, line_index: int, delta: int) -> None:
        nxt = line_index + delta
        if 0 <= nxt < len(self._active_page_cards):
            target = self._active_page_cards[nxt]
            target.text_edit.setFocus()
            self.lines_scroll.ensureWidgetVisible(target)
        elif (
            delta > 0
            and self._current_page_idx + 1 < len(self._page_numbers)
        ):
            self._show_page_at_index(self._current_page_idx + 1)
            if self._active_page_cards:
                self._active_page_cards[0].text_edit.setFocus()

    def _mark_all_current_page(self) -> None:
        for card in self._active_page_cards:
            if (
                card.review_status != STATUS_SKIPPED
                and card.diplomatic_text
                and "[?]" not in card.diplomatic_text
            ):
                card.set_review_status(STATUS_VERIFIED)
        self._update_summary_and_buttons()

    def _unmark_all_current_page(self) -> None:
        for card in self._active_page_cards:
            if card.review_status != STATUS_SKIPPED:
                card.set_review_status(STATUS_NOT_REVIEWED)
        self._update_summary_and_buttons()

    # -- student / writer management, rollback & backup --------------------
    def _refresh_writer_combo(self, select_id: str = "") -> None:
        self.writer_combo.blockSignals(True)
        self.writer_combo.clear()
        self.writer_combo.addItem(
            "כללי / לא ידוע (מודל בסיס ללא מתאם אישי)", ""
        )
        writers = self.store.list_writers()
        selected_idx = 0
        for idx, prof in enumerate(writers, start=1):
            badge = (
                f"{prof.name} ({prof.samples_count} מאומתות"
                + (f", גרסה #{prof.active_round}" if prof.active_round else "")
                + ")"
            )
            self.writer_combo.addItem(badge, prof.writer_id)
            if prof.writer_id == select_id:
                selected_idx = idx
        self.writer_combo.setCurrentIndex(selected_idx)
        self.writer_combo.blockSignals(False)
        self.selected_writer_id = str(self.writer_combo.currentData() or "")
        has_student = bool(self.selected_writer_id)
        self.rename_writer_btn.setEnabled(has_student)
        self.delete_writer_btn.setEnabled(has_student)
        self.rollback_btn.setEnabled(has_student)
        self._refresh_school_stats_label()

    def _on_writer_changed(self, _idx: int) -> None:
        self.selected_writer_id = str(self.writer_combo.currentData() or "")
        has_student = bool(self.selected_writer_id)
        self.rename_writer_btn.setEnabled(has_student)
        self.delete_writer_btn.setEnabled(has_student)
        self.rollback_btn.setEnabled(has_student)
        self._refresh_school_stats_label()
        self._update_summary_and_buttons()

    def _prompt_new_writer(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            "הוספת תלמיד / כותב חדש",
            "שם התלמיד או מזהה כיתה (למשל: תלמיד 07 / יוסף כהן):",
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
            self, "שינוי שם תלמיד", "שם מעודכן:", text=prof.name
        )
        if not ok or not name.strip():
            return
        try:
            updated = self.store.rename_writer(prof.writer_id, name.strip())
        except (ValueError, KeyError) as exc:
            QMessageBox.warning(self, "שינוי שם", str(exc))
            return
        self._refresh_writer_combo(select_id=updated.writer_id)

    def _prompt_delete_writer(self) -> None:
        if not self.selected_writer_id:
            return
        prof = self.store.get_writer(self.selected_writer_id)
        if prof is None:
            return
        ans = QMessageBox.question(
            self,
            "מחיקת פרופיל תלמיד",
            f"למחוק את פרופיל התלמיד '{prof.name}', המתאמים האישיים וכל חיתוכי השורות שלו מהדיסק?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        self.store.delete_writer(prof.writer_id, delete_verified_lines=True)
        self._refresh_writer_combo(select_id="")
        self._update_summary_and_buttons()

    def _open_adapter_history(self) -> None:
        if not self.selected_writer_id:
            return
        dlg = AdapterHistoryDialog(self.store, self.selected_writer_id, self)
        dlg.exec()
        if dlg.rolled_back:
            self._refresh_writer_combo(select_id=self.selected_writer_id)

    def _open_vocab_admin(self) -> None:
        dlg = SchoolVocabularyDialog(self.store, self)
        dlg.exec()
        self._refresh_school_stats_label()

    def _prompt_backup_or_restore(self) -> None:
        choice, ok = QInputDialog.getItem(
            self,
            "גיבוי או שחזור מאגר מקומי",
            "בחרו פעולה:",
            ["יצירת קובץ גיבוי מלא (ZIP)", "שחזור מאגר מקובץ גיבוי (ZIP)"],
            0,
            False,
        )
        if not ok:
            return
        if choice.startswith("יצירת"):
            path, _ = QFileDialog.getSaveFileName(
                self,
                "שמירת גיבוי מקומי מלא",
                "school-learning-backup.zip",
                "ארכיון ZIP (*.zip)",
            )
            if not path:
                return
            try:
                saved = self.store.backup_database_zip(path)
                QMessageBox.information(
                    self, "גיבוי הושלם", f"הגיבוי נשמר בהצלחה אל:\n{saved}"
                )
            except Exception as exc:
                QMessageBox.warning(self, "שגיאה בגיבוי", str(exc))
        else:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "בחירת קובץ גיבוי לשחזור",
                "",
                "ארכיון ZIP (*.zip)",
            )
            if not path:
                return
            try:
                self.store.restore_database_zip(path)
                self._refresh_writer_combo(select_id=self.selected_writer_id)
                QMessageBox.information(
                    self, "שחזור הושלם", "מאגר הלמידה שוחזר ואומת בהצלחה."
                )
            except Exception as exc:
                QMessageBox.warning(self, "שגיאה בשחזור", str(exc))

    def _refresh_school_stats_label(self) -> None:
        summary = self.store.school_summary()
        prof: WriterProfile | None = (
            self.store.get_writer(self.selected_writer_id)
            if self.selected_writer_id
            else None
        )
        if prof is not None:
            personal_part = (
                f"תלמיד פעיל: {prof.name} ({prof.samples_count} מאומתות, "
                f"{prof.uncertain_count} מסופקות, מתאם #{prof.active_round})  |  "
            )
        else:
            personal_part = "פרופיל פעיל: כללי / לא ידוע (מודל בסיס)  |  "
        sharing_state = (
            f"מילון משותף פעיל ({summary['shared_vocab_words']} מאושרות, {summary['pending_vocab_words']} בהמתנה)"
            if self.store.vocab_sharing_enabled()
            else "מילון משותף כבוי (Opt-in)"
        )
        self.school_stats_label.setText(
            f"{personal_part}מאגר מקומי: {summary['writers_count']} פרופילים · "
            f"{summary['verified_lines_count']} שורות מאומתות · {sharing_state}"
        )

    def _export_school_zip(self) -> None:
        summary = self.store.school_summary()
        if summary["verified_lines_count"] == 0:
            QMessageBox.information(
                self,
                "ייצוא לאימון אונליין/חיצוני",
                "אין עדיין שורות שסומנו ב-'✓ אומת כפי שנכתב'. רק שורות מאומתות מיוצאות לאימון.",
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "ייצוא חבילת אימון מאומתת (מוכנה ל-Colab / GPU אונליין)",
            "verified-school-handwriting-bundle.zip",
            "ארכיון ZIP (*.zip)",
        )
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != ".zip":
            target = target.with_suffix(".zip")
        try:
            saved = self.store.export_online_training_bundle_zip(
                target, anonymize_writers=True
            )
        except OSError as exc:
            QMessageBox.warning(self, "ייצוא לאימון", str(exc))
            return
        QMessageBox.information(
            self,
            "ייצוא הושלם",
            f"חבילת האימון המאומתת (ללא שמות תלמידים מזהים, מוכנה לאימון חיצוני/אונליין) נשמרה אל:\n{saved}\n\n"
            f"כוללת train.jsonl, val.jsonl, metadata.jsonl ו-{summary['verified_lines_count']} חיתוכי שורות מאומתות.",
        )

    # -- inspection helpers & persistence ----------------------------------
    def _all_cards(self) -> list[_LineVerificationCard]:
        return list(self._active_page_cards)

    def _all_states(self) -> list[_DraftLineState]:
        self._sync_active_cards_into_states()
        out: list[_DraftLineState] = []
        for pnum in self._page_numbers:
            out.extend(self._states_by_page.get(pnum, []))
        return out

    def verified_cards(self) -> list[_LineVerificationCard]:
        return [c for c in self._active_page_cards if c.is_verified_for_training]

    def _verified_states(self) -> list[_DraftLineState]:
        return [s for s in self._all_states() if s.is_verified_for_training]

    def _update_summary_and_buttons(self) -> None:
        states = self._all_states()
        ver_n = sum(1 for s in states if s.is_verified_for_training)
        unc_n = sum(1 for s in states if s.review_status == STATUS_UNCERTAIN)
        drf_n = sum(1 for s in states if s.review_status == STATUS_NOT_REVIEWED)
        skp_n = sum(1 for s in states if s.review_status == STATUS_SKIPPED)
        self.selection_summary_label.setText(
            f"סה״כ במסמך: {ver_n} מאומתות לאימון · {unc_n} מסופקות · "
            f"{drf_n} לא נבדקו · {skp_n} דולגו"
        )
        busy = self._train_task is not None and self._train_task.isRunning()
        self.save_draft_btn.setEnabled(not busy and bool(states))
        self.save_and_train_btn.setEnabled(
            not busy
            and ver_n > 0
            and self.confirm_exact_checkbox.isChecked()
        )

    def _assemble_diplomatic_transcription(self) -> str:
        lines: list[str] = []
        for st in self._all_states():
            if st.review_status == STATUS_SKIPPED:
                continue
            txt = st.diplomatic_text.strip()
            if txt:
                lines.append(txt)
        return "\n".join(lines)

    def _persist_all_reviewed_states(
        self, *, grammar_confirmed_for_verified: bool
    ) -> list:
        """Stream page-by-page from original scan to persist local state with low RAM."""
        self._sync_active_cards_into_states()
        persisted = []
        with DocumentPreview(self.entry.file_path) as preview:
            for pnum in self._page_numbers:
                states = self._states_by_page.get(pnum, [])
                if not states or pnum < 1 or pnum > preview.page_count:
                    continue
                rendered = _apply_page_skew(
                    preview.render(pnum, dpi=OCR_RENDER_DPI).image,
                    self._page_skew_by_num.get(pnum, 0.0),
                )
                pw, ph = rendered.size
                n_lines = max(1, len(states))
                page_inputs: list[VerifiedLineInput] = []
                for st in states:
                    eff_status = st.review_status
                    previously_confirmed = (
                        st.confirmed_verified_writer_id == self.selected_writer_id
                        and st.confirmed_verified_text is not None
                        and st.confirmed_verified_text == st.diplomatic_text.strip()
                        and _boxes_match(st.confirmed_verified_box, st.box, tol=1.0)
                    )
                    if (
                        eff_status == STATUS_VERIFIED
                        and not grammar_confirmed_for_verified
                        and not previously_confirmed
                    ):
                        # Saving draft without ticking the Stage-A confirmation gate
                        # never promotes NEW or EDITED lines to verified training data,
                        # while preserving untouched lines that were already confirmed.
                        eff_status = STATUS_NOT_REVIEWED
                    if (
                        eff_status == STATUS_VERIFIED
                        and (not st.diplomatic_text.strip() or "[?]" in st.diplomatic_text)
                    ):
                        eff_status = (
                            STATUS_UNCERTAIN
                            if "[?]" in st.diplomatic_text
                            else STATUS_NOT_REVIEWED
                        )
                    if st.box is not None:
                        crop_im = crop_line_from_page(rendered, st.box)
                    else:
                        y0 = int(ph * st.line_index / n_lines)
                        y1 = max(y0 + 16, int(ph * (st.line_index + 1) / n_lines))
                        crop_im = rendered.crop((0, y0, pw, min(ph, y1)))
                    page_inputs.append(
                        VerifiedLineInput(
                            crop_image=crop_im,
                            diplomatic_text=st.diplomatic_text.strip(),
                            page_number=pnum,
                            line_index=st.line_index,
                            box=st.box,
                            page_size=(pw, ph),
                            ocr_text=st.ocr_text,
                            ocr_confidence=st.confidence,
                            engine_name=st.engine_name,
                            engine_version=st.engine_version,
                            model_id=st.model_id,
                            model_sha256=st.model_sha256,
                            decoding_mode=st.decoding_mode,
                            preprocessing=st.preprocessing,
                            review_status=eff_status,
                            verified_exact_as_written=(
                                eff_status == STATUS_VERIFIED
                            ),
                            grammar_unedited_confirmed=(
                                eff_status == STATUS_VERIFIED
                                and (grammar_confirmed_for_verified or previously_confirmed)
                            ),
                        )
                    )
                persisted.extend(
                    self.store.record_reviewed_lines(
                        self.selected_writer_id,
                        self.entry.file_path,
                        page_inputs,
                    )
                )
        active_keys = {
            (max(1, int(pnum)), max(0, int(st.line_index)))
            for pnum, states in self._states_by_page.items()
            for st in states
        }
        self.store.reconcile_document_lines(
            self.selected_writer_id,
            self.entry.file_path,
            active_keys,
        )
        return persisted

    def _on_save_draft_clicked(self) -> None:
        if not self._all_states():
            return
        try:
            saved = self._persist_all_reviewed_states(
                grammar_confirmed_for_verified=self.confirm_exact_checkbox.isChecked()
            )
        except Exception as exc:
            QMessageBox.warning(self, "שמירת התקדמות מקומית", str(exc))
            return
        self.saved_samples_count = sum(
            1 for s in saved if s.review_status == STATUS_VERIFIED
        )
        self.committed_writer_id = self.selected_writer_id
        self.updated_diplomatic_transcription = (
            self._assemble_diplomatic_transcription()
        )
        self._refresh_school_stats_label()
        self.accept()

    def _set_writer_controls_enabled(self, enabled: bool) -> None:
        self.writer_combo.setEnabled(enabled)
        self.add_writer_btn.setEnabled(enabled)
        has_student = enabled and bool(self.selected_writer_id)
        self.rename_writer_btn.setEnabled(has_student)
        self.delete_writer_btn.setEnabled(has_student)
        self.rollback_btn.setEnabled(has_student)

    def _set_review_controls_enabled(self, enabled: bool) -> None:
        self.lines_container.setEnabled(enabled)
        self.confirm_exact_checkbox.setEnabled(enabled)
        self.mark_all_page_btn.setEnabled(enabled and bool(self._active_page_cards))
        self.unmark_all_page_btn.setEnabled(enabled and bool(self._active_page_cards))
        self.vocab_admin_btn.setEnabled(enabled)
        self.export_school_btn.setEnabled(enabled)
        self.backup_btn.setEnabled(enabled)
        if not enabled:
            self.prev_page_btn.setEnabled(False)
            self.next_page_btn.setEnabled(False)
        else:
            self.prev_page_btn.setEnabled(self._current_page_idx > 0)
            self.next_page_btn.setEnabled(
                self._current_page_idx < len(self._page_numbers) - 1
            )

    def _on_save_and_train_clicked(self) -> None:
        verified = self._verified_states()
        if not verified:
            QMessageBox.information(
                self,
                "אימות שורות",
                "יש לסמן לפחות שורה אחת ב-'✓ אומת כפי שנכתב' (עריכה לבדה אינה מסמנת שורה כמאומתת).",
            )
            return
        if not self.confirm_exact_checkbox.isChecked():
            QMessageBox.information(
                self,
                "אישור שלב א׳",
                "יש לאשר בתחתית החלון שהשורות המאומתות נבדקו כפי שנכתבו בדף לפני עריכת דקדוק.",
            )
            return

        writer_id = self.selected_writer_id
        self.committed_writer_id = writer_id
        self._set_writer_controls_enabled(False)
        self._set_review_controls_enabled(False)

        try:
            saved = self._persist_all_reviewed_states(
                grammar_confirmed_for_verified=True
            )
        except Exception as exc:
            self._set_writer_controls_enabled(True)
            self._set_review_controls_enabled(True)
            QMessageBox.warning(self, "שמירת שורות מאומתות", str(exc))
            return

        self.saved_samples_count = sum(
            1 for s in saved if s.review_status == STATUS_VERIFIED
        )
        self.updated_diplomatic_transcription = (
            self._assemble_diplomatic_transcription()
        )
        store_root = self.store.root

        self.progress_bar.setVisible(True)
        self.save_draft_btn.setEnabled(False)
        self.save_and_train_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.selection_summary_label.setText(
            f"נשמרו {self.saved_samples_count} שורות מאומתות. בודק התאמה אישית מול קבוצת בקרה נפרדת..."
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
            "בדיקת התאמה אישית",
            f"השורות נשמרו במאגר המקומי ({self.saved_samples_count} שורות מאומתות), "
            f"אך אימון המתאם האישי נתקל בשגיאה:\n{message}",
        )
        self.accept()

    def _on_training_finished(self) -> None:
        self.progress_bar.setVisible(False)
        self.save_draft_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self._set_writer_controls_enabled(True)
        self._set_review_controls_enabled(True)
        self._train_task = None
        self._update_summary_and_buttons()

    def reject(self) -> None:
        if self._train_task is not None and self._train_task.isRunning():
            return
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._train_task is not None and self._train_task.isRunning():
            self._train_task.cancel()
            if not self._train_task.wait(2500):
                event.ignore()
                return
        self._rendered_page_lru.clear()
        super().closeEvent(event)
