"""The shape of a correction proposal.

A proposal is never applied by itself.  The user sees it, and accepts
or refuses it.  Every module of the program - the spell checker, the
grammar rules and the scholarly style rules - produces proposals of
this shape, so that the interface does not have to know where a
proposal came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Suggestion", "SuggestionModule", "KIND_SPELLING", "KIND_GRAMMAR", "KIND_STYLE"]

#: The kinds of proposals.  Every kind is a separate module, and every
#: module can be switched on and off by itself.
KIND_SPELLING = "spelling"
KIND_GRAMMAR = "grammar"
KIND_STYLE = "style"


@dataclass(frozen=True)
class Suggestion:
    """One proposal to change the text of a document."""

    #: The module that made the proposal.
    module: str
    #: The text that is in the document now.
    original: str
    #: The text that is proposed instead.
    replacement: str
    #: What the proposal says, in words for the user.
    message: str = ""
    #: Where the text is in the document.
    start: int = 0
    end: int = 0
    #: What kind of change it is: a word, punctuation, or a style.
    kind: str = "text"
    #: Other possibilities, when the module knows more than one.
    alternatives: tuple[str, ...] = field(default_factory=tuple)

    def describe(self) -> str:
        """A line for the user, in words."""
        if self.original == self.replacement:
            return self.message or self.original
        return f"{self.original} → {self.replacement}"


class SuggestionModule:
    """The base of every module that proposes corrections.

    A module never changes the text of the document.  It only looks at
    the text and returns proposals, and the user decides what happens.
    """

    #: The identifier of the module, e.g. ``spelling``.
    id: str = ""
    #: The name of the module, for the user.
    name: str = ""
    #: What kind of proposals the module makes.
    kind: str = "text"
    #: What the module does, in one sentence.
    description: str = ""
    #: Whether the module is switched on when the program starts.
    enabled_by_default: bool = True

    def available(self) -> bool:
        """Can the module work at all right now?"""
        return True

    def unavailable_reason(self) -> str:
        """Why the module cannot work, for the user."""
        return ""

    def check(self, text: str) -> list[Suggestion]:
        """Look at the text and return the proposals."""
        raise NotImplementedError
