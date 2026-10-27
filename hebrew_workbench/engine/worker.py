"""Running the recognition engine in a separate process.

The recognition engine needs a large machine learning library.  Keeping it
in a separate executable has two advantages: the main application stays
small and quick to start, and a crash inside the engine cannot take the
user interface down with it.

The two processes talk through a small JSON protocol: the application
writes a job file, the worker writes a result file.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
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

__all__ = ["WorkerEngine", "worker_path", "make_worker_engine"]


def worker_path() -> Path | None:
    """The optional OCR worker executable, if it has been installed."""
    import sys

    candidates = []
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        candidates.append(Path(bundle) / "ocr-worker.exe")
        candidates.append(Path(bundle) / "ocr-worker")
    from .models import models_directory

    candidates.append(models_directory().parent / "ocr-worker.exe")
    candidates.append(models_directory().parent / "ocr-worker")
    program_folder = Path(sys.executable).resolve().parent
    candidates.append(program_folder / "ocr-worker.exe")
    candidates.append(program_folder / "ocr-worker")
    # The worker that comes with the program is a folder of its own,
    # with its own libraries beside it.
    candidates.append(program_folder / "ocr-worker" / "ocr-worker.exe")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def make_worker_engine(options: dict | None = None) -> "WorkerEngine":
    """Build the worker engine for the plugin system."""
    from .models import MODEL_ARTIFACTS, models_directory

    settings = dict(options or {})
    artifact_id = str(settings.get("model_id", "kraken-ppocrv6-small"))
    artifact = MODEL_ARTIFACTS.get(artifact_id)
    model_path = None
    if artifact is not None:
        candidate = models_directory() / artifact.filename
        if candidate.is_file():
            model_path = candidate
    worker = worker_path()
    if worker is None or model_path is None:
        return None
    return WorkerEngine(worker, model_path)


class WorkerEngine:
    """An OCR engine that runs the recognition worker as a subprocess."""

    name = "kraken PP-OCRv6 (worker, Apache-2.0)"

    def __init__(
        self,
        worker: str | Path,
        model_path: str | Path,
        timeout_seconds: float = 1800.0,
    ) -> None:
        self.worker = Path(worker)
        self.model_path = Path(model_path)
        self.timeout_seconds = timeout_seconds

    def manifest(self) -> EngineManifest:
        from .kraken_local import build_manifest

        return build_manifest(self.model_path)

    def available(self) -> bool:
        return self.worker.is_file() and self.model_path.is_file()

    def recognize(
        self,
        file_path: str | Path,
        progress: Callable[[str], None] | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> OCRResult:
        if not self.available():
            raise EngineUnavailable(
                "מנוע הזיהוי אינו מותקן (חסר קובץ המנוע או קובץ המודל)."
            )
        document = Path(file_path)
        if not document.is_file():
            raise FileNotFoundError(document)

        with tempfile.TemporaryDirectory(prefix="ocr-job-") as folder:
            job_path = Path(folder) / "job.json"
            result_path = Path(folder) / "result.json"
            job_path.write_text(
                json.dumps(
                    {
                        "document": str(document),
                        "model_path": str(self.model_path),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            command = [
                str(self.worker),
                "--job",
                str(job_path),
                "--result",
                str(result_path),
            ]
            error_path = Path(folder) / "error.txt"
            started = time.monotonic()
            # The output of the worker goes to files, not to pipes that
            # nobody reads.  A pipe that is not read fills up and stops
            # the worker in the middle of the work.
            with open(error_path, "wb") as error_file:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=error_file,
                )
                try:
                    while True:
                        code = process.poll()
                        if code is not None:
                            break
                        if cancel and cancel():
                            process.terminate()
                            try:
                                process.wait(timeout=10)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait()
                            raise EngineCancelled("המשימה בוטלה.")
                        if time.monotonic() - started > self.timeout_seconds:
                            process.kill()
                            process.wait()
                            raise EngineTimeout(
                                "זיהוי המסמך ארך מהזמן המותר. אפשר לנסות מסמך קצר יותר."
                            )
                        if progress:
                            progress("מזהה את המסמך...")
                        time.sleep(0.5)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()

            payload: dict = {}
            if result_path.is_file():
                try:
                    payload = json.loads(result_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    payload = {}

            # The worker writes what went wrong into its result file, so
            # that message is used before the exit code is looked at.
            if payload.get("error"):
                raise EngineFailure(str(payload["error"]))

            if process.returncode != 0:
                detail = ""
                if error_path.is_file():
                    detail = error_path.read_text(
                        encoding="utf-8", errors="replace"
                    ).strip()
                raise EngineFailure(
                    "מנוע הזיהוי נכשל:"
                    + (f"\n{detail}" if detail else f" (קוד {process.returncode})")
                )
            if not result_path.is_file():
                raise EngineFailure("מנוע הזיהוי לא החזיר תוצאה.")

        if payload.get("error"):
            raise EngineFailure(str(payload["error"]))

        pages = tuple(
            PageResult(
                number=int(page.get("number", index + 1)),
                text=str(page.get("text", "")),
                confidence=page.get("confidence"),
                lines=tuple(
                    LineResult(
                        text=str(line.get("text", "")),
                        confidence=line.get("confidence"),
                        box=tuple(line["box"]) if line.get("box") else None,
                    )
                    for line in page.get("lines", [])
                ),
            )
            for index, page in enumerate(payload.get("pages", []))
        )
        return OCRResult(
            text=str(payload.get("text", "")),
            engine_name=str(payload.get("engine_name", self.name)),
            pages=pages,
            duration_seconds=float(payload.get("duration_seconds", 0.0)),
            manifest=self.manifest(),
        )
