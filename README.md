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
> PP-OCRv6 (both Apache-2.0).  A second engine, *Mishkefet-v1*, was added
> for the handwriting the program is really made for - modern Hebrew
> cursive - and it is the best open model that was found for that
> material; its weights carry a non-commercial licence. They are bundled
> only in **All Models — Noncommercial**; Lite/ZIP users can install them
> separately after licence confirmation.
>
> The measured accuracy on early modern
> Hebrew cursive is a character error rate of 57.6% (small model) and
> 55.7% (medium model) over the 4 pages whose
> ground truth is complete, so the result of a recognition is a **starting
> point that has to be read by a person**, and the program says so after
> every recognition.  The second engine reads those old pages with 73.0%
> - the segmenter that came with it cuts the lines of the old cursive in
> two, and it was written for the modern cursive and not for these pages;
> the whole explanation is in `docs/OCR_ACCURACY.md`.  The numbers and
> what they mean are in
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
| Handwriting recognition with a real model | **Works; assets depend on edition** | kraken + PP-OCRv6 (Apache-2.0): both EXEs include small; All Models also includes medium. ZIP users install weights explicitly. Integrity is checked; read every result line by line |
| A second engine, written for modern Hebrew cursive | **Works; noncommercial assets** | Mishkefet-v1: MIT code ships with the app; CC-BY-NC-SA-4.0 weights are included only in All Models — Noncommercial. Lite/ZIP users can install them after licence confirmation. Pinned integrity checks apply; see `docs/ENGINES.md` for model-selection research |
| Accuracy on the handwriting of today | **Not verified** | The corpus of the modern school handwriting is empty: the tools that build it and that measure the engines on it are ready, and the pages with a verified transcript have to be added by the school; see `docs/MODERN_SCHOOL_BENCHMARK.md` |
| Accuracy on the handwriting of old times (a diagnostic) | **Works** | 57.6% character error rate with the small model and 55.7% with the medium model, on the 4 pages of early modern cursive whose ground truth is complete - the build reads 5 pages of the dataset, and the numbers are in `docs/OCR_ACCURACY.md` |
| Comparing several engines on the same pages | **Works** | Every engine is measured on the same pages, and the numbers of each of them are written into `docs/OCR_ACCURACY.md`; choosing the default engine by the measurement is the plan and is not done by the program yet - the user chooses the engine in the settings screen, and a choice of the user is never overridden |
| A warning about the numbers of the second engine | **Written down** | *Mishkefet-v1* was trained on part of the Pinkas corpus, so its rates on the pages of that corpus are optimistic and are **not** a clean comparison with the first engine; the clean comparison is the school corpus, which is still empty - see `docs/OCR_ACCURACY.md` and `docs/ENGINES.md` |
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
  the core spelling module uses a user word list. An optional native
  Hunspell/Hspell plugin is now available to build separately; it is
  experimental, AGPL-licensed and uses pre-2017 spelling rules. AGPL
  redistribution requires compliance, not a blanket prohibition. See
  [the plugin guide](optional_plugins/hunspell_hebrew/README.md).
* **A grammar engine.**  The grammar module has a few punctuation and
  spacing rules.  It is not a grammar checker.
* **לשון הספר.**  The module is a frame, it is switched off, and it
  proposes nothing.  See `docs/SUGGESTIONS.md`.
* **Automatic correction.**  Nothing in the program changes the text of
  a document by itself.  Every change is a proposal that is shown first
  and that the user accepts or refuses.

## One-click offline Windows executables

For Windows, **download a single EXE and double-click it**. No installer,
administrator privileges, Python installation, manual ZIP extraction, or model
downloads are required. Both editions contain the app, OCR worker, dependencies
and their licenses:

| Edition | Download asset | Models included | Use |
| --- | --- | --- | --- |
| **Lite** | `HebrewNotesWorkbench-<version>-one-click.exe` | Kraken PP-OCRv6 small (Apache-2.0) | Permissive-license lightweight edition |
| **All Models** | `HebrewNotesWorkbench-<version>-all-models-noncommercial-one-click.exe` | Kraken small and medium, Mishkefet-v1 and its character/word language models | **Noncommercial only**; all OCR modes work offline, including assisted decoding |

The **All Models** edition includes five verified model files in one download.
It can compare the three OCR models and use Mishkefet's optional beam and
assisted decoding modes without contacting the model hosts. **The Mishkefet
weights and both language-model files are licensed CC-BY-NC-SA-4.0.** Their
original copyright, source, attribution and license link are included. Do not
use this edition commercially without obtaining separate permission.

A standard PyInstaller one-file launcher automatically unpacks its supporting
files into a versioned per-user folder at
`%LOCALAPPDATA%\\HebrewNotesWorkbench\\one-click\\`. Qt's DLLs remain
separately replaceable there for LGPL compliance. The launcher verifies each
model before use. Its internal archive is temporarily extracted by PyInstaller
on each launch, so startup may take time even after the application cache has
been created. The full edition also uses more disk space.

No online activation or automatic updater is required. Windows can display a
security warning for an unsigned executable. The existing portable ZIP is
still available for users who prefer a traditional extracted folder.

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

### Experimental assisted Mishkefet decoding

Settings offers Raw (default), Beam + three scales, and Assisted (optional
character/word language models). Both readings are preserved side by side;
the alternative is never auto-applied. Additional files are non-commercial and digest-verified: bundled in All Models,
explicitly installed in Lite/ZIP. See [the guide](docs/ASSISTED_DECODING.md).
Accuracy improvement on your pages remains unverified.


### Is the whole project final?

**Not yet.** All Models includes all supported OCR models, not every planned
correction feature. Spelling still needs a user word list, grammar is limited
to punctuation/spacing, and לשון הספר is an unavailable placeholder. See the
[full inventory and completion gates](docs/FINAL_READINESS.md). The audit also
found a Qt 6 printing/PDF defect in v0.4.0; the source patch and stronger
packaged self-tests must ship in a subsequent release, not be assumed present
in the existing downloads.


### Optional offline Hebrew spelling plugin

`hunspell-hebrew` is a separately installable/removable native spelling plugin.
It is **not included in the existing releases**. The Windows CI artifact
`Hebrew-spelling-plugin-Windows` contains its ZIP, source/license materials and
verification report. It uses pinned Hunspell 1.7.6 plus Hspell 1.4 data; Hspell
1.4 predates the June 2017 spelling changes, so it is an experimental candidate,
not a proven best modern-school checker. Every change remains accept/reject.
Personal vocabulary is stored outside the plugin; raw OCR is untouched.
See [installation, licensing and limitations](optional_plugins/hunspell_hebrew/README.md).
