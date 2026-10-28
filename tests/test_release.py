"""Tests for putting the built application into a folder for a user."""

from __future__ import annotations

import importlib.util
import os
import subprocess
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

    def make_packages(
        self, root: Path, with_worker: bool = True
    ) -> Path:
        """A folder with the licence texts of the packages of the program."""
        packages = root / "packages"
        names = list(release.REQUIRED_LICENCE_PACKAGES)
        if with_worker:
            names += list(release.REQUIRED_LICENCE_PACKAGES_OF_THE_WORKER)
        for name in names:
            info = packages / f"{release.distribution_name(name)}-1.0.dist-info"
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

    def test_the_packages_that_the_worker_needs_are_in_the_release(self) -> None:
        """The worker collects kraken, and kraken needs other packages.
        Their licences go into the release as well."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            packages = root / "packages"
            kraken = packages / "kraken-1.0.dist-info"
            kraken.mkdir(parents=True)
            (kraken / "LICENSE").write_text("the licence of kraken", encoding="utf-8")
            (kraken / "METADATA").write_text(
                "Name: kraken\nRequires-Dist: numpy\n"
                "Requires-Dist: mypy ; extra == 'dev'\n",
                encoding="utf-8",
            )
            numpy = packages / "numpy-1.0.dist-info"
            numpy.mkdir(parents=True)
            (numpy / "LICENSE").write_text("the licence of numpy", encoding="utf-8")
            (packages / "mypy-1.0.dist-info").mkdir()
            (packages / "mypy-1.0.dist-info" / "LICENSE").write_text(
                "the licence of mypy", encoding="utf-8"
            )
            found = {name for name, _ in release.licence_files(packages)}
            self.assertIn("numpy-1.0.dist-info", found)
            # An extra of a package is not installed with it.
            self.assertNotIn("mypy-1.0.dist-info", found)

    def test_the_release_without_the_worker_does_not_need_its_licences(self) -> None:
        """The worker is not in the release, and the licences of the
        worker are not needed."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = self.make_application(root)
            output = root / "release.zip"
            packages = self.make_packages(root, with_worker=False)
            archive = self.build(app, output, packages)
            self.assertTrue(archive.exists())

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

    def test_every_archive_has_a_digest_file_of_its_own(self) -> None:
        """A digest file that is written with a glob in its name is a
        file whose name is the glob itself."""
        self.assertIn('sha256sum "$name" > "${name}.sha256"', self.text)
        self.assertNotIn("sha256sum ./*.zip > ./*.sha256", self.text)

    def test_the_manifest_of_the_repository_is_the_one_that_is_checked(self) -> None:
        """The build writes its own manifest to another place, and the
        measurement is checked against the manifest of the repository."""
        self.assertIn("--output build/manifest-of-the-build.json", self.text)


