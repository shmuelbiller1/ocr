"""Tests for putting the built application into a folder for a user."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "build_release.py"
SPEC = importlib.util.spec_from_file_location("build_release", MODULE_PATH)
release = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def make_application(self, root: Path) -> Path:
        app = root / "HebrewNotesWorkbench"
        (app / "_internal").mkdir(parents=True)
        (app / "HebrewNotesWorkbench.exe").write_bytes(b"the program")
        (app / "_internal" / "Qt6Core.dll").write_bytes(b"the library")
        return app

    def make_packages(self, root: Path) -> Path:
        """A folder with the licence texts of the packages of the program."""
        packages = root / "packages"
        for name in release.REQUIRED_LICENCE_PACKAGES:
            info = packages / f"{name}-1.0.dist-info"
            info.mkdir(parents=True, exist_ok=True)
            (info / "LICENSE").write_text(f"the licence of {name}", encoding="utf-8")
        return packages

    def fetch_text(self, url: str) -> str:
        """A stand-in for the texts that are fetched from the network."""
        return (
            "GNU LESSER GENERAL PUBLIC LICENSE\n"
            "GNU GENERAL PUBLIC LICENSE\n"
            "PYTHON SOFTWARE FOUNDATION LICENSE\n"
        )

    def build(self, app: Path, output: Path, packages: Path, worker: Path | None = None):
        """Make a release with licence texts that were fetched."""
        return release.build_release(
            app,
            output,
            packages,
            fetch_licences=True,
            worker=worker,
            fetch=self.fetch_text,
        )

    def make_worker(self, root: Path) -> Path:
        worker = root / "ocr-worker"
        (worker / "_internal").mkdir(parents=True)
        (worker / "ocr-worker.exe").write_bytes(b"the worker")
        (worker / "_internal" / "torch.dll").write_bytes(b"the library")
        return worker

    def test_the_archive_holds_the_application_the_licences_and_the_readme(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = self.make_application(root)
            output = root / "release" / "program.zip"

            self.build(app, output, self.make_packages(root))

            self.assertTrue(output.is_file())
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
            self.assertIn("HebrewNotesWorkbench/HebrewNotesWorkbench.exe", names)
            self.assertIn("HebrewNotesWorkbench/_internal/Qt6Core.dll", names)
            self.assertIn("HebrewNotesWorkbench/LICENCES/NOTICE.txt", names)
            self.assertIn("HebrewNotesWorkbench/LICENCES/THIRD_PARTY.md", names)
            self.assertTrue(
                any(name.endswith("README-להשימה.txt") for name in names), names
            )
            self.assertTrue(
                all(name.startswith("HebrewNotesWorkbench/") for name in names), names
            )

    def test_the_notice_names_every_component(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = self.make_application(root)
            output = root / "program.zip"
            self.build(app, output, self.make_packages(root))
            with zipfile.ZipFile(output) as archive:
                notice = archive.read(
                    "HebrewNotesWorkbench/LICENCES/NOTICE.txt"
                ).decode("utf-8")
            self.assertIn("PySide6-Essentials", notice)
            self.assertIn("LGPL-3.0-only", notice)
            self.assertIn("Pillow", notice)

    def test_the_licence_texts_of_the_packages_are_copied(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = self.make_application(root)
            packages = self.make_packages(root)
            output = root / "program.zip"

            self.build(app, output, packages)

            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
            self.assertIn(
                "HebrewNotesWorkbench/LICENCES/pillow-1.0.dist-info-LICENSE", names
            )

    def test_a_licence_text_that_is_not_the_right_one_is_not_kept(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "licences"
            target.mkdir()

            missing = release.download_licence_texts(
                target, fetch=lambda url: "this is not a licence"
            )

            self.assertIn("LGPL-3.0.txt", missing)
            self.assertFalse((target / "LGPL-3.0.txt").exists())

    def test_a_licence_text_that_arrives_is_kept(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "licences"
            target.mkdir()

            missing = release.download_licence_texts(
                target,
                fetch=lambda url: "GNU LESSER GENERAL PUBLIC LICENSE\nVersion 3",
            )

            self.assertNotIn("LGPL-3.0.txt", missing)
            self.assertTrue((target / "LGPL-3.0.txt").is_file())

    def test_the_digest_of_the_archive_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = self.make_application(root)
            output = root / "program.zip"
            self.build(app, output, self.make_packages(root))
            self.assertEqual(len(release.sha256_of(output)), 64)

    def test_the_archive_holds_the_licence_of_the_program(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = self.make_application(root)
            output = root / "program.zip"
            self.build(app, output, self.make_packages(root))
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
            self.assertIn("HebrewNotesWorkbench/LICENCES/LICENSE", names)

    def test_the_archive_holds_the_recognition_worker(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = self.make_application(root)
            worker = self.make_worker(root)
            output = root / "program.zip"
            self.build(app, output, self.make_packages(root), worker=worker)
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
            self.assertIn("HebrewNotesWorkbench/ocr-worker/ocr-worker.exe", names)
            self.assertIn("HebrewNotesWorkbench/ocr-worker/_internal/torch.dll", names)

    def test_the_release_is_not_made_when_a_licence_text_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = self.make_application(root)
            output = root / "program.zip"
            with self.assertRaises(SystemExit):
                release.build_release(app, output, root / "no-packages")
            self.assertFalse(output.exists())

    def test_the_release_is_not_made_when_a_licence_text_cannot_be_fetched(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = self.make_application(root)
            output = root / "program.zip"
            with self.assertRaises(SystemExit):
                release.build_release(
                    app,
                    output,
                    self.make_packages(root),
                    fetch_licences=True,
                    fetch=lambda url: "this is not a licence",
                )
            self.assertFalse(output.exists())

    def test_the_release_is_not_made_without_the_licence_of_qt(self) -> None:
        """The text of the LGPL has to be in the release."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = self.make_application(root)
            output = root / "program.zip"
            with self.assertRaises(SystemExit):
                release.build_release(app, output, self.make_packages(root))
            self.assertFalse(output.exists())

    def test_the_release_holds_the_licence_of_qt_and_of_python(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = self.make_application(root)
            output = root / "program.zip"
            self.build(app, output, self.make_packages(root))
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
            self.assertIn("HebrewNotesWorkbench/LICENCES/LGPL-3.0.txt", names)
            self.assertIn("HebrewNotesWorkbench/LICENCES/GPL-3.0.txt", names)
            self.assertIn("HebrewNotesWorkbench/LICENCES/PSF-LICENSE.txt", names)


if __name__ == "__main__":
    unittest.main()
