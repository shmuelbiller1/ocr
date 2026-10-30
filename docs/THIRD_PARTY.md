# Third-party components and their licenses

Every component that ends up inside the shipped executable is listed here
with the license that was actually checked, the source it came from, and
what still has to be done before a public release.

The rule of this project: *no third-party code, model, dictionary or
binary is bundled before its license and its integrity were verified.*
Downloadable artefacts (models, dictionaries) additionally carry a
SHA-256 checksum that is verified before the file is used.

## Bundled in the Windows executable

| Component | Version | License | Source | Notes |
| --- | --- | --- | --- | --- |
| CPython | 3.12 | PSF License 2.0 | python.org | Runtime of the packaged executable |
| PySide6-Essentials | 6.9.1 | LGPL-3.0-only | PyPI (`PySide6-Essentials`) | Qt 6 for Python: user interface, printing |
| shiboken6 | 6.9.1 | LGPL-3.0-only | PyPI (`shiboken6`) | Binding generator, pulled in by PySide6 |
| Pillow | 11.3.0 | MIT-CMU | PyPI (`pillow`) | Image handling for the preview |
| pypdfium2 | 4.30.0 | BSD-3-Clause / Apache-2.0 | PyPI (`pypdfium2`) | Rasterising PDF pages (PDFium, Apache-2.0/BSD-3) |
| python-docx | 1.2.0 | MIT | PyPI (`python-docx`) | Writing the DOCX file |
| lxml | 6.0.2 | BSD-3-Clause | PyPI (`lxml`) | Reading the corpus and the manifests |
| PyInstaller | 6.16.0 | GPL-2.0-or-later **with a bundling exception** | PyPI (`pyinstaller`) | Build-time only; the exception permits shipping the result under any license |

## Bundled in the worker of the recognition

The worker (`ocr-worker`) goes with the program in the archive of the
user, so that the program can read handwriting without anything else.

| Component | Version | License | Source | Notes |
| --- | --- | --- | --- | --- |
| kraken | 7.1.1 | Apache-2.0 | PyPI (`kraken`) | The engine that reads the handwriting |
| PyTorch | 2.14.0 | BSD-3-Clause | PyPI (`torch`) | The library that kraken runs on |
| torchvision | 0.29.0 | BSD-3-Clause | PyPI (`torchvision`) | The library that kraken asks for |
| opencv-python-headless | 4.12.0.88 | Apache-2.0 | PyPI (`opencv-python-headless`) | The page segmentation of the second engine (Mishkefet); the "headless" package needs no display |

The licence texts of these are inside their own packages, and
`tools/build_release.py` copies them into the folder `LICENCES` of the
archive.  The release is not made when one of them is missing.

### The code of the second engine

The engine *Mishkefet-v1* is written in Python by Itay Inbar and
published under the MIT licence.  The parts of that code that recognise a
page are shipped with the program, unchanged, under
`hebrew_workbench/engine/vendor/hebocr/`:

| Component | Version | License | Source | Notes |
| --- | --- | --- | --- | --- |
| heb-ocr (`hebocr`) | 0.1.0 | MIT, Copyright (c) 2026 Itay Inbar | github.com/itayinbarr/heb-ocr | The line recognition and the page segmentation of the second engine; the text of the licence is in `docs/licences/HEB-OCR-MIT.txt` |

The copied code was not changed at all.  The parts of the project that
build a training set, that fine-tune a model and that build a language
model were **not** copied: the program never trains anything, and the text
of a recognition is never changed by a language model.  The file of the
model is loaded with the code of its author, which is a `pickle`; the file
is safe to load because its SHA-256 is checked against the digest that
this project pinned before it is read, and a file that does not match is
deleted and is never used.

`PySide6-Essentials` is used instead of the full `PySide6` package on
purpose: the Essentials package contains only modules that are available
under LGPL (no Qt PDF, no Qt Charts, no Qt Data Visualization), which keeps
the licensing of the shipped executable unambiguous.

### Obligations that are still open

These have **not** been legally reviewed by a lawyer and are tracked as
open work:

1. The LGPL requires that the user can replace the Qt shared libraries.
   The build therefore produces a **folder** and not a single file, so
   that the DLLs of Qt stay separate files that can be replaced.  The
   release job must ship the Qt licence texts and a short note
   explaining that the DLLs are in the folder of the application, next
   to `HebrewNotesWorkbench.exe`.
2. The release package must include the licence texts of CPython,
   PySide6/Qt, shiboken6, Pillow, PDFium, python-docx, lxml, kraken,
   PyTorch and torchvision in a `LICENCES/` folder.  `tools/build_release.py` does this: it copies the licence
   texts that are inside the installed packages, copies the texts of
   the LGPL, of the GPL and of the PSF licence from `docs/licences/`,
   and writes a notice that says what every component is and where its
   licence is.  The texts of the LGPL, of the GPL and of the PSF
   licence are in the repository, so that the release does not depend
   on a network; a text that does not look like the licence it claims
   to be is not kept, and the build says so.  The texts that are not
   in the repository can still be fetched with `--download-licences`,
   and the build fails when one of them does not arrive.
3. The PyInstaller exception only covers the bundling of the executable;
   the licences of the bundled libraries keep applying.

## Standard ZIP: downloaded on request, not bundled

This section describes manual ZIP installation. The one-click editions and
which assets they bundle are described in the next section.

