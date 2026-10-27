"""The replaceable OCR engine contract.

An *engine* is anything that can turn a local document into text.  The
contract is intentionally tiny so that a new engine can be dropped in
without touching the user interface or the rest of the application.

The most important rule of this module: an engine that cannot run has to
say so.  It must never return placeholder or sample text, because the
application presents the result as a transcription of a real page.

Every engine also describes itself with an :class:`EngineManifest`, so
the user (and the release documentation) can see which model produced a
text, under which license, and on which device.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable

__all__ = [
    "OCRResult",
    "OCREngine",
    "EngineManifest",
    "LineResult",
    "PageResult",
    "EngineError",
    "EngineUnavailable",
    "EngineFailure",
    "EngineTimeout",
    "EngineCancelled",
]


@dataclass(frozen=True)
class EngineManifest:
    """What the user needs to know about an engine before using it.

    Attributes:
        id: Stable identifier, used in project files and logs.
        name: Human readable name.
        version: Version of the engine or of the model.
        script: The script the engine was trained for, e.g. ``Hebrew``.
        license: SPDX identifier of the license of the weights.
        license_url: Where the license text can be read.
        device: ``cpu`` or ``gpu``.
        model_id: Identifier of the model file, if the engine needs one.
        model_sha256: SHA-256 digest the model file must match.
        model_size_bytes: Size of the model file.
        notes: Free text for the user.
    """

    id: str
    name: str
    version: str
    script: str
    license: str
    license_url: str
    device: str = "cpu"
    model_id: str | None = None
    model_sha256: str | None = None
    model_size_bytes: int | None = None
    notes: str = ""


@dataclass(frozen=True)
class LineResult:
    """One recognised line."""

    text: str
    confidence: float | None = None
    box: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class PageResult:
    """One recognised page."""

    number: int
    text: str
    confidence: float | None = None
    lines: tuple[LineResult, ...] = ()


@dataclass(frozen=True)
class OCRResult:
    """The outcome of recognising a single document.

    Attributes:
        text: The recognised text exactly as the engine produced it.  The
            application never rewrites it silently.
        engine_name: Human readable name of the engine that produced the
            text, shown to the user so they know what they are reading.
        pages: Per page results, when the engine reports them.
        duration_seconds: How long the recognition took.
        manifest: The description of the engine that was used.
    """

    text: str
    engine_name: str
    pages: tuple[PageResult, ...] = ()
    duration_seconds: float = 0.0
    manifest: EngineManifest | None = None


class EngineError(RuntimeError):
    """Base class for every recoverable engine problem."""


class EngineUnavailable(EngineError):
    """The engine is not installed, not licensed for this machine, or the
    required model files are missing."""


class EngineFailure(EngineError):
    """The engine was installed but failed while processing a document."""


class EngineTimeout(EngineError):
    """The engine exceeded the time budget allowed for a document."""


class EngineCancelled(EngineError):
    """The user cancelled the job."""


@runtime_checkable
class OCREngine(Protocol):
    """Protocol every OCR adapter has to satisfy."""

    name: str

    def available(self) -> bool:
        """Return ``True`` when the engine can recognise a document now."""

    def recognize(self, file_path: Path) -> OCRResult:
        """Recognise ``file_path`` and return the transcription."""
