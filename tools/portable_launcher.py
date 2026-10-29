"""One-click, offline Windows launcher for the packaged workbench.

This *small* Python program is built as a windowed PyInstaller --onefile
executable with a verified offline release ZIP included as PyInstaller data.
The original Qt DLLs remain separate files in the automatically unpacked
per-user application cache.

On the first launch, the app is unpacked once to a versioned per-user cache,
without admin rights, an installer, internet access or a setup dialog.
Subsequent launches reuse the already unpacked application.

All bundled model files are independently checked before every launch.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

APP_FOLDER = "HebrewNotesWorkbench"
MODEL_FILENAME = "small.safetensors"
MODEL_SIZE = 13_065_380
MODEL_SHA256 = "3108259779f5abfed3908a1c9eafba64d17e4a2a169368c539ecfeff04c018f3"
MARKER_NAME = ".offline-bundle-ready"
CHUNK_SIZE = 1024 * 1024

MANIFEST_FILENAME = "OFFLINE-MODELS.json"
# Independent pinned digests: a cached file is checked every launch.
FULL_EXTRA_HASHES = {
    "medium.safetensors": (
        63_779_644, "15313b51ace64cbfa81f8f6ef25ad64f04e5a6fb7f7823e67b107527bc081ac9"
    ),
    "mishkefet-v1.pt": (
        120_864_761, "0dfb82e440ebfa9dd61f562ad36a83ec41c23904eacd96623c3bd8f6fd850b88"
    ),
    "hebrew_char6.pkl": (
        28_241_531, "60e6b974e797c74e2c543b27bfe1f9b02e8e8960594cfde7dc452553e4be2161"
    ),
    "hebrew_words.pkl": (
        3_796_006, "39f8ed30114125d53a47d4c383e48338bd5f8ffce21ae981e5fd7f99ade08874"
    ),
}


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _model_is_verified(app_dir: Path) -> bool:
    """The entire edition must be intact, not merely its first model."""
    folder = app_dir / "models"
    manifest_path = folder / MANIFEST_FILENAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        edition = manifest["edition"]
        entries = manifest["models"]
        if edition not in ("lite", "full-noncommercial"):
            return False
        expected = {MODEL_FILENAME: (MODEL_SIZE, MODEL_SHA256)}
        if edition == "full-noncommercial":
            expected.update(FULL_EXTRA_HASHES)
        if not isinstance(entries, list) or len(entries) != len(expected):
            return False
        files = [entry["filename"] for entry in entries]
        if set(files) != set(expected) or len(files) != len(set(files)):
            return False
        for filename, (size, digest) in expected.items():
            path = folder / filename
            if not path.is_file() or path.stat().st_size != size or _checksum(path) != digest:
                return False
            record = next(row for row in entries if row["filename"] == filename)
            if record["size_bytes"] != size or record["sha256"] != digest:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        return False


def _is_ready(app_dir: Path, fingerprint: str) -> bool:
    marker = app_dir / MARKER_NAME
    return (
        marker.is_file()
        and marker.read_text(encoding="ascii").strip() == fingerprint
        and (app_dir / "HebrewNotesWorkbench.exe").is_file()
        and (app_dir / "ocr-worker" / "ocr-worker.exe").is_file()
        and _model_is_verified(app_dir)
    )


def _members(archive: zipfile.ZipFile) -> tuple[list[zipfile.ZipInfo], str]:
    """Reject members that could write outside the application directory."""
    members = archive.infolist()
    if not members:
        raise RuntimeError("The offline application archive is empty.")
    digest = hashlib.sha256()
    seen: set[str] = set()
    for item in members:
        name = item.filename
        parts = PurePosixPath(name).parts
        if (
            not parts
            or parts[0] != APP_FOLDER
            or any(part in ("..", ".") or "\\" in part or ":" in part for part in parts)
            or name.startswith("/")
        ):
            raise RuntimeError("The offline application contains an unsafe file path.")
        if name in seen:
            raise RuntimeError("The offline application contains duplicate file entries.")
        seen.add(name)
        digest.update(f"{name}\0{item.file_size}\0{item.CRC}\n".encode("utf-8"))
    return members, digest.hexdigest()[:24]


def _cache_base() -> Path:
    base = os.getenv("LOCALAPPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Local")
    return Path(base) / "HebrewNotesWorkbench" / "one-click"


def unpack_once(executable: Path, cache_base: Path | None = None) -> Path:
    """Extract the embedded ZIP into a stable per-user cache, atomically."""
    base = cache_base or _cache_base()
    with zipfile.ZipFile(executable, "r") as archive:
        members, fingerprint = _members(archive)
        destination = base / fingerprint
        if _is_ready(destination, fingerprint):
            return destination

        base.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="extract-", dir=base))
        try:
            for member in members:
                relative = PurePosixPath(member.filename)
                # All paths were checked before extraction began.
                target = staging.joinpath(*relative.parts)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, CHUNK_SIZE)

            app_dir = staging / APP_FOLDER
            if not _model_is_verified(app_dir):
                raise RuntimeError("At least one bundled OCR model did not pass SHA-256 verification.")
            if not (app_dir / "HebrewNotesWorkbench.exe").is_file():
                raise RuntimeError("The Windows application is missing from the bundle.")
            if not (app_dir / "ocr-worker" / "ocr-worker.exe").is_file():
                raise RuntimeError("The OCR worker is missing from the bundle.")
            (app_dir / MARKER_NAME).write_text(fingerprint + "\n", encoding="ascii")

            if destination.exists():
                # Another concurrent launch may have completed the same setup.
                if _is_ready(destination, fingerprint):
                    return destination
                raise RuntimeError("An incomplete offline cache is already present. Remove the cache and retry.")
            os.replace(app_dir, destination)
            return destination
        finally:
            shutil.rmtree(staging, ignore_errors=True)


def main(args: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if args is None else args)
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    embedded_archive = base / "one-click-payload.zip"
    if not embedded_archive.is_file():
        raise RuntimeError("The verified offline application data is missing.")
    app_dir = unpack_once(embedded_archive)
    env = dict(os.environ)
    env["HEBREW_WORKBENCH_MODELS"] = str(app_dir / "models")
    command = [str(app_dir / "HebrewNotesWorkbench.exe"), *args]
    # CI can exercise the real, extracted app without a network connection.
    if "--selftest" in args or "--version" in args:
        return subprocess.call(command, cwd=app_dir, env=env)
    subprocess.Popen(command, cwd=app_dir, env=env)
    return 0


def _report_error(error: Exception) -> None:
    message = (
        "Hebrew Notes Workbench could not start its offline package.\n\n"
        f"{error}\n\nThe file is not damaged by this attempt."
    )
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "Hebrew Notes Workbench", 0x10)
    else:
        print(message, file=sys.stderr)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _report_error(exc)
        raise SystemExit(1)