class PublishTheReleaseTests(unittest.TestCase):
    """The step of the build that gives the archive to the user."""

    def setUp(self) -> None:
        self.workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "windows.yml"
        )
        self.text = self.workflow.read_text(encoding="utf-8")
        self.script = self._the_script_of_the_step()

    def _the_script_of_the_step(self) -> str:
        """The commands of the step, as the runner of GitHub sees them."""
        lines = self.text.splitlines()
        start = None
        for index, line in enumerate(lines):
            if line.strip() == "- name: Publish the release":
                start = index
                break
        self.assertIsNotNone(start, "the step of the release is not in the file")
        body: list[str] = []
        inside = False
        for line in lines[start:]:
            if not inside:
                if line.strip() == "run: |":
                    inside = True
                continue
            if line.strip() and not line.startswith(" " * 10):
                break
            body.append(line[10:])
        self.assertTrue(body, "the step of the release has no commands")
        return "\n".join(body)

    def test_the_step_looks_for_a_release_that_is_already_there(self) -> None:
        """A tag that was pushed before the build had made the archive may
        leave a release without an archive, and the build must fill it."""
        self.assertIn('select(.tag_name == ', self.script)
        self.assertIn("gh release upload", self.script)

    def test_the_draft_flag_is_sent_as_a_boolean(self) -> None:
        """The release API wants a boolean and not a text, and it refuses
        a text with an error.  The step would stop before the files are
        put there, and the release would stay without them."""
        self.assertIn("-F draft=false", self.script)
        self.assertNotIn("-f draft=false", self.script)

    def test_the_file_of_the_user_is_not_replaced_with_a_clobber(self) -> None:
        """`gh release upload --clobber` deletes the file that was
        published before it puts the new one, and a failure in between
        leaves the user with nothing.  The new file goes up under a
        temporary name, and the old one is taken away afterwards."""
        calls, _ = self._run_the_script(a_release_is_already_there=True)
        lines = [line for line in calls.splitlines() if line]
        uploads = [
            index for index, line in enumerate(lines) if "release upload" in line
        ]
        self.assertTrue(uploads, "nothing was uploaded")
        for index in uploads:
            self.assertIn(".new", lines[index])
        delete = next(
            index for index, line in enumerate(lines) if "-X DELETE" in line
        )
        rename = next(
            index
            for index, line in enumerate(lines)
            if "-X PATCH" in line and "/assets/" in line
        )
        # The new file is uploaded before the file that was published
        # is taken away, and the new file gets the name of the old one
        # afterwards.
        self.assertLess(min(uploads), delete)
        self.assertLess(delete, rename)

    def test_the_release_is_made_only_when_there_is_none(self) -> None:
        self.assertIn("gh release create", self.script)
        self.assertIn("--verify-tag", self.script)

    @unittest.skipIf(
        os.name == "nt",
        "the release is made by the runner of Linux, and the shell of the "
        "Windows runner is not the shell of that runner",
    )
    def test_the_step_writes_the_release_that_is_already_there(self) -> None:
        """Run the step as the runner of GitHub runs it, with a tool of
        GitHub that only writes what it does."""
        calls, _ = self._run_the_script(a_release_is_already_there=True)
        self.assertNotIn("release create", calls)
        self.assertIn("release upload v0.2.0", calls)
        self.assertIn("--clobber", calls)
        self.assertIn("PATCH", calls)

    @unittest.skipIf(
        os.name == "nt",
        "the release is made by the runner of Linux, and the shell of the "
        "Windows runner is not the shell of that runner",
    )
    def test_the_step_makes_the_release_when_there_is_none(self) -> None:
        calls, digest = self._run_the_script(a_release_is_already_there=False)
        self.assertIn("release create v0.2.0", calls)
        self.assertIn("--verify-tag", calls)
        self.assertIn("app.zip", digest)
        self.assertRegex(digest, r"^[0-9a-f]{64} ")

    def _run_the_script(self, a_release_is_already_there: bool) -> tuple[str, str]:
        """Run the step with a tool of GitHub that only writes what it does."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "release").mkdir()
            (root / "release" / "app.zip").write_bytes(b"zip")
            (root / "release-notes.md").write_text("the notes\n", encoding="utf-8")
            tools = root / "bin"
            tools.mkdir()
            fake = tools / "gh"
            log = root / "calls.log"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                f'echo "$*" >> "{log.as_posix()}"\n'
                + ("echo 4242\n" if a_release_is_already_there else "")
                + "exit 0\n",
                encoding="utf-8",
                newline="\n",
            )
            fake.chmod(0o755)
            script = root / "run.sh"
            script.write_text(
                self.script.replace("${{ github.repository }}", "owner/repo"),
                encoding="utf-8",
                newline="\n",
            )
            environment = dict(os.environ)
            environment["PATH"] = f"{tools}{os.pathsep}{environment['PATH']}"
            environment["TAG"] = "v0.2.0"
            result = subprocess.run(
                ["bash", script.as_posix()],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                result.returncode,
                0,
                f"stdout: {result.stdout}\nstderr: {result.stderr}",
            )
            calls = log.read_text(encoding="utf-8") if log.exists() else ""
            digest = root / "release" / "app.zip.sha256"
            digest_text = (
                digest.read_text(encoding="utf-8") if digest.exists() else ""
            )
            return calls, digest_text


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
