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


def _sync_directory(folder: Path) -> None:
    """Make sure that the name of the new file is on the disk.

    The file itself is written and synchronized before it replaces the
    old one, but the name of the file is kept by the folder.  Without
    this, a power loss right after the writing can leave the old file,
    or no file at all.  Windows has no way to do this, and there the
    name of the file is kept by the system itself.
    """
    if os.name != "posix":
        return
    try:
        handle = os.open(str(folder), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(handle)
    except OSError:
        pass
    finally:
        os.close(handle)


def _read_changes(value) -> list[dict]:
    """The corrections of a document, as they are in the project file.

    A file that was written by another program may hold something that
    is not a list of corrections, and then the file is refused instead
    of being opened with a mistake in it.
    """
    if value is None:
        raise ValueError("the project file holds no list of corrections")
    if not isinstance(value, list):
        raise ValueError("the corrections of a document must be a list")
    changes = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("a correction must be an object")
        # The numbers of the corrections are read when the corrections
        # are taken back, and a file that holds something else is
        # refused here, and not in the middle of the work.
        for name in ("identifier", "covered_by", "batch"):
            number = item.get(name)
            if number is None:
                continue
            try:
                int(number)
            except (TypeError, ValueError):
                raise ValueError(
                    f"the {name} of a correction must be a number"
                ) from None
        changes.append(dict(item))
    return changes


@dataclass
class DocumentEntry:
    """One opened scan plus the transcription the user is working on."""

    path: str
    added_at: str = field(default_factory=_now)
    transcription: str = ""
    #: The text as the recognition gave it, before any correction.  It
    #: is kept so that the user can go back to it.
    original_transcription: str = ""
    assisted_transcription: str | None = None
    decoding_mode: str = "raw"
    engine_name: str = ""
    notes: str = ""
    #: The corrections that the user accepted, in the order they were
    #: accepted.  They are kept so that they can be shown and undone.
    changes: list[dict] = field(default_factory=list)
    #: Did the user write something in this document by hand?  It is
    #: kept so that the program knows that going back to the text of
    #: the recognition would take away what was written, and it asks
    #: the user first.
    edited: bool = False

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
            "original_transcription": self.original_transcription,
            "engine_name": self.engine_name,
            "assisted_transcription": self.assisted_transcription,
            "decoding_mode": self.decoding_mode,
            "notes": self.notes,
            "changes": list(self.changes),
            "edited": bool(self.edited),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DocumentEntry":
        return cls(
            path=str(data.get("path", "")),
            added_at=str(data.get("added_at", _now())),
            transcription=str(data.get("transcription", "")),
            original_transcription=str(data.get("original_transcription", "")),
            engine_name=str(data.get("engine_name", "")),
            assisted_transcription=(str(data["assisted_transcription"])
                                    if data.get("assisted_transcription") is not None else None),
            decoding_mode=str(data.get("decoding_mode", "raw")),
            notes=str(data.get("notes", "")),
            changes=_read_changes(data.get("changes", [])),
            edited=bool(data.get("edited", False)),
        )


class Project:
    """An ordered collection of :class:`DocumentEntry` objects."""

    def __init__(self, documents: Iterable[DocumentEntry] | None = None) -> None:
        self.documents: list[DocumentEntry] = list(documents or [])
        self.path: Path | None = None
        # Is there work that was not written to a project file?  The
        # program asks the user before it throws it away.
        self.dirty: bool = False

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
                # The text of the user must not be lost if the machine
                # loses power in the middle of the writing.
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, target)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
        _sync_directory(target.parent)
        self.path = target
        # The work is in a file now, and the program does not have to
        # ask about it any more.
        self.dirty = False
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
