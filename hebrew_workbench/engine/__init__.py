"""OCR engine adapters.

Every adapter implements the contract in :mod:`hebrew_workbench.engine.base`
and can be replaced without touching the user interface.
"""

from __future__ import annotations

from .base import (
    EngineError,
    EngineFailure,
    EngineTimeout,
    EngineUnavailable,
    OCREngine,
    OCRResult,
)
from .registry import DisabledEngine, EngineRegistry

__all__ = [
    "DisabledEngine",
    "EngineError",
    "EngineFailure",
    "EngineRegistry",
    "EngineTimeout",
    "EngineUnavailable",
    "OCREngine",
    "OCRResult",
]
