"""Experimental acceptance-only modern Hebrew supplement to Hspell.

A word in the supplementary list is considered known, never used to invent a
replacement. All other words use the unmodified Hspell affix engine. This is
not an independent verification that every supplemented word is correct.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .hspell_base import HunspellSpelling

# Pin the data independently of any editable manifest; a modified or truncated
# supplement must not turn a spellcheck into a falsely successful check.
MODERN_SIZE = 2670751
MODERN_SHA256 = '30a01c45da1381637da708d74af81c0f1b4ad225d9a3a85252683217fe107be3'
MODERN_COUNT = 196227


class ModernHebrewSpelling(HunspellSpelling):
    name = 'איות עברי מודרני (ניסיוני)'

    def __init__(self, options=None):
        path = Path(__file__).resolve().parent / 'data' / 'modern-words.txt'
        try:
            data = path.read_bytes()
            if len(data) != MODERN_SIZE or hashlib.sha256(data).hexdigest() != MODERN_SHA256:
                raise ValueError('Supplement failed integrity verification')
            words = data.decode('utf-8').splitlines()
            if len(words) != MODERN_COUNT or len(set(words)) != MODERN_COUNT:
                raise ValueError('Supplement has invalid word count')
            if any(not w or len(w) > 64 or not all('א' <= c <= 'ת' for c in w) for w in words):
                raise ValueError('Supplement has invalid Hebrew word data')
            self._modern_words = frozenset(words)
        except (OSError, ValueError, UnicodeError) as exc:
            raise OSError(f'Modern Hebrew supplement unavailable: {exc}') from exc
        super().__init__(options)

    def _lookup(self, words):
        modern = {word: (True, ()) for word in words if word in self._modern_words}
        remaining = [word for word in words if word not in modern]
        # Do not strip prefixes from the supplement: arbitrary prefix peeling
        # turns misspellings into apparent valid words. Hspell handles its own
        # known morphological prefixes as before.
        if remaining:
            modern.update(super()._lookup(remaining))
        return modern
