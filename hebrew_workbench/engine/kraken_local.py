"""Recognition with the `kraken` engine and the PP-OCRv6 model.

This module is the only place that talks to `kraken`.  It is imported
lazily, so the application keeps working - and keeps starting quickly -
when the engine is not installed.

The engine (Apache-2.0) and the model (Apache-2.0) are separate: the code
is installed with the application, the weights are downloaded on request
and verified against the digests published by the model authors.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from .base import (
    EngineCancelled,
    EngineFailure,
    EngineManifest,
    EngineTimeout,
    EngineUnavailable,
    LineResult,
    OCRResult,
    PageResult,
)

__all__ = [
    "KrakenEngine",
    "kraken_importable",
    "default_segmentation_model",
    "build_manifest",
    "make_engine",
]


def kraken_importable() -> bool:
    """Is the recognition engine installed in this environment?"""
    try:
        import kraken  # noqa: F401
    except Exception:
        return False
    return True


def default_segmentation_model() -> Path | None:
    """The line segmentation model that ships with `kraken`.

    ``None`` when the file cannot be found, so that the availability
    check can report a missing model instead of failing later, in the
    middle of a recognition.
    """
    try:
        from importlib import resources

        path = resources.files("kraken").joinpath("blla.mlmodel")
    except Exception:
        return None
    try:
        resolved = Path(str(path))
    except Exception:
        return None
    if not resolved.is_file():
        return None
    return resolved


def build_manifest(model_path: Path | None, artifact_id: str = "kraken-ppocrv6-small") -> EngineManifest:
    from .models import MODEL_ARTIFACTS

    artifact = MODEL_ARTIFACTS.get(artifact_id)
    return EngineManifest(
        id=artifact.id if artifact else "kraken-ppocrv6",
        name=artifact.name if artifact else "kraken PP-OCRv6",
        version=artifact.engine_version if artifact else "kraken",
        script=artifact.script if artifact else "Hebrew",
        license=artifact.license if artifact else "Apache-2.0",
        license_url=artifact.license_url if artifact else "https://zenodo.org/records/21788405",
        device="cpu",
        model_id=artifact.id if artifact else None,
        model_sha256=artifact.sha256 if artifact else None,
        model_size_bytes=artifact.size_bytes if artifact else None,
        notes=artifact.notes if artifact else "",
    )


def make_engine(options: dict | None = None) -> "KrakenEngine":
    """Build the engine for the plugin system.

    The options of the plugin say which of the known models is used.  A
    model that was not downloaded is not an error here: the engine says
    that it is not available, and the program tells the user what to do.
    """
    from .models import MODEL_ARTIFACTS, models_directory

    settings = dict(options or {})
    artifact_id = str(settings.get("model_id", "kraken-ppocrv6-small"))
    artifact = MODEL_ARTIFACTS.get(artifact_id)
    model_path = None
    if artifact is not None:
        candidate = models_directory() / artifact.filename
        if candidate.is_file():
            model_path = candidate
    return KrakenEngine(model_path, artifact_id=artifact_id)


class KrakenEngine:
    """An OCR engine that runs `kraken` with the PP-OCRv6 weights.

    Args:
        model_path: The recognition weights (``.safetensors``).
        artifact_id: Which known model this is, used for the manifest.
        timeout_seconds: Budget for a whole document.
    """

    name = "kraken PP-OCRv6 (Apache-2.0)"

    def __init__(
        self,
        model_path: str | Path | None = None,
        artifact_id: str = "kraken-ppocrv6-small",
        timeout_seconds: float = 900.0,
    ) -> None:
        self.model_path = Path(model_path) if model_path else None
        self.artifact_id = artifact_id
        self.timeout_seconds = timeout_seconds
        self._segmentation_model = None
        self._recognition_model = None

    # -- availability ------------------------------------------------------
    def manifest(self) -> EngineManifest:
        return build_manifest(self.model_path, self.artifact_id)

    def available(self) -> bool:
        if not kraken_importable():
            return False
        if self.model_path is None:
            return False
        if not self.model_path.is_file():
            return False
        return default_segmentation_model() is not None

    def unavailable_reason(self) -> str:
        if not kraken_importable():
            return (
                "מנוע הזיהוי (kraken) אינו מותקן ביישום זה. "
                "אפשר להתקין את חבילת המנוע המלאה."
            )
        if self.model_path is None or not self.model_path.is_file():
            return "קובץ המודל אינו מותקן. יש להתקין את המודל מהתפריט 'כלים'."
        if default_segmentation_model() is None:
            return "קובץ מודל הפילוח (blla) אינו נמצא בתוך חבילת kraken."
        return "המנוע מוכן."

    # -- recognition -------------------------------------------------------
    def recognize(
        self,
        file_path: str | Path,
        progress: Callable[[str], None] | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> OCRResult:
        if not self.available():
            raise EngineUnavailable(self.unavailable_reason())

        from ..preview.loader import DocumentPreview, PreviewError

        started = time.monotonic()
        # The budget of the whole document.  A page that runs out of
        # time is given up on, so that a stuck page cannot hold the
        # program for ever.
        deadline = (
            None
            if not self.timeout_seconds
            else started + float(self.timeout_seconds)
        )
        try:
            with DocumentPreview(file_path) as preview:
                pages: list[PageResult] = []
                for number in range(1, preview.page_count + 1):
                    if cancel and cancel():
                        raise EngineCancelled("המשימה בוטלה.")
                    if progress:
                        progress(f"מזהה עמוד {number} מתוך {preview.page_count}...")
                    page_image = preview.render(number).image
                    budget = (
                        None
                        if deadline is None
                        else max(0.0, deadline - time.monotonic())
                    )
                    pages.append(self._recognize_page(number, page_image, budget))
        except PreviewError as exc:
            raise EngineFailure(str(exc)) from exc

        text = "\n".join(page.text for page in pages if page.text.strip())
        return OCRResult(
            text=text,
            engine_name=self.name,
            pages=tuple(pages),
            duration_seconds=round(time.monotonic() - started, 2),
            manifest=self.manifest(),
        )

    def _load_models(self):
        if self._recognition_model is not None:
            return
        from kraken.tasks import RecognitionTaskModel, SegmentationTaskModel

        segmentation_path = default_segmentation_model()
        if segmentation_path is None:
            raise EngineUnavailable("קובץ מודל הפילוח (blla) אינו נמצא בתוך kraken.")
        self._segmentation_model = SegmentationTaskModel.load_model(str(segmentation_path))
        self._recognition_model = RecognitionTaskModel.load_model(str(self.model_path))

    def _recognize_page(
        self, number: int, image, budget: float | None = None
    ) -> PageResult:
        """Recognise one page, and give up when the time is up.

        The engine of `kraken` cannot be interrupted in the middle of a
        page.  The work is therefore done in a thread that is left behind
        when the time is up, so that the program is not held up by it.
        """
        if budget is None:
            return self._recognize_page_now(number, image)

        outcome: dict = {}

        def work() -> None:
            try:
                outcome["page"] = self._recognize_page_now(number, image)
            except BaseException as exc:  # noqa: BLE001 - reported below
                outcome["error"] = exc

        thread = threading.Thread(
            target=work, name=f"kraken-page-{number}", daemon=True
        )
        thread.start()
        thread.join(budget)
        if thread.is_alive():
            raise EngineTimeout(
                f"הזיהוי של עמוד {number} עבר את מגבלת הזמן של {self.timeout_seconds:.0f} שניות."
            )
        if "error" in outcome:
            raise outcome["error"]
        return outcome["page"]

    def _recognize_page_now(self, number: int, image) -> PageResult:
        from kraken.configs import RecognitionInferenceConfig, SegmentationInferenceConfig

        self._load_models()

        segmentation_config = SegmentationInferenceConfig(text_direction="horizontal-rl")
        recognition_config = RecognitionInferenceConfig(
            bidi_reordering=True,
            padding=16,
            num_line_workers=0,
        )

        segmentation = self._segmentation_model.predict(
            im=image, config=segmentation_config
        )
        records = list(
            self._recognition_model.predict(
                im=image, segmentation=segmentation, config=recognition_config
            )
        )

        lines: list[LineResult] = []
        for record in records:
            text = (getattr(record, "prediction", "") or "").strip()
            if not text:
                continue
            lines.append(
                LineResult(
                    text=text,
                    confidence=_mean_confidence(record),
                    box=_line_box(record),
                )
            )
        page_text = "\n".join(line.text for line in lines)
        confidences = [
            line.confidence for line in lines if line.confidence is not None
        ]
        page_confidence = (
            round(sum(confidences) / len(confidences), 4) if confidences else None
        )
        return PageResult(
            number=number,
            text=page_text,
            confidence=page_confidence,
            lines=tuple(lines),
        )


def _mean_confidence(record) -> float | None:
    """Average confidence of a record, when the engine reports one."""
    if record is None:
        return None
    confidences = getattr(record, "confidences", None) or []
    values = [float(value) for value in confidences if isinstance(value, (int, float))]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _line_box(record) -> tuple[float, float, float, float] | None:
    """Bounding box of a line, when the engine reports one."""
    bbox = getattr(record, "bbox", None)
    if bbox:
        try:
            x0, y0, x1, y1 = (float(value) for value in bbox)
            return (x0, y0, x1, y1)
        except Exception:
            return None
    points = getattr(record, "points", None)
    if points:
        try:
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
            return (min(xs), min(ys), max(xs), max(ys))
        except Exception:
            return None
    return None
