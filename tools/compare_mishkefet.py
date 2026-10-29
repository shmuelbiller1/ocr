"""Compare raw and optional decoding on one document, without changing either.

This diagnostic is deliberately separate from the raw-engine benchmark.
Supply --transcript AND --verified-by only for an independently checked UTF-8
transcription. Otherwise no accuracy scores are emitted. Files preserve the
exact output, including line order, abbreviations and Hebrew vowel points.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hebrew_workbench.console import use_utf8
from hebrew_workbench.engine.mishkefet import MishkefetEngine
from hebrew_workbench.benchmark.metrics import character_error_rate, word_error_rate


def main(argv=None) -> int:
    use_utf8()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--mode", choices=("beam", "assisted"), default="assisted")
    parser.add_argument("--output", default="build/decoding-comparison")
    parser.add_argument("--transcript")
    parser.add_argument("--verified-by")
    args = parser.parse_args(argv)
    if bool(args.transcript) != bool(args.verified_by):
        parser.error("--transcript requires --verified-by, and vice versa")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    report = {"document": args.document, "mode": args.mode, "accuracy": "unverified",
              "runtime_note": "Comparison runtime includes BOTH raw and alternative decoding.",
              "readings": {}}
    try:
        raw = MishkefetEngine(args.model).recognize(args.document)
        compared = MishkefetEngine(args.model, mode=args.mode).recognize(args.document)
        if not raw.text.strip() or not (compared.assisted_text or "").strip():
            raise RuntimeError("Comparison requires nonempty raw and alternative readings")
        # The comparison run also contains its own independent raw reading.
        for name, text in (("raw", raw.text), ("comparison-raw", compared.text),
                           (args.mode, compared.assisted_text)):
            path = output / f"decoding-{name}.txt"
            path.write_text(text, encoding="utf-8")
            report["readings"][name] = {"text_file": str(path), "characters": len(text)}
        report["raw_seconds"] = raw.duration_seconds
        report["comparison_seconds"] = compared.duration_seconds
        if args.transcript:
            reference = Path(args.transcript).read_text(encoding="utf-8")
            if not reference.strip():
                raise ValueError("The verified transcript must not be empty")
            report["accuracy"] = "user-attested independently verified transcript"
            report["verified_by"] = args.verified_by
            report["metric_policy"] = "Exact characters including points, punctuation and line breaks; whitespace-separated WER. No normalisation/correction."
            for name, text in (("raw", raw.text), (args.mode, compared.assisted_text)):
                report["readings"][name].update(
                    cer=character_error_rate(reference, text),
                    wer=word_error_rate(reference, text))
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    (output / "decoding-comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if "error" in report else 0


if __name__ == "__main__":
    raise SystemExit(main())
