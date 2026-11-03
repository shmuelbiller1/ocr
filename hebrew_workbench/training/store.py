"""SQLite-backed offline school handwriting store, provenance, vocab & export.

Design invariants:
1. **100% offline & local**: Uses Python's built-in ``sqlite3`` (WAL mode, ACID
   transactions) plus lossless PNG line crops on disk. Student scans and
   handwriting never leave the machine. Original scans are never modified.
2. **Stage-A exact diplomatic truth only**:
   Every line has an explicit review status:
   - ``not_reviewed``: unconfirmed draft (saved locally so edits are never lost,
     **never** treated as verified or used for training).
   - ``uncertain``: reviewer is unsure of >=1 letter or ``[?]`` appears (saved
     locally, **never** used for training).
   - ``verified``: reviewer explicitly confirmed the transcription matches what
     was physically written before any spelling/grammar/style edits. **Only**
     ``verified`` lines may train an adapter or enter exported training splits.
   - ``skipped``: crossed-out / illegible scribble, excluded from training and
     diplomatic text assembly.
3. **Full provenance & correction history**:
   Preserves original scan crop + ``(x, y, w, h)`` coordinates, student ID (or
   ``""`` for General/Unknown), original OCR text + engine/model/SHA-256,
   preprocessing settings, timestamps, source document SHA-256 ID, and an
   append-only ``line_revisions`` audit log.
4. **Opt-in, administrator-approved shared vocabulary**:
   Private notes, personal names, student typos, and unverified OCR guesses are
   never auto-injected into the shared dictionary. Sharing is opt-in and only
   administrator-approved words/abbreviations are active in decoding/spelling.
5. **Backup, restore, deletion, adapter rollback, and online-training export**:
   Supports atomic SQLite backup/restore, profile/sample deletion, multi-round
   adapter history with one-click rollback, and privacy-safe (anonymized by
   default) ZIP export with ``train.jsonl`` / ``val.jsonl`` / ``metadata.jsonl``
   ready for external/online GPU training later.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from PIL import Image

from ..plugins.paths import application_directory

DEFAULT_LEARNING_DIR_ENV = "HEBREW_WORKBENCH_LEARNING_DIR"

STATUS_NOT_REVIEWED = "not_reviewed"
STATUS_VERIFIED = "verified"
STATUS_UNCERTAIN = "uncertain"
STATUS_SKIPPED = "skipped"
VALID_REVIEW_STATUSES = frozenset(
    {STATUS_NOT_REVIEWED, STATUS_VERIFIED, STATUS_UNCERTAIN, STATUS_SKIPPED}
)

VOCAB_PENDING = "pending"
VOCAB_APPROVED = "approved"
VOCAB_REJECTED = "rejected"
VALID_VOCAB_STATUSES = frozenset({VOCAB_PENDING, VOCAB_APPROVED, VOCAB_REJECTED})

GENERAL_BUCKET = "general"

_SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
_STRIP_MARKS_RE = re.compile(r"[\u0591-\u05bd\u05bf-\u05c7]")
_HEBREW_WORD_RE = re.compile(r"[\u05d0-\u05ea\"'״׳\u05be]{2,}")

MIN_CROP_WIDTH = 16
MIN_CROP_HEIGHT = 8


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_learning_directory() -> Path:
    override = os.environ.get(DEFAULT_LEARNING_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return application_directory() / "school_learning"


def fnv1a_32(text: str) -> int:
    """Deterministic 32-bit FNV-1a hash (matches ``mishkefet-app`` spec)."""
    h = 0x811C9DC5
    for byte in text.encode("utf-8"):
        h ^= byte
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def is_held_out_sample(sample_id: str) -> bool:
    """Deterministic ~12.5% line-level holdout fallback."""
    return (fnv1a_32(sample_id) % 8) == 0


def compute_document_id(document_path: str | Path) -> str:
    """Compute a stable SHA-256 identifier for a source document without loading all into RAM."""
    p = Path(document_path)
    hasher = hashlib.sha256()
    if p.is_file():
        try:
            with p.open("rb") as fh:
                while True:
                    chunk = fh.read(65536)
                    if not chunk:
                        break
                    hasher.update(chunk)
            return hasher.hexdigest()
        except OSError:
            pass
    hasher.update(str(p).encode("utf-8", errors="replace"))
    return hasher.hexdigest()


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _atomic_save_png(path: Path, image: Image.Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.stem}.", suffix=".png", dir=str(path.parent)
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        image.convert("RGB").save(tmp_path, format="PNG", optimize=False)
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def extract_school_vocab_tokens(diplomatic_text: str) -> list[str]:
    """Extract clean Hebrew words & abbreviations (>= 2 Hebrew letters) from verified text."""
    if not diplomatic_text or "[?]" in diplomatic_text:
        # Lines containing uncertainty markers never contribute tokens automatically
        cleaned_src = (diplomatic_text or "").replace("[?]", " ")
    else:
        cleaned_src = diplomatic_text
    cleaned = _STRIP_MARKS_RE.sub("", cleaned_src)
    cleaned = cleaned.replace("״", '"').replace("׳", "'")
    tokens: list[str] = []
    for match in _HEBREW_WORD_RE.finditer(cleaned):
        tok = match.group(0).strip("\"'")
        heb_letters = sum(1 for ch in tok if "\u05d0" <= ch <= "\u05ea")
        if heb_letters >= 2:
            tokens.append(tok)
    return tokens


def crop_line_from_page(
    page_image: Image.Image,
    box: tuple[float, float, float, float],
    *,
    pad_x: int = 8,
    pad_y: int = 6,
) -> Image.Image:
    """Crop one line bounding box ``(x, y, w, h)`` from the unedited scan image."""
    pw, ph = page_image.size
    x, y, w, h = box
    x0 = max(0, min(pw - 1, int(round(x)) - pad_x))
    y0 = max(0, min(ph - 1, int(round(y)) - pad_y))
    x1 = max(x0 + 1, min(pw, int(round(x + w)) + pad_x))
    y1 = max(y0 + 1, min(ph, int(round(y + h)) + pad_y))
    return page_image.crop((x0, y0, x1, y1)).convert("RGB")


@dataclass(frozen=True)
class WriterProfile:
    """Metadata for one student / recurring handwriting author."""

    writer_id: str
    name: str
    created_at: str
    samples_count: int = 0
    uncertain_count: int = 0
    draft_count: int = 0
    active_round: int = 0
    last_trained_at: str | None = None
    model_sha256: str | None = None
    held_out_cer_before: float | None = None
    held_out_cer_after: float | None = None

    def to_dict(self) -> dict:
        return {
            "writer_id": self.writer_id,
            "name": self.name,
            "created_at": self.created_at,
            "samples_count": int(self.samples_count),
            "uncertain_count": int(self.uncertain_count),
            "draft_count": int(self.draft_count),
            "active_round": int(self.active_round),
            "last_trained_at": self.last_trained_at,
            "model_sha256": self.model_sha256,
            "held_out_cer_before": self.held_out_cer_before,
            "held_out_cer_after": self.held_out_cer_after,
        }


@dataclass(frozen=True)
class AdapterVersion:
    """Recorded personal CTC-head version supporting audit & one-click rollback."""

    writer_id: str
    round_number: int
    created_at: str
    head_relpath: str
    model_sha256: str
    samples_total: int
    train_samples: int
    held_out_samples: int
    held_out_chars: int
    held_out_cer_before: float | None
    held_out_cer_after: float | None
    held_out_wer_before: float | None
    held_out_wer_after: float | None
    is_active: bool

    def to_dict(self) -> dict:
        return {
            "writer_id": self.writer_id,
            "round_number": int(self.round_number),
            "created_at": self.created_at,
            "head_relpath": self.head_relpath,
            "model_sha256": self.model_sha256,
            "samples_total": int(self.samples_total),
            "train_samples": int(self.train_samples),
            "held_out_samples": int(self.held_out_samples),
            "held_out_chars": int(self.held_out_chars),
            "held_out_cer_before": self.held_out_cer_before,
            "held_out_cer_after": self.held_out_cer_after,
            "held_out_wer_before": self.held_out_wer_before,
            "held_out_wer_after": self.held_out_wer_after,
            "is_active": bool(self.is_active),
        }


@dataclass(frozen=True)
class LineRevision:
    """Single audit entry in a line's local correction history."""

    revision_id: int
    sample_id: str
    changed_at: str
    old_text: str
    new_text: str
    old_status: str
    new_status: str


@dataclass(frozen=True)
class VocabTermEntry:
    """Shared school vocabulary candidate or administrator-approved entry."""

    term: str
    status: str
    occurrences: int
    writers_count: int
    updated_at: str
    note: str = ""


