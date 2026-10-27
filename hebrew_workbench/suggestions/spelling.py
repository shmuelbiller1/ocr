"""The spelling module: proposals from a word list that the user brings.

The program does not ship a Hebrew dictionary.  The Hebrew Hunspell
dictionary of LibreOffice is under the AGPL, and it may not be given
away inside this program.  The module therefore works with a word list
that the user has, and it says whose word list it is and what licence
it has.

The word list is a text file with one word in every line.  A line may
hold the word and its alternatives, separated by a slash, the way a
Hunspell dictionary does::

    שלום/תחתונות
    בית

The first word of the line is the spelling that the list prefers, and
the words after the slash are the other spellings of the same word.
All of them are known words, and none of them is reported as a
mistake.  When the text holds one of the other spellings, the preferred
spelling is proposed for it, and the user decides.
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import KIND_SPELLING, Suggestion, SuggestionModule

__all__ = ["SpellingModule", "load_word_list"]

#: The letters of the word and the punctuation that is around it.
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

#: A word shorter than this is not proposed, because a short word is
#: often an abbreviation or a name.
MINIMUM_LENGTH = 4

#: The name of the file with the licence of the word list, if it is
#: next to it.
LICENCE_NAMES = ("LICENSE", "LICENSE.txt", "LICENCE", "COPYING")


def load_word_list(path: str | Path) -> dict[str, list[str]]:
    """Read a word list into a dictionary of words and alternatives."""
    words: dict[str, list[str]] = {}
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("/")
        word = parts[0].strip()
        if not word:
            continue
        alternatives = [part.strip() for part in parts[1:] if part.strip()]
        words[word] = alternatives
    return words


def build_spellings(words: dict[str, list[str]]) -> dict[str, list[str]]:
    """Every known spelling, with the spellings of its own word.

    The first spelling of a word is the one that the list prefers, and
    the others are the ways the word is also written.
    """
    spellings: dict[str, list[str]] = {}
    for word, alternatives in words.items():
        group = [word] + [item for item in alternatives if item != word]
        for member in group:
            spellings.setdefault(member, group)
    return spellings


class SpellingModule(SuggestionModule):
    """Proposes the words that are not in the word list of the user."""

    id = KIND_SPELLING
    name = "איות"
    kind = KIND_SPELLING
    description = "מציע מילים שאינן במילון שנבחר על יד המשתמש"

    def __init__(self) -> None:
        self._path: Path | None = None
        self._words: dict[str, list[str]] = {}
        # Every known spelling, with the spellings of its own word.
        self._spellings: dict[str, list[str]] = {}
        self._licence = ""

    # -- the word list of the user ----------------------------------------
    def set_dictionary(self, path: str | Path) -> None:
        """Use the word list of the user."""
        target = Path(path)
        if not target.is_file():
            raise FileNotFoundError(target)
        self._path = target
        self._words = load_word_list(target)
        self._spellings = build_spellings(self._words)
        self._licence = self._read_licence(target)

    @property
    def dictionary_path(self) -> Path | None:
        return self._path

    @property
    def word_count(self) -> int:
        return len(self._words)

    def licence_text(self) -> str:
        """The licence of the word list, if it was found next to it."""
        return self._licence

    def _read_licence(self, dictionary: Path) -> str:
        for name in LICENCE_NAMES:
            candidate = dictionary.parent / name
            if candidate.is_file():
                try:
                    return candidate.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    return ""
        return ""

    # -- the module itself ------------------------------------------------
    def available(self) -> bool:
        return self._path is not None and bool(self._words)

    def unavailable_reason(self) -> str:
        if self._path is None:
            return "לא נבחר מילון. יש לבחור מילון בתפריט 'הצעות תיקון'."
        return "המילון שנבחר אינו מכיל מילים."

    def check(self, text: str) -> list[Suggestion]:
        if not self.available():
            return []
        proposals: list[Suggestion] = []
        for match in WORD.finditer(text):
            word = match.group(0)
            if len(word) < MINIMUM_LENGTH:
                continue
            group = self._spellings.get(word)
            if group is None:
                # The word is not in the list of the user at all.
                proposals.append(
                    Suggestion(
                        module=self.id,
                        original=word,
                        replacement=word,
                        message="המילה אינה במילון",
                        start=match.start(),
                        end=match.end(),
                        kind="word",
                    )
                )
                continue
            if word == group[0]:
                # The word is written the way the list prefers it.
                continue
            # The word is one of the other spellings, so the spelling
            # that the list prefers is proposed for it.
            others = [item for item in group if item != word]
            proposal = Suggestion(
                module=self.id,
                original=word,
                replacement=others[0],
                message="אפשרות נוספת למילה",
                start=match.start(),
                end=match.end(),
                kind="word",
                alternatives=tuple(others[1:]),
            )
            proposals.append(proposal)
            proposals.extend(self.proposals_with_alternatives([proposal]))
        return proposals

    def proposals_with_alternatives(self, proposals: list[Suggestion]) -> list[Suggestion]:
        """The proposals that have other possibilities, with the first one."""
        result: list[Suggestion] = []
        for proposal in proposals:
            if not proposal.alternatives:
                continue
            result.append(
                Suggestion(
                    module=proposal.module,
                    original=proposal.original,
                    replacement=proposal.alternatives[0],
                    message=proposal.message,
                    start=proposal.start,
                    end=proposal.end,
                    kind=proposal.kind,
                    alternatives=proposal.alternatives[1:],
                )
            )
        return result
