"""Tests for the model manifest, the download and the integrity checks."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from hebrew_workbench.engine import models
from hebrew_workbench.engine.models import (
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

    def test_installing_a_broken_download_does_not_leave_a_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "model.bin"
            source.write_bytes(b"model weights")
            artifact = make_artifact(source, md5="0" * 32)
            target_dir = Path(folder) / "models"
            with self.assertRaises(InstallError):
                install_artifact(artifact, target_dir)
            self.assertEqual(list(target_dir.glob("*")), [])

    def test_known_models_declare_a_license_and_a_size(self) -> None:
        for artifact in models.MODEL_ARTIFACTS.values():
            self.assertTrue(artifact.license)
            self.assertTrue(artifact.license_url.startswith("https://"))
            self.assertGreater(artifact.size_bytes, 0)
            self.assertEqual(len(artifact.md5), 32)

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
