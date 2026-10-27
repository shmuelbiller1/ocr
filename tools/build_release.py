"""Put the built application into a folder that can be given to a user.

    python tools/build_release.py --app dist/HebrewNotesWorkbench

The result is a ZIP file with

* the application itself, exactly as it was built,
* a folder `LICENCES` with the licence texts of the components that are
  inside the application, and a notice that says what every component
  is and where its licence comes from,
* a file `README-להשימה.txt` that tells a user who does not know
  anything about programs what to do with the program.

The script prints the SHA-256 of the ZIP, so that the file that is
published can be checked by the person who downloads it.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from hebrew_workbench import __version__  # noqa: E402

#: The components that end up inside the application, and where the
#: text of their licence is found.
COMPONENTS = [
    ("CPython", "PSF License 2.0", "https://www.python.org/psf/license/"),
    ("PySide6-Essentials", "LGPL-3.0-only", "https://www.gnu.org/licenses/lgpl-3.0.html"),
    ("shiboken6", "LGPL-3.0-only", "https://www.gnu.org/licenses/lgpl-3.0.html"),
    ("Pillow", "MIT-CMU", "https://raw.githubusercontent.com/python-pillow/Pillow/main/LICENSE"),
    (
        "pypdfium2",
        "BSD-3-Clause",
        "https://github.com/pypdfium2-team/pypdfium2/blob/master/LICENSE.txt",
    ),
    ("python-docx", "MIT", "https://github.com/python-openxml/python-docx/blob/master/LICENSE"),
]

#: The licence texts that are not inside the packages, with the place
#: they can be read.  They are only text; nothing is run.
LICENCE_TEXTS = [
    (
        "LGPL-3.0.txt",
        "https://www.gnu.org/licenses/lgpl-3.0.txt",
        "GNU LESSER GENERAL PUBLIC LICENSE",
    ),
    (
        "GPL-3.0.txt",
        "https://www.gnu.org/licenses/gpl-3.0.txt",
        "GNU GENERAL PUBLIC LICENSE",
    ),
    (
        "PSF-LICENSE.txt",
        "https://www.python.org/psf/license/",
        "PYTHON SOFTWARE FOUNDATION LICENSE",
    ),
]

README = """מסמך למשתמש - Hebrew Notes Workbench
====================================

מה זה
-----
תוכנה למחשב (ללא חיבור לאינטרנט) להכנת מסמכים בכתב יד עברי: מייבאים סריקה,
מזהים את הכתב, עורכים את הטקסט, מציעים תיקוני איות וניסוח, ומדפיסים.

התוכנה מופיעה בשם HebrewNotesWorkbench.exe. היא עובדת במחשב עם Windows,
ואין צורך להתקין Python ואין צורך בחיבור לאינטרנט.

איך מתחילים
------------
1. פרקו את קובץ ה-ZIP לתיקייה אחת.
2. הפעילו את HebrewNotesWorkbench.exe.
3. בתפריט "כלים" אפשר לבקש להתקין את מנוע הזיהוי. ההתקנה מורידה קובץ
   של כ-13 MB (או כ-64 MB למנוע הגדול) ובודקת אותו מול הטבעה שפורסמה
   על יד מפרסם המודל ומול טבעת SHA-256 שנעוץ בתוכנה. אין התקנה אוטומטית
   ואין שום מידע שנשלח לשום מקום.
4. בתפריט "קובץ" אפשר להוסיף קבצים (תמונות PNG, JPEG, TIFF, או PDF).
5. הטקסט המזוהה מופיע באמצע. אפשר לערוך אותו, לשמור את הפרויקט
   (קובץ .hwproj), לייצא אותו ל-TXT או ל-DOCX, ולהדפיס אותו.
6. הצעות התיקון מופיעות בחלונית "הצעות תיקון" בצד. כל הצעה מתקבלת או
   נדחית בנפרד, ואפשר לבטל את כל השינויים.

קבצים
-----
* HebrewNotesWorkbench.exe - התוכנה.
* LICENCES - טקסטים של הרישיונות של הרכיבים שבתוכנה, ורשימה שלהם.
* samples - דפי דוגמה (דפים מלאכותיים, לא סריקות אמיתיות).

דרך לשמירה על התוכנה
--------------------
רישיון התוכנה עצמה: ראו את הקובץ LICENSE בתיקייה הזו. רכיבי Qt מגיעים
עם רישיון LGPL, ולכן אפשר להחליף את קובצי ה-DLL של Qt שבתיקייה
_INTERNAL בלי לשנות את שאר התוכנה.

