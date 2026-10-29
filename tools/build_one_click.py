"""Build a single downloaded EXE from the verified Windows ZIP.

Prepare a ZIP containing the existing application, the OCR worker, and
the verified Apache-2.0 Kraken-small model. GitHub Actions then embeds this
payload as data inside a standard PyInstaller --onefile launcher.

The finished EXE has no installer, no manual extraction step and no model
download. Its launcher automatically unpacks once into a versioned per-user
cache and starts the offline application.
"""

from __future__ import annotations

import argparse
import hashlib
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


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(archive: Path, model: Path, output: Path) -> Path:
    for path in (archive, model):
        if not path.is_file():
            raise ValueError(f"Required file is missing: {path}")
    if model.stat().st_size != MODEL_SIZE or checksum(model) != MODEL_SHA256:
        raise ValueError("The model is not the verified Apache-2.0 Kraken-small weights.")

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.resolve() in (archive.resolve(), model.resolve()):
        raise ValueError("Output would overwrite an input.")
    fd, intermediate = tempfile.mkstemp(suffix=".zip", dir=output.parent)
    os.close(fd)
    staged = Path(intermediate)
    try:
        shutil.copyfile(archive, staged)
        with zipfile.ZipFile(staged, "a", zipfile.ZIP_STORED, allowZip64=True) as payload:
            files = set(payload.namelist())
            if MODEL_NAME in files or NOTICE_NAME in files:
                raise ValueError("The model is already present in the input release ZIP.")
            if "HebrewNotesWorkbench/HebrewNotesWorkbench.exe" not in files:
                raise ValueError("The release ZIP lacks the desktop application.")
            if "HebrewNotesWorkbench/ocr-worker/ocr-worker.exe" not in files:
                raise ValueError("The release ZIP lacks the OCR worker.")
            if "HebrewNotesWorkbench/LICENCES/NOTICE.txt" not in files:
                raise ValueError("The release ZIP lacks third-party notices.")
            payload.write(model, MODEL_NAME, compress_type=zipfile.ZIP_STORED)
            payload.writestr(NOTICE_NAME, MODEL_NOTICE.encode("utf-8"))

        with zipfile.ZipFile(staged, "r") as result:
            member = result.getinfo(MODEL_NAME)
            if member.file_size != MODEL_SIZE:
                raise ValueError("The offline bundle contains an incorrect model.")
            digest = hashlib.sha256()
            with result.open(member) as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != MODEL_SHA256:
                raise ValueError("The offline bundle failed SHA-256 verification.")
        os.replace(staged, output)
    finally:
        staged.unlink(missing_ok=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    created = build(args.archive, args.model, args.output)
    print(f"one-click offline payload: {created}")
    print(f"size: {created.stat().st_size} bytes")
    print(f"sha256: {checksum(created)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
