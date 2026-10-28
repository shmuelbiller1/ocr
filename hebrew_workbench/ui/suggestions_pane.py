"""The pane that shows the proposals for corrections.

The pane only shows things and sends the wishes of the user.  It never
changes the text of the document by itself: the window does that, and
only when the user pressed a button.

Every proposal has its own buttons, and the pane has buttons for the
proposals as a whole: accept all of them, refuse all of them, accept
the ones that were checked, and take back the last group of changes as
one action.  Nothing is applied without the user pressing something.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..suggestions.base import Suggestion

__all__ = ["SuggestionsPane"]


class SuggestionRow(QFrame):
    """One proposal, with the buttons to accept it or to refuse it."""

    accept_requested = Signal(object)
    refuse_requested = Signal(object)
    every_occurrence_requested = Signal(object)
    keep_word_requested = Signal(object)
    alternative_chosen_requested = Signal(object, str)

    def __init__(self, suggestion: Suggestion, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.suggestion = suggestion
        self.setFrameShape(QFrame.StyledPanel)
        self.setLayoutDirection(Qt.RightToLeft)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        top = QHBoxLayout()
        self.checkbox = QCheckBox()
        self.checkbox.setToolTip("סמן את ההצעה כדי לקבל או לדחות אותה עם שאר המסומנות")
        top.addWidget(self.checkbox)
        title = QLabel(suggestion.describe())
        title.setWordWrap(True)
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        top.addWidget(title, 1)
        layout.addLayout(top)

        if suggestion.message:
            message = QLabel(suggestion.message)
            message.setWordWrap(True)
            message.setStyleSheet("color: #555;")
            layout.addWidget(message)

        self.alternatives = None
        choices = [suggestion.replacement] + [
            item for item in suggestion.alternatives if item != suggestion.replacement
        ]
        if len(choices) > 1:
            self.alternatives = QComboBox()
            self.alternatives.addItems(choices)
            self.alternatives.setToolTip("אפשר לבחור ניסוח אחר לפני שמקבלים")
            self.alternatives.currentTextChanged.connect(self._alternative_changed)
            row = QHBoxLayout()
            row.addWidget(QLabel("אפשרות:"))
            row.addWidget(self.alternatives, 1)
            layout.addLayout(row)

        buttons = QHBoxLayout()
        accept = QPushButton("קבל")
        accept.clicked.connect(lambda: self.accept_requested.emit(self.suggestion))
        refuse = QPushButton("דחה")
        refuse.clicked.connect(lambda: self.refuse_requested.emit(self.suggestion))
        buttons.addWidget(accept)
        buttons.addWidget(refuse)
        if suggestion.kind == "word" and suggestion.original:
            every = QPushButton("בכל המקומות")
            every.setToolTip("לקבל את ההצעה בכל המקומות שבהם המילה מופיעה")
            every.clicked.connect(
                lambda: self.every_occurrence_requested.emit(self.suggestion)
            )
            buttons.addWidget(every)
            keep = QPushButton("לשמור את המילה")
            keep.setToolTip("להוסיף את המילה למילון של המשתמש")
            keep.clicked.connect(lambda: self.keep_word_requested.emit(self.suggestion))
            buttons.addWidget(keep)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def _alternative_changed(self, text: str) -> None:
        if text and text != self.suggestion.replacement:
            self.alternative_chosen_requested.emit(self.suggestion, text)

    @property
    def checked(self) -> bool:
        """Did the user mark this proposal?"""
        return self.checkbox.isChecked()


class SuggestionsPane(QWidget):
    """The proposals of the document that is open."""

    check_requested = Signal()
    undo_requested = Signal()
    undo_batch_requested = Signal()
    restore_original_requested = Signal()
    accept_requested = Signal(object)
    refuse_requested = Signal(object)
    every_occurrence_requested = Signal(object)
    keep_word_requested = Signal(object)
    alternative_chosen_requested = Signal(object, str)
    accept_selected_requested = Signal(list)
    refuse_selected_requested = Signal(list)
    accept_all_requested = Signal()
    refuse_all_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setLayoutDirection(Qt.RightToLeft)
        self._rows: list[SuggestionRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        title = QLabel("<b>הצעות תיקון</b>")
        layout.addWidget(title)

        self.summary = QLabel("אין עדיין הצעות.")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("color: #555;")
        layout.addWidget(self.summary)

        buttons = QHBoxLayout()
        self.check_button = QPushButton("בדיקת הצעות")
        self.check_button.clicked.connect(self.check_requested.emit)
        buttons.addWidget(self.check_button)
        layout.addLayout(buttons)

        bulk = QHBoxLayout()
        self.accept_all_button = QPushButton("קבל הכל")
        self.accept_all_button.setToolTip("לקבל את כל ההצעות שמוצגות")
        self.accept_all_button.clicked.connect(self.accept_all_requested.emit)
        self.refuse_all_button = QPushButton("דחה הכל")
        self.refuse_all_button.setToolTip("לדחות את כל ההצעות שמוצגות")
        self.refuse_all_button.clicked.connect(self.refuse_all_requested.emit)
        self.accept_selected_button = QPushButton("קבל מסומנות")
        self.accept_selected_button.setToolTip("לקבל את ההצעות שסומנו")
        self.accept_selected_button.clicked.connect(
            lambda: self.accept_selected_requested.emit(self.checked_suggestions())
        )
        self.refuse_selected_button = QPushButton("דחה מסומנות")
        self.refuse_selected_button.setToolTip("לדחות את ההצעות שסומנו")
        self.refuse_selected_button.clicked.connect(
            lambda: self.refuse_selected_requested.emit(self.checked_suggestions())
        )
        bulk.addWidget(self.accept_all_button)
        bulk.addWidget(self.refuse_all_button)
        bulk.addWidget(self.accept_selected_button)
        bulk.addWidget(self.refuse_selected_button)
        bulk.addStretch(1)
        layout.addLayout(bulk)

        more = QHBoxLayout()
        self.undo_batch_button = QPushButton("ביטול הפעולה האחרונה")
        self.undo_batch_button.setToolTip("לקחת בחזרה את הקבוצה האחרונה של השינויים")
        self.undo_batch_button.clicked.connect(self.undo_batch_requested.emit)
        self.undo_button = QPushButton("ביטול כל השינויים")
        self.undo_button.clicked.connect(self.undo_requested.emit)
        self.undo_button.setEnabled(False)
        self.restore_button = QPushButton("חזרה לטקסט המקורי")
        self.restore_button.setToolTip("לחזור לטקסט שהזיהוי נתן, לפני כל השינויים")
        self.restore_button.clicked.connect(self.restore_original_requested.emit)
        more.addWidget(self.undo_batch_button)
        more.addWidget(self.undo_button)
        more.addWidget(self.restore_button)
        more.addStretch(1)
        layout.addLayout(more)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.holder = QWidget()
        self.rows_layout = QVBoxLayout(self.holder)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.addStretch(1)
        self.scroll.setWidget(self.holder)
        layout.addWidget(self.scroll, 1)

    # -- what is shown -----------------------------------------------------
    def show_suggestions(self, suggestions: list[Suggestion]) -> None:
        """Show the proposals that are waiting.

        The button that takes back the corrections is not touched here:
        the window knows whether there is something to take back, and
        it says so with :meth:`set_undo_available`.
        """
        while self.rows_layout.count() > 1:
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows = []
        for suggestion in suggestions:
            row = SuggestionRow(suggestion)
            row.accept_requested.connect(self.accept_requested.emit)
            row.refuse_requested.connect(self.refuse_requested.emit)
            row.every_occurrence_requested.connect(self.every_occurrence_requested.emit)
            row.keep_word_requested.connect(self.keep_word_requested.emit)
            row.alternative_chosen_requested.connect(
                self.alternative_chosen_requested.emit
            )
            self.rows_layout.insertWidget(self.rows_layout.count() - 1, row)
            self._rows.append(row)
        if suggestions:
            self.summary.setText(f"יש {len(suggestions)} הצעות לבחירה.")
        else:
            self.summary.setText("אין הצעות.")
        self._set_bulk_enabled(bool(suggestions))

    def _set_bulk_enabled(self, enabled: bool) -> None:
        self.accept_all_button.setEnabled(enabled)
        self.refuse_all_button.setEnabled(enabled)
        self.accept_selected_button.setEnabled(enabled)
        self.refuse_selected_button.setEnabled(enabled)

    def checked_suggestions(self) -> list[Suggestion]:
        """The proposals that the user marked."""
        return [row.suggestion for row in self._rows if row.checked]

    def visible_suggestions(self) -> list[Suggestion]:
        """The proposals that are shown now."""
        return [row.suggestion for row in self._rows]

    def set_undo_available(self, available: bool) -> None:
        self.undo_button.setEnabled(bool(available))

    def set_batch_available(self, available: bool) -> None:
        self.undo_batch_button.setEnabled(bool(available))

    def set_restore_available(self, available: bool) -> None:
        self.restore_button.setEnabled(bool(available))

    def clear(self) -> None:
        self.show_suggestions([])
