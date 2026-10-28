# Local Hebrew-Script Handwriting Workbench

A Windows-first, offline desktop application for turning scanned handwritten
Hebrew-script notes into editable, printable documents.

**The material it is made for is the handwriting of today:** the notes
that students write in class, with a pen, in a notebook or on a sheet
of paper.  The program reads the Hebrew letters of those notes, and it
does not care whether the words are Hebrew, Yiddish, Aramaic,
abbreviations or the terms of the subject: the spelling, the
abbreviations and the order of the lines of the writer are kept, and
the text is never changed by the program itself.

The pages of old handwriting are measured as well, as a diagnostic of
the engine, but they are not what the program is made for.

> **Status: the engine works.** The Windows executable builds and starts on
> the CI build machine, the interface is right-to-left and Hebrew-capable,
> and the recognition engine reads real handwritten pages with kraken and
> PP-OCRv6 (both Apache-2.0).  The measured accuracy on early modern
> Hebrew cursive is a character error rate of 57.6% (small model) and
> 55.7% (medium model) over the 4 pages whose
> ground truth is complete, so the result of a recognition is a **starting
> point that has to be read by a person**, and the program says so after
> every recognition.  The numbers and what they mean are in
> `docs/OCR_ACCURACY.md`; the table below says what is real and what is
> not.

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
| OCR engine slot | **Works** | The engine is found by itself: the worker of the recognition is in the folder `ocr-worker` of the program |
| Handwriting recognition with a real model | **Works, needs the model** | kraken + PP-OCRv6 (Apache-2.0); the model is installed by the user and checked against two digests; the result has to be read line by line |
| Accuracy on the handwriting of today | **Not verified** | The corpus of the modern school handwriting is empty: the tools that build it and that measure the engines on it are ready, and the pages with a verified transcript have to be added by the school; see `docs/MODERN_SCHOOL_BENCHMARK.md` |
| Accuracy on the handwriting of old times (a diagnostic) | **Works** | 57.6% character error rate with the small model and 55.7% with the medium model, on the 4 pages of early modern cursive whose ground truth is complete - the numbers are in `docs/OCR_ACCURACY.md` |
| Comparing several engines on the same pages | **Works** | Every engine is measured on the same pages, and the numbers of each of them are written into `docs/OCR_ACCURACY.md`; choosing the default engine by the measurement is the plan and is not done by the program yet - the user chooses the engine in the settings screen, and a choice of the user is never overridden |
| Spelling proposals | **Works, needs a word list** | The word list of the user; the program ships no dictionary (the Hebrew Hunspell dictionary is AGPL) |
| Grammar proposals | **Works, a few rules** | Punctuation and spacing |
| `לשון הספר` proposals | **Not implemented** | The module exists, is switched off, and says so; see `docs/SUGGESTIONS.md` |
| Accepting and refusing proposals | **Works** | Every proposal is shown first and is accepted or refused on its own; every accepted change is logged and can be undone |
| Working on many proposals at once | **Works** | Accept or refuse all of them, or only the ones that were checked; change one word in all its places; keep a word in the word list of the user; take the last group of changes back as one action; go back to the text that the recognition gave.  Nothing is applied without the press of the user - there is no button that applies the corrections it judges to be safe |
| Plugins (engines and word lists) | **Works** | The engines and the modules of proposals are plugins; they are installed, removed, switched on and off, and chosen in `Settings > Plugins and engines`; see `docs/PLUGINS.md` |
| Text search inside the document | **Not implemented** | Planned |
| Undoing a correction of the style guide | **Not implemented** | The style module has no rules yet |
| Reading a page of a PDF at the resolution of the scan | **Works** | The pages of a PDF are given to the engine at 300 dots per inch |
| Installing and removing an engine or a word list | **Works** | They are plugins: they are installed, removed, switched on and off, and chosen in the settings screen; see `docs/PLUGINS.md` |

### What is not there yet

* **A dictionary of Hebrew spelling.**  The program does not ship one:
  the Hebrew Hunspell dictionary of LibreOffice is under the AGPL, and
  it may not be given away inside this program.  The spelling module
  works with a word list that the user brings.
* **A grammar engine.**  The grammar module has a few punctuation and
  spacing rules.  It is not a grammar checker.
* **לשון הספר.**  The module is a frame, it is switched off, and it
  proposes nothing.  See `docs/SUGGESTIONS.md`.
* **Automatic correction.**  Nothing in the program changes the text of
  a document by itself.  Every change is a proposal that is shown first
  and that the user accepts or refuses.

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
4. builds the worker of the recognition, `dist/ocr-worker/`, so that the
   program can read handwriting without anything else,
5. puts the program, the worker, the licence texts and a readme for the
   user into one archive (`release/HebrewNotesWorkbench-<version>-win64.zip`), and
6. uploads the folder and the archive as the workflow artifacts
   `HebrewNotesWorkbench-Windows` and `HebrewNotesWorkbench-release`.

A user without Python downloads the archive, unpacks the folder, and
starts `HebrewNotesWorkbench.exe`.  The application is a folder and not a
single file on purpose: the Qt libraries stay separate files, so that they
can be replaced, as the LGPL requires.

## Building the executable by hand

```bash
pip install -r requirements.txt pyinstaller==6.16.0
pyinstaller --noconfirm --clean --onedir --windowed --add-data "samples;samples" --name HebrewNotesWorkbench app.py

# the worker of the recognition, with the engine that it needs
pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.14.0" "torchvision==0.29.0"
pip install --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple "kraken==7.1.1" "pillow==11.3.0"
pyinstaller --noconfirm --clean --onedir --console --collect-all kraken --collect-all torchvision --name ocr-worker ocr_worker/main.py

python tools/build_release.py --app dist/HebrewNotesWorkbench --worker dist/ocr-worker --download-licences
```

The last command writes the archive for the user and prints the
SHA-256 of the archive.  It refuses to make the archive when a licence
text is missing.

## Repository layout

```
app.py                        launcher (--selftest, --version)
hebrew_workbench/
    engine/                   replaceable OCR adapters (base contract + registry)
    plugins/                  the plugin system: manifests, installer, registry
    suggestions/              the spelling, grammar and style modules (proposals only)
    preview/                  offline rendering of PDF pages and images
    ui/                       the Qt main window, the preview pane, the proposals pane,
                              the settings screen of the plugins
    exporting.py              TXT, DOCX and printing helpers
    project.py                workspace model: documents + their transcriptions
    resources.py              finding the files that ship with the application
    selftest.py               staged checks used by the packaging job
samples/                      synthetic test pages (no real documents)
tests/                        unit tests (standard library unittest)
tools/make_samples.py         regenerates the sample pages
docs/                         build plan, licenses, accuracy reports
benchmark/modern_school/       the corpus of the handwriting of today
```

## Documents

- `docs/AGENT_BUILD_PLAN.md` - the staged implementation plan and its rules.
- `docs/THIRD_PARTY.md` - every bundled component with its license, and the
  obligations that are still open.
- `docs/OCR_ACCURACY.md` - measured accuracy of the handwriting engine,
  on the material of the program and on the diagnostic corpus
- `docs/MODERN_SCHOOL_BENCHMARK.md` - the benchmark of the modern school
  handwriting: the rules of the corpus, the verification of the
  transcripts, and how the engines are compared
  (filled in when the engine lands).
- `docs/SUGGESTIONS.md` - the modules that propose corrections, and how a
  proposal is accepted, refused and undone.
- `docs/PLUGINS.md` - how to add another engine or another word list, and
  what the program does with a plugin that does not work.
