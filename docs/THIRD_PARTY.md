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
| PyInstaller | 6.16.0 | GPL-2.0-or-later **with a bundling exception** | PyPI (`pyinstaller`) | Build-time only; the exception permits shipping the result under any license |

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
   PySide6/Qt, shiboken6, Pillow, PDFium and python-docx in a `LICENCES/`
   folder.  `tools/build_release.py` does this: it copies the licence
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

## Planned, not bundled yet

| Component | Version | License | Where it will be used |
| --- | --- | --- | --- |
| Pillow | 11.3.0 | MIT-CMU | Image handling for the preview |
| pypdfium2 | 4.30.0 | BSD-3-Clause / Apache-2.0 | Rasterising PDF pages (PDFium, Apache-2.0/BSD-3) |
| kraken | 7.1.1 | Apache-2.0 | Handwritten text recognition engine (optional adapter) |
| kraken PP-OCRv6 model | see `docs/OCR_ACCURACY.md` | Apache-2.0 | Recognition weights, downloaded on request with a checksum check |

## Test material

| Material | License | Where it is used |
| --- | --- | --- |
| Pinkas corpus (handwritten Hebrew) | CC-BY-4.0 | Accuracy measurement of the handwriting engine, see `docs/OCR_ACCURACY.md` |

Sample pages that are distributed with the application must carry the
attribution of their original authors in `docs/SAMPLES.md`.
