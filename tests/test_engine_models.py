"""Tests for the model manifest, the download and the integrity checks."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from hebrew_workbench.engine import models
from hebrew_workbench.engine.models import (
    InstallCancelled,
    InstallError,
    ModelArtifact,
    install_artifact,
    md5_of,
    sha256_of,
    verify_file,
)


def make_artifact(path: Path, **overrides) -> ModelArtifact:
    data = path.read_bytes()
    fields = {
        "id": "test-model",
        "name": "Test model",
        "filename": path.name,
        "url": path.as_uri(),
        "size_bytes": len(data),
        "md5": hashlib.md5(data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "license": "Apache-2.0",
        "license_url": "https://example.invalid/",
        "script": "Hebrew",
        "engine_version": "test",
    }
    fields.update(overrides)
    return ModelArtifact(**fields)


class ModelTests(unittest.TestCase):
    def test_cancellation_during_verification_never_installs(self) -> None:
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "model.bin"
            source.write_bytes(b"model weights")
            artifact = make_artifact(source)
            destination = Path(folder) / "installed"
            stopped = False

            def verify(*args):
                nonlocal stopped
                stopped = True
                return None

            with patch.object(models, "verify_file", side_effect=verify):
                with self.assertRaises(InstallCancelled):
                    install_artifact(artifact, destination, cancel=lambda: stopped)
            self.assertEqual(list(destination.iterdir()), [])

    def test_cancellable_download_caps_network_operation_timeout(self) -> None:
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "model.bin"
            source.write_bytes(b"weights")
            artifact = make_artifact(source)
            with patch.object(models.urllib.request, "urlopen", side_effect=TimeoutError) as open_url:
                with self.assertRaises(InstallError):
                    install_artifact(artifact, Path(folder) / "out", cancel=lambda: False)
                self.assertEqual(open_url.call_args.kwargs["timeout"], 5.0)

    def test_digests_are_computed_over_the_whole_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.bin"
            path.write_bytes(b"x" * 10000)
            self.assertEqual(md5_of(path), hashlib.md5(b"x" * 10000).hexdigest())
            self.assertEqual(sha256_of(path), hashlib.sha256(b"x" * 10000).hexdigest())

    def test_a_good_file_passes_the_check(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.bin"
            path.write_bytes(b"model weights")
            artifact = make_artifact(path)
            self.assertIsNone(verify_file(path, artifact))

    def test_a_wrong_md5_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.bin"
            path.write_bytes(b"model weights")
            artifact = make_artifact(path, md5="0" * 32)
            problem = verify_file(path, artifact)
            self.assertIsNotNone(problem)
            self.assertIn("MD5", problem)

    def test_a_wrong_sha256_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.bin"
            path.write_bytes(b"model weights")
            artifact = make_artifact(path, sha256="0" * 64)
            problem = verify_file(path, artifact)
            self.assertIsNotNone(problem)
            self.assertIn("SHA-256", problem)

    def test_a_wrong_size_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.bin"
            path.write_bytes(b"model weights")
            artifact = make_artifact(path, size_bytes=999)
            problem = verify_file(path, artifact)
            self.assertIsNotNone(problem)
            self.assertIn("גודל", problem)

    def test_installing_checks_the_file_and_moves_it_into_place(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "model.bin"
            source.write_bytes(b"model weights")
            artifact = make_artifact(source)
            target_dir = Path(folder) / "models"
            installed = install_artifact(artifact, target_dir)
            self.assertTrue(installed.is_file())
            self.assertIsNone(verify_file(installed, artifact))

    def test_installing_uses_fallback_when_primary_download_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            primary = Path(folder) / "primary.bin"
            fallback = Path(folder) / "fallback.bin"
            primary.write_bytes(b"bad weights!!")
            fallback.write_bytes(b"model weights")
            artifact = make_artifact(
                fallback,
                url=primary.as_uri(),
                fallback_urls=(fallback.as_uri(),),
            )
            target_dir = Path(folder) / "models"
            installed = install_artifact(artifact, target_dir)
            self.assertEqual(installed.read_bytes(), b"model weights")
            self.assertIsNone(verify_file(installed, artifact))

    def test_installing_a_broken_download_does_not_leave_a_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "model.bin"
            source.write_bytes(b"model weights")
            artifact = make_artifact(source, md5="0" * 32)
            target_dir = Path(folder) / "models"
            with self.assertRaises(InstallError):
                install_artifact(artifact, target_dir)
            self.assertEqual(list(target_dir.glob("*")), [])

    def test_the_download_can_be_stopped(self) -> None:
        """The user has to be able to stop the download of a model."""
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "model.bin"
            source.write_bytes(b"model weights")
            artifact = make_artifact(source)
            target_dir = Path(folder) / "models"
            with self.assertRaises(InstallError):
                install_artifact(artifact, target_dir, cancel=lambda: True)
            # Nothing is left behind: a file that was not finished is
            # never mistaken for a model.
            self.assertEqual(list(target_dir.glob("*")), [])

    def test_the_download_continues_when_nothing_asks_to_stop_it(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "model.bin"
            source.write_bytes(b"model weights")
            artifact = make_artifact(source)
            target_dir = Path(folder) / "models"
            installed = install_artifact(artifact, target_dir, cancel=lambda: False)
            self.assertTrue(installed.is_file())

    def test_a_stopped_download_does_not_try_the_other_places(self) -> None:
        """A download that was stopped is not a place that failed: the
        other places are not tried."""
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "model.bin"
            source.write_bytes(b"model weights")
            other = Path(folder) / "other.bin"
            other.write_bytes(b"model weights")
            artifact = make_artifact(
                source, fallback_urls=(other.as_uri(),)
            )
            target_dir = Path(folder) / "models"
            with self.assertRaises(InstallCancelled):
                install_artifact(artifact, target_dir, cancel=lambda: True)
            self.assertEqual(list(target_dir.glob("*")), [])

    def test_known_models_declare_a_license_and_a_size(self) -> None:
        for artifact in models.MODEL_ARTIFACTS.values():
            self.assertTrue(artifact.license)
            self.assertTrue(artifact.license_url.startswith("https://"))
            self.assertGreater(artifact.size_bytes, 0)
            # Some hosts publish no MD5.  The SHA-256 that the project
            # pinned is then the digest that the file is checked against.
            if artifact.md5 is not None:
                self.assertEqual(len(artifact.md5), 32)

    def test_a_model_without_a_published_md5_is_checked_by_its_sha256(self) -> None:
        """Some hosts publish no MD5, and the file is still checked."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.bin"
            path.write_bytes(b"model weights")
            artifact = make_artifact(path, md5=None)
            self.assertIsNone(verify_file(path, artifact))
            wrong = make_artifact(path, md5=None, sha256="0" * 64)
            self.assertIsNotNone(verify_file(path, wrong))

    def test_the_model_of_the_second_engine_is_known(self) -> None:
        """The model of the second engine is in the catalogue, with its
        licence and with the digest that the file must have."""
        artifact = models.MODEL_ARTIFACTS["mishkefet-v1"]
        self.assertEqual(artifact.engine, "mishkefet")
        self.assertEqual(artifact.license, "CC-BY-NC-SA-4.0")
        self.assertEqual(artifact.size_bytes, 120_864_761)
        self.assertEqual(
            artifact.sha256,
            "0dfb82e440ebfa9dd61f562ad36a83ec41c23904eacd96623c3bd8f6fd850b88",
        )
        self.assertTrue(artifact.url.startswith("https://"))
        # The licence of the model is not a commercial one, and the user
        # has to be told about it before the file is fetched.
        self.assertIn("CC-BY-NC-SA-4.0", artifact.summary())
        self.assertIn("non-commercial", artifact.notes)

    def test_every_model_belongs_to_an_engine_that_exists(self) -> None:
        """A model of an engine that is not in the program would never be
        measured and never be read."""
        for artifact in models.MODEL_ARTIFACTS.values():
            self.assertIn(artifact.engine, ("kraken", "mishkefet"))

    def test_known_models_have_a_pinned_sha256(self) -> None:
        """Every model file is checked against two digests."""
        for artifact in models.MODEL_ARTIFACTS.values():
            self.assertIsNotNone(artifact.sha256)
            self.assertEqual(len(artifact.sha256 or ""), 64)
            self.assertTrue(
                all(char in "0123456789abcdef" for char in artifact.sha256 or "")
            )
            self.assertNotEqual(artifact.sha256, "0" * 64)

    def test_models_directory_follows_the_environment(self) -> None:
        import os
        import tempfile

        original = os.environ.get("HEBREW_WORKBENCH_MODELS")
        # A path that is built with Path, so that the test is the same
        # on every system.
        target = Path(tempfile.gettempdir()) / "somewhere"
        os.environ["HEBREW_WORKBENCH_MODELS"] = str(target)
        try:
            self.assertEqual(models.models_directory(), target)
        finally:
            if original is None:
                os.environ.pop("HEBREW_WORKBENCH_MODELS", None)
            else:
                os.environ["HEBREW_WORKBENCH_MODELS"] = original


if __name__ == "__main__":
    unittest.main()
