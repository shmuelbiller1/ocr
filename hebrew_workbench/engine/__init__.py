"""OCR engine adapters.

Every adapter implements the contract in :mod:`hebrew_workbench.engine.base`
and can be replaced without touching the user interface.

The parts that need the machine learning library (`kraken_local`) are
imported lazily, so the application starts fast and works without them.
"""

from __future__ import annotations

from .base import (
    EngineCancelled,
    EngineError,
    EngineFailure,
    EngineManifest,
    EngineTimeout,
    EngineUnavailable,
    LineResult,
    OCREngine,
    OCRResult,
    PageResult,
)
from .factory import detect_engines, installed_model_path
from .models import MODEL_ARTIFACTS, ModelArtifact, install_artifact, verify_file
from .registry import DisabledEngine, EngineRegistry

__all__ = [
    "DisabledEngine",
    "EngineCancelled",
    "EngineError",
    "EngineFailure",
    "EngineManifest",
    "EngineRegistry",
    "EngineTimeout",
    "EngineUnavailable",
    "LineResult",
    "MODEL_ARTIFACTS",
    "ModelArtifact",
    "OCREngine",
    "OCRResult",
    "PageResult",
    "detect_engines",
    "install_artifact",
    "installed_model_path",
    "verify_file",
]
