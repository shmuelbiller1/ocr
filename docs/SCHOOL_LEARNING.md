# School Handwriting Verification, Vocabulary & Personal Adaptation

This document describes the fully offline school handwriting verification,
opt-in vocabulary sharing, local data export, and validation-gated per-student
adaptation workflow in `HebrewNotesWorkbench`.

## 1. Strict Separation: Stage A (Exact Transcription) vs. Stage B (Language Improvements)

To ensure OCR training data always reflects what was physically written on the
scanned page, transcription review is divided into two separate stages:

- **Stage A — Exact Diplomatic Transcription (`אימות כפי שנכתב`, `Ctrl+Shift+V`)**:
  - Right-to-left side-by-side view pairing the original scanned page (with live
    bounding-box highlighting) beside per-line crops and pre-filled OCR text.
  - Users fix *only* OCR reading errors so the text matches the ink on paper,
    preserving the writer's abbreviations and original spelling.
  - Every line carries an explicit 4-state review status:
    1. `not_reviewed` (`לא נבדק` — default): saved locally as a draft so edits
       are never lost; **never** treated as verified merely because it was
       edited or saved.
    2. `verified` (`✓ אומת כפי שנכתב`): reviewer explicitly confirmed the line
       matches the handwriting (`Ctrl+Enter` / `Alt+Enter` confirms and jumps to
       the next line). **Only `verified` lines** enter adapter training or
       exported training splits.
    3. `uncertain` (`? מסופק` / `Alt+U` / `[?]`): saved locally, **strictly
       excluded** from training.
    4. `skipped` (`דלג / מחוק`): crossed-out/scribbled lines excluded from both
       training and diplomatic text assembly.
- **Stage B — Optional Language Improvements (`בדיקת הצעות תיקון` in Main Editor)**:
  - Spelling, grammar, and style modules propose individual corrections with
    per-item Accept / Refuse controls and full Undo.
  - Stage B edits apply only to `entry.transcription` (`entry.changes`) and
    **never** overwrite `entry.diplomatic_transcription` or Stage-A training
    records in `learning.sqlite3`.

## 2. Local SQLite Storage, Backup, Deletion & Online-Training Export

All student profiles, line crops, and audit history stay 100% local in
`school_learning/learning.sqlite3` (SQLite WAL mode) plus lossless PNG crops
from the unmodified original scan:

- **Per-line provenance**: original crop PNG + `(x, y, w, h)` coordinates + page
  dimensions, student profile ID (or `""` for **General / Unknown**), original
  OCR text + confidence + engine/model/SHA-256, preprocessing flags, timestamps,
  document SHA-256 ID, and an append-only `line_revisions` correction history.
- **Backup, restore & deletion**:
  - `backup_database_zip()` creates an atomic `sqlite3.backup()` snapshot +
    crops + adapter history with SHA-256 verification manifest.
  - `restore_database_zip()` validates archive paths (blocking zip-slip),
    verifies file digests, runs `PRAGMA integrity_check`, and checks `.npz`
    files with `allow_pickle=False` before swapping.
  - `delete_writer()` removes a student's profile, personal adapters, cached
    features, and line crops from disk.
- **Export for external / online GPU training & offline re-import**:
  - `export_online_training_bundle_zip()` exports **only `verified` Stage-A lines**
    into page-grouped `train.jsonl` and `val.jsonl` splits plus HuggingFace-compatible
    `metadata.jsonl`, `approved_shared_vocab.json`, `load_dataset_example.py`, and
    `train_online_guide.py` (including profiles that do not yet have verified lines).
  - **Anonymized by default (`writer_001`, `doc_<hash>`)** so schools can take
    verified data offline-to-online (e.g., Colab / GPU cluster for full
    base-model or cohort head training) without exposing student names or OS file paths.
  - `import_external_adapter_npz()` (and `ייבוא מתאם מאומן (.npz)...` inside
    `AdapterHistoryDialog`) safely imports an online-trained `(198, 512)` `float32`
    `.npz` head back into an offline Windows PC using pure-Python `.npy` header
    verification (never executing `pickle`) with full version history and 1-click rollback.

## 3. Opt-In, Administrator-Approved Shared Vocabulary

- Shared school vocabulary is **opt-in (`vocab_sharing_enabled = False` by
  default)**.
- Even when candidate collection is enabled, words from verified lines that are
  not in the bundled CC0 Hebrew lexicon enter a **`pending` administrator review
  queue** — private names, personal notes, student Stage-A typos, and unverified
  OCR guesses are **never** automatically added to the active shared dictionary.
- Only administrator-approved terms (`approve_vocab_term` /
  `SchoolVocabularyDialog`) are exported to `approved_shared_vocab.json` to
  assist optional `Mishkefet` word-prior decoding and `SpellingModule`.

## 4. Validation-Gated Per-Student Head Adaptation & One-Click Rollback

- **Shared frozen base model + separate ~405 KB `.npz` personal heads**:
  `Mishkefet-v1`'s 30M encoder stays frozen and unmodified on disk; each student
  profile adapts only a linear CTC head `(W, b)` stored with
  `allow_pickle=False`.
- **General / Unknown option (`""`)**: Uses the unmodified base model.
- **Strict held-out validation & honest small-sample reporting**:
  - Requires at least `MIN_VERIFIED_FOR_ADAPT = 8` verified lines for that
    student, with an independent held-out set (`>= 2` lines, preferring
    separate pages when `>= 2` pages exist). Training examples are **never**
    reused as test examples.
  - Below 8 verified lines, the system saves all verified lines locally and
    reports *insufficient evidence* rather than claiming guaranteed improvement.
  - A candidate head is activated **only** when independent held-out evaluation
    demonstrates lower character error rate (or tied CER below the base model
    with better held-out CTC log-likelihood and non-worsening WER). Otherwise
    the previous adapter (or base model) remains active.
- **Version history & one-click rollback**: Every accepted round (`head-r0001`,
  `head-r0002`, ...) is recorded in `adapter_versions` and can be rolled back in
  one click (`AdapterHistoryDialog` / `rollback_writer_adapter`) to any earlier
  round or to the pure Base Model (`round 0`).

## 5. Low-Memory & 50-Student Store Resource Profile

- **Bounded page cache**: `DiplomaticVerificationDialog` renders only the active
  page at 300 DPI with a strict 2-page LRU (`MAX_RENDERED_PAGE_CACHE = 2`),
  preventing multi-page PDFs from exhausting RAM on 8 GB Windows PCs.
- **Measured 50-student offline store benchmark**
  (`python tools/benchmark_writer_adaptation.py --low-memory-only`):
  - **50 student profiles + 100 lines (50 verified, 50 uncertain) + admin vocab
    approval + anonymized online ZIP export + full backup & verified restore +
    25-page 300-DPI LRU sweep**: `~1.1s` wall time, `~138 MB` peak RSS,
    `~168 KB` SQLite DB (`learning.sqlite3`).
- Real-page 4-way (`Base`, `Base + Adapter`, `Base + Approved Vocab`,
  `Combined`), cross-writer isolation, reload, and rollback measurements run
  automatically in isolated processes on Windows CI (`ocr-engine` ->
  `writer-adaptation-benchmark.json`).
