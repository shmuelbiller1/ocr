"""The replaceable OCR engine contract.

An *engine* is anything that can turn a local document into text.  The
contract is intentionally tiny so that a new engine can be dropped in
without touching the user interface or the rest of the application.

The most important rule of this module: an engine that cannot run has to
say so.  It must never return placeholder or sample text, because the
application presents the result as a transcription of a real page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

__all__ = [
    "OCRResult",
    "OCREngine",
    "EngineError",
    "EngineUnavailable",
    "EngineFailure",
    "EngineTimeout",
]


@dataclass(frozen=True)
class OCRResult:
    """The outcome of recognising a single document.

    Attributes:
        text: The recognised text exactly as the engine produced it.  The
            application never rewrites it silently.
        engine_name: Human readable name of the engine that produced the
            text, shown to the user so they know what they are reading.
    """

    text: str
    engine_name: str


class EngineError(RuntimeError):
    """Base class for every recoverable engine problem."""


class EngineUnavailable(EngineError):
    """The engine is not installed, not licensed for this machine, or the
    required model files are missing."""


class EngineFailure(EngineError):
    """The engine was installed but failed while processing a document."""


class EngineTimeout(EngineError):
    """The engine exceeded the time budget allowed for a document."""


@runtime_checkable
class OCREngine(Protocol):
    """Protocol every OCR adapter has to satisfy."""

    name: str

    def available(self) -> bool:
        """Return ``True`` when the engine can recognise a document now."""

    def recognize(self, file_path: Path) -> OCRResult:
        """Recognise ``file_path`` and return the transcription."""
