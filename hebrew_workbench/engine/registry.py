"""Engine registry: keeps track of the OCR adapter that the UI talks to.

The registry is the only place that knows *which* engine is active.  The
user interface asks the registry for a transcription and receives either a
real result or an :class:`EngineUnavailable` error.  It never receives
fabricated text.
"""

from __future__ import annotations

from pathlib import Path

from .base import EngineUnavailable, OCREngine, OCRResult

__all__ = ["DisabledEngine", "EngineRegistry"]


class DisabledEngine:
    """The fail-closed default engine.

    It is used when no verified engine adapter has been installed.  It
    refuses to recognise anything and explains what the user has to do.
    """

    name = "No OCR engine installed"

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

    def status(self) -> str:
        return (
            f"OCR: {self.engine.name}\n"
            f"Available: {self.engine.available()}\n"
            "Spelling, grammar, and style: not installed"
        )

    def transcribe(self, file_path: str | Path) -> OCRResult:
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        if not self.engine.available():
            raise EngineUnavailable(
                f"{self.engine.name}. No OCR was performed. "
                "Choose or install an engine adapter."
            )
        return self.engine.recognize(path)
