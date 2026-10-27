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
| Page preview | **Works** | PDF and images, zoom, rotate, first/previous/next/last page, fit to window |
| Keep the work (project file) | **Works** | `File > Save project` writes a `.hwproj` file; `File > Open project` loads it again |
| Export `.txt` | **Works** | UTF-8 with BOM so Windows editors show Hebrew correctly |
| Export `.docx` | **Works** | Word document with right-to-left paragraphs |
| Print | **Works** | Print dialog with the Windows printers, print preview, and "save as PDF" |
| Sample pages | **Works** | `File > Open samples` loads the synthetic pages from `samples/` |
| OCR engine slot | **Fails closed on purpose** | `Run OCR` reports that no engine is installed and changes nothing |
| Handwriting recognition with a real model | **Works, needs the model** | kraken + PP-OCRv6 (Apache-2.0); the model is installed by the user and checked against two digests; the accuracy is measured in `docs/OCR_ACCURACY.md` |
| Spelling proposals | **Works, needs a word list** | The word list of the user; the program ships no dictionary (the Hebrew Hunspell dictionary is AGPL) |
| Grammar proposals | **Works, a few rules** | Punctuation and spacing |
| `לשון הספר` proposals | **Not implemented** | The module exists, is switched off, and says so; see `docs/SUGGESTIONS.md` |
| Accepting and refusing proposals | **Works** | Every proposal is shown first and is accepted or refused on its own; every accepted change is logged and can be undone |
| Text search inside the document | **Not implemented** | Planned |

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
2. builds `dist/HebrewNotesWorkbench/` with PyInstaller,
3. **starts the packaged executable** and runs its self-test (the test also
   creates the real main window),
4. puts the program, the licence texts and a readme for the user into one
   archive (`release/HebrewNotesWorkbench-<version>-win64.zip`), and
5. uploads the folder and the archive as the workflow artifacts
   `HebrewNotesWorkbench-Windows` and `HebrewNotesWorkbench-release`.

A user without Python downloads the archive, unpacks the folder, and
starts `HebrewNotesWorkbench.exe`.  The application is a folder and not a
single file on purpose: the Qt libraries stay separate files, so that they
can be replaced, as the LGPL requires.

## Building the executable by hand

```bash
pip install -r requirements.txt pyinstaller==6.16.0
pyinstaller --noconfirm --clean --onedir --windowed --add-data "samples;samples" --name HebrewNotesWorkbench app.py
python tools/build_release.py --app dist/HebrewNotesWorkbench --download-licences
```

The second command writes the archive for the user and prints the
SHA-256 of the archive.

## Repository layout

```
app.py                        launcher (--selftest, --version)
hebrew_workbench/
    engine/                   replaceable OCR adapters (base contract + registry)
    suggestions/              the spelling, grammar and style modules (proposals only)
    preview/                  offline rendering of PDF pages and images
    ui/                       the Qt main window, the preview pane, the proposals pane
    exporting.py              TXT, DOCX and printing helpers
    project.py                workspace model: documents + their transcriptions
    resources.py              finding the files that ship with the application
    selftest.py               staged checks used by the packaging job
samples/                      synthetic test pages (no real documents)
tests/                        unit tests (standard library unittest)
tools/make_samples.py         regenerates the sample pages
docs/                         build plan, licenses, accuracy reports
```

## Documents

- `docs/AGENT_BUILD_PLAN.md` - the staged implementation plan and its rules.
- `docs/THIRD_PARTY.md` - every bundled component with its license, and the
  obligations that are still open.
- `docs/OCR_ACCURACY.md` - measured accuracy of the handwriting engine
  (filled in when the engine lands).
