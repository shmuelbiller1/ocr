"""The modules of the program, and the switch of every one of them.

The spelling, the grammar and the scholarly style are three separate
modules.  Every module has its own switch, so that a user who does not
want proposals about grammar does not get them, and a user who does
not want the scholarly style rules does not get them either.
"""

from __future__ import annotations

from .base import KIND_GRAMMAR, KIND_SPELLING, KIND_STYLE, Suggestion, SuggestionModule
from .grammar import GrammarModule
from .spelling import SpellingModule
from .style import StyleModule

__all__ = ["SuggestionRegistry", "default_modules"]


def default_modules() -> list[SuggestionModule]:
    """The modules that the program starts with."""
    return [SpellingModule(), GrammarModule(), StyleModule()]


class SuggestionRegistry:
    """Keeps the modules and asks them for proposals."""

    def __init__(self, modules: list[SuggestionModule] | None = None) -> None:
        self.modules: list[SuggestionModule] = (
            modules if modules is not None else default_modules()
        )
        self._enabled: dict[str, bool] = {
            module.id: module.enabled_by_default for module in self.modules
        }

    # -- the modules -------------------------------------------------------
    def module(self, kind: str) -> SuggestionModule | None:
        """The module of a kind, e.g. ``spelling``."""
        for module in self.modules:
            if module.kind == kind or module.id == kind:
                return module
        return None

    def kinds(self) -> list[str]:
        """The kinds of the modules, in the order they are shown."""
        return [module.kind for module in self.modules]

    # -- the switch of every module ---------------------------------------
    def is_enabled(self, kind: str) -> bool:
        return bool(self._enabled.get(kind, False))

    def set_enabled(self, kind: str, enabled: bool) -> None:
        if kind in self._enabled:
            self._enabled[kind] = bool(enabled)

    def toggle(self, kind: str) -> bool:
        self.set_enabled(kind, not self.is_enabled(kind))
        return self.is_enabled(kind)

    # -- the proposals -----------------------------------------------------
    def check(self, text: str) -> list[Suggestion]:
        """The proposals of every module that is switched on."""
        proposals: list[Suggestion] = []
        for module in self.modules:
            if not self.is_enabled(module.kind):
                continue
            if not module.available():
                continue
            try:
                proposals.extend(module.check(text))
            except Exception:
                # A module that breaks must not stop the others, and it
                # must never change the text.
                continue
        proposals.sort(key=lambda item: (item.start, item.end, item.module))
        return proposals

    def status(self) -> list[str]:
        """One line per module, for the user."""
        lines: list[str] = []
        for module in self.modules:
            state = "פעיל" if self.is_enabled(module.kind) else "מושבת"
            if not module.available():
                state = f"{state} ({module.unavailable_reason()})"
            lines.append(f"{module.name}: {state}")
        return lines
