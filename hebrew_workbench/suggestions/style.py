"""The scholarly style module (לשון הספר).

**This module does not do anything yet.**  It is a frame, and the
program says so where the user sees it: the module is switched off
until it has rules that were checked against the guide of the Israel
Academy of the Hebrew Language.

The reason it is not filled in with rules from memory: a rule of
לשון הספר that is wrong is worse than no rule at all, because the user
would have to check every proposal.  The rules that will be here are
written down in `PLANNED_RULES`, each one with the place in the guide
it comes from, and each one with a test.
"""

from __future__ import annotations

from .base import KIND_STYLE, Suggestion, SuggestionModule

__all__ = ["StyleModule", "PLANNED_RULES"]

#: The rules that will be here, and where each one comes from.  Every
#: rule needs a test before it is used.
PLANNED_RULES = [
    {
        "id": "no-extra-hyphen",
        "rule": "A maqaf is not used between a number and its unit.",
        "source": "הלשון הספר, כללי הכתיב המסורתי",
        "state": "not implemented",
    },
    {
        "id": "no-double-vav",
        "rule": "Two consecutive vav letters are not written.",
        "source": "הלשון הספר, כללי הכתיב המסורתי",
        "state": "not implemented",
    },
    {
        "id": "prefix-forms",
        "rule": "The prefixes of the letters are written in their short form.",
        "source": "הלשון הספר, פרק הכתיב המסורתי",
        "state": "not implemented",
    },
]


class StyleModule(SuggestionModule):
    """The frame of the scholarly style rules.

    The module is switched off when the program starts, and it never
    proposes anything until it has rules that were checked.
    """

    id = KIND_STYLE
    name = "לשון הספר"
    kind = KIND_STYLE
    description = "מסגרת לכללי לשון הספר. הכללים עדיין לא מיושמים"
    enabled_by_default = False

    def available(self) -> bool:
        return False

    def unavailable_reason(self) -> str:
        return "הכללים של לשון הספר עדיין לא מיושמים, ולכן המודול מושבת."

    def check(self, text: str) -> list[Suggestion]:
        """Nothing yet: the module has no rule."""
        return []
