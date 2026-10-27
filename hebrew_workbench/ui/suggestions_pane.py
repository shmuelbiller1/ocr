"""The pane that shows the proposals for corrections.

The pane only shows things and sends the wishes of the user.  It never
changes the text of the document by itself: the window does that, and
only when the user pressed "accept".
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
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

    def __init__(self, suggestion: Suggestion, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.suggestion = suggestion
        self.setFrameShape(QFrame.StyledPanel)
        self.setLayoutDirection(Qt.RightToLeft)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        title = QLabel(suggestion.describe())
        title.setWordWrap(True)
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(title)

        if suggestion.message:
            message = QLabel(suggestion.message)
            message.setWordWrap(True)
            message.setStyleSheet("color: #555;")
            layout.addWidget(message)

        if suggestion.alternatives:
            alternatives = QLabel("אפשרויות נוספות: " + ", ".join(suggestion.alternatives))
            alternatives.setWordWrap(True)
            alternatives.setStyleSheet("color: #555;")
            layout.addWidget(alternatives)

        buttons = QHBoxLayout()
        accept = QPushButton("קבל")
        accept.clicked.connect(lambda: self.accept_requested.emit(self.suggestion))
        refuse = QPushButton("דחה")
        refuse.clicked.connect(lambda: self.refuse_requested.emit(self.suggestion))
        buttons.addWidget(accept)
        buttons.addWidget(refuse)
        buttons.addStretch(1)
        layout.addLayout(buttons)


class SuggestionsPane(QWidget):
    """The proposals of the document that is open."""

    check_requested = Signal()
    undo_requested = Signal()
    accept_requested = Signal(object)
    refuse_requested = Signal(object)

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
        self.undo_button = QPushButton("ביטול כל השינויים")
        self.undo_button.clicked.connect(self.undo_requested.emit)
        self.undo_button.setEnabled(False)
        buttons.addWidget(self.check_button)
        buttons.addWidget(self.undo_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

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
        """Show the proposals that are waiting."""
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
            self.rows_layout.insertWidget(self.rows_layout.count() - 1, row)
            self._rows.append(row)
        if suggestions:
            self.summary.setText(f"יש {len(suggestions)} הצעות לבחירה.")
        else:
            self.summary.setText("אין הצעות.")
        self.undo_button.setEnabled(False)

    def set_undo_available(self, available: bool) -> None:
        self.undo_button.setEnabled(bool(available))

    def clear(self) -> None:
        self.show_suggestions([])
