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

## Downloaded on request, not bundled

| Component | Version | License | Where it is used |
| --- | --- | --- | --- |
| kraken PP-OCRv6 model | see `docs/OCR_ACCURACY.md` | Apache-2.0 | Recognition weights, downloaded on request with a checksum check |
| Mishkefet-v1 model | 115.3 MB (120,864,761 bytes) | **CC-BY-NC-SA-4.0 — not a commercial licence** | Recognition weights of the second engine, downloaded on request from the place where the author published them, and checked against the SHA-256 `0dfb82e4…f6fd850b88` |

The weights of *Mishkefet-v1* are **not** bundled with the program and are
not redistributed by it: the user downloads them, on request, from the
place where the author published them.  The licence is not a commercial
one, so the model may be used for non-commercial purposes only, and a
modified file keeps the same licence.  A user who needs a commercial
licence has to ask the author of the model.  The program shows the licence
of every model before it is fetched, and the file is checked against the
digest that this project pinned.

## One-click offline EXE

An additional Windows release asset is a standard PyInstaller single-file
launcher with an embedded ZIP. The ZIP contains the same replaceable Windows program files,
the same license notices, the OCR worker and a **verified** copy of the
**Kraken PP-OCRv6 small** model (Apache-2.0). The model's source, SHA-256
and license are listed in `models/MODEL-SOURCE.txt`; the full Apache-2.0
license and notices are included in the extracted `LICENCES` folder.
The original ZIP release continues to download its model on user request.

On first launch, the one-click EXE automatically unpacks to
`%LOCALAPPDATA%\\HebrewNotesWorkbench\\one-click\\<bundle-id>\\`.
This is an **automatic unpack**, not a privileged installation.
The Qt DLLs are present there as separate, replaceable files in accordance
with the LGPL obligations. The launcher does not prevent DLL replacement,
and it does not redistribute Mishkefet weights. Users who need to replace
the Qt DLLs may open the cache folder directly.

## Test material

| Material | License | Where it is used |
| --- | --- | --- |
| Pinkas corpus (handwritten Hebrew) | CC-BY-4.0 | Accuracy measurement of the handwriting engine, see `docs/OCR_ACCURACY.md` |
| ivrit.ai Hebrew handwriting benchmark | ivrit.ai licence (gated) | The public benchmark of Hebrew handwriting; the model of the second engine was measured on it by its author, and the program does not download it |

Sample pages that are distributed with the application must carry the
attribution of their original authors in `docs/SAMPLES.md`.
