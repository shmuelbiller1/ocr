"""Compare baseline/slim packaged workers with local models and no online lookup.

Run from an empty working directory with isolated caches, outbound Python socket
access denied, no source PYTHONPATH, and absolute local model/document paths.
Both bundles must produce exactly the same nonempty raw and alternative text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

CASES = (
    ("kraken-small-pdf", "small.safetensors", "kraken", "raw", "pdf"),
    ("kraken-medium-pdf", "medium.safetensors", "kraken", "raw", "pdf"),
    ("mishkefet-raw-image", "mishkefet-v1.pt", "mishkefet", "raw", "image"),
    ("mishkefet-beam-pdf", "mishkefet-v1.pt", "mishkefet", "beam", "pdf"),
    ("mishkefet-assisted-pdf", "mishkefet-v1.pt", "mishkefet", "assisted", "pdf"),
)


def inventory(folder: Path) -> dict:
    """Measure actual files, not installed package metadata or estimated savings."""
    groups = {}
    total = 0
    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        size = path.stat().st_size
        parts = path.relative_to(folder).parts
        key = parts[1] if len(parts) > 2 and parts[0] == "_internal" else parts[0]
        groups[key] = groups.get(key, 0) + size
        total += size
    return {"bytes": total, "components": dict(sorted(groups.items(), key=lambda item: -item[1]))}


def zip_bytes(folder: Path) -> int:
    """Measure equally compressed worker-only archives, then discard them."""
    with tempfile.TemporaryDirectory() as temp:
        target = Path(temp) / "worker.zip"
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(folder))
        return target.stat().st_size


def validate_payload(payload: dict, mode: str) -> None:
    """Treat empty output, silent fallback and attempted online access as failures."""
    if payload.get("error"):
        raise RuntimeError(payload["error"])
    if not isinstance(payload.get("text"), str) or not payload["text"].strip():
        raise RuntimeError("No raw reading")
    if payload.get("decoding_mode") != mode:
        raise RuntimeError("Wrong decoding mode")
    if mode != "raw" and not (payload.get("assisted_text") or "").strip():
        raise RuntimeError("No alternative reading")
    check = payload.get("offline_check", {})
    if check.get("enabled") is not True or check.get("blocked_attempts") != []:
        raise RuntimeError(f"Offline check failed: {check}")


def run_case(executable: Path, model: Path, document: Path, engine: str, mode: str) -> tuple[dict, float]:
    """Launch the frozen executable outside the checkout with fresh caches."""
    with tempfile.TemporaryDirectory(prefix="ocr-offline-") as temp:
        folder = Path(temp)
        job = {"model_path": str(model.resolve()), "document": str(document.resolve()),
               "engine": engine, "decoding_mode": mode, "offline_check": True}
        (folder / "job.json").write_text(json.dumps(job), encoding="utf-8")
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        for name in ("home", "local", "roaming"):
            (folder / name).mkdir()
        env.update(HOME=str(folder / "home"), USERPROFILE=str(folder / "home"),
                   LOCALAPPDATA=str(folder / "local"), APPDATA=str(folder / "roaming"),
                   HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1",
                   HF_HOME=str(folder / "hf"), TORCH_HOME=str(folder / "torch"),
                   XDG_CACHE_HOME=str(folder / "cache"), PYTHONNOUSERSITE="1")
        started = time.monotonic()
        result = subprocess.run([str(executable.resolve()), "--job", "job.json", "--result", "result.json"],
                                cwd=folder, env=env, capture_output=True, timeout=900)
        seconds = round(time.monotonic() - started, 2)
        if not (folder / "result.json").is_file():
            raise RuntimeError(f"Worker returned {result.returncode}, no result: {result.stderr[-2000:]!r}")
        payload = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        validate_payload(payload, mode)
        if result.returncode:
            raise RuntimeError(f"Worker exited {result.returncode}")
        return payload, seconds


def main(argv=None) -> int:
    """Keep reports even on failure; never accept a smaller but broken worker."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    report = {"offline_scope": "Python socket guard + fresh caches; local IPC allowed; not an OS firewall",
              "cases": [], "bundles": {}, "timing_note": "Cold subprocess wall time including model loading; no memory measurement."}
    try:
        executables = {"inference": args.worker}
        if args.baseline:
            executables = {"baseline": args.baseline, **executables}
        for label, exe in executables.items():
            report["bundles"][label] = inventory(exe.parent)
            if args.baseline:
                report["bundles"][label]["worker_zip_bytes"] = zip_bytes(exe.parent)
        for name, filename, engine, mode, kind in CASES:
            outputs = {}
            case = {"case": name, "runs": {}}
            report["cases"].append(case)
            for label, exe in executables.items():
                payload, seconds = run_case(exe, args.models / filename,
                                           args.pdf if kind == "pdf" else args.image, engine, mode)
                outputs[label] = (payload["text"], payload.get("assisted_text"))
                case["runs"][label] = {"wall_seconds": seconds, "characters": len(payload["text"]),
                                       "raw_sha256": hashlib.sha256(payload["text"].encode()).hexdigest(),
                                       "alternative_characters": len(payload.get("assisted_text") or "")}
            if args.baseline and outputs["baseline"] != outputs["inference"]:
                raise RuntimeError(f"Recognition differs from baseline: {name}")
            case["passed"] = True
            print(f"{name}: passed", flush=True)
        if args.baseline and report["bundles"]["inference"]["bytes"] >= report["bundles"]["baseline"]["bytes"]:
            raise RuntimeError("No measured reduction in worker size")
        report["passed"] = True
    except Exception as exc:
        report.update(passed=False, error=f"{type(exc).__name__}: {exc}")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