@dataclass(frozen=True)
class VerifiedLineInput:
    """Line submission from Stage-A verification (supports all 4 review states)."""

    crop_image: Image.Image
    diplomatic_text: str
    page_number: int
    line_index: int
    box: tuple[float, float, float, float] | None = None
    page_size: tuple[int, int] | None = None
    ocr_text: str = ""
    ocr_confidence: float | None = None
    engine_name: str = ""
    engine_version: str = ""
    model_id: str = ""
    model_sha256: str = ""
    decoding_mode: str = "raw"
    preprocessing: dict = field(default_factory=dict)
    review_status: str | None = None
    verified_exact_as_written: bool = False
    grammar_unedited_confirmed: bool = False

    def effective_status(self) -> str:
        """Resolve explicit review status; never infer ``verified`` without confirmation."""
        if self.review_status is not None:
            if self.review_status not in VALID_REVIEW_STATUSES:
                raise ValueError(f"Unknown review_status: {self.review_status!r}")
            status = self.review_status
        elif self.verified_exact_as_written:
            status = STATUS_VERIFIED
        else:
            raise ValueError(
                "לכל שורה חייב להיות מצב בדיקה מפורש; שורות שלא אומתו אינן נשמרות כמאומתות."
            )

        if status == STATUS_VERIFIED:
            if not self.verified_exact_as_written:
                raise ValueError(
                    "שורה המסומנת כ-'אומת' חייבת לכלול אישור verified_exact_as_written=True."
                )
            if not self.grammar_unedited_confirmed:
                raise ValueError(
                    "שורה המסומנת כ-'אומת' חייבת להיות לפני עריכת דקדוק/סגנון (grammar_unedited_confirmed=True)."
                )
            if "[?]" in (self.diplomatic_text or ""):
                raise ValueError(
                    "שורה הכוללת סימן אי-ודאות '[?]' אינה יכולה להישמר כ-'אומת' לאימון — סמנו אותה כ-'מסופק'."
                )
        return status


@dataclass(frozen=True)
class VerifiedLineSample:
    """Persisted Stage-A line record with full local provenance."""

    sample_id: str
    writer_id: str
    writer_name: str
    diplomatic_text: str
    review_status: str
    image_relpath: str
    document_key: str
    document_name: str
    page_number: int
    line_index: int
    box: tuple[float, float, float, float] | None
    page_size: tuple[int, int] | None
    ocr_text: str
    ocr_confidence: float | None
    engine_name: str
    engine_version: str
    model_id: str
    model_sha256: str
    decoding_mode: str
    preprocessing: dict
    created_at: str
    verified_at: str
    verified_exact_as_written: bool = True
    grammar_unedited_confirmed: bool = True

    def to_dict(self) -> dict:
        return {
            "sample_id": self.sample_id,
            "writer_id": self.writer_id,
            "writer_name": self.writer_name,
            "diplomatic_text": self.diplomatic_text,
            "review_status": self.review_status,
            "image_relpath": self.image_relpath,
            "document_key": self.document_key,
            "document_name": self.document_name,
            "page_number": int(self.page_number),
            "line_index": int(self.line_index),
            "box": list(self.box) if self.box is not None else None,
            "page_size": list(self.page_size) if self.page_size is not None else None,
            "ocr_text": self.ocr_text,
            "ocr_confidence": self.ocr_confidence,
            "engine_name": self.engine_name,
            "engine_version": self.engine_version,
            "model_id": self.model_id,
            "model_sha256": self.model_sha256,
            "decoding_mode": self.decoding_mode,
            "preprocessing": dict(self.preprocessing),
            "created_at": self.created_at,
            "verified_at": self.verified_at,
            "verified_exact_as_written": bool(self.verified_exact_as_written),
            "grammar_unedited_confirmed": bool(self.grammar_unedited_confirmed),
        }


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS store_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS writers (
    writer_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    active_round INTEGER NOT NULL DEFAULT 0,
    last_trained_at TEXT,
    model_sha256 TEXT,
    held_out_cer_before REAL,
    held_out_cer_after REAL
);

CREATE TABLE IF NOT EXISTS reviewed_lines (
    sample_id TEXT PRIMARY KEY,
    writer_id TEXT NOT NULL,
    document_key TEXT NOT NULL,
    document_name TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    line_index INTEGER NOT NULL,
    box_json TEXT,
    page_size_json TEXT,
    image_relpath TEXT NOT NULL,
    ocr_text TEXT NOT NULL DEFAULT '',
    ocr_confidence REAL,
    engine_name TEXT NOT NULL DEFAULT '',
    engine_version TEXT NOT NULL DEFAULT '',
    model_id TEXT NOT NULL DEFAULT '',
    model_sha256 TEXT NOT NULL DEFAULT '',
    decoding_mode TEXT NOT NULL DEFAULT 'raw',
    preprocessing_json TEXT NOT NULL DEFAULT '{}',
    diplomatic_text TEXT NOT NULL DEFAULT '',
    review_status TEXT NOT NULL,
    verified_exact INTEGER NOT NULL DEFAULT 0,
    grammar_unedited INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(writer_id, document_key, page_number, line_index)
);

CREATE INDEX IF NOT EXISTS idx_lines_writer_status
    ON reviewed_lines(writer_id, review_status);
CREATE INDEX IF NOT EXISTS idx_lines_doc_page
    ON reviewed_lines(document_key, page_number);

