# Implementation plan for an AI coding agent

Goal: Offline, Windows-first Hebrew-script handwriting -> editable document ->
reviewed corrections -> print. Keep all engine components replaceable.

## The material the program is made for

**Contemporary handwritten Hebrew-script school notes**: the notes that
students write in class, with a pen, in a notebook or on a sheet of
paper.  The program reads the Hebrew letters of those notes, whatever
the words are - Hebrew, Yiddish, Aramaic, an abbreviation or the term
of the subject - and it keeps the spelling, the abbreviations and the
order of the lines of the writer.

The rules that follow from this:

* The pages of old handwriting are a **diagnostic** of the engine, not
  the measure of the success of the program.  They are measured on
  every build, and they do not decide which engine is the better one.
* The accuracy on the material of the program is measured on a corpus
  of **modern school handwriting** whose transcripts were checked by
  somebody who is not the one who wrote them down.  While that corpus
  is empty, the accuracy on the material of the program is **not
  verified**, and every document of this repository says so.
* The measurement is of the **raw recognition**.  No dictionary, no
  language model and no proposal of the spelling, of the grammar or of
  the scholarly style is ever part of a number, because a number that
  was made better by a correction is not the number of the mistakes of
  the engine.
* The engines are compared with the measurement - the rate of the
  errors **and** the time a teacher needs to correct the text - and not
  with the order in which they are listed.  **This is the plan and it is
  not what the program does yet:** today the program restores the engine
  that the user chose, and when there is no such choice it takes the
  first engine that it finds.  The user can choose another engine at
  any time, and a choice of the user is never overridden.

## Rules
- Work on a feature branch with small pull requests. Do not replace code without reading it.
- Preserve original page bytes and user's transcription unchanged.
- Never present sample data or dummy output as actual OCR.
- Never auto-apply spelling, grammar, or scholarly-style changes. Maintain accepted/rejected proposals separately.
- No unapproved network calls, telemetry, model auto-downloads or redistribution of third-party weights. Approved licensed bundles are explicitly labelled below and in `docs/THIRD_PARTY.md`.
- Review actual license terms for CODE, WEIGHTS, DICTIONARIES, and DATA independently before inclusion.
- Program must install/run under a standard Windows account, without Python or WSL preinstalled.
- Every release must be compiled and smoke-tested on Windows CI, not just built in Linux.
- Keep user data out of repository and logs.

## Decisions taken so far

| Decision | Reason |
| --- | --- |
| The user interface is built with **PySide6 (Qt 6)** instead of Tkinter | Tk has no bidirectional text support and no letter shaping, so Hebrew is rendered in the wrong order and unjoined. Qt renders Hebrew correctly and also provides a real printing stack (`QtPrintSupport`). The Tk prototype from the first draft is therefore replaced. |
| The OCR adapter contract stays tiny and fails closed | A user must never see invented text where a transcription is expected. |
| Every engine, model file and dictionary is described in a manifest with a license and a checksum | Makes "did we check the rights?" a testable question instead of a habit. |
| The packaged executable is verified by *starting it* | Producing a `.exe` file is not evidence that it runs. The build job runs `app.exe --selftest`, which creates the real main window. |

## Where the work stands

