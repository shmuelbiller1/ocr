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

# The sizes of the text around a correction that are used to find it
# back in a text that was written by hand after it.
CONTEXT_SIZES = (40, 20, 10)


def _place_of_change(change: "AcceptedChange", old: str, new: str) -> int | None:
    """Where the correction is in the new text.

    The place is looked for with the text that surrounds the
    correction, so that a correction is not taken back in a place where
    the user wrote something else.  When the place cannot be found, or
    when the same text is in more than one place, nothing is returned:
    a correction that cannot be told apart is not taken back.
    """
    start = change.position
    end = start + len(change.replacement)
    for size in CONTEXT_SIZES:
        before = old[max(0, start - size) : start]
        after = old[end : end + size]
        piece = before + change.replacement + after
        found = new.find(piece)
        if found < 0:
            continue
        if new.find(piece, found + 1) >= 0:
            # The same text is in two places, and the place of the
            # correction cannot be told.
            continue
        return found + len(before)
    return None


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
        # The corrections that could not be taken back in the last time
        # the user took back the corrections.
        self.last_undo_skipped: list[AcceptedChange] = []
        # The places of the proposals of the last round, and the change
        # every accepted correction made to the length of the text.
        # The proposals keep the places they had when the round began,
        # so only the corrections of this round may move them.
        self._round_shifts: list[tuple[int, int]] = []

    # -- the proposals -----------------------------------------------------
    def set_suggestions(self, suggestions: list[Suggestion], text: str | None = None) -> None:
        """Start a new round of proposals.

        The proposals of the new round have their places in the text as
        it is now.  The corrections of the earlier rounds are kept, so
        that they can still be taken back, but they do not move the new
        places any more.
        """
        self.suggestions = list(suggestions)
        if text is not None:
            self.current_text = text
        self.refused = []
        self._round_shifts = []

    def pending(self) -> list[Suggestion]:
        """The proposals that the user did not decide about yet."""
        return [item for item in self.suggestions if item not in self.refused]

    @property
    def undo_available(self) -> bool:
        """Is there something that can be taken back?"""
        return bool(self.accepted)

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
        for end, change in self._round_shifts:
            if end <= position:
                shift += change
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
        # The proposals of this round keep the places of the text as it
        # was when the round began, so the correction is remembered in
        # those places and not in the place of the new text.
        self._round_shifts.append(
            (
                suggestion.start + len(suggestion.original),
                len(suggestion.replacement) - len(suggestion.original),
            )
        )
        self.remove(suggestion)
        self.refused = [item for item in self.refused if item is not suggestion]
        return new_text, start

    def undo_all(self, text: str | None = None) -> str:
        """Take back every change that was accepted, and return the text.

        When the text of the editor is given, the corrections are taken
        back in that text, so that what the user wrote after them is
        kept.

        A correction is only taken back where it really is: the place is
        looked for with the text around the correction.  A correction
        whose place cannot be found is not taken back at all, so that a
        text that was never corrected is not changed.  The corrections
        that were not taken back are in ``last_undo_skipped``.
        """
        result = self.current_text if text is None else text
        source = self.current_text
        self.last_undo_skipped = []
        places: list[tuple[int, AcceptedChange]] = []
        for change in self.accepted:
            if not change.replacement:
                continue
            place = _place_of_change(change, source, result)
            if place is None:
                self.last_undo_skipped.append(change)
                continue
            places.append((place, change))
        # The corrections are taken back from the last one to the first
        # one, so that the place of a correction is not moved by the
        # taking back of another one.
        for place, change in sorted(places, key=lambda item: item[0], reverse=True):
            result = (
                result[:place]
                + change.original
                + result[place + len(change.replacement) :]
            )
        self.current_text = result
        self.accepted = []
        self._round_shifts = []
        # The proposals of the last round have the places of the text
        # as it was before the corrections were taken back, and they
        # are of no use now.  They are taken away, so that a proposal
        # is never applied to a place that it does not belong to; the
        # user has to check the suggestions again.
        self.suggestions = []
        self.refused = []
        return result

    # -- the changes of a project ------------------------------------------
    def restore_accepted(self, changes: list[dict]) -> None:
        """Take the corrections of a saved project back into the session.

        The changes are kept, so that they can be taken back, and the
        places of the proposals of the next round are not moved by them.
        """
        self.accepted = [AcceptedChange.from_dict(change) for change in changes]
        self._round_shifts = []

    def change_log(self) -> list[dict]:
        """The changes that were accepted, for the file of the project."""
        return [change.to_dict() for change in self.accepted]