CREATE TABLE IF NOT EXISTS line_revisions (
    revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    old_text TEXT NOT NULL,
    new_text TEXT NOT NULL,
    old_status TEXT NOT NULL,
    new_status TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_revisions_sample
    ON line_revisions(sample_id, revision_id);

CREATE TABLE IF NOT EXISTS adapter_versions (
    writer_id TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    head_relpath TEXT NOT NULL,
    model_sha256 TEXT NOT NULL,
    samples_total INTEGER NOT NULL,
    train_samples INTEGER NOT NULL,
    held_out_samples INTEGER NOT NULL,
    held_out_chars INTEGER NOT NULL DEFAULT 0,
    held_out_cer_before REAL,
    held_out_cer_after REAL,
    held_out_wer_before REAL,
    held_out_wer_after REAL,
    is_active INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (writer_id, round_number)
);

CREATE TABLE IF NOT EXISTS vocab_terms (
    term TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    occurrences INTEGER NOT NULL DEFAULT 1,
    writers_json TEXT NOT NULL DEFAULT '[]',
    note TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
"""


class SchoolLearningStore:
    """Reliable local SQLite-backed store for 50+ student profiles & verified lines."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = (
            Path(root).expanduser().resolve()
            if root is not None
            else default_learning_directory()
        )
        self.db_path = self.root / "learning.sqlite3"
        self.writers_dir = self.root / "writers"
        self.crops_dir = self.root / "crops"
        self.shared_dir = self.root / "shared_corpus"
        self.shared_manifest_path = self.shared_dir / "lines.jsonl"
        self.shared_vocab_path = self.root / "approved_shared_vocab.json"
        self._schema_ready = False

    def _ensure_db(self) -> None:
        if self._schema_ready and self.db_path.is_file():
            return
        self.root.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA_SQL)
            conn.execute(
                "INSERT OR IGNORE INTO store_settings(key, value) VALUES (?, ?)",
                ("vocab_sharing_enabled", "0"),
            )
        self._schema_ready = True

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.root.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _validate_id(value: str, label: str = "id") -> str:
        clean = (value or "").strip()
        if not _SAFE_ID_RE.match(clean):
            raise ValueError(
                f"Invalid {label} {value!r}: must match ^[a-z0-9][a-z0-9_-]{{0,47}}$"
            )
        return clean

    def writer_dir(self, writer_id: str) -> Path:
        wid = self._validate_id(writer_id, "writer_id")
        resolved = (self.writers_dir / wid).resolve()
        if self.writers_dir.resolve() not in resolved.parents:
            raise ValueError(f"Unsafe writer path for {writer_id!r}")
        return resolved

    def writer_head_path(self, writer_id: str) -> Path:
        return self.writer_dir(writer_id) / "head-current.npz"

    def writer_head_meta_path(self, writer_id: str) -> Path:
        return self.writer_dir(writer_id) / "head-current.json"

    def active_head_path(
        self, writer_id: str, *, model_sha256: str | None = None
    ) -> Path | None:
        """Return the active verified personal head ``.npz`` if valid, else ``None``."""
        if not (writer_id or "").strip():
            return None
        try:
            head_path = self.writer_head_path(writer_id)
            meta_path = self.writer_head_meta_path(writer_id)
        except ValueError:
            return None
        if not head_path.is_file() or not meta_path.is_file():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if int(meta.get("round", 0) or 0) <= 0:
            return None
        if model_sha256 and meta.get("model_sha256") != model_sha256:
            return None
        return head_path

    # -- student / writer profiles -----------------------------------------
    def list_writers(self) -> list[WriterProfile]:
        if not self.db_path.is_file():
            return []
        self._ensure_db()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT w.*,
                       COALESCE(SUM(CASE WHEN l.review_status = 'verified' THEN 1 ELSE 0 END), 0) AS verified_cnt,
                       COALESCE(SUM(CASE WHEN l.review_status = 'uncertain' THEN 1 ELSE 0 END), 0) AS uncertain_cnt,
                       COALESCE(SUM(CASE WHEN l.review_status = 'not_reviewed' THEN 1 ELSE 0 END), 0) AS draft_cnt
                FROM writers w
                LEFT JOIN reviewed_lines l ON l.writer_id = w.writer_id
                GROUP BY w.writer_id
                ORDER BY w.created_at ASC, w.writer_id ASC
                """
            ).fetchall()
        return [
            WriterProfile(
                writer_id=str(r["writer_id"]),
                name=str(r["name"]),
                created_at=str(r["created_at"]),
                samples_count=int(r["verified_cnt"]),
                uncertain_count=int(r["uncertain_cnt"]),
                draft_count=int(r["draft_cnt"]),
                active_round=int(r["active_round"]),
                last_trained_at=r["last_trained_at"],
                model_sha256=r["model_sha256"],
                held_out_cer_before=r["held_out_cer_before"],
                held_out_cer_after=r["held_out_cer_after"],
            )
            for r in rows
        ]

    def get_writer(self, writer_id: str) -> WriterProfile | None:
        wid = (writer_id or "").strip()
        if not wid or not _SAFE_ID_RE.match(wid):
            return None
        for prof in self.list_writers():
            if prof.writer_id == wid:
                return prof
        return None

    def create_writer(
        self, name: str, writer_id: str | None = None
    ) -> WriterProfile:
        clean_name = " ".join((name or "").strip().split())
        if not clean_name:
            raise ValueError("יש להזין שם תלמיד או כותב.")
        self._ensure_db()
        existing = self.list_writers()
        for prof in existing:
            if prof.name == clean_name:
                raise ValueError(
                    f"כבר קיים פרופיל בשם '{clean_name}'. יש להוסיף פרט מזהה (למשל כיתה או אות שם משפחה) כדי לא לערבב שני תלמידים."
                )
        if writer_id is not None:
            wid = self._validate_id(writer_id, "writer_id")
            if wid == GENERAL_BUCKET:
                raise ValueError("Reserved writer_id 'general'")
            if any(p.writer_id == wid for p in existing):
                raise ValueError(f"Writer ID already exists: {wid}")
        else:
            digest = hashlib.sha1(clean_name.encode("utf-8")).hexdigest()[:8]
            idx = len(existing) + 1
            wid = f"student-{idx:03d}-{digest}"
            while any(p.writer_id == wid for p in existing):
                idx += 1
                wid = f"student-{idx:03d}-{digest}"

        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO writers(writer_id, name, created_at, active_round)
                VALUES (?, ?, ?, 0)
                """,
                (wid, clean_name, now),
            )
        self.writer_dir(wid).mkdir(parents=True, exist_ok=True)
        return WriterProfile(writer_id=wid, name=clean_name, created_at=now)

    def rename_writer(self, writer_id: str, new_name: str) -> WriterProfile:
        wid = self._validate_id(writer_id, "writer_id")
        clean_name = " ".join((new_name or "").strip().split())
        if not clean_name:
            raise ValueError("השם החדש אינו יכול להיות ריק.")
        self._ensure_db()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE writers SET name = ? WHERE writer_id = ?",
                (clean_name, wid),
            )
            if cur.rowcount == 0:
                raise KeyError(f"Unknown writer_id: {wid}")
        prof = self.get_writer(wid)
        assert prof is not None
        return prof

    def delete_writer(
        self, writer_id: str, *, delete_verified_lines: bool = True
    ) -> None:
        """Delete a student profile, personal adapters, and (by default) their line crops."""
        wid = self._validate_id(writer_id, "writer_id")
        self._ensure_db()
        with self._connect() as conn:
            sample_rows = conn.execute(
                "SELECT sample_id, image_relpath FROM reviewed_lines WHERE writer_id = ?",
                (wid,),
            ).fetchall()
            if delete_verified_lines:
                for sr in sample_rows:
                    conn.execute(
                        "DELETE FROM line_revisions WHERE sample_id = ?",
                        (str(sr["sample_id"]),),
                    )
                conn.execute(
                    "DELETE FROM reviewed_lines WHERE writer_id = ?", (wid,)
                )
            else:
                conn.execute(
                    "UPDATE reviewed_lines SET writer_id = '' WHERE writer_id = ?",
                    (wid,),
                )
            conn.execute(
                "DELETE FROM adapter_versions WHERE writer_id = ?", (wid,)
            )
            conn.execute("DELETE FROM writers WHERE writer_id = ?", (wid,))

        if delete_verified_lines:
            crop_bucket = self.crops_dir / wid
            if crop_bucket.is_dir():
                shutil.rmtree(crop_bucket, ignore_errors=True)
        wdir = self.writer_dir(wid)
        if wdir.is_dir():
            shutil.rmtree(wdir, ignore_errors=True)
        self._sync_shared_manifest_files()

    # -- recording Stage-A lines & audit history ---------------------------
    def record_reviewed_lines(
        self,
        writer_id: str,
        document_path: str | Path,
        lines: list[VerifiedLineInput],
    ) -> list[VerifiedLineSample]:
        """Persist reviewed/draft/uncertain/verified lines with full history.

         accepts ``writer_id == ""`` for the **General / Unknown** profile.
        Only lines whose ``effective_status() == 'verified'`` become training
        samples; ``not_reviewed``, ``uncertain``, and ``skipped`` lines are
        stored safely as local state without polluting training data.
        """
        self._ensure_db()
        clean_wid = (writer_id or "").strip()
        writer_name = "כללי / לא ידוע"
        if clean_wid:
            prof = self.get_writer(clean_wid)
            if prof is None:
                raise KeyError(f"לא נמצא פרופיל תלמיד עבור {clean_wid!r}.")
            writer_name = prof.name
            bucket = clean_wid
        else:
            bucket = GENERAL_BUCKET

        if not lines:
            return []

        doc_path = Path(document_path)
        doc_key = compute_document_id(doc_path)[:16]
        doc_name = doc_path.name or "document"
        now = _now_iso()

        # Validate every input up-front before touching disk or DB
        resolved_statuses: list[tuple[VerifiedLineInput, str]] = []
        for item in lines:
            status = item.effective_status()
            txt = (item.diplomatic_text or "").strip()
            if status == STATUS_VERIFIED and not txt:
                raise ValueError("שורה ריקה אינה יכולה להישמר כ-'אומת'.")
            if item.crop_image is None:
                raise ValueError("חסרה תמונת שורה חתוכה מהסריקה המקורית.")
            cw, ch = item.crop_image.size
            if cw < MIN_CROP_WIDTH or ch < MIN_CROP_HEIGHT:
                raise ValueError(
                    f"גודל חיתוך השורה קטן מדי ({cw}x{ch}); נדרש לפחות {MIN_CROP_WIDTH}x{MIN_CROP_HEIGHT}."
                )
            resolved_statuses.append((item, status))

        persisted: list[VerifiedLineSample] = []
        sharing_on = self.vocab_sharing_enabled()
        new_verified_texts: list[str] = []

        # Stage all crop PNGs to sibling temp files FIRST so a mid-batch I/O or
        # DB failure never overwrites an existing crop while leaving old DB labels.
        staged_crops: dict[tuple[int, int], tuple[str, str, Path, Path]] = {}
        try:
            for idx, (item, _status) in enumerate(resolved_statuses):
                pnum = max(1, int(item.page_number))
                lidx = max(0, int(item.line_index))
                sample_id = f"{bucket}--{doc_key}-p{pnum:03d}-l{lidx:03d}"
                rel_crop = f"crops/{bucket}/{sample_id}.png"
                abs_crop = self.root.joinpath(*rel_crop.split("/"))
                stage_crop = abs_crop.with_name(
                    f".stage-{os.getpid()}-{idx}-{sample_id}.png"
                )
                _atomic_save_png(stage_crop, item.crop_image)
                prev_staged = staged_crops.get((pnum, lidx))
                if prev_staged is not None:
                    prev_staged[2].unlink(missing_ok=True)
                staged_crops[(pnum, lidx)] = (
                    sample_id,
                    rel_crop,
                    stage_crop,
                    abs_crop,
                )

            invalidated_samples: list[str] = []
            with self._connect() as conn:
                for item, status in resolved_statuses:
                    pnum = max(1, int(item.page_number))
                    lidx = max(0, int(item.line_index))
                    sample_id, rel_crop, _stage_crop, _abs_crop = staged_crops[
                        (pnum, lidx)
                    ]

                    txt = " ".join((item.diplomatic_text or "").strip().split())
                    prev = conn.execute(
                        "SELECT diplomatic_text, review_status FROM reviewed_lines WHERE sample_id = ?",
                        (sample_id,),
                    ).fetchone()

                    created_at = now
                    if prev is not None:
                        old_txt = str(prev["diplomatic_text"])
                        old_st = str(prev["review_status"])
                        invalidated_samples.append(sample_id)
                        if old_txt != txt or old_st != status:
                            conn.execute(
                                """
                                INSERT INTO line_revisions(
                                    sample_id, changed_at, old_text, new_text, old_status, new_status
                                ) VALUES (?, ?, ?, ?, ?, ?)
                                """,
                                (sample_id, now, old_txt, txt, old_st, status),
                            )
                        created_row = conn.execute(
                            "SELECT created_at FROM reviewed_lines WHERE sample_id = ?",
                            (sample_id,),
                        ).fetchone()
                        if created_row is not None:
                            created_at = str(created_row["created_at"])
                    else:
                        conn.execute(
                            """
                            INSERT INTO line_revisions(
                                sample_id, changed_at, old_text, new_text, old_status, new_status
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                sample_id,
                                now,
                                (item.ocr_text or "").strip(),
                                txt,
                                STATUS_NOT_REVIEWED,
                                status,
                            ),
                        )

                    box_tuple = (
                        tuple(float(v) for v in item.box[:4])
                        if item.box is not None and len(item.box) == 4
                        else None
                    )
                    psize_tuple = (
                        (int(item.page_size[0]), int(item.page_size[1]))
                        if item.page_size is not None and len(item.page_size) == 2
                        else None
                    )
                    preproc = dict(item.preprocessing or {})
                    is_ver = 1 if status == STATUS_VERIFIED else 0
                    is_gram_unedited = (
                        1
                        if (
                            status == STATUS_VERIFIED
                            and item.grammar_unedited_confirmed
                        )
                        else 0
                    )

                    conn.execute(
                        """
                        INSERT INTO reviewed_lines(
                            sample_id, writer_id, document_key, document_name,
                            page_number, line_index, box_json, page_size_json,
                            image_relpath, ocr_text, ocr_confidence,
                            engine_name, engine_version, model_id, model_sha256,
                            decoding_mode, preprocessing_json,
                            diplomatic_text, review_status,
                            verified_exact, grammar_unedited,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(writer_id, document_key, page_number, line_index) DO UPDATE SET
                            sample_id = excluded.sample_id,
                            document_name = excluded.document_name,
                            box_json = excluded.box_json,
                            page_size_json = excluded.page_size_json,
                            image_relpath = excluded.image_relpath,
                            ocr_text = CASE WHEN excluded.ocr_text != '' THEN excluded.ocr_text ELSE reviewed_lines.ocr_text END,
                            ocr_confidence = COALESCE(excluded.ocr_confidence, reviewed_lines.ocr_confidence),
                            engine_name = CASE WHEN excluded.engine_name != '' THEN excluded.engine_name ELSE reviewed_lines.engine_name END,
                            engine_version = CASE WHEN excluded.engine_version != '' THEN excluded.engine_version ELSE reviewed_lines.engine_version END,
                            model_id = CASE WHEN excluded.model_id != '' THEN excluded.model_id ELSE reviewed_lines.model_id END,
                            model_sha256 = CASE WHEN excluded.model_sha256 != '' THEN excluded.model_sha256 ELSE reviewed_lines.model_sha256 END,
                            decoding_mode = excluded.decoding_mode,
                            preprocessing_json = excluded.preprocessing_json,
                            diplomatic_text = excluded.diplomatic_text,
                            review_status = excluded.review_status,
                            verified_exact = excluded.verified_exact,
                            grammar_unedited = excluded.grammar_unedited,
                            updated_at = excluded.updated_at
                        """,
                        (
                            sample_id,
                            clean_wid,
                            doc_key,
                            doc_name,
                            pnum,
                            lidx,
                            json.dumps(list(box_tuple)) if box_tuple else None,
                            json.dumps(list(psize_tuple)) if psize_tuple else None,
                            rel_crop,
                            (item.ocr_text or "").strip(),
                            (
                                float(item.ocr_confidence)
                                if item.ocr_confidence is not None
                                else None
                            ),
                            str(item.engine_name or ""),
                            str(item.engine_version or ""),
                            str(item.model_id or ""),
                            str(item.model_sha256 or ""),
                            str(item.decoding_mode or "raw"),
                            json.dumps(preproc, ensure_ascii=False),
                            txt,
                            status,
                            is_ver,
                            is_gram_unedited,
                            created_at,
                            now,
                        ),
                    )

                    if status == STATUS_VERIFIED and sharing_on:
                        new_verified_texts.append(txt)

                    persisted.append(
                        VerifiedLineSample(
                            sample_id=sample_id,
                            writer_id=clean_wid,
                            writer_name=writer_name,
                            diplomatic_text=txt,
                            review_status=status,
                            image_relpath=rel_crop,
                            document_key=doc_key,
                            document_name=doc_name,
                            page_number=pnum,
                            line_index=lidx,
                            box=box_tuple,
                            page_size=psize_tuple,
                            ocr_text=(item.ocr_text or "").strip(),
                            ocr_confidence=(
                                float(item.ocr_confidence)
                                if item.ocr_confidence is not None
                                else None
                            ),
                            engine_name=str(item.engine_name or ""),
                            engine_version=str(item.engine_version or ""),
                            model_id=str(item.model_id or ""),
                            model_sha256=str(item.model_sha256 or ""),
                            decoding_mode=str(item.decoding_mode or "raw"),
                            preprocessing=preproc,
                            created_at=created_at,
                            verified_at=now,
                            verified_exact_as_written=bool(is_ver),
                            grammar_unedited_confirmed=bool(is_gram_unedited),
                        )
                    )

            # DB committed cleanly -> atomically promote all staged crop PNGs
            for _sid, _rel, stage_crop, abs_crop in staged_crops.values():
                abs_crop.parent.mkdir(parents=True, exist_ok=True)
                stage_crop.replace(abs_crop)
            for sid in invalidated_samples:
                self._invalidate_sample_features(clean_wid, sid)
        except Exception:
            for _sid, _rel, stage_crop, _abs_crop in staged_crops.values():
                stage_crop.unlink(missing_ok=True)
            raise

        if sharing_on and new_verified_texts:
            self._queue_vocab_candidates(clean_wid or GENERAL_BUCKET, new_verified_texts)
        self._sync_shared_manifest_files()
        return persisted

    def reconcile_document_lines(
        self,
        writer_id: str,
        document_path: str | Path,
        active_keys: set[tuple[int, int]],
    ) -> int:
        """Retire obsolete lines from an older segmentation while keeping audit history."""
        self._ensure_db()
        clean_wid = (writer_id or "").strip()
        if clean_wid and self.get_writer(clean_wid) is None:
            raise KeyError(f"לא נמצא פרופיל תלמיד עבור {clean_wid!r}.")
        doc_key = compute_document_id(Path(document_path))[:16]
        now = _now_iso()
        retired_ids: list[str] = []

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT sample_id, page_number, line_index, diplomatic_text, review_status
                FROM reviewed_lines
                WHERE writer_id = ? AND document_key = ?
                """,
                (clean_wid, doc_key),
            ).fetchall()
            for r in rows:
                key = (int(r["page_number"]), int(r["line_index"]))
                old_st = str(r["review_status"])
                if key in active_keys or old_st == STATUS_SKIPPED:
                    continue
                sid = str(r["sample_id"])
                txt = str(r["diplomatic_text"])
                conn.execute(
                    """
                    INSERT INTO line_revisions(
                        sample_id, changed_at, old_text, new_text, old_status, new_status
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (sid, now, txt, txt, old_st, STATUS_SKIPPED),
                )
                conn.execute(
                    """
                    UPDATE reviewed_lines
                    SET review_status = ?,
                        verified_exact = 0,
                        grammar_unedited = 0,
                        updated_at = ?
                    WHERE sample_id = ?
                    """,
                    (STATUS_SKIPPED, now, sid),
                )
                retired_ids.append(sid)

        if retired_ids:
            for sid in retired_ids:
                self._invalidate_sample_features(clean_wid, sid)
            self._sync_shared_manifest_files()
        return len(retired_ids)

    def record_verified_lines(
        self,
        writer_id: str,
        document_path: str | Path,
        lines: list[VerifiedLineInput],
    ) -> list[VerifiedLineSample]:
        """Strict wrapper requiring every submitted line to be ``STATUS_VERIFIED``."""
        if not (writer_id or "").strip():
            raise ValueError("נדרש לבחור פרופיל תלמיד עבור שמירת שורות אימון אישיות.")
        for item in lines:
            st = item.effective_status()
            if st != STATUS_VERIFIED:
                raise ValueError(
                    f"record_verified_lines accepts only verified lines, got {st!r}"
                )
        return self.record_reviewed_lines(writer_id, document_path, lines)

    def _invalidate_sample_features(self, writer_id: str, sample_id: str) -> None:
        if not writer_id:
            return
        try:
            feat_dir = self.writer_dir(writer_id) / "features"
        except ValueError:
            return
        if feat_dir.is_dir():
            for stale in feat_dir.glob(f"{sample_id}--*.npz"):
                stale.unlink(missing_ok=True)

    def _row_to_sample(self, r: sqlite3.Row, writer_names: dict[str, str]) -> VerifiedLineSample:
        wid = str(r["writer_id"])
        raw_box = json.loads(r["box_json"]) if r["box_json"] else None
        raw_ps = json.loads(r["page_size_json"]) if r["page_size_json"] else None
        try:
            preproc = json.loads(r["preprocessing_json"] or "{}")
        except ValueError:
            preproc = {}
        return VerifiedLineSample(
            sample_id=str(r["sample_id"]),
            writer_id=wid,
            writer_name=writer_names.get(wid, "כללי / לא ידוע" if not wid else wid),
            diplomatic_text=str(r["diplomatic_text"]),
            review_status=str(r["review_status"]),
            image_relpath=str(r["image_relpath"]),
            document_key=str(r["document_key"]),
            document_name=str(r["document_name"]),
            page_number=int(r["page_number"]),
            line_index=int(r["line_index"]),
            box=tuple(float(v) for v in raw_box[:4]) if raw_box else None,
            page_size=(int(raw_ps[0]), int(raw_ps[1])) if raw_ps else None,
            ocr_text=str(r["ocr_text"]),
            ocr_confidence=(
                float(r["ocr_confidence"])
                if r["ocr_confidence"] is not None
                else None
            ),
            engine_name=str(r["engine_name"]),
            engine_version=str(r["engine_version"]),
            model_id=str(r["model_id"]),
            model_sha256=str(r["model_sha256"]),
            decoding_mode=str(r["decoding_mode"]),
            preprocessing=preproc if isinstance(preproc, dict) else {},
            created_at=str(r["created_at"]),
            verified_at=str(r["updated_at"]),
            verified_exact_as_written=bool(r["verified_exact"]),
            grammar_unedited_confirmed=bool(r["grammar_unedited"]),
        )

    def list_writer_samples(
        self,
        writer_id: str,
        *,
        status: str | None = STATUS_VERIFIED,
    ) -> list[VerifiedLineSample]:
        """List lines for ``writer_id`` (defaults strictly to ``verified`` only)."""
        if not self.db_path.is_file():
            return []
        self._ensure_db()
        clean_wid = (writer_id or "").strip()
        wnames = {w.writer_id: w.name for w in self.list_writers()}
        with self._connect() as conn:
            if status is None:
                rows = conn.execute(
                    """
                    SELECT * FROM reviewed_lines
                    WHERE writer_id = ?
                    ORDER BY created_at ASC, page_number ASC, line_index ASC
                    """,
                    (clean_wid,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM reviewed_lines
                    WHERE writer_id = ? AND review_status = ?
                    ORDER BY created_at ASC, page_number ASC, line_index ASC
                    """,
                    (clean_wid, status),
                ).fetchall()
        out: list[VerifiedLineSample] = []
        for r in rows:
            smp = self._row_to_sample(r, wnames)
            if self.root.joinpath(*smp.image_relpath.split("/")).is_file():
                out.append(smp)
        return out

    def list_document_lines(
        self, writer_id: str, document_path: str | Path
    ) -> dict[tuple[int, int], VerifiedLineSample]:
        """Return saved Stage-A line records for ``(writer_id, document_path)`` across all statuses."""
        if not self.db_path.is_file():
            return {}
        self._ensure_db()
        doc_key = compute_document_id(document_path)[:16]
        clean_wid = (writer_id or "").strip()
        wnames = {w.writer_id: w.name for w in self.list_writers()}
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM reviewed_lines
                WHERE writer_id = ? AND document_key = ?
                ORDER BY page_number ASC, line_index ASC
                """,
                (clean_wid, doc_key),
            ).fetchall()
        return {
            (int(r["page_number"]), int(r["line_index"])): self._row_to_sample(
                r, wnames
            )
            for r in rows
        }

    def get_line_history(self, sample_id: str) -> list[LineRevision]:
        """Return chronological correction history for ``sample_id``."""
        if not self.db_path.is_file():
            return []
        self._ensure_db()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM line_revisions
                WHERE sample_id = ?
                ORDER BY revision_id ASC
                """,
                (sample_id,),
            ).fetchall()
        return [
            LineRevision(
                revision_id=int(r["revision_id"]),
                sample_id=str(r["sample_id"]),
                changed_at=str(r["changed_at"]),
                old_text=str(r["old_text"]),
                new_text=str(r["new_text"]),
                old_status=str(r["old_status"]),
                new_status=str(r["new_status"]),
            )
            for r in rows
        ]

    def list_all_school_samples(
        self, *, verified_only: bool = True
    ) -> list[VerifiedLineSample]:
        if not self.db_path.is_file():
            return []
        self._ensure_db()
        wnames = {w.writer_id: w.name for w in self.list_writers()}
        with self._connect() as conn:
            if verified_only:
                rows = conn.execute(
                    """
                    SELECT * FROM reviewed_lines
                    WHERE review_status = 'verified'
                    ORDER BY writer_id ASC, document_key ASC, page_number ASC, line_index ASC
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM reviewed_lines
                    ORDER BY writer_id ASC, document_key ASC, page_number ASC, line_index ASC
                    """
                ).fetchall()
        return [
            s
            for s in (self._row_to_sample(r, wnames) for r in rows)
            if self.root.joinpath(*s.image_relpath.split("/")).is_file()
        ]

    # -- adapter version history & one-click rollback ----------------------
    def record_adapter_version(
        self,
        writer_id: str,
        *,
        round_number: int,
        head_relpath: str,
        model_sha256: str,
        samples_total: int,
        train_samples: int,
        held_out_samples: int,
        held_out_chars: int,
        held_out_cer_before: float | None,
        held_out_cer_after: float | None,
        held_out_wer_before: float | None = None,
        held_out_wer_after: float | None = None,
        activate: bool = True,
    ) -> AdapterVersion:
        wid = self._validate_id(writer_id, "writer_id")
        self._ensure_db()
        now = _now_iso()
        with self._connect() as conn:
            if activate:
                conn.execute(
                    "UPDATE adapter_versions SET is_active = 0 WHERE writer_id = ?",
                    (wid,),
                )
            conn.execute(
                """
                INSERT OR REPLACE INTO adapter_versions(
                    writer_id, round_number, created_at, head_relpath, model_sha256,
                    samples_total, train_samples, held_out_samples, held_out_chars,
                    held_out_cer_before, held_out_cer_after,
                    held_out_wer_before, held_out_wer_after, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    wid,
                    int(round_number),
                    now,
                    head_relpath,
                    model_sha256,
                    int(samples_total),
                    int(train_samples),
                    int(held_out_samples),
                    int(held_out_chars),
                    held_out_cer_before,
                    held_out_cer_after,
                    held_out_wer_before,
                    held_out_wer_after,
                    1 if activate else 0,
                ),
            )
            if activate:
                conn.execute(
                    """
                    UPDATE writers SET
                        active_round = ?,
                        last_trained_at = ?,
                        model_sha256 = ?,
                        held_out_cer_before = ?,
                        held_out_cer_after = ?
                    WHERE writer_id = ?
                    """,
                    (
                        int(round_number),
                        now,
                        model_sha256,
                        held_out_cer_before,
                        held_out_cer_after,
                        wid,
                    ),
                )
        return AdapterVersion(
            writer_id=wid,
            round_number=int(round_number),
            created_at=now,
            head_relpath=head_relpath,
            model_sha256=model_sha256,
            samples_total=int(samples_total),
            train_samples=int(train_samples),
            held_out_samples=int(held_out_samples),
            held_out_chars=int(held_out_chars),
            held_out_cer_before=held_out_cer_before,
            held_out_cer_after=held_out_cer_after,
            held_out_wer_before=held_out_wer_before,
            held_out_wer_after=held_out_wer_after,
            is_active=activate,
        )

    def update_writer_training_metadata(
        self,
        writer_id: str,
        *,
        active_round: int,
        model_sha256: str,
        held_out_cer_before: float | None,
        held_out_cer_after: float | None,
    ) -> WriterProfile:
        wid = self._validate_id(writer_id, "writer_id")
        self._ensure_db()
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE writers SET
                    active_round = ?,
                    last_trained_at = ?,
                    model_sha256 = ?,
                    held_out_cer_before = ?,
                    held_out_cer_after = ?
                WHERE writer_id = ?
                """,
                (
                    int(active_round),
                    now,
                    model_sha256,
                    held_out_cer_before,
                    held_out_cer_after,
                    wid,
                ),
            )
        prof = self.get_writer(wid)
        if prof is None:
            raise KeyError(f"Unknown writer_id: {wid}")
        return prof

    def list_adapter_versions(self, writer_id: str) -> list[AdapterVersion]:
        if not self.db_path.is_file():
            return []
        wid = self._validate_id(writer_id, "writer_id")
        self._ensure_db()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM adapter_versions
                WHERE writer_id = ?
                ORDER BY round_number DESC
                """,
                (wid,),
            ).fetchall()
        return [
            AdapterVersion(
                writer_id=str(r["writer_id"]),
                round_number=int(r["round_number"]),
                created_at=str(r["created_at"]),
                head_relpath=str(r["head_relpath"]),
                model_sha256=str(r["model_sha256"]),
                samples_total=int(r["samples_total"]),
                train_samples=int(r["train_samples"]),
                held_out_samples=int(r["held_out_samples"]),
                held_out_chars=int(r["held_out_chars"]),
                held_out_cer_before=r["held_out_cer_before"],
                held_out_cer_after=r["held_out_cer_after"],
                held_out_wer_before=r["held_out_wer_before"],
                held_out_wer_after=r["held_out_wer_after"],
                is_active=bool(r["is_active"]),
            )
            for r in rows
        ]

    def rollback_writer_adapter(
        self, writer_id: str, target_round: int | None = None
    ) -> WriterProfile:
        """One-click rollback to a previous adapter version or Base Model (round 0).

        - ``target_round == 0``: reverts to the unmodified Base Model.
        - ``target_round is None``: steps back one version prior to current active
          round (or to Base Model ``0`` if currently on round 1).
        - ``target_round > 0``: restores ``head-r{target_round:04d}.npz`` as active.
        """
        wid = self._validate_id(writer_id, "writer_id")
        prof = self.get_writer(wid)
        if prof is None:
            raise KeyError(f"Unknown writer_id: {wid}")
        versions = sorted(
            self.list_adapter_versions(wid), key=lambda v: v.round_number
        )
        if target_round is None:
            earlier = [
                v.round_number
                for v in versions
                if v.round_number < prof.active_round
                and (
                    v.held_out_cer_before is None
                    or v.held_out_cer_after is None
                    or v.held_out_cer_after <= v.held_out_cer_before + 1e-6
                )
            ]
            chosen_round = earlier[-1] if earlier else 0
        else:
            chosen_round = int(target_round)

        if chosen_round <= 0:
            # Revert to Base Model while keeping historical round files intact
            self.writer_head_path(wid).unlink(missing_ok=True)
            self.writer_head_meta_path(wid).unlink(missing_ok=True)
            with self._connect() as conn:
                conn.execute(
                    "UPDATE adapter_versions SET is_active = 0 WHERE writer_id = ?",
                    (wid,),
                )
                conn.execute(
                    """
                    UPDATE writers SET
                        active_round = 0,
                        held_out_cer_before = NULL,
                        held_out_cer_after = NULL
                    WHERE writer_id = ?
                    """,
                    (wid,),
                )
            updated = self.get_writer(wid)
            assert updated is not None
            return updated

        match = next(
            (v for v in versions if v.round_number == chosen_round), None
        )
        if match is None:
            raise ValueError(
                f"גרסת מתאם #{chosen_round} אינה קיימת עבור {prof.name}."
            )
        if (
            match.held_out_cer_before is None
            or match.held_out_cer_after is None
            or match.held_out_cer_after > match.held_out_cer_before + 1e-6
        ):
            raise ValueError(
                f"גרסת מתאם #{chosen_round} לא עברה אימות שיפור על קבוצת בקרה עצמאית ולכן לא ניתן להפעילה."
            )
        src_head = self.root.joinpath(*match.head_relpath.split("/")).resolve()
        if not src_head.is_file():
            raise FileNotFoundError(f"Missing adapter file: {src_head}")

        dst_head = self.writer_head_path(wid)
        dst_head.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_head, dst_head)
        _atomic_write_text(
            self.writer_head_meta_path(wid),
            json.dumps(
                {
                    "writer_id": wid,
                    "writer_name": prof.name,
                    "round": match.round_number,
                    "model_sha256": match.model_sha256,
                    "samples_total": match.samples_total,
                    "train_samples": match.train_samples,
                    "held_out_samples": match.held_out_samples,
                    "held_out_cer_before": match.held_out_cer_before,
                    "held_out_cer_after": match.held_out_cer_after,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )
        with self._connect() as conn:
            conn.execute(
                "UPDATE adapter_versions SET is_active = CASE WHEN round_number = ? THEN 1 ELSE 0 END WHERE writer_id = ?",
                (chosen_round, wid),
            )
            conn.execute(
                """
                UPDATE writers SET
                    active_round = ?,
                    model_sha256 = ?,
                    held_out_cer_before = ?,
                    held_out_cer_after = ?
                WHERE writer_id = ?
                """,
                (
                    chosen_round,
                    match.model_sha256,
                    match.held_out_cer_before,
                    match.held_out_cer_after,
                    wid,
                ),
            )
        updated = self.get_writer(wid)
        assert updated is not None
        return updated

    # -- opt-in, administrator-approved shared school vocabulary -----------
    def vocab_sharing_enabled(self) -> bool:
        """Whether school-wide shared vocabulary is enabled (opt-in, default False)."""
        if not self.db_path.is_file():
            return False
        self._ensure_db()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM store_settings WHERE key = 'vocab_sharing_enabled'"
            ).fetchone()
        return bool(row is not None and str(row["value"]) == "1")

    def set_vocab_sharing_enabled(self, enabled: bool) -> None:
        self._ensure_db()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO store_settings(key, value) VALUES ('vocab_sharing_enabled', ?)",
                ("1" if enabled else "0",),
            )
        self._sync_approved_vocab_file()

    def _queue_vocab_candidates(
        self, writer_bucket: str, diplomatic_texts: list[str]
    ) -> None:
        """Queue unknown words/abbreviations as ``pending`` for admin review (never auto-active)."""
        known_lexicon = None
        try:
            from ..suggestions.hebrew_lexicon import default_hebrew_lexicon

            known_lexicon = default_hebrew_lexicon()
        except Exception:
            known_lexicon = None

        counts: dict[str, int] = {}
        for txt in diplomatic_texts:
            for tok in extract_school_vocab_tokens(txt):
                if known_lexicon is not None and known_lexicon.is_known(tok):
                    continue
                counts[tok] = counts.get(tok, 0) + 1
        if not counts:
            return

        now = _now_iso()
        with self._connect() as conn:
            for term, inc in counts.items():
                existing = conn.execute(
                    "SELECT status, occurrences, writers_json FROM vocab_terms WHERE term = ?",
                    (term,),
                ).fetchone()
                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO vocab_terms(term, status, occurrences, writers_json, note, updated_at)
                        VALUES (?, ?, ?, ?, '', ?)
                        """,
                        (
                            term,
                            VOCAB_PENDING,
                            int(inc),
                            json.dumps([writer_bucket]),
                            now,
                        ),
                    )
                else:
                    try:
                        wset = set(json.loads(existing["writers_json"] or "[]"))
                    except ValueError:
                        wset = set()
                    wset.add(writer_bucket)
                    conn.execute(
                        """
                        UPDATE vocab_terms
                        SET occurrences = occurrences + ?,
                            writers_json = ?,
                            updated_at = ?
                        WHERE term = ?
                        """,
                        (
                            int(inc),
                            json.dumps(sorted(wset)),
                            now,
                            term,
                        ),
                    )

    def list_vocab_terms(self, status: str | None = None) -> list[VocabTermEntry]:
        if not self.db_path.is_file():
            return []
        self._ensure_db()
        with self._connect() as conn:
            if status is None:
                rows = conn.execute(
                    "SELECT * FROM vocab_terms ORDER BY occurrences DESC, term ASC"
                ).fetchall()
            else:
                if status not in VALID_VOCAB_STATUSES:
                    raise ValueError(f"Invalid vocab status: {status!r}")
                rows = conn.execute(
                    "SELECT * FROM vocab_terms WHERE status = ? ORDER BY occurrences DESC, term ASC",
                    (status,),
                ).fetchall()
        out: list[VocabTermEntry] = []
        for r in rows:
            try:
                wlist = json.loads(r["writers_json"] or "[]")
            except ValueError:
                wlist = []
            out.append(
                VocabTermEntry(
                    term=str(r["term"]),
                    status=str(r["status"]),
                    occurrences=int(r["occurrences"]),
                    writers_count=len(wlist) if isinstance(wlist, list) else 0,
                    updated_at=str(r["updated_at"]),
                    note=str(r["note"] or ""),
                )
            )
        return out

    def approve_vocab_term(
        self, term: str, *, note: str = "", enable_sharing: bool = True
    ) -> VocabTermEntry:
        """Administrator approval (or manual addition) of a shared school term/abbreviation."""
        tokens = extract_school_vocab_tokens(term)
        if len(tokens) != 1:
            raise ValueError(
                "יש להזין מילה או ראשי-תיבות עבריים תקינים (לפחות 2 אותיות)."
            )
        clean_term = tokens[0]
        self._ensure_db()
        now = _now_iso()
        with self._connect() as conn:
            if enable_sharing:
                conn.execute(
                    "INSERT OR REPLACE INTO store_settings(key, value) VALUES ('vocab_sharing_enabled', '1')"
                )
            existing = conn.execute(
                "SELECT occurrences, writers_json FROM vocab_terms WHERE term = ?",
                (clean_term,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO vocab_terms(term, status, occurrences, writers_json, note, updated_at)
                    VALUES (?, ?, 1, '["admin"]', ?, ?)
                    """,
                    (clean_term, VOCAB_APPROVED, note.strip(), now),
                )
                occ = 1
                wcnt = 1
            else:
                conn.execute(
                    """
                    UPDATE vocab_terms
                    SET status = ?, note = ?, updated_at = ?
                    WHERE term = ?
                    """,
                    (VOCAB_APPROVED, note.strip(), now, clean_term),
                )
                occ = int(existing["occurrences"])
                try:
                    wcnt = len(json.loads(existing["writers_json"] or "[]"))
                except ValueError:
                    wcnt = 1
        self._sync_approved_vocab_file()
        return VocabTermEntry(
            term=clean_term,
            status=VOCAB_APPROVED,
            occurrences=occ,
            writers_count=wcnt,
            updated_at=now,
            note=note.strip(),
        )

    def reject_vocab_term(self, term: str) -> None:
        clean = (term or "").strip().replace("״", '"').replace("׳", "'")
        self._ensure_db()
        with self._connect() as conn:
            conn.execute(
                "UPDATE vocab_terms SET status = ?, updated_at = ? WHERE term = ?",
                (VOCAB_REJECTED, _now_iso(), clean),
            )
        self._sync_approved_vocab_file()

    def remove_vocab_term(self, term: str) -> None:
        clean = (term or "").strip().replace("״", '"').replace("׳", "'")
        self._ensure_db()
        with self._connect() as conn:
            conn.execute("DELETE FROM vocab_terms WHERE term = ?", (clean,))
        self._sync_approved_vocab_file()

    def _sync_approved_vocab_file(self) -> None:
        if not self.vocab_sharing_enabled():
            if self.shared_vocab_path.is_file():
                self.shared_vocab_path.unlink(missing_ok=True)
            return
        approved = self.list_vocab_terms(status=VOCAB_APPROVED)
        word_counts = {e.term: max(1, e.occurrences) for e in approved}
        _atomic_write_text(
            self.shared_vocab_path,
            json.dumps(
                {
                    "updated_at": _now_iso(),
                    "sharing_enabled": True,
                    "approved_words_count": len(word_counts),
                    "word_counts": word_counts,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )

    def load_shared_vocab_counts(self) -> dict[str, int]:
        """Return ONLY administrator-approved shared vocabulary when opt-in sharing is ON."""
        if not self.db_path.is_file() or not self.vocab_sharing_enabled():
            return {}
        approved = self.list_vocab_terms(status=VOCAB_APPROVED)
        return {e.term: max(1, e.occurrences) for e in approved}

    def _sync_shared_manifest_files(self) -> None:
        verified = self.list_all_school_samples(verified_only=True)
        self.shared_dir.mkdir(parents=True, exist_ok=True)
        lines_jsonl = [
            json.dumps(s.to_dict(), ensure_ascii=False) for s in verified
        ]
        _atomic_write_text(
            self.shared_manifest_path,
            ("\n".join(lines_jsonl) + "\n") if lines_jsonl else "",
        )
        self._sync_approved_vocab_file()

    def school_summary(self) -> dict[str, int]:
        if not self.db_path.is_file():
            return {
                "writers_count": 0,
                "trained_writers_count": 0,
                "verified_lines_count": 0,
                "uncertain_lines_count": 0,
                "draft_lines_count": 0,
                "shared_vocab_words": 0,
                "pending_vocab_words": 0,
            }
        self._ensure_db()
        writers = self.list_writers()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN review_status = 'verified' THEN 1 ELSE 0 END), 0) AS ver,
                    COALESCE(SUM(CASE WHEN review_status = 'uncertain' THEN 1 ELSE 0 END), 0) AS unc,
                    COALESCE(SUM(CASE WHEN review_status = 'not_reviewed' THEN 1 ELSE 0 END), 0) AS drf
                FROM reviewed_lines
                """
            ).fetchone()
        approved = self.load_shared_vocab_counts()
        pending = self.list_vocab_terms(status=VOCAB_PENDING)
        return {
            "writers_count": len(writers),
            "trained_writers_count": sum(1 for w in writers if w.active_round > 0),
            "verified_lines_count": int(row["ver"]) if row else 0,
            "uncertain_lines_count": int(row["unc"]) if row else 0,
            "draft_lines_count": int(row["drf"]) if row else 0,
            "shared_vocab_words": len(approved),
            "pending_vocab_words": len(pending),
        }

    # -- Online-Training-Ready Export + Local Backup & Restore -------------
    def export_online_training_bundle_zip(
        self,
        destination_zip: str | Path,
        *,
        anonymize_writers: bool = True,
        include_uncertain_separate: bool = False,
    ) -> Path:
        """Export verified lines into a turnkey ZIP ready to train online (Colab/HF/heb-ocr).

        - Strictly puts **only** ``STATUS_VERIFIED`` lines into ``train.jsonl``,
          ``val.jsonl``, and ``metadata.jsonl``.
        - Groups validation split by ``(writer_id, document_key, page_number)``
          where possible (falling back to deterministic FNV-1a) so same-page
          lines do not leak across ``train.jsonl`` and ``val.jsonl``.
        - Anonymizes student names & strips original filenames by default
          (``writer_001``, ``doc_43eebe84``) so the school can safely upload the
          archive to an online GPU environment without exposing student PII.
        """
        dest = Path(destination_zip).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        all_samples = self.list_all_school_samples(verified_only=False)
        verified = [s for s in all_samples if s.review_status == STATUS_VERIFIED]
        writers_list = self.list_writers()

        # Deterministic writer anonymization map across ALL profiles + samples
        # (so profiles with 0 verified samples yet never fail lookup during export)
        distinct_wids = sorted(
            {w.writer_id for w in writers_list if w.writer_id}
            | {s.writer_id for s in all_samples if s.writer_id}
        )
        anon_map: dict[str, str] = {"": "general"}
        for idx, wid in enumerate(distinct_wids, start=1):
            anon_map[wid] = f"writer_{idx:03d}" if anonymize_writers else wid

        # Page-grouped train/val split per writer so validation is leakage-free
        by_writer: dict[str, list[VerifiedLineSample]] = {}
        for smp in verified:
            by_writer.setdefault(smp.writer_id, []).append(smp)

        val_ids: set[str] = set()
        for wid, wsamples in by_writer.items():
            pages = sorted({(s.document_key, s.page_number) for s in wsamples})
            if len(pages) >= 2:
                held_pages = {
                    pg
                    for pg in pages
                    if (fnv1a_32(f"{wid}:{pg[0]}:{pg[1]}") % 5) == 0
                }
                if not held_pages:
                    held_pages = {pages[-1]}
                if len(held_pages) == len(pages):
                    held_pages.remove(pages[0])
                for s in wsamples:
                    if (s.document_key, s.page_number) in held_pages:
                        val_ids.add(s.sample_id)
            elif len(wsamples) >= 6:
                for s in wsamples:
                    if is_held_out_sample(s.sample_id):
                        val_ids.add(s.sample_id)
                if not any(s.sample_id in val_ids for s in wsamples):
                    val_ids.add(wsamples[-1].sample_id)

        train_rows: list[str] = []
        val_rows: list[str] = []
        hf_meta_rows: list[str] = []

        loader_py = (
            '"""Minimal loader for online fine-tuning (PyTorch / heb-ocr / HuggingFace)."""\n'
            "import json\n"
            "from pathlib import Path\n"
            "from PIL import Image\n\n"
            "def iter_split(bundle_dir: str | Path, split: str = 'train'):\n"
            "    root = Path(bundle_dir)\n"
            "    manifest = root / f'{split}.jsonl'\n"
            "    for line in manifest.read_text(encoding='utf-8').splitlines():\n"
            "        if not line.strip():\n"
            "            continue\n"
            "        rec = json.loads(line)\n"
            "        with Image.open(root / rec['file_name']) as im:\n"
            "            yield im.convert('RGB'), rec['text'], rec\n"
        )
        online_train_py = (
            '"""Example online GPU/CPU head or full-model training script.\n\n'
            "After training online (e.g. Colab / GPU server), save a head `.npz` with:\n"
            "    np.savez('head-online.npz', W=head_weight_f32, b=head_bias_f32)\n"
            "and import `head-online.npz` back into HebrewNotesWorkbench offline via\n"
            "Adapter History -> 'ייבוא מתאם מאומן (.npz)...'.\n"
            '"""\n'
            "from pathlib import Path\n"
            "from load_dataset_example import iter_split\n\n"
            "if __name__ == '__main__':\n"
            "    root = Path(__file__).resolve().parent\n"
            "    tr = list(iter_split(root, 'train'))\n"
            "    va = list(iter_split(root, 'val'))\n"
            "    print(f'Loaded {len(tr)} train lines and {len(va)} validation lines.')\n"
        )
        readme = (
            "# Exported Verified School Handwriting Corpus (Online-Training Ready)\n\n"
            "- Contains **only** human-verified Stage-A diplomatic transcriptions\n"
            "  (exact handwriting as written on the page, prior to Stage-B grammar edits).\n"
            "- `train.jsonl` / `val.jsonl`: deterministic page-grouped train/validation splits.\n"
            "- `metadata.jsonl`: HuggingFace `datasets.load_dataset('imagefolder', data_dir=...)` compatible.\n"
            "- `approved_shared_vocab.json` (and `shared_vocab.json`): administrator-approved school vocabulary & abbreviations.\n"
            "- `load_dataset_example.py`: zero-dependency Python/Pillow iterator for Colab / GPU training.\n"
            "- `train_online_guide.py`: offline-to-online training & `.npz` re-import template.\n"
        )

        with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("README.md", readme)
            zf.writestr("README.txt", readme)
            zf.writestr("load_dataset_example.py", loader_py)
            zf.writestr("train_online_guide.py", online_train_py)

            for smp in verified:
                src_img = self.root.joinpath(*smp.image_relpath.split("/"))
                if not src_img.is_file():
                    continue
                exp_writer = anon_map.get(smp.writer_id, "general")
                exp_sample = (
                    f"{exp_writer}--{smp.document_key[:10]}-p{smp.page_number:03d}-l{smp.line_index:03d}"
                    if anonymize_writers
                    else smp.sample_id
                )
                arc_img = f"images/{exp_writer}/{exp_sample}.png"
                zf.write(src_img, arc_img)
                split = "validation" if smp.sample_id in val_ids else "train"
                rec = {
                    "file_name": arc_img,
                    "text": smp.diplomatic_text,
                    "split": split,
                    "writer_id": exp_writer,
                    "document_id": smp.document_key,
                    "document_name": (
                        f"doc_{smp.document_key[:8]}"
                        if anonymize_writers
                        else smp.document_name
                    ),
                    "page_number": smp.page_number,
                    "line_index": smp.line_index,
                    "box": list(smp.box) if smp.box else None,
                    "page_size": list(smp.page_size) if smp.page_size else None,
                    "ocr_text": smp.ocr_text,
                    "ocr_confidence": smp.ocr_confidence,
                    "engine_name": smp.engine_name,
                    "engine_version": smp.engine_version,
                    "model_id": smp.model_id,
                    "model_sha256": smp.model_sha256,
                    "preprocessing": smp.preprocessing,
                    "verified_at": smp.verified_at,
                }
                if not anonymize_writers:
                    rec["writer_name"] = smp.writer_name
                line_json = json.dumps(rec, ensure_ascii=False)
                hf_meta_rows.append(line_json)
                if split == "validation":
                    val_rows.append(line_json)
                else:
                    train_rows.append(line_json)

            zf.writestr(
                "train.jsonl",
                ("\n".join(train_rows) + "\n") if train_rows else "",
            )
            zf.writestr(
                "val.jsonl",
                ("\n".join(val_rows) + "\n") if val_rows else "",
            )
            zf.writestr(
                "lines.jsonl",
                ("\n".join(hf_meta_rows) + "\n") if hf_meta_rows else "",
            )
            zf.writestr(
                "metadata.jsonl",
                ("\n".join(hf_meta_rows) + "\n") if hf_meta_rows else "",
            )

            writers_export = [
                {
                    "writer_id": anon_map.get(w.writer_id, w.writer_id or "general"),
                    **(
                        {}
                        if anonymize_writers
                        else {"name": w.name, "original_writer_id": w.writer_id}
                    ),
                    "verified_samples": w.samples_count,
                    "active_round": w.active_round,
                }
                for w in writers_list
            ]
            zf.writestr(
                "writers.json",
                json.dumps(writers_export, ensure_ascii=False, indent=2) + "\n",
            )
            vocab_json_str = (
                json.dumps(
                    {
                        "approved_word_counts": self.load_shared_vocab_counts(),
                        "anonymized": anonymize_writers,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
            zf.writestr("approved_shared_vocab.json", vocab_json_str)
            zf.writestr("shared_vocab.json", vocab_json_str)

            if include_uncertain_separate:
                unc_rows = [
                    json.dumps(
                        {
                            "writer_id": anon_map.get(s.writer_id, "general"),
                            "text": s.diplomatic_text,
                            "review_status": s.review_status,
                            "document_id": s.document_key,
                            "page_number": s.page_number,
                            "line_index": s.line_index,
                        },
                        ensure_ascii=False,
                    )
                    for s in all_samples
                    if s.review_status == STATUS_UNCERTAIN
                ]
                zf.writestr(
                    "uncertain_do_not_train.jsonl",
                    ("\n".join(unc_rows) + "\n") if unc_rows else "",
                )

        return dest

    def export_school_dataset_zip(
        self,
        destination_zip: str | Path,
        *,
        anonymize_writers: bool = True,
    ) -> Path:
        """Export verified school dataset ZIP (anonymized by default)."""
        return self.export_online_training_bundle_zip(
            destination_zip, anonymize_writers=anonymize_writers
        )

    def backup_database_zip(self, destination_zip: str | Path) -> Path:
        """Create a complete local backup ZIP (SQLite snapshot + crops + adapters)."""
        self._ensure_db()
        dest = Path(destination_zip).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="hw-backup-") as td:
            snap_db = Path(td) / "learning.sqlite3"
            with self._connect() as src_conn:
                dst_conn = sqlite3.connect(str(snap_db))
                try:
                    src_conn.backup(dst_conn)
                finally:
                    dst_conn.close()

            checksums: dict[str, str] = {}
            with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(snap_db, "learning.sqlite3")
                checksums["learning.sqlite3"] = compute_document_id(snap_db)

                for folder_name in ("crops", "writers", "shared_corpus"):
                    folder = self.root / folder_name
                    if not folder.is_dir():
                        continue
                    for file_path in sorted(folder.rglob("*")):
                        if not file_path.is_file():
                            continue
                        # Skip regenerable float16 feature caches to keep backups compact
                        if "features" in file_path.parts and file_path.suffix == ".npz":
                            continue
                        rel = file_path.relative_to(self.root).as_posix()
                        zf.write(file_path, rel)
                        checksums[rel] = compute_document_id(file_path)

                if self.shared_vocab_path.is_file():
                    zf.write(self.shared_vocab_path, "approved_shared_vocab.json")
                    checksums["approved_shared_vocab.json"] = compute_document_id(
                        self.shared_vocab_path
                    )

                zf.writestr(
                    "backup_manifest.json",
                    json.dumps(
                        {
                            "created_at": _now_iso(),
                            "files": checksums,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                )
        return dest

    def restore_database_zip(self, source_zip: str | Path) -> None:
        """Validate & atomically restore a local backup archive created by ``backup_database_zip``."""
        src = Path(source_zip).resolve()
        if not src.is_file():
            raise FileNotFoundError(f"Backup archive not found: {src}")

        self.root.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".hw-restore-", dir=str(self.root.parent)
        ) as td:
            stage = Path(td) / "staged"
            prev_root = Path(td) / "previous"
            stage.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(src, "r") as zf:
                names = zf.namelist()
                if "learning.sqlite3" not in names or "backup_manifest.json" not in names:
                    raise ValueError("הקובץ אינו גיבוי תקין של מאגר הלמידה.")
                manifest = json.loads(
                    zf.read("backup_manifest.json").decode("utf-8")
                )
                expected_hashes: dict[str, str] = manifest.get("files", {})
                for member in zf.infolist():
                    rel_parts = Path(member.filename).parts
                    if (
                        not rel_parts
                        or Path(member.filename).is_absolute()
                        or ".." in rel_parts
                    ):
                        raise ValueError(
                            f"Unsafe path in backup archive: {member.filename!r}"
                        )
                    target = (stage / member.filename).resolve()
                    if stage.resolve() not in target.parents and target != stage.resolve():
                        raise ValueError(f"Blocked zip-slip path: {member.filename!r}")
                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(member, "r") as src_f, target.open("wb") as dst_f:
                            shutil.copyfileobj(src_f, dst_f)

            # Verify SHA-256 digests against manifest
            for rel, digest in expected_hashes.items():
                staged_file = stage / rel
                if not staged_file.is_file():
                    raise ValueError(f"Missing expected file in backup: {rel}")
                if compute_document_id(staged_file) != digest:
                    raise ValueError(f"Checksum mismatch in backup file: {rel}")

            # Verify SQLite integrity before swapping
            chk_conn = sqlite3.connect(str(stage / "learning.sqlite3"))
            try:
                res = chk_conn.execute("PRAGMA integrity_check").fetchone()
                if not res or str(res[0]).lower() != "ok":
                    raise ValueError("SQLite integrity check failed on backup.")
            finally:
                chk_conn.close()

            # Verify any .npz adapter heads contain zero pickle objects when numpy is present
            try:
                import numpy as np

                for npz_file in stage.rglob("*.npz"):
                    with np.load(npz_file, allow_pickle=False) as data:
                        _ = list(data.keys())
            except ImportError:
                pass

            (stage / "backup_manifest.json").unlink(missing_ok=True)

            # Atomic same-filesystem swap with full rollback on failure so the
            # existing store is never deleted before replacement succeeds.
            had_existing = self.root.exists()
            if had_existing:
                os.replace(self.root, prev_root)
            try:
                os.replace(stage, self.root)
                self._schema_ready = False
                self._ensure_db()
            except Exception:
                if self.root.exists():
                    shutil.rmtree(self.root, ignore_errors=True)
                if had_existing and prev_root.exists():
                    os.replace(prev_root, self.root)
                raise
