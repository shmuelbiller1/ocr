"""Proposals for corrections: spelling, grammar and scholarly style.

The three kinds of proposals are three separate modules, and every
module has its own switch.  Nothing is ever changed without the user
accepting it.
"""

from __future__ import annotations

from .base import (
    KIND_GRAMMAR,
    KIND_SPELLING,
    KIND_STYLE,
    Suggestion,
    SuggestionModule,
)
from .grammar import GrammarModule
from .registry import SuggestionRegistry, default_modules
from .session import AcceptedChange, SuggestionSession
from .spelling import SpellingModule, load_word_list
from .style import PLANNED_RULES, StyleModule

__all__ = [
    "Suggestion",
    "SuggestionModule",
    "SuggestionRegistry",
    "SuggestionSession",
    "AcceptedChange",
    "SpellingModule",
    "GrammarModule",
    "StyleModule",
    "default_modules",
    "load_word_list",
    "PLANNED_RULES",
    "KIND_SPELLING",
    "KIND_GRAMMAR",
    "KIND_STYLE",
]
