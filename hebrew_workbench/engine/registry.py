"""Engine registry: keeps track of the OCR adapter that the UI talks to.

The registry is the only place that knows *which* engine is active.  The
user interface asks the registry for a transcription and receives either a
real result or an :class:`EngineUnavailable` error.  It never receives
fabricated text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from .base import (
    EngineCancelled,
    EngineError,
    EngineManifest,
    EngineTimeout,
    EngineUnavailable,
    OCREngine,
    OCRResult,
)

__all__ = ["DisabledEngine", "EngineRegistry"]


class DisabledEngine:
    """The fail-closed default engine.

    It is used when no verified engine adapter has been installed.  It
    refuses to recognise anything and explains what the user has to do.
    """

    name = "No OCR engine installed"

    def manifest(self) -> EngineManifest | None:
        return None

    def available(self) -> bool:
        return False

    def recognize(self, file_path: Path) -> OCRResult:
        raise EngineUnavailable(
            "No verified local handwriting OCR engine has been installed. "
            "The document was not processed. Install a licensed engine "
            "adapter first."
        )


class EngineRegistry:
    """Holds the active engine and gives it a single, safe entry point."""

    def __init__(self, engine: OCREngine | None = None) -> None:
        self.engine: OCREngine = engine or DisabledEngine()

    # -- the active engine -------------------------------------------------
    @property
    def name(self) -> str:
        return getattr(self.engine, "name", "unknown engine")

    def manifest(self) -> EngineManifest | None:
        getter = getattr(self.engine, "manifest", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                return None
        return None

    def available(self) -> bool:
        try:
            return bool(self.engine.available())
        except Exception:
            # An engine that cannot even answer the question is not usable.
            return False

    def status(self) -> str:
        manifest = self.manifest()
        lines = [
            f"OCR: {self.name}",
            f"Available: {self.available()}",
        ]
        if manifest is not None:
            lines.append(f"Script: {manifest.script}")
            lines.append(f"License: {manifest.license} ({manifest.license_url})")
            lines.append(f"Device: {manifest.device}")
            if manifest.notes:
                lines.append(manifest.notes)
        lines.append("Spelling, grammar, and style: not installed")
        return "\n".join(lines)

    # -- the one safe entry point ------------------------------------------
    def transcribe(
        self,
        file_path: str | Path,
        progress: Callable[[str], None] | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> OCRResult:
        """Recognise a document, or explain why that is not possible."""
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        if not self.available():
            raise EngineUnavailable(
                f"{self.name}. No OCR was performed. "
                "Choose or install an engine adapter."
            )
        try:
            return self._recognize(path, progress, cancel)
        except (EngineUnavailable, EngineTimeout, EngineCancelled):
            raise
        except Exception as exc:
            raise EngineError(f"The engine failed: {exc}") from exc

    def _recognize(
        self,
        path: Path,
        progress: Callable[[str], None] | None,
        cancel: Callable[[], bool] | None,
    ) -> OCRResult:
        """Call the engine, with the callbacks when it can take them.

        An adapter that was written for the first version of the
        contract only knows the path of the document.  It keeps working:
        the callbacks are simply not passed on to it.
        """
        import inspect

        try:
            parameters = inspect.signature(self.engine.recognize).parameters
        except (TypeError, ValueError):
            parameters = {}

        def accepts(name: str) -> bool:
            if name in parameters:
                return True
            return any(
                item.kind is inspect.Parameter.VAR_KEYWORD
                for item in parameters.values()
            )

        keywords: dict = {}
        if progress is not None and accepts("progress"):
            keywords["progress"] = progress
        if cancel is not None and accepts("cancel"):
            keywords["cancel"] = cancel
        return self.engine.recognize(path, **keywords)
