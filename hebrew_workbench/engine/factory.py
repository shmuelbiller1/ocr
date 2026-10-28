"""Finding the OCR engines that are usable on this machine.

The application does not hard-code one engine.  It asks this module what
is installed, and the user interface shows the result.  When nothing is
installed the registry keeps its fail-closed default.
"""

from __future__ import annotations

from pathlib import Path

from .base import OCREngine
from .models import MODEL_ARTIFACTS, models_directory
from .worker import WorkerEngine, worker_path

__all__ = ["installed_model_path", "detect_engines", "worker_path"]


def installed_model_path(artifact_id: str = "kraken-ppocrv6-small") -> Path | None:
    """Where the model file would live, whether it is there or not."""
    artifact = MODEL_ARTIFACTS.get(artifact_id)
    if artifact is None:
        return None
    return models_directory() / artifact.filename



def detect_engines() -> list[OCREngine]:
    """Return every engine that could run right now, best first.

    The engines are the OCR plugins of the program.  A user who adds
    another engine gets it here, without a change in this file.
    """
    engines: list[OCREngine] = []

    try:
        from ..plugins import PluginRegistry

        for plugin in PluginRegistry().ocr_engines():
            if plugin.object is not None:
                engines.append(plugin.object)
    except Exception:
        # A broken plugin must not stop the program from starting.
        engines = []

    if engines:
        return engines

    worker = worker_path()
    if worker is not None:
        model = installed_model_path()
        if model is not None and model.is_file():
            engines.append(WorkerEngine(worker, model))

    try:
        from .kraken_local import KrakenEngine, kraken_importable
    except Exception:
        kraken_importable = lambda: False  # noqa: E731
        KrakenEngine = None  # type: ignore[assignment]

    if KrakenEngine is not None and kraken_importable():
        model = installed_model_path()
        if model is not None and model.is_file():
            engines.append(KrakenEngine(model))

    return engines
