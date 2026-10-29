"""Recognition with *Mishkefet-v1*, a compact recogniser for modern Hebrew
cursive.

This engine is the one that was written for the material the program is
made for: contemporary handwritten Hebrew.  The model is a small
character-level CTC recogniser (30 million parameters) that runs on the
processor of the computer, and the code that runs it was published under
the MIT licence and is shipped with the program under
``hebrew_workbench/engine/vendor``.

Two things are said plainly here, because they matter to the user:

* **The weights are not ours and they are not free of conditions.**
  They are published under CC-BY-NC-SA-4.0: non-commercial use, and the
  same licence for a modified file.  They are *not* bundled with the
  program.  The user downloads them, on request, from the place where the
  author published them, and the file is checked against a digest that
  this project pinned.  A user who needs a commercial licence has to ask
  the author of the model.
* **The text is what the engine read.**  The engine decodes greedily:
  no dictionary, no language model and no spelling rule is added to the
  result.  The program never rewrites a recognition on its own.

The model was trained on the published lines of real Hebrew cursive of
the Pinkas corpus.  Its numbers on that corpus are therefore not a clean
measurement, and ``docs/OCR_ACCURACY.md`` says so.
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
    "MishkefetEngine",
    "mishkefet_importable",
    "build_manifest",
    "make_engine",
    "OCR_DPI",
]

#: The resolution that a page is read at, the same as the other engine:
#: a handwriting needs about three hundred dots per inch.
OCR_DPI = 300


def mishkefet_importable() -> bool:
    """Is everything that the engine needs installed in this environment?"""
    try:
        import torch  # noqa: F401
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except Exception:
        return False
    return True


def build_manifest(
    model_path: Path | None, artifact_id: str = "mishkefet-v1"
) -> EngineManifest:
    from .models import MODEL_ARTIFACTS

    artifact = MODEL_ARTIFACTS.get(artifact_id)
    return EngineManifest(
        id=artifact.id if artifact else "mishkefet-v1",
        name=artifact.name if artifact else "Mishkefet-v1",
        version=artifact.engine_version if artifact else "heb-ocr 0.1.0",
        script=artifact.script if artifact else "Hebrew (modern cursive)",
        license=artifact.license if artifact else "CC-BY-NC-SA-4.0",
        license_url=(
            artifact.license_url
            if artifact
            else "https://huggingface.co/itayinbar/Mishkefet-v1"
        ),
        device="cpu",
        model_id=artifact.id if artifact else None,
        model_sha256=artifact.sha256 if artifact else None,
        model_size_bytes=artifact.size_bytes if artifact else None,
        notes=artifact.notes if artifact else "",
    )


def make_engine(options: dict | None = None) -> "MishkefetEngine":
    """Build the engine for the plugin system.

    A model that was not downloaded is not an error here: the engine says
    that it is not available, and the program tells the user what to do.
    """
    from .models import MODEL_ARTIFACTS, models_directory

    settings = dict(options or {})
    artifact_id = str(settings.get("model_id", "mishkefet-v1"))
    artifact = MODEL_ARTIFACTS.get(artifact_id)
    model_path = None
    if artifact is not None:
        candidate = models_directory() / artifact.filename
        if candidate.is_file():
            model_path = candidate
    return MishkefetEngine(model_path, artifact_id=artifact_id)


class MishkefetEngine:
    """An OCR engine that runs *Mishkefet-v1* on the processor.

    Args:
        model_path: The recognition weights (``mishkefet-v1.pt``).
        artifact_id: Which known model this is, used for the manifest.
        timeout_seconds: Budget for a whole document.
    """

    name = "Mishkefet-v1 (modern Hebrew cursive, CC-BY-NC-SA-4.0)"

    def __init__(
        self,
        model_path: str | Path | None = None,
        artifact_id: str = "mishkefet-v1",
        timeout_seconds: float = 900.0,
    ) -> None:
        self.model_path = Path(model_path) if model_path else None
        self.artifact_id = artifact_id
        self.timeout_seconds = timeout_seconds
        self._recognizer = None

    # -- availability ------------------------------------------------------
    def manifest(self) -> EngineManifest:
        return build_manifest(self.model_path, self.artifact_id)

    def available(self) -> bool:
        if not mishkefet_importable():
            return False
        if self.model_path is None:
            return False
        return self.model_path.is_file()

    def unavailable_reason(self) -> str:
        if not mishkefet_importable():
            return (
                "חבילת הזיהוי של המנוע Mishkefet אינה מותקנת ביישום זה "
                "(נדרשים torch ו-opencv)."
            )
        if self.model_path is None or not self.model_path.is_file():
            return "קובץ המודל של Mishkefet אינו מותקן. יש להתקין אותו מהתפריט 'כלים'."
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

    def _load_recognizer(self):
        if self._recognizer is not None:
            return self._recognizer
        if self.model_path is None:
            raise EngineUnavailable("קובץ המודל של Mishkefet אינו מותקן.")
        # The file is checked before the library that reads it is even
        # loaded, so that a file that was replaced after the download
        # never reaches the code that runs what is inside the file.
        self._verify_checkpoint()
        from .vendor.hebocr.recognize import Recognizer

        try:
            self._recognizer = Recognizer(str(self.model_path), device="cpu")
        except Exception as exc:
            raise EngineFailure(
                f"לא ניתן לטעון את מודל Mishkefet: {exc}"
            ) from exc
        return self._recognizer

    def _verify_checkpoint(self) -> None:
        """Check the checkpoint against the digest that the project pinned.

        The file is checked again when it is loaded, and not only when it
        is downloaded.  A file that was replaced after the download would
        otherwise reach ``torch.load``, which runs the code that is inside
        the file, and the code of the checkpoint is not ours to trust.
        """
        from .models import MODEL_ARTIFACTS, verify_file

        artifact = MODEL_ARTIFACTS.get(self.artifact_id)
        if artifact is None:
            raise EngineFailure(
                f"מנוע הזיהוי אינו יודע את המודל {self.artifact_id!r}."
            )
        problem = verify_file(self.model_path, artifact)
        if problem is not None:
            raise EngineFailure(
                "קובץ המודל של Mishkefet אינו תואם למה שנעוץ בפרויקט "
                f"({problem}). המודל לא נטען."
            )

    def _recognize_page(
        self, number: int, image, budget: float | None = None
    ) -> PageResult:
        """Recognise one page, and give up when the time is up.

        The model cannot be interrupted in the middle of a page, so the
        work is done in a thread that is left behind when the time is up,
        the same way the other engine does it.
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
            target=work, name=f"mishkefet-page-{number}", daemon=True
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
        from .vendor.hebocr.page.segment import segment_page

        recognizer = self._load_recognizer()
        crops, boxes, _skew = segment_page(image)
        if not crops:
            return PageResult(number=number, text="", confidence=None, lines=())

        texts, confidences = recognizer.read(crops, return_confidence=True)

        lines: list[LineResult] = []
        for text, confidence, box in zip(texts, confidences, boxes):
            text = (text or "").strip()
            if not text:
                continue
            lines.append(
                LineResult(
                    text=text,
                    confidence=_round(confidence),
                    box=(float(box.x), float(box.y), float(box.w), float(box.h)),
                )
            )
        page_text = "\n".join(line.text for line in lines)
        values = [line.confidence for line in lines if line.confidence is not None]
        page_confidence = round(sum(values) / len(values), 4) if values else None
        return PageResult(
            number=number,
            text=page_text,
            confidence=page_confidence,
            lines=tuple(lines),
        )


def _round(value) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None
