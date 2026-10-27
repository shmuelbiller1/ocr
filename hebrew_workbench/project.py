"""The workspace model: the list of documents and the text typed for them.

A *project* is a small JSON file (``.hwproj``) that stores which scans
were opened and what the user typed for each of them.  It never stores a
copy of the scan itself, and it never stores anything the user did not
type.  Saving a project is how the user "keeps the work for later".
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

__all__ = ["DocumentEntry", "Project", "PROJECT_SUFFIX", "SCHEMA_VERSION"]

PROJECT_SUFFIX = ".hwproj"
SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class DocumentEntry:
    """One opened scan plus the transcription the user is working on."""

    path: str
    added_at: str = field(default_factory=_now)
    transcription: str = ""
    engine_name: str = ""
    notes: str = ""

    @property
    def file_path(self) -> Path:
        return Path(self.path)

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def exists(self) -> bool:
        return self.file_path.exists()

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "added_at": self.added_at,
            "transcription": self.transcription,
            "engine_name": self.engine_name,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DocumentEntry":
        return cls(
            path=str(data.get("path", "")),
            added_at=str(data.get("added_at", _now())),
            transcription=str(data.get("transcription", "")),
            engine_name=str(data.get("engine_name", "")),
            notes=str(data.get("notes", "")),
        )


class Project:
    """An ordered collection of :class:`DocumentEntry` objects."""

    def __init__(self, documents: Iterable[DocumentEntry] | None = None) -> None:
        self.documents: list[DocumentEntry] = list(documents or [])
        self.path: Path | None = None

    # -- container helpers -------------------------------------------------
    def __len__(self) -> int:
        return len(self.documents)

    def __iter__(self) -> Iterator[DocumentEntry]:
        return iter(self.documents)

    def __getitem__(self, index: int) -> DocumentEntry:
        return self.documents[index]

    def add(self, path: str | Path, transcription: str = "") -> DocumentEntry:
        """Add a document.  Adding the same file twice is a no-op."""
        resolved = str(Path(path).resolve())
        for entry in self.documents:
            if entry.path == resolved:
                return entry
        entry = DocumentEntry(path=resolved, transcription=transcription)
        self.documents.append(entry)
        return entry

    def remove(self, index: int) -> DocumentEntry:
        return self.documents.pop(index)

    def index_of(self, path: str | Path) -> int | None:
        resolved = str(Path(path).resolve())
        for index, entry in enumerate(self.documents):
            if entry.path == resolved:
                return index
        return None

    def clear(self) -> None:
        self.documents.clear()

    @property
    def has_text(self) -> bool:
        return any(entry.transcription.strip() for entry in self.documents)

    # -- persistence -------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "documents": [entry.to_dict() for entry in self.documents],
        }

    def save(self, path: str | Path) -> Path:
        """Write the project atomically so a crash cannot corrupt it."""
        target = Path(path)
        if target.suffix == "":
            target = target.with_suffix(PROJECT_SUFFIX)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        handle, temp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=target.name, suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(payload)
            os.replace(temp_name, target)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
        self.path = target
        return target

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        source = Path(path)
        data = json.loads(source.read_text(encoding="utf-8"))
        version = int(data.get("schema_version", 0))
        if version > SCHEMA_VERSION:
            raise ValueError(
                f"Project file {source} was written by a newer version of the "
                f"application (schema {version}). Update the application first."
            )
        entries = [DocumentEntry.from_dict(item) for item in data.get("documents", [])]
        project = cls(entries)
        project.path = source
        return project
