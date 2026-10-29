"""Model files: what they are, where they come from, and how they are checked.

Nothing is downloaded behind the user's back.  The application asks first,
shows the license, and verifies the file against the digests published by
the model authors *and* against a SHA-256 digest that this project pinned
when the file was first fetched.  A file that does not match is deleted
and reported.

The models listed here are the pretrained weights of the `kraken`
handwriting recognition engine (Apache-2.0).  The engine code itself is
installed separately, and the application keeps working without it.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

__all__ = [
    "ModelArtifact",
    "MODEL_ARTIFACTS",
    "models_directory",
    "artifact_by_id",
    "sha256_of",
    "md5_of",
    "verify_file",
    "install_artifact",
    "InstallError",
]

#: Largest model file the application is willing to download (bytes).
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024


class InstallError(RuntimeError):
    """The model file could not be downloaded or did not pass the check."""


@dataclass(frozen=True)
class ModelArtifact:
    """A downloadable model file with its provenance and its digests."""

    id: str
    name: str
    filename: str
    url: str
    size_bytes: int
    license: str
    license_url: str
    script: str
    engine_version: str
    #: Which engine reads this model: ``kraken`` or ``mishkefet``.
    engine: str = "kraken"
    notes: str = ""
    #: The MD5 that the author of the model published.  Some hosts publish
    #: no MD5, and then only the SHA-256 that this project pinned is
    #: checked.
    md5: str | None = None
    #: The SHA-256 of the file, as it was when this project fetched it.
    sha256: str | None = None

    @property
    def size_mb(self) -> float:
        return round(self.size_bytes / (1024 * 1024), 1)

    def summary(self) -> str:
        return (
            f"{self.name} ({self.id})\n"
            f"Script: {self.script}\n"
            f"License: {self.license} - {self.license_url}\n"
            f"Size: {self.size_mb} MB\n"
            f"Source: {self.url}\n"
            f"{self.notes}"
        )


#: The pretrained models this application knows about.
MODEL_ARTIFACTS: dict[str, ModelArtifact] = {
    "kraken-ppocrv6-small": ModelArtifact(
        id="kraken-ppocrv6-small",
        name="kraken PP-OCRv6 (small) multilingual handwriting model",
        filename="small.safetensors",
        url="https://zenodo.org/api/records/21788405/files/small.safetensors/content",
        size_bytes=13_065_380,
        md5="07279cd68cd4402807542799f12d0f4a",
        # The digest of the file of the record above, taken from the
        # mirror of the same record (the model card points at the same
        # Zenodo DOI) and checked by the build after every download.
        sha256="3108259779f5abfed3908a1c9eafba64d17e4a2a169368c539ecfeff04c018f3",
        license="Apache-2.0",
        license_url="https://zenodo.org/records/21788405",
        script="Hebrew (among 43 other languages)",
        engine_version="kraken >= 7.1.0",
        notes=(
            "The model covers Hebrew together with 43 other languages. "
            "The published character error rate for Hebrew is 6.5% and the "
            "word error rate 18.5% on the authors' test set."
        ),
    ),
    "kraken-ppocrv6-medium": ModelArtifact(
        id="kraken-ppocrv6-medium",
        name="kraken PP-OCRv6 (medium) multilingual handwriting model",
        filename="medium.safetensors",
        url="https://zenodo.org/api/records/21788410/files/medium.safetensors/content",
        size_bytes=63_779_644,
        md5="e3411a453ce3b9e9efae3f8631d85762",
        sha256="15313b51ace64cbfa81f8f6ef25ad64f04e5a6fb7f7823e67b107527bc081ac9",
        license="Apache-2.0",
        license_url="https://zenodo.org/records/21788410",
        script="Hebrew (among 43 other languages)",
        engine_version="kraken >= 7.1.0",
        notes=(
            "The larger variant of the same family. The published character "
            "error rate for Hebrew is 5.1% and the word error rate 14.2%."
        ),
    ),
    "mishkefet-v1": ModelArtifact(
        id="mishkefet-v1",
        name="Mishkefet-v1, a compact recogniser for modern Hebrew cursive",
        filename="mishkefet-v1.pt",
        url=(
            "https://huggingface.co/itayinbar/Mishkefet-v1/resolve/main/"
            "mishkefet-v1.pt"
        ),
        size_bytes=120_864_761,
        license="CC-BY-NC-SA-4.0",
        license_url="https://huggingface.co/itayinbar/Mishkefet-v1",
        script="Hebrew (modern cursive)",
        engine_version="heb-ocr 0.1.0",
        engine="mishkefet",
        notes=(
            "The model was written for modern Hebrew cursive, which is the "
            "material this program is made for. The file is not part of the "
            "program: it is downloaded by the user, on request, and is "
            "checked against the SHA-256 below. The licence is not a "
            "commercial one: the weights may be used for non-commercial "
            "purposes only, and a modified file keeps the same licence. "
            "The model was trained on the published lines of real Hebrew "
            "cursive of the Pinkas corpus, so its numbers on that corpus "
            "are not a clean measurement."
        ),
        sha256=(
            "0dfb82e440ebfa9dd61f562ad36a83ec41c23904eacd96623c3bd8f6fd850b88"
        ),
    ),
}


def artifact_by_id(identifier: str) -> ModelArtifact:
    try:
        return MODEL_ARTIFACTS[identifier]
    except KeyError as exc:
        raise InstallError(f"Unknown model: {identifier}") from exc


def models_directory() -> Path:
    """The folder where downloaded model files are kept."""
    override = os.environ.get("HEBREW_WORKBENCH_MODELS")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "HebrewNotesWorkbench" / "models"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "hebrew-notes-workbench" / "models"


def md5_of(path: str | Path) -> str:
    digest = hashlib.md5()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_of(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: str | Path, artifact: ModelArtifact) -> str | None:
    """Check a downloaded file against the published digests.

    Returns ``None`` when the file is good, otherwise a message that
    explains what is wrong.
    """
    target = Path(path)
    if not target.is_file():
        return "הקובץ אינו קיים"
    size = target.stat().st_size
    if size != artifact.size_bytes:
        return (
            f"גודל הקובץ אינו תואם ({size} במקום {artifact.size_bytes} בתים)"
        )
    if artifact.md5:
        published_md5 = md5_of(target)
        if published_md5.lower() != artifact.md5.lower():
            return "ה-MD5 שפורסם על יד מפרסם המודל אינו תואם"
    if artifact.sha256:
        digest = sha256_of(target)
        if digest.lower() != artifact.sha256.lower():
            return "ה-SHA-256 שנעוץ בפרויקט אינו תואם"
    return None


def install_artifact(
    artifact: ModelArtifact,
    destination: str | Path | None = None,
    progress: Callable[[int, int], None] | None = None,
    timeout: float = 600.0,
    cancel: Callable[[], bool] | None = None,
) -> Path:
    """Download a model file and verify it.

    The file is written to a temporary name first and only moved into
    place after every check passed, so an interrupted download can never
    be mistaken for a good model.

    The download can be stopped: the ``cancel`` callable is asked at
    every step, and a download that was stopped leaves nothing behind.
    """
    target_dir = Path(destination) if destination else models_directory()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / artifact.filename

    if target.exists():
        problem = verify_file(target, artifact)
        if problem is None:
            return target
        target.unlink()

    handle, temp_name = tempfile.mkstemp(
        dir=str(target_dir), prefix=artifact.filename, suffix=".part"
    )
    os.close(handle)
    temp_path = Path(temp_name)
    try:
        request = urllib.request.Request(
            artifact.url, headers={"User-Agent": "HebrewNotesWorkbench/0.2"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with open(temp_path, "wb") as stream:
                while True:
                    if cancel and cancel():
                        raise InstallError("ההורדה בוטלה.")
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    stream.write(chunk)
                    done += len(chunk)
                    if done > MAX_ARTIFACT_BYTES:
                        raise InstallError("הקובץ גדול מדי; ההורדה בוטלה.")
                    if progress:
                        progress(done, total)
        problem = verify_file(temp_path, artifact)
        if problem is not None:
            raise InstallError(
                f"הקובץ שהורד אינו תואם לפרסום ({problem}). הקובץ נמחק ולא ייעשה בו שימוש."
            )
        shutil.move(str(temp_path), str(target))
    except InstallError:
        temp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise InstallError(f"ההורדה נכשלה: {exc}") from exc
    return target
