"""Stable replaceable OCR contract. Never substitute fabricated text for an unavailable engine."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

@dataclass(frozen=True)
class OCRResult:
    text: str
    engine_name: str

class EngineUnavailable(RuntimeError):
    pass

class OCREngine(Protocol):
    name: str
    def available(self) -> bool: ...
    def recognize(self, file_path: Path) -> OCRResult: ...

class DisabledEngine:
    name = "No OCR engine installed"
    def available(self) -> bool:
        return False
    def recognize(self, file_path: Path) -> OCRResult:
        raise EngineUnavailable(
            "No verified local handwriting OCR engine has been installed. "
            "The document was not processed. Set up a licensed engine adapter first."
        )

class EngineRegistry:
    def __init__(self, engine: OCREngine | None = None):
        self.engine = engine or DisabledEngine()
    def status(self) -> str:
        return f"OCR: {self.engine.name}\nAvailable: {self.engine.available()}\nSpelling, grammar, and style: not installed"
    def transcribe(self, file_path: str | Path) -> OCRResult:
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        if not self.engine.available():
            raise EngineUnavailable(f"{self.engine.name}. No OCR was performed. Choose or install an engine adapter.")
        return self.engine.recognize(path)
