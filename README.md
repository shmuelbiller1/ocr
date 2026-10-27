# Local Hebrew-Script Handwriting Workbench

A Windows-first, offline desktop application for turning scanned handwritten Hebrew-script notes into editable, printable documents.

> Status: early foundation. No pretrained recognition models or commercial third-party binaries are bundled yet. The application must never claim to have transcribed a page unless a configured OCR engine actually did so.

## Design principles

- **Model independent:** OCR, spelling, grammar, and editorial-style processing are separate replaceable adapters.
- **Exact first:** Preserve the source image and unedited transcription; all suggested edits must be individually reviewable.
- **Offline by default:** No telemetry, cloud requests, or automatic model downloads.
- **User-controlled:** Spelling, grammar, and `לשון הספר` modes are opt-in and cannot silently rewrite original text.
- **Rights checked before bundling:** Each engine, model weight file, language dictionary, and installer needs independent licensing verification.
- **Slow and verifiable:** Small pull requests, unit tests, and actual Windows packaging tests before a school pilot.

## Roadmap

1. Minimal runnable Windows UI, local file import, page preview, editable right-to-left text, export, modular adapters, CI.
2. One genuinely working offline handwriting OCR adapter with a documented license and measured accuracy.
3. Word-level spelling suggestions using a licensed Hebrew-script dictionary and explicit accept/reject.
4. Optional local grammar and scholarly-style suggestions behind review controls.
5. Portable Windows packaging with verified bundled engines and school pilot.

See the proposed first feature branch / PR for the initial implementation.