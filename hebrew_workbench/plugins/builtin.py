"""The plugins that come with the program.

They are ordinary plugins: they have a manifest like every other
plugin, and the user can switch them off or leave them alone.  The
recognition engine is one of them, so that another Hebrew engine can be
added later without changing a line of the program.
"""

from __future__ import annotations

from .base import (
    KIND_GRAMMAR,
    KIND_OCR,
    KIND_SPELLING,
    KIND_STYLE,
    PluginManifest,
)

__all__ = ["BUILTIN_MANIFESTS", "builtin_manifests"]


#: The plugins that are part of the program.
BUILTIN_MANIFESTS: tuple[PluginManifest, ...] = (
    PluginManifest(
        id="kraken",
        name="Kraken + PP-OCRv6 (in the program)",
        version="1.0.0",
        kind=KIND_OCR,
        entry="hebrew_workbench.engine.kraken_local:make_engine",
        license="Apache-2.0",
        license_url="https://github.com/mittagessen/kraken",
        description="זיהוי כתב יד עברי עם kraken ומודל PP-OCRv6.",
        builtin=True,
        options={"model_id": "kraken-ppocrv6-small"},
    ),
    PluginManifest(
        id="kraken-worker",
        name="Kraken + PP-OCRv6 (תהליך נפרד)",
        version="1.0.0",
        kind=KIND_OCR,
        entry="hebrew_workbench.engine.worker:make_worker_engine",
        license="Apache-2.0",
        license_url="https://github.com/mittagessen/kraken",
        description=(
            "אותו מנוע, אבל בתהליך נפרד, כדי שהתוכנית לא תיתקע על זיהוי ארוך."
        ),
        builtin=True,
        options={"model_id": "kraken-ppocrv6-small"},
    ),
    PluginManifest(
        id="spelling-hebrew",
        name="בדיקת איות עברית",
        version="1.0.0",
        kind=KIND_SPELLING,
        entry="hebrew_workbench.suggestions.spelling:SpellingModule",
        license="MIT",
        license_url="https://opensource.org/license/mit",
        description="מילים שאינן במילון שהמשתמש בוחר.",
        builtin=True,
    ),
    PluginManifest(
        id="grammar-hebrew",
        name="בדיקת ניסוח עברית",
        version="1.0.0",
        kind=KIND_GRAMMAR,
        entry="hebrew_workbench.suggestions.grammar:GrammarModule",
        license="MIT",
        license_url="https://opensource.org/license/mit",
        description="פסיקים ורווחים: הצעות, ולא שינויים.",
        builtin=True,
    ),
    PluginManifest(
        id="style-leshon-ha-sefer",
        name="לשון הספר",
        version="0.1.0",
        kind=KIND_STYLE,
        entry="hebrew_workbench.suggestions.style:StyleModule",
        license="MIT",
        license_url="https://opensource.org/license/mit",
        description=(
            "מסגרת לכללי לשון הספר. הכללים עדיין לא כתובים, ולכן המודול "
            "כבוי ואינו מציע דבר."
        ),
        builtin=True,
        enabled_by_default=False,
    ),
)


def builtin_manifests() -> list[PluginManifest]:
    """The manifests of the built-in plugins, as a list."""
    return list(BUILTIN_MANIFESTS)
