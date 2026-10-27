"""Running slow work without freezing the window."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QThread, Signal

__all__ = ["TaskThread"]


class TaskThread(QThread):
    """Runs a function in the background and reports what it does.

    The function receives a ``progress`` callable and a ``cancel``
    callable.  Cancelling only asks the function to stop at the next
    safe point; the thread never kills work in the middle of a write.
    """

    progress = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, function: Callable[[Callable[[str], None], Callable[[], bool]], object], parent=None) -> None:
        super().__init__(parent)
        self._function = function
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        """Was the job asked to stop?"""
        return self._cancelled

    def run(self) -> None:  # noqa: D102 - Qt override
        try:
            result = self._function(self.progress.emit, lambda: self._cancelled)
        except Exception as exc:
            if self._cancelled:
                # The user asked to stop, and the work reported that it
                # was stopped.  This is not a failure.
                self.cancelled.emit()
                return
            self.failed.emit(str(exc))
            return
        if self._cancelled:
            self.cancelled.emit()
            return
        self.succeeded.emit(result)
