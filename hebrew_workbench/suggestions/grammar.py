"""The grammar module: proposals about punctuation and spacing.

The rules are the simple ones that a text editor can check without a
language model: a space before a comma, a missing space after a comma,
two spaces in a row, and a space before a closing quote.

Every rule is a separate function, so that a rule can be taken out or
added without touching the others.
"""

from __future__ import annotations

import re

from .base import KIND_GRAMMAR, Suggestion, SuggestionModule

__all__ = ["GrammarModule"]


def _proposal(
    text: str, start: int, end: int, replacement: str, message: str
) -> Suggestion:
    return Suggestion(
        module=KIND_GRAMMAR,
        original=text[start:end],
        replacement=replacement,
        message=message,
        start=start,
        end=end,
        kind="punctuation",
    )


def space_before_comma(text: str) -> list[Suggestion]:
    """A comma is written without a space before it."""
    proposals: list[Suggestion] = []
    for match in re.finditer(r" +([,;])", text):
        proposals.append(
            _proposal(
                text,
                match.start(),
                match.end(),
                match.group(1),
                "אין רווח לפני הפסיק",
            )
        )
    return proposals


def space_after_comma(text: str) -> list[Suggestion]:
    """A comma is written with a space after it."""
    proposals: list[Suggestion] = []
    for match in re.finditer(r"([,;])(?=[^\s\d])", text):
        proposals.append(
            _proposal(
                text,
                match.start(),
                match.end(),
                match.group(1) + " ",
                "חסר רווח אחרי הפסיק",
            )
        )
    return proposals


def double_space(text: str) -> list[Suggestion]:
    """Two spaces in a row are written as one."""
    proposals: list[Suggestion] = []
    for match in re.finditer(r" {2,}", text):
        proposals.append(
            _proposal(text, match.start(), match.end(), " ", "יותר מרווח אחד")
        )
    return proposals


def space_before_closing_quote(text: str) -> list[Suggestion]:
    """A closing quote is written without a space before it."""
    proposals: list[Suggestion] = []
    for match in re.finditer(r" +([\"״»])", text):
        proposals.append(
            _proposal(
                text,
                match.start(),
                match.end(),
                match.group(1),
                "אין רווח לפני הגרשיים",
            )
        )
    return proposals


#: The rules of the module, in the order they are applied.
RULES = (
    space_before_comma,
    space_after_comma,
    double_space,
    space_before_closing_quote,
)


class GrammarModule(SuggestionModule):
    """Proposes the small corrections of punctuation and spacing."""

    id = KIND_GRAMMAR
    name = "ניסוח"
    kind = KIND_GRAMMAR
    description = "מציע תיקוני סימני פיסוק ורווחים"

    def check(self, text: str) -> list[Suggestion]:
        proposals: list[Suggestion] = []
        for rule in RULES:
            proposals.extend(rule(text))
        proposals.sort(key=lambda item: (item.start, item.end))
        return proposals
