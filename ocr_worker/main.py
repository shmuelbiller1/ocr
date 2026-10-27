"""The recognition worker.

This is the small executable that carries the machine learning library.
The main application starts it, hands it a document and a model file, and
reads the transcription back.  Keeping it separate means the main
application stays small and that a crash in the engine cannot take the
user interface with it.

The worker is built by the packaging job::

    pyinstaller --onefile --console --name ocr-worker ocr_worker/main.py
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

# Make the package importable when the worker runs from a source checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hebrew Notes Workbench OCR worker")
    parser.add_argument("--job", required=True, help="path of the job description")
    parser.add_argument("--result", required=True, help="path of the result file")
    args = parser.parse_args(argv)

    job_path = Path(args.job)
    result_path = Path(args.result)

    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
        from hebrew_workbench.engine.kraken_local import KrakenEngine

        engine = KrakenEngine(job["model_path"])
        result = engine.recognize(job["document"])
        payload = {
            "text": result.text,
            "engine_name": result.engine_name,
            "duration_seconds": result.duration_seconds,
            "pages": [
                {
                    "number": page.number,
                    "text": page.text,
                    "confidence": page.confidence,
                    "lines": [
                        {
                            "text": line.text,
                            "confidence": line.confidence,
                            "box": list(line.box) if line.box else None,
                        }
                        for line in page.lines
                    ],
                }
                for page in result.pages
            ],
        }
    except Exception as exc:
        message = str(exc) or type(exc).__name__
        # The message also goes to the error output, so that it is not
        # lost when the result file cannot be read.
        print(message, file=sys.stderr)
        payload = {"error": message, "traceback": traceback.format_exc()}

    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return 0 if "error" not in payload else 1


if __name__ == "__main__":
    raise SystemExit(main())