| Part | State | Where |
| --- | --- | --- |
| Windows executable that starts | **Works** | `.github/workflows/windows.yml` builds it and starts it; the self-test creates the real window |
| Preview of PDF and image pages | **Works** | `hebrew_workbench/preview/` |
| Project file, export, print | **Works** | `hebrew_workbench/project.py`, `hebrew_workbench/exporting.py` |
| OCR engine contract, fail-closed default | **Works** | `hebrew_workbench/engine/` |
| One pretrained Hebrew engine (kraken + PP-OCRv6, Apache-2.0) | **Works; assets depend on edition** | small is bundled in Lite, small/medium in All Models; ZIP installation is explicit and integrity checked; accuracy is in `docs/OCR_ACCURACY.md` |
| A second pretrained engine for modern Hebrew cursive (Mishkefet-v1) | **Works; noncommercial assets** | MIT code ships with the app. CC-BY-NC-SA-4.0 weights are bundled only in All Models — Noncommercial; Lite/ZIP users opt in to installation. Pinned SHA-256 checks apply; search is in `docs/ENGINES.md` |
| Spelling proposals | **Works, needs a word list** | `hebrew_workbench/suggestions/spelling.py`; the program ships no dictionary (the Hebrew Hunspell dictionary is AGPL) |
| Working on the proposals of a page together | **Works** | accept or refuse all of them, or only the ones that were checked; change one word in all its places; keep a word in the word list of the user; take the last group of changes back as one action; go back to the text that the recognition gave |
| Grammar proposals | **Works, a few rules** | `hebrew_workbench/suggestions/grammar.py` |
| לשון הספר proposals | **Not implemented** | the module is a frame, it is switched off, and it says so |
| Plugins: install, remove, switch on and off, choose | **Works** | `hebrew_workbench/plugins/`, `hebrew_workbench/ui/settings_dialog.py`, `docs/PLUGINS.md` |
| Text search inside the document | **Not implemented** | Planned |
| Real school pages | **Not verified** | the corpus of the modern school handwriting is empty; the tools that build it and that measure the engines on it are ready (`tools/build_benchmark.py`, `tools/benchmark_ocr.py`); the pages with a verified transcript have to be added by the school - see `benchmark/modern_school/README.md` and `docs/MODERN_SCHOOL_BENCHMARK.md` |
| The same pages are measured every time | **Works** | the manifest of the corpus is in the repository, and the build checks the images against it before it measures anything: a page that was changed, added or removed stops the measurement |
| Comparing several engines on the same pages | **Works** | `tools/benchmark_ocr.py --engines ...` measures every engine on the same pages and writes the rate of each of them |
| Diagnostic measurement on the old handwriting | **Works** | the Pinkas pages are measured on every build; the numbers are in `docs/OCR_ACCURACY.md` |
| A release that a user can download | **Works** | a tag that starts with `v` makes the build publish the archive that was built and checked, with its digest and with the notes of the release |
| The release of a tag that is already there | **Works** | GitHub may make a release the moment the tag is pushed; the build writes the archive, the digest and the notes into the release that is already there, and does not stop. A file that was published before is taken away only when the new one is there, so that a failure in between leaves the user with the file he had |

## First milestone (historical scaffold; superseded by the status table)
- Runnable Windows desktop interface with batch file selection, RTL editor, TXT export and explicit adapter status.
- A proper OCR adapter interface with a fail-closed default.
- CI builds a Windows .exe with PyInstaller **and starts it**.
- Absent at that historical milestone: PDF/image preview, real OCR, real spell checker, DOCX/PDF export, printer integration. See the current status table and `docs/FINAL_READINESS.md`, not this historical list, for remaining work.
- Do not mark these absent features as complete.

## Next milestones, sequentially
1. Make document preview work offline: PDF page rasterization plus image viewport with zoom, rotation, next/previous pages. Reject malformed, massive, or encrypted documents gracefully.
2. Add project save/load so the user can keep the work, plus TXT/DOCX export and a print path with a printer choice.
3. Add a selectable OCR-engine registry: manifest id, version, supported script, executable location, license, CPU/GPU, availability, health check, typed per-page results, line bounding boxes, confidence if meaningful, cancellation and timeout.
4. Choose ONE verified, genuinely tested, appropriately licensed pretrained model. Set up reproducible local packaging and benchmark on school handwriting; never claim unsupported languages work. **Done for kraken + PP-OCRv6, and a second engine was added for the modern cursive (Mishkefet-v1) after a search of the open models - `docs/ENGINES.md`; the benchmark of the modern school handwriting is built and waiting for the pages of the school, so the accuracy of the program on the material it is made for is still unverified.**
5. Add simple spelling adapter with a licensed Hebrew-script dictionary and user custom vocabulary. Show 0-3 ranked choices and 'keep original'; log exact source and accepted replacement. Preserve specialized abbreviations.
6. Add optional local language model for grammar and לשון הספר changes, with passage-by-passage approval. It cannot overwrite exact transcription.
7. Add right-to-left DOCX and PDF output with correct punctuation, Hebrew/English mixed text, headings, page numbers, quote marks and reasonable printable margins. Add print preview and Windows printer choice.
8. Ship verified portable ZIP and installer with engine dependencies, licenses, checksums, offline startup checks, versioned migration and clear hardware guidance.
9. Test real school examples with approved sample material. Report line recall, word/character error rates, corrections introduced by the checker, peak RAM, CPU time per page, size of installer, and human minutes per print-ready page. **The tools of the measurement are ready; the pages and the minutes of the correction are the work of the school.**

## Acceptance gates
- Import one or multiple files, cancel a job, reopen a saved project, edit RTL text, export and print.
- No application hang/crash from OCR adapter failure or missing weight file; surface an actionable error.
- Switching engines never loses prior transcription or edits.
- No fabricated page transcription, fabricated confidence, silent changes, accidental uploads, or edits to original images.
- Windows CI produces an executable **and starts it** and reports an automated build result.
