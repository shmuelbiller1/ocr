"""The session of the proposals: what is waiting, and what was accepted.

The session keeps the proposals of one text and the changes that the
user accepted.  It never changes the text itself: the interface asks
the session what to write, and the session says what the text looks
like after a change was accepted.

Every accepted change is remembered, so that it can be taken back.
"""

from __future__ import annotations

from .base import Suggestion

__all__ = ["SuggestionSession", "AcceptedChange"]


class AcceptedChange:
    """One change that the user accepted."""

    def __init__(
        self,
        module: str,
        original: str,
        replacement: str,
        position: int,
        message: str = "",
    ) -> None:
        self.module = module
        self.original = original
        self.replacement = replacement
        self.position = position
        self.message = message

    def describe(self) -> str:
        return f"{self.original} → {self.replacement}"

    def to_dict(self) -> dict:
        return {
            "module": self.module,
            "original": self.original,
            "replacement": self.replacement,
            "position": self.position,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AcceptedChange":
        return cls(
            module=str(data.get("module", "")),
            original=str(data.get("original", "")),
            replacement=str(data.get("replacement", "")),
            position=int(data.get("position", 0)),
            message=str(data.get("message", "")),
        )


class SuggestionSession:
    """The proposals of one text and the changes that were accepted."""

    def __init__(self, text: str = "") -> None:
        self.current_text: str = text
        self.suggestions: list[Suggestion] = []
        self.accepted: list[AcceptedChange] = []
        self.refused: list[Suggestion] = []

    # -- the proposals -----------------------------------------------------
    def set_suggestions(self, suggestions: list[Suggestion], text: str | None = None) -> None:
        """Start a new round of proposals."""
        self.suggestions = list(suggestions)
        if text is not None:
            self.current_text = text
        self.refused = []

    def pending(self) -> list[Suggestion]:
        """The proposals that the user did not decide about yet."""
        return [item for item in self.suggestions if item not in self.refused]

    def proposal(self, suggestion: Suggestion) -> Suggestion | None:
        """The proposal with the same text, if it is still waiting."""
        for item in self.suggestions:
            if item is suggestion:
                return item
            if (
                item.module == suggestion.module
                and item.start == suggestion.start
                and item.end == suggestion.end
                and item.original == suggestion.original
            ):
                return item
        return None

    def remove(self, suggestion: Suggestion) -> None:
        """Take a proposal out of the list."""
        self.suggestions = [item for item in self.suggestions if item is not suggestion]

    def refuse(self, suggestion: Suggestion) -> None:
        """The user does not want this proposal."""
        self.refused.append(suggestion)

    # -- the places in the text --------------------------------------------
    def shift(self, position: int) -> int:
        """Where a place of the old text is in the text after the changes."""
        shift = 0
        for change in self.accepted:
            if change.position + len(change.original) <= position:
                shift += len(change.replacement) - len(change.original)
        return position + shift

    def place_of(self, suggestion: Suggestion) -> tuple[int, int] | None:
        """Where the text of a proposal is now, after the accepted changes."""
        start = self.shift(suggestion.start)
        end = start + len(suggestion.original)
        if end > len(self.current_text):
            return None
        if self.current_text[start:end] != suggestion.original:
            return None
        return start, end

    # -- accepting and refusing --------------------------------------------
    def accept(self, suggestion: Suggestion) -> tuple[str, int] | None:
        """Accept a proposal.

        Returns the new text of the document and the place of the change
        in it, or ``None`` when the proposal does not fit the text any
        more (because another change was made in the same place).
        """
        place = self.place_of(suggestion)
        if place is None:
            return None
        start, end = place
        new_text = self.current_text[:start] + suggestion.replacement + self.current_text[end:]
        self.accepted.append(
            AcceptedChange(
                module=suggestion.module,
                original=suggestion.original,
                replacement=suggestion.replacement,
                position=start,
                message=suggestion.message,
            )
        )
        self.current_text = new_text
        self.remove(suggestion)
        self.refused = [item for item in self.refused if item is not suggestion]
        return new_text, start

    def undo_all(self) -> str:
        """Take back every change that was accepted, and return the text."""
        for change in reversed(self.accepted):
            start = change.position
            end = start + len(change.replacement)
            if self.current_text[start:end] == change.replacement:
                self.current_text = (
                    self.current_text[:start] + change.original + self.current_text[end:]
                )
        self.accepted = []
        return self.current_text

    def change_log(self) -> list[dict]:
        """The changes that were accepted, for the file of the project."""
        return [change.to_dict() for change in self.accepted]
