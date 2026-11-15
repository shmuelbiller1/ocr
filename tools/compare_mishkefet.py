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
from hebrew_workbench.safe_paths import confine_path, default_bases
from hebrew_workbench.engine.mishkefet import MishkefetEngine
from hebrew_workbench.benchmark.metrics import character_error_rate, word_error_rate


#: The name of the file of a reading.  It is taken from this table and
#: never from the argument itself, so that a value that was typed cannot
#: name a file.
MODE_FILE_NAME = {"beam": "beam", "assisted": "assisted"}


def main(argv=None) -> int:
    """Write exact separate readings; score only a user-attested transcript."""
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
    # Every path the tool was given is resolved and kept inside the
    # folders it may use before anything is read or written.
    bases = default_bases()
    output = confine_path(args.output, *bases)
    document = confine_path(args.document, *bases)
    transcript = confine_path(args.transcript, *bases) if args.transcript else None
    output.mkdir(parents=True, exist_ok=True)
    targets = [
        output / f"decoding-{name}.txt"
        for name in ("raw", "comparison-raw", MODE_FILE_NAME[args.mode])
    ]
    targets.append(output / "decoding-comparison.json")
    # Refuse path aliases (including existing hard links) before inference or
    # writing. In particular, never overwrite the reference we intend to score.
    for source in (document, transcript):
        if source is None:
            continue
        for target in targets:
            same_existing_file = source.exists() and target.exists() and source.samefile(target)
            if source.resolve() == target.resolve() or same_existing_file:
                parser.error("An input document/transcript collides with a generated output path")
    report = {"document": args.document, "mode": args.mode, "accuracy": "unverified",
              "runtime_note": "Comparison runtime includes BOTH raw and alternative decoding.",
              "readings": {}}
    try:
        reference = transcript.read_bytes().decode("utf-8") if transcript else None
        if reference is not None and not reference.strip():
            raise ValueError("The verified transcript must not be empty")
        raw = MishkefetEngine(args.model).recognize(document)
        compared = MishkefetEngine(args.model, mode=args.mode).recognize(document)
        if not raw.text.strip() or not (compared.assisted_text or "").strip():
            raise RuntimeError("Comparison requires nonempty raw and alternative readings")
        # The comparison run also contains its own independent raw reading.
        for name, text in (("raw", raw.text), ("comparison-raw", compared.text),
                           (MODE_FILE_NAME[args.mode], compared.assisted_text)):
            path = output / f"decoding-{name}.txt"
            path.write_bytes(text.encode("utf-8"))
            report["readings"][name] = {"text_file": str(path), "characters": len(text)}
        report["raw_seconds"] = raw.duration_seconds
        report["comparison_seconds"] = compared.duration_seconds
        if args.transcript:
            report["accuracy"] = "user-attested independently verified transcript"
            report["verified_by"] = args.verified_by
            report["metric_policy"] = "Exact characters including points, punctuation and line breaks; whitespace-separated WER. No normalisation/correction."
            for name, text in (("raw", raw.text), (MODE_FILE_NAME[args.mode], compared.assisted_text)):
                report["readings"][name].update(
                    cer=character_error_rate(reference, text),
                    wer=word_error_rate(reference, text))
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    with open(output / "decoding-comparison.json", "w", encoding="utf-8") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if "error" in report else 0


if __name__ == "__main__":
    raise SystemExit(main())
