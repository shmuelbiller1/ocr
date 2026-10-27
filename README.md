# Local Hebrew-Script Handwriting Workbench

A Windows-first, offline desktop application for turning scanned handwritten
Hebrew-script notes into editable, printable documents.

> **Status: foundation.** The Windows executable builds and starts on the CI
> build machine, the interface is right-to-left and Hebrew-capable, and the
> OCR engine slot is in place but still fails closed. **No page has been
> transcribed yet by a real engine** - see the status table below.

## Design principles

- **Model independent:** OCR, spelling, grammar, and editorial-style processing
  are separate replaceable adapters.
- **Exact first:** Preserve the source image and unedited transcription; all
  suggested edits must be individually reviewable.
- **Offline by default:** No telemetry, no cloud requests, no automatic model
  downloads.
- **User-controlled:** Spelling, grammar, and `לשון הספר` modes are opt-in and
  cannot silently rewrite original text.
- **Rights checked before bundling:** Each engine, model weight file, language
  dictionary, and installer needs independent licensing verification.
- **Slow and verifiable:** Small pull requests, unit tests, and actual Windows
  packaging tests before a school pilot.

## What works today

| Area | State | Notes |
| --- | --- | --- |
| Windows executable | **Works** | Built by `.github/workflows/windows.yml`; the job starts the packaged `.exe` and fails if it does not answer its self-test |
| Right-to-left interface | **Works** | Qt draws Hebrew with proper bidi layout and letter shaping |
| Import scanned documents | **Works** | Files and folders; PDF, PNG, JPEG, BMP, TIFF, WebP; original files are opened read-only |
| Document list management | **Works** | Add, remove, clear; the files on disk are never touched |
| Editable transcription pane | **Works** | Per-document text, undo/redo, kept separately for every document |
| Save text as `.txt` | **Works** | UTF-8 with BOM so Windows editors show Hebrew correctly |
| OCR engine slot | **Fails closed on purpose** | `Run OCR` reports that no engine is installed and changes nothing |
| PDF/image preview | **Not implemented** | Planned as the next step |
| Spelling / grammar / `לשון הספר` | **Not implemented** | Planned as separate, opt-in modules with a review step |
| Project save/load (keep the work) | **Not implemented** | The data model exists (`hebrew_workbench/project.py`), the menu entry does not |
| Print | **Not implemented** | Planned together with the preview |
| Handwriting recognition with a real model | **Not implemented** | Planned with one licensed, pretrained model |

## Running it from source

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
python app.py
```

The application starts offline, never contacts a server, and never modifies
the documents you open.

## The Windows build

`push` or `pull_request` runs `.github/workflows/windows.yml`, which

1. runs the unit tests,
2. builds `dist/HebrewNotesWorkbench.exe` with PyInstaller,
3. **starts the packaged executable** and runs its self-test (the test also
   creates the real main window), and
4. uploads the executable as the workflow artifact
   `HebrewNotesWorkbench-Windows`.

A user without Python downloads the artifact, unpacks it, and starts
`HebrewNotesWorkbench.exe`.

## Building the executable by hand

```bash
pip install -r requirements.txt pyinstaller==6.16.0
pyinstaller --noconfirm --clean --onefile --windowed --name HebrewNotesWorkbench app.py
```

## Repository layout

```
app.py                        launcher (--selftest, --version)
hebrew_workbench/
    engine/                   replaceable OCR adapters (base contract + registry)
    ui/                       the Qt main window
    project.py                workspace model: documents + their transcriptions
    selftest.py               staged checks used by the packaging job
tests/                        unit tests (standard library unittest)
docs/                         build plan, licenses, accuracy reports
```

## Documents

- `docs/AGENT_BUILD_PLAN.md` - the staged implementation plan and its rules.
- `docs/THIRD_PARTY.md` - every bundled component with its license, and the
  obligations that are still open.
- `docs/OCR_ACCURACY.md` - measured accuracy of the handwriting engine
  (filled in when the engine lands).
