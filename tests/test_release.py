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

    def test_a_licence_text_that_cannot_be_fetched_does_not_stop_the_release(
        self,
    ) -> None:
        """The texts are in the repository, and the network is only a way
        to refresh them."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = self.make_application(root)
            output = root / "program.zip"
            release.build_release(
                app,
                output,
                self.make_packages(root),
                fetch_licences=True,
                fetch=lambda url: "this is not a licence",
            )
            self.assertTrue(output.is_file())
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
            self.assertIn("HebrewNotesWorkbench/LICENCES/LGPL-3.0.txt", names)

    def test_the_licence_texts_are_taken_from_the_repository(self) -> None:
        """The release does not need a network for the licence texts."""
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "licences"
            target.mkdir()
            copied = release.copy_repository_licences(target)
            self.assertIn("LGPL-3.0.txt", copied)
            self.assertIn("GPL-3.0.txt", copied)
            self.assertIn("PSF-LICENSE.txt", copied)
            for name, _url, marker in release.LICENCE_TEXTS:
                text = (target / name).read_text(encoding="utf-8")
                self.assertIn(marker.lower(), text.lower())

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


class ReleaseWorkflowTests(unittest.TestCase):
    """The build that makes a release for the user."""

    def setUp(self) -> None:
        self.workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "windows.yml"
        )
        self.text = self.workflow.read_text(encoding="utf-8")

    def test_a_tag_makes_the_build(self) -> None:
        self.assertIn("tags: ['v*']", self.text)

    def test_the_release_is_published_only_for_a_tag(self) -> None:
        self.assertIn("if: startsWith(github.ref, 'refs/tags/v')", self.text)

    def test_the_release_is_made_of_the_program_that_was_checked(self) -> None:
        """The archive of the user is the one that was unpacked and started."""
        self.assertIn("needs: [test-and-package]", self.text)
        self.assertIn("name: HebrewNotesWorkbench-release", self.text)

    def test_the_release_may_write_to_the_repository(self) -> None:
        self.assertIn("gh release create", self.text)
        self.assertIn("contents: write", self.text)

    def test_the_digest_of_the_archive_is_published_with_it(self) -> None:
        self.assertIn("sha256sum", self.text)
        self.assertIn(".sha256", self.text)

    def test_the_release_is_made_for_the_tag_that_was_pushed(self) -> None:
        self.assertIn("--verify-tag", self.text)

    def test_the_release_has_the_token_that_it_needs(self) -> None:
        self.assertIn("GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}", self.text)

    def test_the_notes_of_the_release_have_the_token_that_they_need(self) -> None:
        self.assertGreaterEqual(
            self.text.count("GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}"), 2
        )

    def test_the_notes_of_the_release_are_the_notes_of_the_repository(self) -> None:
        self.assertIn("docs/RELEASE_NOTES.md", self.text)


class ReleaseNotesTests(unittest.TestCase):
    """The notes of the release say what works and what does not."""

    def setUp(self) -> None:
        self.notes = (
            Path(__file__).resolve().parents[1] / "docs" / "RELEASE_NOTES.md"
        ).read_text(encoding="utf-8")

    def test_the_notes_say_what_does_not_work(self) -> None:
        # The text is written in lines, and the words of a sentence may
        # be on two lines: the text is made one line before it is read.
        text = " ".join(self.notes.split())
        self.assertIn("not verified", text)
        self.assertIn("לשון הספר", text)

    def test_the_notes_say_what_the_program_needs_from_the_user(self) -> None:
        text = " ".join(self.notes.split())
        self.assertIn("the model file is checked against the digest", text)

    def test_the_notes_say_that_nothing_is_uploaded(self) -> None:
        text = " ".join(self.notes.split())
        self.assertIn("Nothing is uploaded anywhere", text)


if __name__ == "__main__":
    unittest.main()
