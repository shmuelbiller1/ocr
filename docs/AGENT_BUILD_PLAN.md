# Implementation plan for an AI coding agent

Goal: Offline, Windows-first Hebrew-script handwriting -> editable document -> reviewed corrections -> print. Keep all engine components replaceable.

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

## First milestone (current scaffold)
- Runnable Windows desktop interface with batch file selection, RTL editor, TXT export and explicit adapter status.
- A proper OCR adapter interface with a fail-closed default.
- CI builds a Windows .exe with PyInstaller.
- Known absent: PDF/image preview, real OCR, real spell checker, DOCX/PDF export, printer integration.
- Do not mark these absent features as complete.

## Next milestones, sequentially
1. Make document preview work offline: PDF page rasterization plus image viewport with zoom, rotation, next/previous pages. Reject malformed, massive, or encrypted documents gracefully.
2. Add a selectable OCR-engine registry: manifest id, version, supported script, executable location, license, CPU/GPU, availability, health check, typed per-page results, line bounding boxes, confidence if meaningful, cancellation and timeout.
3. Choose ONE verified, genuinely tested, appropriately licensed pretrained model. Set up reproducible local packaging and benchmark on school handwriting; never claim unsupported languages work.
4. Add simple spelling adapter with Hunspell dictionaries and user custom vocabulary. Show 0–3 ranked choices and 'keep original'; log exact source and accepted replacement. Preserve specialized abbreviations.
5. Add optional local language model for grammar and לשון הספר changes, with passage-by-passage approval. It cannot overwrite exact transcription.
6. Add right-to-left DOCX and PDF output with correct punctuation, Hebrew/English mixed text, headings, page numbers, quote marks and reasonable printable margins. Add print preview and Windows printer choice.
7. Ship verified portable ZIP and installer with engine dependencies, licenses, checksums, offline startup checks, versioned migration and clear hardware guidance.
8. Test real school examples with approved sample material. Report line recall, word/character error rates, corrections introduced by the checker, peak RAM, CPU time per page, size of installer, and human minutes per print-ready page.

## Acceptance gates
- Import one or multiple files, cancel a job, reopen a saved project, edit RTL text, export and print.
- No application hang/crash from OCR adapter failure or missing weight file; surface an actionable error.
- Switching engines never loses prior transcription or edits.
- No fabricated page transcription, fabricated confidence, silent changes, accidental uploads, or edits to original images.
- Windows CI produces an executable and reports an automated build result.
