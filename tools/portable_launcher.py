"""One-click, offline Windows launcher for the packaged workbench.

This *small* Python program is built as a windowed PyInstaller --onefile
executable with a verified offline release ZIP included as PyInstaller data.
The original Qt DLLs remain separate files in the automatically unpacked
per-user application cache.

On the first launch, the app is unpacked once to a versioned per-user cache,
without admin rights, an installer, internet access or a setup dialog.
Subsequent launches reuse the already unpacked application.

The bundled model is independently checked before every launch.
"""

from __future__ import annotations

import hashlib
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


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _model_is_verified(app_dir: Path) -> bool:
    model = app_dir / "models" / MODEL_FILENAME
    return model.is_file() and model.stat().st_size == MODEL_SIZE and _checksum(model) == MODEL_SHA256


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
                raise RuntimeError("The bundled OCR model did not pass its SHA-256 check.")
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
