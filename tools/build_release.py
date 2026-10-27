"""Put the built application into a folder that can be given to a user.

    python tools/build_release.py --app dist/HebrewNotesWorkbench

The result is a ZIP file with

* the application itself, exactly as it was built,
* the folder `ocr-worker` with the recognition worker, so that the
  program can read handwriting without anything else,
* a folder `LICENCES` with the licence texts of the components that are
  inside the application, and a notice that says what every component
  is and where its licence comes from,
* a file `README-להשימה.txt` that tells a user who does not know
  anything about programs what to do with the program.

The script prints the SHA-256 of the ZIP, so that the file that is
published can be checked by the person who downloads it.

The archive is not made when a licence text is missing: a program that
is given to somebody has to carry the licence of every part of it.
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

#: The packages that are inside the application.  Only the licence
#: texts of these packages are put into the release.
PACKAGES_IN_THE_APP = (
    "pyside6_essentials",
    "shiboken6",
    "pillow",
    "pypdfium2",
    "python_docx",
    "lxml",
)

#: The packages whose licence text has to be inside the installed
#: package.  The release is not made when one of them is missing.  The
#: Qt packages are not among them: their licence is the LGPL, and its
#: text is fetched (see LICENCE_TEXTS).
REQUIRED_LICENCE_PACKAGES = (
    "pillow",
    "pypdfium2",
    "python_docx",
    "lxml",
)

#: The files of an installed package that are not licence texts.
NOT_LICENCE_FILES = {
    "METADATA",
    "RECORD",
    "WHEEL",
    "INSTALLER",
    "REQUESTED",
    "entry_points.txt",
    "top_level.txt",
    "direct_url.json",
    "AUTHORS.txt",
    "CHANGES.txt",
    "CHANGELOG.md",
    "CONTRIBUTORS.txt",
    "HISTORY.txt",
    "NEWS.txt",
    "zip-safe",
}

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
* ocr-worker - תיקיית מנוע הזיהוי. התוכנה מוצאת אותו בעצמה, ולכן אין
  צורך להתקין Python ואין צורך להתקין דבר אחר.
* LICENCES - טקסטים של הרישיונות של הרכיבים שבתוכנה, ורשימה שלהם.
* samples - דפי דוגמה (דפים מלאכותיים, לא סריקות אמיתיות).

דרך לשמירה על התוכנה
--------------------
רישיון התוכנה עצמה: ראו את הקובץ LICENSE בתיקיית LICENCES. רכיבי Qt
מגיעים עם רישיון LGPL, ולכן אפשר להחליף את קובצי ה-DLL של Qt שבתיקייה
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
    """Every licence text that is inside the installed packages.

    Only the packages that are inside the application are looked at.
    The name of the file of a licence is not the same in every
    package: some use ``LICENSE``, some ``LICENSE.txt``, some
    ``licenses/LICENSE`` and some the name of the licence itself, like
    ``Apache-2.0.txt``.  Every text file of the package that is not
    one of the known files of the format is taken, so that no licence
    is left out.
    """
    found: list[tuple[str, Path]] = []
    if not site_packages.is_dir():
        return found
    for info in sorted(site_packages.glob("*.dist-info")):
        name = info.name.lower()
        if not any(name.startswith(package) for package in PACKAGES_IN_THE_APP):
            continue
        for path in sorted(info.iterdir()):
            if not path.is_file():
                continue
            if path.name in NOT_LICENCE_FILES:
                continue
            if path.suffix.lower() not in (".txt", ".md") and path.name.upper() not in (
                "LICENSE",
                "COPYING",
                "NOTICE",
            ):
                continue
            found.append((info.name, path))
        licences = info / "licenses"
        if licences.is_dir():
            for path in sorted(licences.rglob("*")):
                if not path.is_file():
                    continue
                if path.suffix.lower() in (".txt", ".md") or path.name.upper() in (
                    "LICENSE",
                    "COPYING",
                    "NOTICE",
                ):
                    found.append((info.name, path))
    return found


def licence_name(package: str, path: Path, info: Path) -> str:
    """The name a licence text gets in the release.

    Two files of a package can have the same name in different
    folders, so the name of the folder is added when there is one.
    """
    try:
        relative = path.relative_to(info)
    except ValueError:  # pragma: no cover - defensive
        return f"{package}-{path.name}"
    if len(relative.parts) > 1:
        return f"{package}-{relative.parent.name}-{path.name}"
    return f"{package}-{path.name}"


def missing_licence_packages(site_packages: Path) -> list[str]:
    """The packages whose licence text was not found.

    A program that is given to somebody has to carry the licence of
    every part of it, so the release is not made when one of them is
    missing.
    """
    found = {package.lower() for package, _ in licence_files(site_packages)}
    missing = []
    for package in REQUIRED_LICENCE_PACKAGES:
        if not any(name.startswith(package) for name in found):
            missing.append(package)
    return missing


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
    app: Path,
    output: Path,
    site_packages: Path,
    fetch_licences: bool = False,
    worker: Path | None = None,
    fetch=None,
) -> Path:
    """Copy the application, add the licences and the readme, and zip it."""
    if not app.is_dir():
        raise SystemExit(f"the application was not found: {app}")

    missing_packages = missing_licence_packages(site_packages)
    if missing_packages:
        raise SystemExit(
            "the licence texts of these packages were not found, so the "
            "program is not given to anybody: " + ", ".join(missing_packages)
        )

    staging = output.parent / f"{output.stem}-content"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    app_name = app.name
    shutil.copytree(app, staging / app_name)

    # The worker of the recognition goes with the program, so that the
    # program can read handwriting without anything else.
    if worker is not None:
        source = Path(worker)
        if not source.is_dir():
            raise SystemExit(f"the recognition worker was not found: {source}")
        shutil.copytree(source, staging / app_name / "ocr-worker")

    # The licences and the readme go into the folder of the program, so
    # that the user has to unpack only one folder.
    licences = staging / app_name / "LICENCES"
    licences.mkdir()
    third_party = REPO_ROOT / "docs" / "THIRD_PARTY.md"
    if third_party.is_file():
        shutil.copy2(third_party, licences / "THIRD_PARTY.md")
    application_licence = REPO_ROOT / "LICENSE"
    if application_licence.is_file():
        shutil.copy2(application_licence, licences / "LICENSE")
    (licences / "NOTICE.txt").write_text(
        build_notice(site_packages), encoding="utf-8"
    )
    for package, path in licence_files(site_packages):
        info = site_packages / package
        shutil.copy2(path, licences / licence_name(package, path, info))
    if fetch_licences:
        missing = download_licence_texts(
            licences, fetch=fetch if fetch is not None else fetch_text
        )
        if missing:
            raise SystemExit(
                "these licence texts were not fetched, so the program is not "
                "given to anybody: " + ", ".join(missing)
            )
    else:
        # The texts that are in the repository are used, so that a
        # release can be made without a network.
        repository = REPO_ROOT / "docs" / "licences"
        if repository.is_dir():
            for name, _url, _marker in LICENCE_TEXTS:
                source = repository / name
                if source.is_file() and not (licences / name).is_file():
                    shutil.copy2(source, licences / name)
    # The texts of the licences that are not inside the packages have to
    # be in the release: the LGPL of the Qt libraries, the GPL that it
    # points at, and the licence of Python.
    absent = [name for name, _url, _marker in LICENCE_TEXTS if not (licences / name).is_file()]
    if absent:
        raise SystemExit(
            "these licence texts are not in the release, so the program is "
            "not given to anybody: "
            + ", ".join(absent)
            + ".  Use --download-licences to fetch them."
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
    parser.add_argument(
        "--worker",
        help="the built recognition worker, to put it into the release",
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

    worker = Path(args.worker) if args.worker else None
    if worker is not None and not worker.is_absolute():
        worker = Path.cwd() / worker
    archive = build_release(
        app, output, site_packages, args.download_licences, worker
    )
    digest = sha256_of(archive)
    print(f"release: {archive}")
    print(f"size: {archive.stat().st_size} bytes")
    print(f"sha256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
