"""Pure-Python + Pillow store for student handwriting profiles & school corpus.

Designed so ``HebrewNotesWorkbench.exe`` (which ships without ``numpy`` or
``torch``) can manage 50+ student profiles, crop & store verified diplomatic
handwriting lines, maintain the shared school vocabulary, and export a ready-to-
train school dataset completely offline.

Safety & data-integrity invariants:
1. **Verified-only ingestion**: A line is stored ONLY when the caller passes
   ``verified_exact_as_written=True`` AND ``grammar_unedited_confirmed=True``
   with non-empty diplomatic text and a valid line-crop image.
2. **Diplomatic fidelity**: Lines represent what was physically written in ink
   on the page *before* grammar, style, or author-spelling edits.
3. **Path containment**: ``writer_id`` and ``sample_id`` are strictly validated
   against ASCII slug patterns and verified to resolve inside the store root.
4. **Offline-only**: Nothing leaves the local computer unless the user
   explicitly exports a ZIP archive to a local path they choose.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from PIL import Image

from ..plugins.paths import application_directory

DEFAULT_LEARNING_DIR_ENV = "HEBREW_WORKBENCH_LEARNING_DIR"

_SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
_HEBREW_WORD_RE = re.compile(
    r"[\u05d0-\u05ea]+(?:[\"״'׳][\u05d0-\u05ea]+)*[\u05d0-\u05ea'׳]?"
)
_STRIP_MARKS_RE = re.compile(r"[\u0591-\u05c7]")

MIN_CROP_WIDTH = 16
MIN_CROP_HEIGHT = 8


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def fnv1a_32(text: str) -> int:
    """Deterministic 32-bit FNV-1a hash matching ``mishkefet-app``'s holdout split."""
    h = 0x811C9DC5
    for byte in text.encode("utf-8"):
        h ^= byte
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def is_held_out_sample(sample_id: str) -> bool:
    """Return True for deterministic 1-in-8 validation samples."""
    return (fnv1a_32(sample_id) % 8) == 0


