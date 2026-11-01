"""Offline Hebrew spelling module: bundled CC0 lexicon + user wordlist support.

Supports two operating modes:
1. **Bundled modern Hebrew lexicon mode** (``options={"bundled": True}``, used by
   the built-in ``spelling-hebrew`` plugin out of the box): validates Hebrew
   tokens against the bundled ``CC0-1.0`` 196,227-word lexicon with productive
   proclitic prefix morphology, rabbinic/abbreviation safeguards, handwritten
   OCR optical-confusion ranking, and a persistent user personal dictionary.
2. **Custom user word-list mode** (``set_dictionary(path)``): reads a plain-text
   user word list with optional ``preferred/variant`` slash entries.

Bare ``SpellingModule()`` without ``options={"bundled": True}`` or
``set_dictionary(...)`` starts inactive until configured, preserving legacy
unit-test contracts.
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import KIND_SPELLING, Suggestion, SuggestionModule
from .hebrew_lexicon import (
    HEBREW_TOKEN_RE,
    HebrewLexicon,
    bundled_lexicon,
    personal_dictionary_path,
    strip_nikud,
)

__all__ = ["SpellingModule", "load_word_list"]

#: Token pattern for custom user word-list mode.
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

#: Minimum length for ordinary unknown words in custom word-list mode.
MINIMUM_LENGTH = 4

#: Licence filenames looked up next to custom user word lists.
LICENCE_NAMES = ("LICENSE", "LICENSE.txt", "LICENCE", "COPYING")


def load_word_list(path: str | Path) -> dict[str, list[str]]:
    """Read a custom user word list into a dictionary of words and alternatives."""
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
    """Every known spelling, with the spellings of its own word."""
    spellings: dict[str, list[str]] = {}
    for word, alternatives in words.items():
        group = [word] + [item for item in alternatives if item != word]
        for member in group:
            spellings.setdefault(member, group)
    for word, alternatives in words.items():
        group = [word] + [item for item in alternatives if item != word]
        spellings[word] = group
    return spellings


def _load_personal_words(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return set()
    out: set[str] = set()
    for line in lines:
        cleaned = strip_nikud(line.strip())
        if cleaned and not cleaned.startswith("#"):
            out.add(cleaned)
    return out


class SpellingModule(SuggestionModule):
    """Offline Hebrew spellchecker with OCR-confusion ranking and user wordlists."""

    id = KIND_SPELLING
    name = "איות"
    kind = KIND_SPELLING
    description = "בדיקת איות עברית לא-מקוונת עם דירוג הצעות מותאם ל-OCR ומילון אישי"

    def __init__(self, options: dict | None = None) -> None:
        self._path: Path | None = None
        self._words: dict[str, list[str]] = {}
        self._spellings: dict[str, list[str]] = {}
        self._licence = ""
        self._bundled = False
        self._lexicon: HebrewLexicon | None = None
        self._personal: set[str] = set()
        self._personal_path: Path | None = None
        if options:
            self.configure(options)

    # -- bundled offline lexicon ------------------------------------------
    def use_bundled_lexicon(self, personal_path: str | Path | None = None) -> None:
        """Activate the bundled CC0-1.0 Hebrew lexicon and personal dictionary."""
        self._lexicon = bundled_lexicon()
        self._bundled = True
        self._path = None
        self._words = {}
        self._spellings = {}
        self._personal_path = (
            Path(personal_path) if personal_path else personal_dictionary_path()
        )
        self._personal = _load_personal_words(self._personal_path)
        licence_file = (
            Path(__file__).resolve().parent / "data" / "LICENSE-CC0-1.0.txt"
        )
        if licence_file.is_file():
            try:
                self._licence = licence_file.read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                self._licence = "CC0-1.0"

    # -- custom word list of the user -------------------------------------
    def set_dictionary(self, path: str | Path) -> None:
        """Use an explicit custom word list chosen by the user."""
        target = Path(path)
        if not target.is_file():
            raise FileNotFoundError(target)
        self._bundled = False
        self._lexicon = None
        self._path = target
        self._words = load_word_list(target)
        self._spellings = build_spellings(self._words)
        self._licence = self._read_licence(target)

    @property
    def dictionary_path(self) -> Path | None:
        if self._path is not None:
            return self._path
        if self._bundled:
            return self._personal_path
        return None

    def keep_word(self, word: str) -> bool:
        """Remember ``word`` as valid so it is no longer flagged."""
        word = word.strip()
        if not word:
            return False
        if self._bundled and self._path is None:
            cleaned = strip_nikud(word)
            if not cleaned:
                return False
            already = cleaned in self._personal
            self._personal.add(cleaned)
            target = self._personal_path or personal_dictionary_path()
            self._personal_path = target
            if already:
                return True
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                return self._append_line(target, cleaned)
            except OSError:
                return False

        already = word in self._words
        if not already:
            self._words[word] = []
            self._spellings = build_spellings(self._words)
        return self._write_word(word, already)

    @staticmethod
    def _append_line(path: Path, word: str) -> bool:
        try:
            with path.open("a+b") as handle:
                handle.seek(0, 2)
                prefix = ""
                if handle.tell() > 0:
                    handle.seek(-1, 2)
                    if handle.read(1) not in (b"\n", b"\r"):
                        prefix = "\n"
                    handle.seek(0, 2)
                handle.write(f"{prefix}{word}\n".encode("utf-8"))
        except OSError:
            return False
        return True

    def _write_word(self, word: str, already: bool) -> bool:
        if already:
            return True
        path = self._path
        if path is None:
            return False
        return self._append_line(path, word)

    @property
    def word_count(self) -> int:
        if self._bundled and self._lexicon is not None:
            return len(self._lexicon.words) + len(self._personal)
        return len(self._words)

    def licence_text(self) -> str:
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

    def configure(self, options: dict) -> None:
        opts = dict(options or {})
        path = opts.get("dictionary")
        if path:
            try:
                self.set_dictionary(path)
                return
            except (OSError, ValueError):
                self._path = None
                self._words = {}
                self._bundled = False
                self._lexicon = None
                if not opts.get("bundled"):
                    return
        if opts.get("bundled"):
            personal = opts.get("personal_dictionary")
            self.use_bundled_lexicon(personal)

    # -- the module itself ------------------------------------------------
    def available(self) -> bool:
        if self._bundled and self._lexicon is not None:
            return True
        return self._path is not None and bool(self._words)

    def unavailable_reason(self) -> str:
        if self._path is None and not self._bundled:
            return "לא נבחר מילון. יש לבחור מילון בתפריט 'הצעות תיקון'."
        return "המילון שנבחר אינו מכיל מילים."

    def check(self, text: str) -> list[Suggestion]:
        if not self.available():
            return []
        if self._bundled and self._lexicon is not None:
            return self._check_bundled(text)
        return self._check_custom_wordlist(text)

    def _check_bundled(self, text: str) -> list[Suggestion]:
        assert self._lexicon is not None
        lexicon = self._lexicon
        # Refresh personal dictionary in case another window/session added words
        if self._personal_path is not None and self._personal_path.is_file():
            self._personal |= _load_personal_words(self._personal_path)

        tokens = list(HEBREW_TOKEN_RE.finditer(text))
        # Collect already-valid words in the current document to boost contextually
        # consistent spellings (e.g. a name or term repeated across the page).
        doc_known: set[str] = set()
        for m in tokens:
            tok = m.group(0)
            cleaned = strip_nikud(tok)
            if len(cleaned) >= 3 and lexicon.is_known(tok, self._personal):
                doc_known.add(cleaned)

        proposals: list[Suggestion] = []
        suggestion_cache: dict[str, list[str]] = {}
        for m in tokens:
            start, end = m.start(), m.end()
            # Skip tokens attached directly to Latin letters or digits
            if start > 0 and (text[start - 1].isascii() and text[start - 1].isalnum()):
                continue
            if end < len(text) and (text[end].isascii() and text[end].isalnum()):
                continue
            word = m.group(0)
            trimmed = word.rstrip('"״')
            if trimmed and '"' not in trimmed and "״" not in trimmed:
                end -= len(word) - len(trimmed)
                word = trimmed
            if lexicon.is_known(word, self._personal):
                continue

            cleaned = strip_nikud(word)
            candidates = suggestion_cache.get(cleaned)
            if candidates is None:
                candidates = lexicon.suggest(
                    word,
                    extra_words=self._personal,
                    document_words=doc_known,
                    limit=4,
                )
                suggestion_cache[cleaned] = candidates

            if candidates:
                proposals.append(
                    Suggestion(
                        module=self.id,
                        original=word,
                        replacement=candidates[0],
                        alternatives=tuple(candidates[1:]),
                        message="חשד לשגיאת כתיב או זיהוי OCR",
                        start=start,
                        end=end,
                        kind="word",
                    )
                )
            else:
                proposals.append(
                    Suggestion(
                        module=self.id,
                        original=word,
                        replacement=word,
                        message="המילה אינה במילון",
                        start=start,
                        end=end,
                        kind="word",
                    )
                )
        return proposals

    def _check_custom_wordlist(self, text: str) -> list[Suggestion]:
        proposals: list[Suggestion] = []
        for match in WORD.finditer(text):
            word = match.group(0)
            if len(word) < MINIMUM_LENGTH:
                continue
            group = self._spellings.get(word)
            if group is None:
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
                continue
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

    def proposals_with_alternatives(
        self, proposals: list[Suggestion]
    ) -> list[Suggestion]:
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
