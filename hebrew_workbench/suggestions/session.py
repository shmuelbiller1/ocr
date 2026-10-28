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

#: The number of the characters around a correction that are kept, so
#: that the correction can be found again in a text that was written by
#: hand after it.
CONTEXT_SIZE = 40


def _is_word_letter(character: str) -> bool:
    """Is this character a part of a word?

    A letter or a digit is a part of a word, and a space or a mark of
    punctuation is not.  It is used to find a word as a whole word and
    not as a part of a longer one.
    """
    if not character:
        return False
    return character.isalnum() or character == "_"


def _place_of_change(change: "AcceptedChange", text: str) -> int | None:
    """Where the correction is in the text.

    The place is looked for with the text that surrounded the
    correction when it was accepted, so that a correction is not taken
    back in a place where the user wrote something else.  When the
    place cannot be found, or when the same text is in two places near
    it, nothing is returned: a correction that cannot be told apart is
    not taken back.

    When the text around the correction was changed by another
    correction that was accepted later, the place of the correction is
    used, because the text around it is not the text that was kept.
    """
    if not change.replacement:
        return None
    start = change.position
    end = start + len(change.replacement)
    if change.before or change.after:
        if not change.context_stale:
            low = max(0, start - 200)
            high = min(len(text), end + 200)
            piece = change.before + change.replacement + change.after
            found = text.find(piece, low, high)
            if found < 0:
                return None
            if text.find(piece, found + 1, high) >= 0:
                # The same text is in two places, and the place of the
                # correction cannot be told.
                return None
            return found + len(change.before)
    # The change comes from a project that was saved before the text
    # around it was kept, or the text around it was changed by another
    # correction: only the place is known.
    if text[start:end] == change.replacement:
        return start
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
        before: str = "",
        after: str = "",
        batch: int = 0,
    ) -> None:
        self.module = module
        self.original = original
        self.replacement = replacement
        self.position = position
        self.message = message
        # The text that surrounds the change, so that the change can be
        # found again in a text that was written by hand after it.
        self.before = before
        self.after = after
        # The number of the group of changes that this change is part
        # of.  Zero means that it was accepted on its own.  A group can
        # be taken back as one action.
        self.batch = batch
        # Is the text around the change still the text that was kept?
        # It is not when another correction was accepted later and
        # touched it.
        self.context_stale = False

    def describe(self) -> str:
        return f"{self.original} → {self.replacement}"

    def to_dict(self) -> dict:
        return {
            "module": self.module,
            "original": self.original,
            "replacement": self.replacement,
            "position": self.position,
            "message": self.message,
            "before": self.before,
            "after": self.after,
            "batch": self.batch,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AcceptedChange":
        return cls(
            module=str(data.get("module", "")),
            original=str(data.get("original", "")),
            replacement=str(data.get("replacement", "")),
            position=int(data.get("position", 0)),
            message=str(data.get("message", "")),
            before=str(data.get("before", "")),
            after=str(data.get("after", "")),
            batch=int(data.get("batch", 0) or 0),
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
        # The number of the last group of changes that the user made at
        # once.  Every group has a number of its own, so that a group
        # can be taken back as one action.
        self._batch_number = 0

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
    def accept(
        self, suggestion: Suggestion, batch: int = 0
    ) -> tuple[str, int] | None:
        """Accept a proposal.

        Returns the new text of the document and the place of the change
        in it, or ``None`` when the proposal does not fit the text any
        more (because another change was made in the same place).

        The number of the group of changes is given, so that several
        changes that the user made at once can be taken back as one
        action.
        """
        place = self.place_of(suggestion)
        if place is None:
            return None
        start, end = place
        new_text = self.current_text[:start] + suggestion.replacement + self.current_text[end:]
        # The changes that were accepted before this one and that are
        # after it in the text move to the right, so that the place of
        # every change is the place it has in the text as it is now.
        shift = len(suggestion.replacement) - len(suggestion.original)
        stop = start + len(suggestion.replacement)
        for change in self.accepted:
            if change.position >= start:
                change.position += shift
            # The text around the change is not the text that was kept
            # when the new correction touches it.
            first = change.position - len(change.before)
            last = change.position + len(change.replacement) + len(change.after)
            if start < last and first < stop:
                change.context_stale = True
        self.accepted.append(
            AcceptedChange(
                module=suggestion.module,
                original=suggestion.original,
                replacement=suggestion.replacement,
                position=start,
                message=suggestion.message,
                before=new_text[max(0, start - CONTEXT_SIZE) : start],
                after=new_text[
                    start
                    + len(suggestion.replacement) : start
                    + len(suggestion.replacement)
                    + CONTEXT_SIZE
                ],
                batch=batch,
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

    # -- several proposals at once ----------------------------------------
    def accept_many(
        self, suggestions: list[Suggestion]
    ) -> tuple[str, list[AcceptedChange]] | None:
        """Accept several proposals as one action.

        The proposals that do not fit the text any more - because
        another proposal was applied to the same place - are refused,
        so that they do not stay in the list of the proposals that are
        waiting for an answer.

        The ones that are accepted are remembered as one group, so
        that the user can take them back as one action.

        Returns the new text and the changes that were made, or
        ``None`` when not one proposal could be applied.
        """
        wanted = list(suggestions)
        if not wanted:
            return None
        self._batch_number += 1
        batch = self._batch_number
        changes: list[AcceptedChange] = []
        applied: set[int] = set()
        for suggestion in wanted:
            before = len(self.accepted)
            outcome = self.accept(suggestion, batch=batch)
            if outcome is None:
                continue
            if len(self.accepted) > before:
                changes.append(self.accepted[-1])
                applied.add(id(suggestion))
        for suggestion in wanted:
            if id(suggestion) not in applied:
                # The proposal was overtaken by another one in the same
                # place, and it cannot be applied any more.
                self.refuse(suggestion)
        if not changes:
            # Nothing was applied: the group is empty, and it is not
            # remembered.
            self._batch_number -= 1
            return None
        return self.current_text, changes

    def accept_every_occurrence(
        self, suggestion: Suggestion
    ) -> tuple[str, list[AcceptedChange]] | None:
        """Accept a proposal in every place where its word appears.

        The word is looked for as a whole word, so that a word that is
        a part of another word is not changed.  Every place is changed
        as one group, and the group can be taken back as one action.
        """
        word = suggestion.original
        if not word:
            return None
        text = self.current_text
        places = []
        start = text.find(word)
        while start >= 0:
            before = text[start - 1] if start > 0 else " "
            after = text[start + len(word)] if start + len(word) < len(text) else " "
            if not _is_word_letter(before) and not _is_word_letter(after):
                places.append(start)
            start = text.find(word, start + 1)
        if not places:
            return None
        proposals = [
            Suggestion(
                module=suggestion.module,
                original=word,
                replacement=suggestion.replacement,
                message=suggestion.message,
                start=place,
                end=place + len(word),
                kind=suggestion.kind,
                alternatives=suggestion.alternatives,
            )
            for place in places
        ]
        return self.accept_many(proposals)

    @property
    def has_batch(self) -> bool:
        """Is there a group of changes that can be taken back as one?"""
        return any(change.batch for change in self.accepted)

    def undo_last_batch(self, text: str | None = None) -> str | None:
        """Take back the last group of changes, as one action.

        The group is taken back in the order the changes were accepted,
        the last one first, so that a change that was made on the text
        of another one is taken back after it.

        ``None`` is returned when there is no group to take back.
        """
        batches = [change.batch for change in self.accepted if change.batch]
        if not batches:
            return None
        last = max(batches)
        result = self.current_text if text is None else text
        self.last_undo_skipped = []
        for change in reversed(list(self.accepted)):
            if change.batch != last:
                continue
            place = _place_of_change(change, result)
            if place is None:
                self.last_undo_skipped.append(change)
                continue
            result = (
                result[:place]
                + change.original
                + result[place + len(change.replacement) :]
            )
            shift = len(change.original) - len(change.replacement)
            for other in self.accepted:
                if other is not change and other.position >= place:
                    other.position += shift
        self.current_text = result
        self.accepted = [
            change for change in self.accepted if change.batch != last
        ]
        self._round_shifts = []
        # The proposals of the last round have the places of the text
        # as it was before the changes were taken back, and they are of
        # no use now.
        self.suggestions = []
        self.refused = []
        return result

    def undo_all(self, text: str | None = None) -> str:
        """Take back every change that was accepted, and return the text.

        When the text of the editor is given, the corrections are taken
        back in that text, so that what the user wrote after them is
        kept.

        The corrections are taken back in the order they were accepted,
        the last one first, so that a correction that was made on the
        text of another one is taken back after it.

        A correction is only taken back where it really is: the place is
        looked for with the text that surrounded it when it was
        accepted.  A correction whose place cannot be found is not taken
        back at all, so that a text that was never corrected is not
        changed.  The corrections that were not taken back are in
        ``last_undo_skipped``.
        """
        result = self.current_text if text is None else text
        self.last_undo_skipped = []
        for change in reversed(list(self.accepted)):
            if not change.replacement:
                continue
            place = _place_of_change(change, result)
            if place is None:
                self.last_undo_skipped.append(change)
                continue
            result = (
                result[:place]
                + change.original
                + result[place + len(change.replacement) :]
            )
            # The changes that are after this one in the text move to
            # the left, so that the place of every change is the place
            # it has in the text as it is now.
            shift = len(change.original) - len(change.replacement)
            for other in self.accepted:
                if other is not change and other.position >= place:
                    other.position += shift
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