English
-------
This is an offline Windows program for Hebrew handwriting: import a
scan, recognise the text, correct it, and print it.  Python is not
needed.  The recognition engine and its model are installed only when
the user asks for it, and the model file is checked against the digest
published by its authors.  Nothing is uploaded anywhere.  The licence
texts of every bundled component are in the folder LICENCES.
"""


def default_site_packages() -> Path:
    """The folder with the packages of the running Python."""
    import site

    folders: list[str] = []
    try:
        folders.extend(site.getsitepackages())
    except Exception:
        pass
    user_site = getattr(site, "getusersitepackages", None)
    if callable(user_site):
        try:
            folders.append(user_site())
        except Exception:
            pass
    for folder in folders:
        path = Path(folder)
        if path.is_dir() and list(path.glob("*.dist-info")):
            return path
    return Path(REPO_ROOT / ".venv" / "lib")


def licence_files(site_packages: Path) -> list[tuple[str, Path]]:
    """Every licence text that is inside the installed packages."""
    found: list[tuple[str, Path]] = []
    if not site_packages.is_dir():
        return found
    for info in sorted(site_packages.glob("*.dist-info")):
        for candidate in ("LICENSE", "LICENSE.txt", "COPYING", "NOTICE"):
            path = info / candidate
            if path.is_file():
                found.append((info.name, path))
        licences = info / "licenses"
        if licences.is_dir():
            for path in sorted(licences.rglob("*")):
                if path.is_file():
                    found.append((info.name, path))
    return found


def fetch_text(url: str) -> str:
    """Read a text file from the network."""
    import urllib.request

    request = urllib.request.Request(
        url, headers={"User-Agent": "HebrewNotesWorkbench/0.2"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def download_licence_texts(target: Path, fetch=fetch_text) -> list[str]:
    """Fetch the licence texts that are not inside the packages.

    Only text is fetched, and only from the address of the project
    itself.  A file that does not look like the licence it claims to be
    is not kept.  The names of the files that were not fetched are
    returned, so that they can be reported.
    """
    missing: list[str] = []
    for name, url, marker in LICENCE_TEXTS:
        path = target / name
        if path.is_file():
            continue
        try:
            text = fetch(url)
        except Exception:
            missing.append(name)
            continue
        if marker.lower() not in text.lower():
            missing.append(name)
            continue
        path.write_text(text, encoding="utf-8")
    return missing


def build_notice(site_packages: Path) -> str:
    """The list of the components, with the place their licence is in."""
    lines = [
        "Third-party components of Hebrew Notes Workbench",
        "================================================",
        "",
        "This program contains the components below.  The text of every",
        "licence is in this folder.  The components that are listed with",
        "a web address are licensed under that licence, and the text can",
        "be read there.",
        "",
    ]
    for name, licence, url in COMPONENTS:
        lines.append(f"* {name} - {licence} - {url}")
    lines += [
        "",
        "The application itself is distributed under the licence in the",
        "file LICENSE, next to this notice.",
        "",
        "The Qt libraries of PySide6 are under the LGPL, which allows the",
        "user to replace the DLL files of Qt.  They are in the folder",
        "_internal of the application and can be replaced there.",
        "",
    ]
    found = licence_files(site_packages)
    if found:
        lines += ["The licence texts that were copied into this folder:", ""]
        for package, path in found:
            lines.append(f"* {path.name} - from {package}")
        lines.append("")
    else:
        lines += [
            "The licence texts of the installed packages were not found on",
            "this machine.  They have to be copied into this folder",
            "before the program is given to anybody.",
            "",
        ]
    return "\n".join(lines)


def build_release(
    app: Path, output: Path, site_packages: Path, fetch_licences: bool = False
) -> Path:
    """Copy the application, add the licences and the readme, and zip it."""
    if not app.is_dir():
        raise SystemExit(f"the application was not found: {app}")

    staging = output.parent / f"{output.stem}-content"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    app_name = app.name
    shutil.copytree(app, staging / app_name)

    # The licences and the readme go into the folder of the program, so
    # that the user has to unpack only one folder.
    licences = staging / app_name / "LICENCES"
    licences.mkdir()
    third_party = REPO_ROOT / "docs" / "THIRD_PARTY.md"
    if third_party.is_file():
        shutil.copy2(third_party, licences / "THIRD_PARTY.md")
    (licences / "NOTICE.txt").write_text(
        build_notice(site_packages), encoding="utf-8"
    )
    for package, path in licence_files(site_packages):
        shutil.copy2(path, licences / f"{package}-{path.name}")
    if fetch_licences:
        missing = download_licence_texts(licences)
        if missing:
            print(
                "warning: these licence texts were not fetched: "
                + ", ".join(missing),
                file=sys.stderr,
            )
    (staging / app_name / "README-להשימה.txt").write_text(README, encoding="utf-8")

    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(staging))
    shutil.rmtree(staging)
    return output


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", default="dist/HebrewNotesWorkbench")
    parser.add_argument("--output")
    parser.add_argument(
        "--site-packages",
        help="where the installed packages are, to find their licence texts",
    )
    parser.add_argument(
        "--download-licences",
        action="store_true",
        help="fetch the licence texts that are not inside the packages",
    )
    args = parser.parse_args(argv)

    app = Path(args.app)
    if not app.is_absolute():
        app = Path.cwd() / app
    output = (
        Path(args.output)
        if args.output
        else Path.cwd() / "release" / f"HebrewNotesWorkbench-{__version__}-win64.zip"
    )
    if not output.is_absolute():
        output = Path.cwd() / output
    output.parent.mkdir(parents=True, exist_ok=True)

    site_packages = Path(args.site_packages) if args.site_packages else None
    if site_packages is None:
        site_packages = default_site_packages()
    if site_packages.is_dir() and not list(site_packages.glob("*.dist-info")):
        # The caller may have given the "lib" folder of the virtual
        # environment instead of the folder with the packages.
        children = list(site_packages.glob("python*/site-packages"))
        if children:
            site_packages = children[0]

    archive = build_release(app, output, site_packages, args.download_licences)
    digest = sha256_of(archive)
    print(f"release: {archive}")
    print(f"size: {archive.stat().st_size} bytes")
    print(f"sha256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
