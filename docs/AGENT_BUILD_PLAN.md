# Implementation plan for an AI coding agent

Goal: Offline, Windows-first Hebrew-script handwriting -> editable document ->
reviewed corrections -> print. Keep all engine components replaceable.

## Rules
- Work on a feature branch with small pull requests. Do not replace code without reading it.
- Preserve original page bytes and user's transcription unchanged.
- Never present sample data or dummy output as actual OCR.
- Never auto-apply spelling, grammar, or scholarly-style changes. Maintain accepted/rejected proposals separately.
- No unapproved network calls, telemetry, model auto-downloads, or shipping third-party copyrighted weights.
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
| One pretrained Hebrew engine (kraken + PP-OCRv6, Apache-2.0) | **Works, needs the model** | the model is downloaded by the user and checked against two digests; the accuracy is in `docs/OCR_ACCURACY.md` |
| Spelling proposals | **Works, needs a word list** | `hebrew_workbench/suggestions/spelling.py`; the program ships no dictionary (the Hebrew Hunspell dictionary is AGPL) |
| Grammar proposals | **Works, a few rules** | `hebrew_workbench/suggestions/grammar.py` |
| לשון הספר proposals | **Not implemented** | the module is a frame, it is switched off, and it says so |
| Plugins: install, remove, switch on and off, choose | **Works** | `hebrew_workbench/plugins/`, `hebrew_workbench/ui/settings_dialog.py`, `docs/PLUGINS.md` |
| Text search inside the document | **Not implemented** | Planned |
| Real school pages | **Not tested here** | the accuracy job measures the published Pinkas pages; real school material needs the user's own pages |

## First milestone (current scaffold)
- Runnable Windows desktop interface with batch file selection, RTL editor, TXT export and explicit adapter status.
- A proper OCR adapter interface with a fail-closed default.
- CI builds a Windows .exe with PyInstaller **and starts it**.
- Known absent: PDF/image preview, real OCR, real spell checker, DOCX/PDF export, printer integration.
- Do not mark these absent features as complete.

## Next milestones, sequentially
1. Make document preview work offline: PDF page rasterization plus image viewport with zoom, rotation, next/previous pages. Reject malformed, massive, or encrypted documents gracefully.
2. Add project save/load so the user can keep the work, plus TXT/DOCX export and a print path with a printer choice.
3. Add a selectable OCR-engine registry: manifest id, version, supported script, executable location, license, CPU/GPU, availability, health check, typed per-page results, line bounding boxes, confidence if meaningful, cancellation and timeout.
4. Choose ONE verified, genuinely tested, appropriately licensed pretrained model. Set up reproducible local packaging and benchmark on school handwriting; never claim unsupported languages work.
5. Add simple spelling adapter with a licensed Hebrew-script dictionary and user custom vocabulary. Show 0-3 ranked choices and 'keep original'; log exact source and accepted replacement. Preserve specialized abbreviations.
6. Add optional local language model for grammar and לשון הספר changes, with passage-by-passage approval. It cannot overwrite exact transcription.
7. Add right-to-left DOCX and PDF output with correct punctuation, Hebrew/English mixed text, headings, page numbers, quote marks and reasonable printable margins. Add print preview and Windows printer choice.
8. Ship verified portable ZIP and installer with engine dependencies, licenses, checksums, offline startup checks, versioned migration and clear hardware guidance.
9. Test real school examples with approved sample material. Report line recall, word/character error rates, corrections introduced by the checker, peak RAM, CPU time per page, size of installer, and human minutes per print-ready page.

## Acceptance gates
- Import one or multiple files, cancel a job, reopen a saved project, edit RTL text, export and print.
- No application hang/crash from OCR adapter failure or missing weight file; surface an actionable error.
- Switching engines never loses prior transcription or edits.
- No fabricated page transcription, fabricated confidence, silent changes, accidental uploads, or edits to original images.
- Windows CI produces an executable **and starts it** and reports an automated build result.