| Component | Version | License | Where it is used |
| --- | --- | --- | --- |
| kraken PP-OCRv6 model | see `docs/OCR_ACCURACY.md` | Apache-2.0 | Recognition weights, downloaded on request with a checksum check |
| Mishkefet-v1 model | 115.3 MB (120,864,761 bytes) | **CC-BY-NC-SA-4.0 — not a commercial licence** | Recognition weights of the second engine, downloaded on request from the place where the author published them, and checked against the SHA-256 `0dfb82e4…f6fd850b88` |

The standard ZIP does not bundle *Mishkefet-v1*: its user downloads the weights
on request from the author's repository. The separately labelled All Models —
Noncommercial edition redistributes the unmodified assets as described below.  The licence is not a commercial
one, so the model may be used for non-commercial purposes only, and a
modified file keeps the same licence.  A user who needs a commercial
licence has to ask the author of the model.  The program shows the licence
of every model before it is fetched, and the file is checked against the
digest that this project pinned.

## One-click offline EXE editions

Two separate standalone Windows executable assets are built from the same
tested application and OCR worker ZIP. The launcher automatically unpacks the
files into `%LOCALAPPDATA%\\HebrewNotesWorkbench\\one-click\\<bundle-id>\\`.
Qt libraries are present as separately replaceable files as required by LGPL.
No Windows installer is run.

- **Lite** contains the original unmodified Kraken PP-OCRv6 small weights,
  Apache-2.0. Its SHA-256 is pinned and verified before publishing and launch.
- **All Models — noncommercial** contains Kraken PP-OCRv6 small/medium
  (Apache-2.0), Mishkefet-v1 checkpoint and its character/word prior files
  (**CC-BY-NC-SA-4.0**). All five files are verified by pinned SHA-256 digests
  before publication and at startup. A source/size/hash manifest and
  attribution notices are included under `models/` and `LICENCES/`.
  The Mishkefet model and language data are unmodified and attributed to
  Itay Inbar; model source:
  <https://huggingface.co/itayinbar/Mishkefet-v1>.
  License: <https://creativecommons.org/licenses/by-nc-sa/4.0/>.
  **This edition is only for noncommercial distribution and use** under
  those conditions; commercial use requires separate authorization.

The standard ZIP edition keeps the original manual, opt-in model installation
process. This document's earlier "downloaded on request" section describes
that standard ZIP, not the two offline EXE variants.

A one-file Windows executable may cause a Windows publisher warning until the
application is digitally signed. PyInstaller temporarily unpacks its payload
on every launch; it then reuses the verified versioned application cache.

## Test material

| Material | License | Where it is used |
| --- | --- | --- |
| Pinkas corpus (handwritten Hebrew) | CC-BY-4.0 | Accuracy measurement of the handwriting engine, see `docs/OCR_ACCURACY.md` |
| ivrit.ai Hebrew handwriting benchmark | ivrit.ai licence (gated) | The public benchmark of Hebrew handwriting; the model of the second engine was measured on it by its author, and the program does not download it |

Sample pages that are distributed with the application must carry the
attribution of their original authors in `docs/SAMPLES.md`.


## Optional Hunspell/Hspell spelling distribution (not bundled in core)

- Hunspell 1.7.6, source commit `15faca15532b34db3106d50f162e5edc2503d6d6`:
  LGPL/GPL/MPL tri-license; complete source and license texts accompany the plugin.
- Hebrew .dic/.aff from LibreOffice, derived from Hspell 1.4: AGPLv3 notices
  retained unmodified. Hspell source/generators commit
  `f4c5f2e760e28bfb9df06e625dae84c98d655e8f` accompanies the dictionary.
- Exact Git blob IDs, sizes and SHA-256s are in
  `optional_plugins/hunspell_hebrew/upstream-pins.json`.
- The separate distribution is labelled AGPL-3.0-only, with a complete tracked
  workbench-source snapshot and build recipe. Project-authored files retain
  their MIT grants; no dictionary is relabelled MIT. This is not a legal
  certification or an assertion that subprocess isolation exempts integration
  from copyleft. No NC OCR model weights are in the plugin ZIP.
- Build dependencies: CMake 3.31.6 and a local C++ compiler; not app runtime
  dependencies. No externally supplied spelling executables are downloaded.

The core editions still contain no Hebrew dictionary. AGPL is **not a blanket
ban on redistribution**; compliance and the actual combination matter. Existing
release assets and model licensing are unchanged. Hspell 1.4's pre-2017 spelling
standard is an explicit quality limitation, not a modern Hebrew certification.

## Optional modern Hebrew spelling supplement

`modern-hebrew-spelling` adds the exact `data/words.txt` from
[hebrew-words-db](https://github.com/roni5604/hebrew-words-db) commit
`879f0f46f687015b97a02469dd745c824c0e8589`, SHA-256
`30a01c45da1381637da708d74af81c0f1b4ad225d9a3a85252683217fe107be3`,
2,670,751 bytes, to the Hspell/Hunspell plugin. Upstream states CC0-1.0 for
its AI-assisted data; its license text and source methodology are included
in the plugin. This declaration/provenance is not independently audited.
The list is not independently certified; using it as a whitelist may accept
misspellings. Hspell remains AGPL-3.0-only and Hunspell LGPL/GPL/MPL, with
all original notices and corresponding source supplied as before. The
supplement does not override those licenses. See the modern plugin guide.
