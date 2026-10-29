"""Read a real document with every engine and write what they read.

This is the smoke test of the program: a real scan goes in, and the
raw text that every engine read comes out.  There is no ground truth
here and no rate is calculated, because a rate without a transcript that
somebody else checked is not a measurement.  The tool says what each
engine read, how long it took and how many lines it found, and nothing
more.

    python tools/smoke_test.py \
        --document benchmark/smoke_test/pages/scan.pdf \
        --models .cache/models \
        --engines kraken-ppocrv6-small kraken-ppocrv6-medium mishkefet-v1 \
        --output build/smoke

The files that are written are the text of every engine, and a small
report in JSON.  The report says that the accuracy of the engines on
this page is **not verified**, because nobody checked the transcript of
the page against what the page says.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from hebrew_workbench.console import use_utf8  # noqa: E402


def _engine_for(artifact, model_path: Path, identifier: str, timeout: float):
    """The engine that reads a given model.

    The catalogue says which engine reads which model, so that a new
    model does not need a change in this file.
    """
    if artifact.engine == "mishkefet":
        from hebrew_workbench.engine.mishkefet import MishkefetEngine

        return MishkefetEngine(
            model_path, artifact_id=identifier, timeout_seconds=timeout
        )
    from hebrew_workbench.engine.kraken_local import KrakenEngine

    return KrakenEngine(model_path, artifact_id=identifier, timeout_seconds=timeout)


def read_with(engine, document: Path) -> dict:
    """Read the document with one engine, and write what it read."""
    started = time.monotonic()
    result = engine.recognize(document)
    seconds = round(time.monotonic() - started, 2)
    pages = []
    for page in result.pages:
        pages.append(
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
        )
    return {
        "engine": getattr(engine, "name", "the engine"),
        "model": engine.artifact_id,
        "document": str(document),
        "seconds": seconds,
        "text": result.text,
        "pages": pages,
        "lines": sum(len(page["lines"]) for page in pages),
        "characters": len(result.text),
    }


def main(argv: list[str] | None = None) -> int:
    use_utf8()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document", required=True, help="the file to read")
    parser.add_argument(
        "--models", default=".cache/models", help="the folder of the model files"
    )
    parser.add_argument(
        "--engines",
        nargs="+",
        default=["kraken-ppocrv6-small", "mishkefet-v1"],
        help="the models to read the document with",
    )
    parser.add_argument("--output", default="build/smoke", help="where to write")
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--require-text", action="store_true",
                        help="fail if no engine returns nonempty text")
    args = parser.parse_args(argv)

    from hebrew_workbench.engine.models import MODEL_ARTIFACTS

    document = Path(args.document)
    if not document.is_file():
        print(f"the document is not there: {document}")
        return 1
    models_folder = Path(args.models)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    engines = []
    skipped = []
    for identifier in args.engines:
        artifact = MODEL_ARTIFACTS.get(identifier)
        if artifact is None:
            skipped.append({"model": identifier, "reason": "the model is not known"})
            continue
        model_path = models_folder / artifact.filename
        if not model_path.is_file():
            skipped.append(
                {
                    "model": identifier,
                    "reason": f"the model file is not there: {model_path}",
                }
            )
            continue
        engines.append((identifier, artifact, model_path))

    report = {
        "document": str(document),
        "note": (
            "There is no transcript that somebody else checked for this page, "
            "so the accuracy of the engines on it is NOT verified.  These are "
            "the raw readings of the engines and nothing more."
        ),
        "engines": [],
        "skipped": skipped,
    }

    failures = 0
    nonempty = 0
    for identifier, artifact, model_path in engines:
        print(f"reading with {identifier} ...", flush=True)
        try:
            engine = _engine_for(artifact, model_path, identifier, args.timeout)
            reading = read_with(engine, document)
        except Exception as exc:  # noqa: BLE001 - one engine does not stop the others
            message = f"{type(exc).__name__}: {exc}"
            print(f"    the engine failed: {message}", flush=True)
            report["engines"].append(
                {"model": identifier, "error": message}
            )
            failures += 1
            continue
        nonempty += bool(reading["text"].strip())
        name = "smoke-" + artifact.filename.rsplit(".", 1)[0]
        (output / f"{name}.txt").write_text(reading["text"], encoding="utf-8")
        (output / f"{name}.json").write_text(
            json.dumps(reading, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            f"    {reading['lines']} lines, {reading['characters']} characters, "
            f"{reading['seconds']}s",
            flush=True,
        )
        report["engines"].append(
            {
                "model": identifier,
                "engine": reading["engine"],
                "seconds": reading["seconds"],
                "lines": reading["lines"],
                "characters": reading["characters"],
                "text_file": str(output / f"{name}.txt"),
            }
        )

    for item in skipped:
        print(f"skipped {item['model']}: {item['reason']}", flush=True)

    (output / "smoke-test.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"the readings are in {output}")
    if failures or (args.require_text and not nonempty):
        print(
            f"smoke test failed: {failures} engine errors, {nonempty} nonempty readings",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
