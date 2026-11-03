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

from .photocraft_audit import (
    encode_preview_png,
    prepare_page_for_ocr,
    resolve_page_enhancement_enabled,
)

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
    "OCR_DPI",
    "disallowed_ctc_labels",
    "script_masked_decoder",
]

#: The resolution that a page is read at.  A page of a PDF that is
#: rendered at the resolution of the screen is far too small for a
#: handwriting: an A4 page would reach the engine with 595 by 842
#: pixels, while a scan of the same page usually has about 2500 by
#: 3500 pixels.  Three hundred dots per inch is the resolution that
#: the writing is usually scanned in.
OCR_DPI = 300


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
    restrict_script = bool(settings.get("restrict_script", True))
    artifact = MODEL_ARTIFACTS.get(artifact_id)
    model_path = None
    if artifact is not None:
        candidate = models_directory() / artifact.filename
        if candidate.is_file():
            model_path = candidate
    page_enh = (
        bool(settings["page_enhancement"])
        if "page_enhancement" in settings and settings["page_enhancement"] is not None
        else None
    )
    return KrakenEngine(
        model_path,
        artifact_id=artifact_id,
        restrict_script=restrict_script,
        page_enhancement=page_enh,
    )


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
        restrict_script: bool = True,
        page_enhancement: bool | None = None,
    ) -> None:
        self.model_path = Path(model_path) if model_path else None
        self.artifact_id = artifact_id
        self.timeout_seconds = timeout_seconds
        self.restrict_script = bool(restrict_script)
        self.page_enhancement = (
            bool(page_enhancement) if page_enhancement is not None else None
        )
        self._segmentation_model = None
        self._recognition_model = None
        self._disallowed_labels: list[int] = []

    def configure(self, options: dict) -> None:
        """Apply runtime plugin options such as automatic page enhancement."""
        if "restrict_script" in options and options["restrict_script"] is not None:
            self.restrict_script = bool(options["restrict_script"])
        if "page_enhancement" in options and options["page_enhancement"] is not None:
            self.page_enhancement = bool(options["page_enhancement"])

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
                    page_image = preview.render(number, dpi=OCR_DPI).image
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
        codec = getattr(getattr(self._recognition_model, "net", None), "codec", None)
        self._disallowed_labels = (
            disallowed_ctc_labels(codec) if self.restrict_script else []
        )

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
        import kraken.lib.ctc_decoder
        from kraken.configs import RecognitionInferenceConfig, SegmentationInferenceConfig

        self._load_models()

        segmentation_config = SegmentationInferenceConfig(text_direction="horizontal-rl")
        decoder = kraken.lib.ctc_decoder.greedy_decoder
        if self.restrict_script and self._disallowed_labels:
            decoder = script_masked_decoder(decoder, self._disallowed_labels)
        # Note: keep batch_size=1 in kraken 7.1.0; CTCRecognitionInferenceMixin
        # fails to flush trailing queued lines when batch_size > 1 and the last
        # segmented crop is blank or degenerate.
        recognition_config = RecognitionInferenceConfig(
            bidi_reordering=True,
            padding=16,
            num_line_workers=0,
            batch_size=1,
            decoder=decoder,
        )

        eff_enh = resolve_page_enhancement_enabled(self.page_enhancement)
        prepared_image, audit = prepare_page_for_ocr(image, enabled=eff_enh)
        was_enhanced = bool(eff_enh and audit is not None and audit.needs_adjustment)
        proc_png = encode_preview_png(prepared_image) if was_enhanced else None
        inv_scale = (
            1.0 / audit.scale_factor
            if audit is not None and audit.scale_factor > 0.0
            else 1.0
        )
        segmentation = self._segmentation_model.predict(
            im=prepared_image, config=segmentation_config
        )
        records = list(
            self._recognition_model.predict(
                im=prepared_image,
                segmentation=segmentation,
                config=recognition_config,
            )
        )

        lines: list[LineResult] = []
        for record in records:
            text = (getattr(record, "prediction", "") or "").strip()
            if not text:
                continue
            raw_box = _line_box(record)
            scaled_box = (
                (
                    raw_box[0] * inv_scale,
                    raw_box[1] * inv_scale,
                    raw_box[2] * inv_scale,
                    raw_box[3] * inv_scale,
                )
                if raw_box is not None and abs(inv_scale - 1.0) > 1e-6
                else raw_box
            )
            lines.append(
                LineResult(
                    text=text,
                    confidence=_mean_confidence(record),
                    box=scaled_box,
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
            enhanced=was_enhanced,
            enhancement_enabled=eff_enh,
            processed_image_png=proc_png,
        )


def _is_target_document_char(ch: str) -> bool:
    code = ord(ch)
    if 0x0590 <= code <= 0x05FF or 0xFB1D <= code <= 0xFB4F:
        return True  # Hebrew & presentation forms
    if 0x0020 <= code <= 0x024F:
        return True  # ASCII, digits, punctuation, Latin
    if 0x2000 <= code <= 0x22FF:
        return True  # Unicode spaces, quotes, dashes, bidi, currency, math
    return False


def disallowed_ctc_labels(codec) -> list[int]:
    """CTC class indices (>0) for non-Hebrew/non-Latin scripts in multilingual heads.

    PP-OCRv6 models cover 43 scripts (Hangul, CJK, Georgian, Cyrillic, Arabic,
    Devanagari, etc.) and otherwise leak foreign-script glyphs onto cursive
    Hebrew strokes. Only active when the codec actually contains Hebrew labels.
    """
    l2c = getattr(codec, "l2c", None)
    if not isinstance(l2c, dict) or not l2c:
        return []
    has_hebrew = any(
        any(0x0590 <= ord(ch) <= 0x05FF for ch in grapheme)
        for grapheme in l2c.values()
        if isinstance(grapheme, str)
    )
    if not has_hebrew:
        return []
    disallowed: list[int] = []
    for labels, grapheme in l2c.items():
        if not isinstance(labels, tuple) or len(labels) != 1:
            continue
        idx = int(labels[0])
        if idx <= 0 or not isinstance(grapheme, str) or not grapheme:
            continue
        if not any(_is_target_document_char(ch) for ch in grapheme):
            disallowed.append(idx)
    return sorted(set(disallowed))


def script_masked_decoder(base_decoder, disallowed_labels: list[int]):
    """Wrap a CTC decoder to zero non-target-script probabilities before argmax."""
    if not disallowed_labels:
        return base_decoder

    def _decode(outputs, seq_lens=None):
        if hasattr(outputs, "clone"):
            tensor = outputs.clone()
            ndim = int(tensor.dim())
            c_dim = tensor.shape[0] if ndim == 2 else tensor.shape[1]
            valid = [i for i in disallowed_labels if 0 < i < c_dim]
            if valid:
                if ndim == 2:
                    tensor[valid, :] = 0.0
                elif ndim == 3:
                    tensor[:, valid, :] = 0.0
            return base_decoder(tensor, seq_lens)
        if hasattr(outputs, "copy") and hasattr(outputs, "ndim"):
            arr = outputs.copy()
            c_dim = arr.shape[0] if arr.ndim == 2 else arr.shape[1]
            valid = [i for i in disallowed_labels if 0 < i < c_dim]
            if valid:
                if arr.ndim == 2:
                    arr[valid, :] = 0.0
                elif arr.ndim == 3:
                    arr[:, valid, :] = 0.0
            return base_decoder(arr, seq_lens)
        if isinstance(outputs, list) and outputs and isinstance(outputs[0], list):
            copied = [
                [
                    [0.0 if c_idx in disallowed_labels else val for val in row]
                    for c_idx, row in enumerate(sample)
                ]
                for sample in outputs
            ]
            return base_decoder(copied, seq_lens)
        return base_decoder(outputs, seq_lens)

    return _decode


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