def default_learning_directory() -> Path:
    """Return the local offline directory holding student profiles & school corpus."""
    override = os.environ.get(DEFAULT_LEARNING_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (application_directory() / "school_learning").resolve()


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
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def extract_school_vocab_tokens(diplomatic_text: str) -> list[str]:
    """Extract clean Hebrew words & acronyms (>= 2 letters) from verified lines."""
    cleaned = _STRIP_MARKS_RE.sub("", diplomatic_text or "")
    cleaned = cleaned.replace("״", '"').replace("׳", "'")
    tokens: list[str] = []
    for match in _HEBREW_WORD_RE.finditer(cleaned):
        tok = match.group(0).strip("\"'")
        heb_letters = sum(1 for ch in tok if "\u05d0" <= ch <= "\u05ea")
        if heb_letters >= 2:
            tokens.append(tok)
    return tokens


@dataclass(frozen=True)
class WriterProfile:
    """Metadata for one student / recurring handwriting author."""

    writer_id: str
    name: str
    created_at: str
    samples_count: int = 0
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
            "active_round": int(self.active_round),
            "last_trained_at": self.last_trained_at,
            "model_sha256": self.model_sha256,
            "held_out_cer_before": self.held_out_cer_before,
            "held_out_cer_after": self.held_out_cer_after,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WriterProfile":
        return cls(
            writer_id=str(data["writer_id"]),
            name=str(data["name"]),
            created_at=str(data.get("created_at") or _now_iso()),
            samples_count=int(data.get("samples_count", 0) or 0),
            active_round=int(data.get("active_round", 0) or 0),
            last_trained_at=(
                str(data["last_trained_at"])
                if data.get("last_trained_at")
                else None
            ),
            model_sha256=(
                str(data["model_sha256"]) if data.get("model_sha256") else None
            ),
            held_out_cer_before=(
                float(data["held_out_cer_before"])
                if data.get("held_out_cer_before") is not None
                else None
            ),
            held_out_cer_after=(
                float(data["held_out_cer_after"])
                if data.get("held_out_cer_after") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class VerifiedLineInput:
    """One user-checked diplomatic handwriting line submitted from the UI."""

    crop_image: Image.Image
    diplomatic_text: str
    page_number: int
    line_index: int
    box: tuple[float, float, float, float] | None = None
    ocr_text: str = ""
    ocr_confidence: float | None = None
    verified_exact_as_written: bool = False
    grammar_unedited_confirmed: bool = False


@dataclass(frozen=True)
class VerifiedLineSample:
    """Persisted verified handwriting line record."""

    sample_id: str
    writer_id: str
    writer_name: str
    diplomatic_text: str
    image_relpath: str
    document_key: str
    document_name: str
    page_number: int
    line_index: int
    box: tuple[float, float, float, float] | None
    ocr_text: str
    ocr_confidence: float | None
    verified_at: str
    verified_exact_as_written: bool = True
    grammar_unedited_confirmed: bool = True

    def to_dict(self) -> dict:
        return {
            "sample_id": self.sample_id,
            "writer_id": self.writer_id,
            "writer_name": self.writer_name,
            "diplomatic_text": self.diplomatic_text,
            "image_relpath": self.image_relpath,
            "document_key": self.document_key,
            "document_name": self.document_name,
            "page_number": int(self.page_number),
            "line_index": int(self.line_index),
            "box": list(self.box) if self.box is not None else None,
            "ocr_text": self.ocr_text,
            "ocr_confidence": self.ocr_confidence,
            "verified_at": self.verified_at,
            "verified_exact_as_written": bool(self.verified_exact_as_written),
            "grammar_unedited_confirmed": bool(self.grammar_unedited_confirmed),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VerifiedLineSample":
        raw_box = data.get("box")
        box = (
            tuple(float(v) for v in raw_box[:4])
            if isinstance(raw_box, (list, tuple)) and len(raw_box) == 4
            else None
        )
        return cls(
            sample_id=str(data["sample_id"]),
            writer_id=str(data["writer_id"]),
            writer_name=str(data.get("writer_name", "")),
            diplomatic_text=str(data["diplomatic_text"]),
            image_relpath=str(data["image_relpath"]),
            document_key=str(data.get("document_key", "")),
            document_name=str(data.get("document_name", "")),
            page_number=int(data.get("page_number", 1)),
            line_index=int(data.get("line_index", 0)),
            box=box,
            ocr_text=str(data.get("ocr_text", "")),
            ocr_confidence=(
                float(data["ocr_confidence"])
                if data.get("ocr_confidence") is not None
                else None
            ),
            verified_at=str(data.get("verified_at") or _now_iso()),
            verified_exact_as_written=bool(
                data.get("verified_exact_as_written", True)
            ),
            grammar_unedited_confirmed=bool(
                data.get("grammar_unedited_confirmed", True)
            ),
        )


def crop_line_from_page(
    page_image: Image.Image,
    box: tuple[float, float, float, float],
    *,
    pad_x: int = 8,
    pad_y: int = 6,
) -> Image.Image:
    """Crop one line bounding box ``(x, y, w, h)`` with safe page-clamped padding."""
    pw, ph = page_image.size
    x, y, w, h = box
    x0 = max(0, min(pw - 1, int(round(x)) - pad_x))
    y0 = max(0, min(ph - 1, int(round(y)) - pad_y))
    x1 = max(x0 + 1, min(pw, int(round(x + w)) + pad_x))
    y1 = max(y0 + 1, min(ph, int(round(y + h)) + pad_y))
    return page_image.crop((x0, y0, x1, y1)).convert("RGB")


class SchoolLearningStore:
    """Manages per-student profiles, verified line crops, and shared school data."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = (
            Path(root).expanduser().resolve()
            if root is not None
            else default_learning_directory()
        )

    # -- path helpers & containment ----------------------------------------
    def _validate_id(self, value: str, label: str = "identifier") -> str:
        text = (value or "").strip()
        if not _SAFE_ID_RE.match(text):
            raise ValueError(f"Invalid {label}: {value!r}")
        return text

    def _safe_subpath(self, *parts: str) -> Path:
        candidate = self.root.joinpath(*parts).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("Path escapes school learning store root")
        return candidate

    @property
    def writers_index_path(self) -> Path:
        return self._safe_subpath("writers.json")

    @property
    def shared_vocab_path(self) -> Path:
        return self._safe_subpath("shared_vocab.json")

    @property
    def shared_manifest_path(self) -> Path:
        return self._safe_subpath("shared_corpus", "lines.jsonl")

    def writer_dir(self, writer_id: str) -> Path:
        wid = self._validate_id(writer_id, "writer_id")
        return self._safe_subpath("writers", wid)

    def writer_samples_path(self, writer_id: str) -> Path:
        return self.writer_dir(writer_id) / "samples.json"

    def writer_head_path(self, writer_id: str) -> Path:
        return self.writer_dir(writer_id) / "heads" / "head-current.npz"

    def writer_head_meta_path(self, writer_id: str) -> Path:
        return self.writer_dir(writer_id) / "heads" / "head-current.json"

    def active_head_path(
        self, writer_id: str | None, *, model_sha256: str | None = None
    ) -> Path | None:
        """Return the accepted personal head path if present & matching base model."""
        if not writer_id or not _SAFE_ID_RE.match(writer_id.strip()):
            return None
        npz = self.writer_head_path(writer_id)
        meta_file = self.writer_head_meta_path(writer_id)
        if not npz.is_file() or not meta_file.is_file():
            return None
        if model_sha256:
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
            if meta.get("model_sha256") != model_sha256:
                return None
        return npz

    # -- student / writer management ---------------------------------------
    def list_writers(self) -> list[WriterProfile]:
        path = self.writers_index_path
        if not path.is_file():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(raw, list):
            return []
        out: list[WriterProfile] = []
        for item in raw:
            if isinstance(item, dict) and _SAFE_ID_RE.match(
                str(item.get("writer_id", ""))
            ):
                out.append(WriterProfile.from_dict(item))
        return out

    def get_writer(self, writer_id: str) -> WriterProfile | None:
        wid = (writer_id or "").strip()
        for profile in self.list_writers():
            if profile.writer_id == wid:
                return profile
        return None

    def create_writer(
        self, name: str, writer_id: str | None = None
    ) -> WriterProfile:
        clean_name = " ".join((name or "").strip().split())
        if not clean_name:
            raise ValueError("יש להזין שם תלמיד או כותב.")
        existing = self.list_writers()
        for prof in existing:
            if prof.name == clean_name:
                return prof
        if writer_id is not None:
            wid = self._validate_id(writer_id, "writer_id")
            if any(p.writer_id == wid for p in existing):
                raise ValueError(f"Writer ID already exists: {wid}")
        else:
            digest = hashlib.sha1(clean_name.encode("utf-8")).hexdigest()[:8]
            wid = f"student-{len(existing) + 1:03d}-{digest}"
            idx = len(existing) + 2
            while any(p.writer_id == wid for p in existing):
                wid = f"student-{idx:03d}-{digest}"
                idx += 1
        profile = WriterProfile(
            writer_id=wid,
            name=clean_name,
            created_at=_now_iso(),
        )
        existing.append(profile)
        self._save_writers(existing)
        self.writer_dir(wid).mkdir(parents=True, exist_ok=True)
        return profile

    def rename_writer(self, writer_id: str, new_name: str) -> WriterProfile:
        wid = self._validate_id(writer_id, "writer_id")
        clean_name = " ".join((new_name or "").strip().split())
        if not clean_name:
            raise ValueError("יש להזין שם תקין לתלמיד.")
        writers = self.list_writers()
        updated: WriterProfile | None = None
        new_list: list[WriterProfile] = []
        for prof in writers:
            if prof.writer_id == wid:
                updated = WriterProfile(
                    writer_id=prof.writer_id,
                    name=clean_name,
                    created_at=prof.created_at,
                    samples_count=prof.samples_count,
                    active_round=prof.active_round,
                    last_trained_at=prof.last_trained_at,
                    model_sha256=prof.model_sha256,
                    held_out_cer_before=prof.held_out_cer_before,
                    held_out_cer_after=prof.held_out_cer_after,
                )
                new_list.append(updated)
            else:
                new_list.append(prof)
        if updated is None:
            raise KeyError(f"Unknown writer_id: {wid}")
        self._save_writers(new_list)
        return updated

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
        samples_count = len(self.list_writer_samples(wid))
        writers = self.list_writers()
        updated: WriterProfile | None = None
        new_list: list[WriterProfile] = []
        for prof in writers:
            if prof.writer_id == wid:
                updated = WriterProfile(
                    writer_id=prof.writer_id,
                    name=prof.name,
                    created_at=prof.created_at,
                    samples_count=samples_count,
                    active_round=int(active_round),
                    last_trained_at=_now_iso(),
                    model_sha256=str(model_sha256),
                    held_out_cer_before=held_out_cer_before,
                    held_out_cer_after=held_out_cer_after,
                )
                new_list.append(updated)
            else:
                new_list.append(prof)
        if updated is None:
            raise KeyError(f"Unknown writer_id: {wid}")
        self._save_writers(new_list)
        return updated

    def _save_writers(self, writers: list[WriterProfile]) -> None:
        payload = json.dumps(
            [w.to_dict() for w in writers], ensure_ascii=False, indent=2
        )
        _atomic_write_text(self.writers_index_path, payload + "\n")

    # -- verified diplomatic line ingestion --------------------------------
    def list_writer_samples(self, writer_id: str) -> list[VerifiedLineSample]:
        path = self.writer_samples_path(writer_id)
        if not path.is_file():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(raw, list):
            return []
        return [
            VerifiedLineSample.from_dict(item)
            for item in raw
            if isinstance(item, dict) and item.get("sample_id")
        ]

    def list_all_school_samples(self) -> list[VerifiedLineSample]:
        """Return every verified diplomatic line across all students in the school."""
        all_samples: list[VerifiedLineSample] = []
        for prof in self.list_writers():
            all_samples.extend(self.list_writer_samples(prof.writer_id))
        return all_samples

    def record_verified_lines(
        self,
        writer_id: str,
        document_path: str | Path,
        lines: Iterable[VerifiedLineInput],
    ) -> list[VerifiedLineSample]:
        """Persist human-verified diplomatic lines for a student & shared school pool.

        Strictly refuses any line that was not explicitly confirmed as verified
        exact-as-written before grammar editing.
        """
        profile = self.get_writer(writer_id)
        if profile is None:
            raise KeyError(f"לא נמצא פרופיל תלמיד עבור {writer_id!r}.")

        doc_p = Path(document_path)
        doc_name = doc_p.name or "document"
        doc_key = hashlib.sha1(
            str(doc_p.resolve() if doc_p.exists() else doc_p).encode("utf-8")
        ).hexdigest()[:12]

        existing = {
            s.sample_id: s for s in self.list_writer_samples(profile.writer_id)
        }
        saved_now: list[VerifiedLineSample] = []

        for item in lines:
            if not item.verified_exact_as_written:
                raise ValueError(
                    "לא ניתן לשמור שורה לאימון ללא סימון מפורש שהיא אומתה מול כתב היד."
                )
            if not item.grammar_unedited_confirmed:
                raise ValueError(
                    "לא ניתן לשמור שורה לאימון ללא אישור שהטקסט נכתב כפי שהוא בדף לפני עריכת דקדוק."
                )
            text = " ".join((item.diplomatic_text or "").strip().split())
            if not text:
                continue
            w, h = item.crop_image.size
            if w < MIN_CROP_WIDTH or h < MIN_CROP_HEIGHT:
                continue

            sample_id = (
                f"{profile.writer_id}--{doc_key}-p{int(item.page_number):03d}"
                f"-l{int(item.line_index):03d}"
            )
            rel_img = f"writers/{profile.writer_id}/crops/{sample_id}.png"
            abs_img = self._safe_subpath(*rel_img.split("/"))
            abs_img.parent.mkdir(parents=True, exist_ok=True)

            # If text or image changed on re-verification, invalidate any cached features
            prev = existing.get(sample_id)
            item.crop_image.convert("RGB").save(abs_img, format="PNG")
            if prev is not None and prev.diplomatic_text != text:
                feat_dir = self.writer_dir(profile.writer_id) / "features"
                if feat_dir.is_dir():
                    for old_feat in feat_dir.glob(f"{sample_id}*.npz"):
                        old_feat.unlink(missing_ok=True)

            sample = VerifiedLineSample(
                sample_id=sample_id,
                writer_id=profile.writer_id,
                writer_name=profile.name,
                diplomatic_text=text,
                image_relpath=rel_img,
                document_key=doc_key,
                document_name=doc_name,
                page_number=int(item.page_number),
                line_index=int(item.line_index),
                box=(
                    tuple(float(v) for v in item.box)
                    if item.box is not None
                    else None
                ),
                ocr_text=(item.ocr_text or "").strip(),
                ocr_confidence=item.ocr_confidence,
                verified_at=_now_iso(),
                verified_exact_as_written=True,
                grammar_unedited_confirmed=True,
            )
            existing[sample_id] = sample
            saved_now.append(sample)

        if not saved_now:
            return []

        ordered = sorted(
            existing.values(),
            key=lambda s: (s.verified_at, s.sample_id),
        )
        _atomic_write_text(
            self.writer_samples_path(profile.writer_id),
            json.dumps(
                [s.to_dict() for s in ordered], ensure_ascii=False, indent=2
            )
            + "\n",
        )

        # Update writer sample count & rebuild shared school index + vocabulary
        writers = self.list_writers()
        new_writers: list[WriterProfile] = []
        for prof in writers:
            if prof.writer_id == profile.writer_id:
                new_writers.append(
                    WriterProfile(
                        writer_id=prof.writer_id,
                        name=prof.name,
                        created_at=prof.created_at,
                        samples_count=len(ordered),
                        active_round=prof.active_round,
                        last_trained_at=prof.last_trained_at,
                        model_sha256=prof.model_sha256,
                        held_out_cer_before=prof.held_out_cer_before,
                        held_out_cer_after=prof.held_out_cer_after,
                    )
                )
            else:
                new_writers.append(prof)
        self._save_writers(new_writers)
        self._rebuild_shared_school_pool()
        return saved_now

    # -- shared 50-student school pool & vocabulary ------------------------
    def _rebuild_shared_school_pool(self) -> None:
        all_samples = self.list_all_school_samples()
        jsonl_lines = [
            json.dumps(s.to_dict(), ensure_ascii=False) for s in all_samples
        ]
        _atomic_write_text(
            self.shared_manifest_path,
            ("\n".join(jsonl_lines) + "\n") if jsonl_lines else "",
        )
        vocab_counts: dict[str, int] = {}
        for sample in all_samples:
            for tok in extract_school_vocab_tokens(sample.diplomatic_text):
                vocab_counts[tok] = vocab_counts.get(tok, 0) + 1
        sorted_vocab = dict(
            sorted(vocab_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        )
        _atomic_write_text(
            self.shared_vocab_path,
            json.dumps(
                {
                    "updated_at": _now_iso(),
                    "writers_count": len(self.list_writers()),
                    "verified_lines_count": len(all_samples),
                    "word_counts": sorted_vocab,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )

    def load_shared_vocab_counts(self) -> dict[str, int]:
        path = self.shared_vocab_path
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        raw = data.get("word_counts", {})
        if not isinstance(raw, dict):
            return {}
        return {
            str(k): int(v)
            for k, v in raw.items()
            if isinstance(k, str) and isinstance(v, (int, float)) and v > 0
        }

    def school_summary(self) -> dict[str, int]:
        writers = self.list_writers()
        total_lines = sum(w.samples_count for w in writers)
        trained_writers = sum(1 for w in writers if w.active_round > 0)
        vocab = self.load_shared_vocab_counts()
        return {
            "writers_count": len(writers),
            "trained_writers_count": trained_writers,
            "verified_lines_count": total_lines,
            "shared_vocab_words": len(vocab),
        }

    def export_school_dataset_zip(self, destination_zip: str | Path) -> Path:
        """Export all verified 50-student line crops & manifests into one ZIP."""
        dest = Path(destination_zip).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        all_samples = self.list_all_school_samples()
        writers = self.list_writers()
        vocab = self.load_shared_vocab_counts()
        readme = (
            "Hebrew Notes Workbench — Verified School Handwriting Corpus\n"
            "============================================================\n"
            f"Exported at: {_now_iso()}\n"
            f"Students / Writers: {len(writers)}\n"
            f"Verified diplomatic lines: {len(all_samples)}\n"
            f"Shared vocabulary entries: {len(vocab)}\n\n"
            "Every line in lines.jsonl was human-verified against its cropped\n"
            "handwriting image as written on the page (prior to grammar editing).\n"
            "Compatible with heb-ocr Stage-B multi-writer fine-tuning and\n"
            "benchmark/modern_school ingestion.\n"
        )
        with zipfile.ZipFile(
            dest, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as zf:
            zf.writestr("README.txt", readme)
            zf.writestr(
                "writers.json",
                json.dumps(
                    [w.to_dict() for w in writers], ensure_ascii=False, indent=2
                )
                + "\n",
            )
            zf.writestr(
                "shared_vocab.json",
                json.dumps(vocab, ensure_ascii=False, indent=2) + "\n",
            )
            jsonl_rows: list[str] = []
            for sample in all_samples:
                img_path = self._safe_subpath(*sample.image_relpath.split("/"))
                if not img_path.is_file():
                    continue
                arc_img = f"crops/{sample.writer_id}/{Path(sample.image_relpath).name}"
                zf.write(img_path, arcname=arc_img)
                row = sample.to_dict()
                row["archive_image"] = arc_img
                jsonl_rows.append(json.dumps(row, ensure_ascii=False))
            zf.writestr(
                "lines.jsonl",
                ("\n".join(jsonl_rows) + "\n") if jsonl_rows else "",
            )
        return dest
