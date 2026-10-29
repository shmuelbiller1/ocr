"""Build a single downloaded EXE from the verified Windows ZIP.

Prepare a ZIP containing the existing application, the OCR worker, and
the verified Apache-2.0 Kraken-small model. An optional full noncommercial
edition also includes Kraken-medium, Mishkefet-v1, and Mishkefet's two
language models. GitHub Actions then embeds this
payload as data inside a standard PyInstaller --onefile launcher.

The finished EXE has no installer, no manual extraction step and no model
download. Its launcher automatically unpacks once into a versioned per-user
cache and starts the offline application.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

MODEL_SIZE = 13_065_380
MODEL_SHA256 = "3108259779f5abfed3908a1c9eafba64d17e4a2a169368c539ecfeff04c018f3"
MODEL_NAME = "HebrewNotesWorkbench/models/small.safetensors"
NOTICE_NAME = "HebrewNotesWorkbench/models/MODEL-SOURCE.txt"
MODEL_NOTICE = """Kraken PP-OCRv6 small multilingual handwriting model
Copyright: respective model authors
Source: https://zenodo.org/records/21788405
File: small.safetensors
License: Apache-2.0
SHA-256: 3108259779f5abfed3908a1c9eafba64d17e4a2a169368c539ecfeff04c018f3
The Apache-2.0 license and third-party notices are in the LICENCES folder.
"""

MANIFEST_NAME = "HebrewNotesWorkbench/models/OFFLINE-MODELS.json"
MISHKEFET_NOTICE_NAME = "HebrewNotesWorkbench/LICENCES/MISHKEFET-MODEL-NOTICE.txt"
MISHKEFET_NOTICE = """Mishkefet-v1 model and optional character/word language models
Author: Itay Inbar
Model source: https://huggingface.co/itayinbar/Mishkefet-v1
License: Creative Commons Attribution-NonCommercial-ShareAlike 4.0
License terms: https://creativecommons.org/licenses/by-nc-sa/4.0/
Unmodified original model files; distributed for noncommercial use only.
Attribution and link to license are preserved. No endorsement is implied.
The source is unchanged. Any adaptations must comply with ShareAlike.
The surrounding application's licenses are documented separately.
"""
# Filename -> (published file size, pinned SHA-256, license, original URL).
# These independent pins are checked before the files are shipped.
FULL_EXTRA_SPECS = {
    "medium.safetensors": (
        63_779_644,
        "15313b51ace64cbfa81f8f6ef25ad64f04e5a6fb7f7823e67b107527bc081ac9",
        "Apache-2.0",
        "https://zenodo.org/records/21788410",
    ),
    "mishkefet-v1.pt": (
        120_864_761,
        "0dfb82e440ebfa9dd61f562ad36a83ec41c23904eacd96623c3bd8f6fd850b88",
        "CC-BY-NC-SA-4.0",
        "https://huggingface.co/itayinbar/Mishkefet-v1",
    ),
    "hebrew_char6.pkl": (
        28_241_531,
        "60e6b974e797c74e2c543b27bfe1f9b02e8e8960594cfde7dc452553e4be2161",
        "CC-BY-NC-SA-4.0",
        "https://huggingface.co/itayinbar/Mishkefet-v1",
    ),
    "hebrew_words.pkl": (
        3_796_006,
        "39f8ed30114125d53a47d4c383e48338bd5f8ffce21ae981e5fd7f99ade08874",
        "CC-BY-NC-SA-4.0",
        "https://huggingface.co/itayinbar/Mishkefet-v1",
    ),
}


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(
    archive: Path,
    model: Path,
    output: Path,
    full_models_dir: Path | None = None,
) -> Path:
    """Make a verified lite or noncommercial full offline payload ZIP."""
    for path in (archive, model):
        if not path.is_file():
            raise ValueError(f"Required file is missing: {path}")
    if model.stat().st_size != MODEL_SIZE or checksum(model) != MODEL_SHA256:
        raise ValueError("The model is not the verified Apache-2.0 Kraken-small weights.")

    selections = [(MODEL_NAME, model, MODEL_SIZE, MODEL_SHA256, "Apache-2.0",
                   "https://zenodo.org/records/21788405")]
    if full_models_dir is not None:
        if not full_models_dir.is_dir():
            raise ValueError(f"Full offline model folder missing: {full_models_dir}")
        for filename, (size, sha, license_name, url) in FULL_EXTRA_SPECS.items():
            item = full_models_dir / filename
            if not item.is_file() or item.stat().st_size != size or checksum(item) != sha:
                raise ValueError(f"Full offline edition model failed verification: {filename}")
            selections.append((f"HebrewNotesWorkbench/models/{filename}",
                               item, size, sha, license_name, url))

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.resolve() in (path.resolve() for path in (archive, model)):
        raise ValueError("Output would overwrite an input.")
    fd, intermediate = tempfile.mkstemp(suffix=".zip", dir=output.parent)
    os.close(fd)
    staged = Path(intermediate)
    manifest = {
        "edition": "full-noncommercial" if full_models_dir else "lite",
        "models": [{
            "filename": Path(name).name,
            "size_bytes": size,
            "sha256": sha,
            "license": license_name,
            "source": url,
        } for name, _path, size, sha, license_name, url in selections],
    }
    try:
        shutil.copyfile(archive, staged)
        with zipfile.ZipFile(staged, "a", zipfile.ZIP_STORED, allowZip64=True) as payload:
            files = set(payload.namelist())
            additions = {item[0] for item in selections} | {MANIFEST_NAME, NOTICE_NAME}
            if full_models_dir is not None:
                additions.add(MISHKEFET_NOTICE_NAME)
            if files.intersection(additions):
                raise ValueError("The release ZIP already contains one of the offline model files.")
            if "HebrewNotesWorkbench/HebrewNotesWorkbench.exe" not in files:
                raise ValueError("The release ZIP lacks the desktop application.")
            if "HebrewNotesWorkbench/ocr-worker/ocr-worker.exe" not in files:
                raise ValueError("The release ZIP lacks the OCR worker.")
            if "HebrewNotesWorkbench/LICENCES/NOTICE.txt" not in files:
                raise ValueError("The release ZIP lacks third-party notices.")
            for name, item, _size, _sha, _license, _url in selections:
                payload.write(item, name, compress_type=zipfile.ZIP_STORED)
            payload.writestr(NOTICE_NAME, MODEL_NOTICE.encode("utf-8"))
            payload.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2).encode("utf-8"))
            if full_models_dir is not None:
                payload.writestr(MISHKEFET_NOTICE_NAME, MISHKEFET_NOTICE.encode("utf-8"))

        with zipfile.ZipFile(staged, "r") as result:
            for name, _path, size, sha, _license, _url in selections:
                member = result.getinfo(name)
                if member.file_size != size:
                    raise ValueError(f"Incorrect model size in offline bundle: {name}")
                digest = hashlib.sha256()
                with result.open(member) as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != sha:
                    raise ValueError(f"Offline bundle SHA-256 mismatch: {name}")
        os.replace(staged, output)
    finally:
        staged.unlink(missing_ok=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--full-models-dir", type=Path,
                        help="include all three recognition models and both language models")
    args = parser.parse_args()
    created = build(args.archive, args.model, args.output, args.full_models_dir)
    print(f"one-click offline payload: {created}")
    print(f"size: {created.stat().st_size} bytes")
    print(f"sha256: {checksum(created)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
