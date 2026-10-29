"""Build the same OCR worker everywhere, with a conservative inference profile.

`--profile baseline` reproduces the previous collect-all build for comparisons.
No package is uninstalled or source library patched. Models are never fetched.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# These are CLI / contribution tools, not model or dataset implementations.
EXCLUDED_MODULES = ("kraken.ketos", "kraken.kraken", "kraken.contrib")
# Model classes resolved by kraken.models entry points in the supported models.
MODEL_MODULES = ("kraken.lib.ppocr", "kraken.lib.vgsl", "kraken.lib.ro", "kraken.lib.pretrain")
RESOURCES = ("blla.mlmodel", "iso15924.json", "lib/dataset/scripts.json")
VIDEO_DLL = re.compile(r"opencv_videoio_ffmpeg[0-9_]+(?:_64)?\.dll", re.IGNORECASE)


def build_arguments(profile: str, distpath: Path, workpath: Path, package: Path) -> list[str]:
    """Keep runtime imports, metadata and offline segmentation assets explicit."""
    args = ["--noconfirm", "--clean", "--onedir", "--console", "--name", "ocr-worker",
            "--distpath", str(distpath), "--workpath", str(workpath)]
    if profile == "baseline":
        args += ["--collect-all", "kraken", "--collect-all", "torchvision"]
    else:
        args += ["--copy-metadata", "kraken"]
        for module in MODEL_MODULES:
            args += ["--hidden-import", module]
        for module in EXCLUDED_MODULES:
            args += ["--exclude-module", module]
        for resource in RESOURCES:
            source = package / resource
            if not source.is_file():
                raise FileNotFoundError(f"Required offline Kraken resource missing: {source}")
            destination = (Path("kraken") / resource).parent.as_posix()
            args += ["--add-data", f"{source}:{destination}"]
    return args + [str(ROOT / "ocr_worker" / "main.py")]


def remove_video_plugin(worker: Path) -> list[dict]:
    """Remove only OpenCV's separately loaded video plugin, never image codecs."""
    removed = []
    folder = worker / "_internal" / "cv2"
    if folder.is_dir():
        for path in sorted(folder.iterdir()):
            if path.is_file() and VIDEO_DLL.fullmatch(path.name):
                removed.append({"path": path.relative_to(worker).as_posix(), "bytes": path.stat().st_size})
                path.unlink()
    return removed


def main(argv=None) -> int:
    """Build once, fail on missing assets, and record every explicit deletion."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("baseline", "inference"), default="inference")
    parser.add_argument("--distpath", type=Path, default=ROOT / "dist")
    parser.add_argument("--workpath", type=Path, default=ROOT / "build" / "worker")
    parser.add_argument("--report", type=Path, default=ROOT / "build" / "worker-build.json")
    args = parser.parse_args(argv)
    args.distpath = args.distpath.resolve()
    args.workpath = args.workpath.resolve()
    args.report = args.report.resolve()
    distribution = importlib.metadata.distribution("kraken")
    if distribution.version != "7.1.1":
        parser.error("Re-audit packaging when changing the pinned Kraken 7.1.1 version")
    command = [sys.executable, "-m", "PyInstaller", *build_arguments(
        args.profile, args.distpath, args.workpath, Path(distribution.locate_file("kraken")))]
    try:
        subprocess.run(command, cwd=ROOT, check=True, timeout=1800)
    except subprocess.TimeoutExpired:
        print("PyInstaller exceeded the 30-minute build budget", file=sys.stderr)
        return 1
    worker = args.distpath / "ocr-worker"
    removed = remove_video_plugin(worker) if args.profile == "inference" else []
    report = {"profile": args.profile, "kraken_version": distribution.version,
              "excluded_modules": list(EXCLUDED_MODULES) if args.profile == "inference" else [],
              "explicitly_removed_files": removed,
              "worker_bytes": sum(p.stat().st_size for p in worker.rglob("*") if p.is_file())}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
