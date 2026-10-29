"""The one-click Windows package can be inspected and extracted without Windows.

These tests inspect the exact offline payload ZIP embedded into the final
standard PyInstaller one-file EXE.
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tools import build_one_click, portable_launcher


class OneClickTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model_bytes = b"test model weights for offline package"
        self.digest = hashlib.sha256(self.model_bytes).hexdigest()
        self.model = self.root / "small.safetensors"
        self.model.write_bytes(self.model_bytes)
        self.release = self.root / "release.zip"
        with zipfile.ZipFile(self.release, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("HebrewNotesWorkbench/HebrewNotesWorkbench.exe", b"app")
            archive.writestr("HebrewNotesWorkbench/ocr-worker/ocr-worker.exe", b"worker")
            archive.writestr("HebrewNotesWorkbench/LICENCES/NOTICE.txt", b"licenses")
        self.patches = [
            patch.object(build_one_click, "MODEL_SIZE", len(self.model_bytes)),
            patch.object(build_one_click, "MODEL_SHA256", self.digest),
            patch.object(portable_launcher, "MODEL_SIZE", len(self.model_bytes)),
            patch.object(portable_launcher, "MODEL_SHA256", self.digest),
        ]
        for obj in self.patches:
            obj.start()
            self.addCleanup(obj.stop)

    def test_payload_contains_complete_program_and_verified_model(self):
        output = self.root / "one-click-payload.zip"
        build_one_click.build(self.release, self.model, output)
        with zipfile.ZipFile(output, "r") as archive:
            self.assertEqual(archive.read(build_one_click.MODEL_NAME), self.model_bytes)
            self.assertIn(build_one_click.NOTICE_NAME, archive.namelist())

        first = portable_launcher.unpack_once(output, self.root / "cache")
        self.assertEqual((first / "models" / "small.safetensors").read_bytes(), self.model_bytes)
        self.assertTrue((first / "ocr-worker" / "ocr-worker.exe").exists())
        second = portable_launcher.unpack_once(output, self.root / "cache")
        self.assertEqual(first, second)

    def test_rejects_wrong_model_digest_before_packaging(self):
        self.model.write_bytes(b"different weights")
        with self.assertRaisesRegex(ValueError, "not the verified"):
            build_one_click.build(self.release, self.model, self.root / "bad.zip")

    def test_rejects_zip_traversal_even_when_model_is_valid(self):
        with zipfile.ZipFile(self.release, "a") as archive:
            archive.writestr("HebrewNotesWorkbench/../outside.txt", b"bad")
        output = self.root / "unsafe.zip"
        build_one_click.build(self.release, self.model, output)
        with self.assertRaisesRegex(RuntimeError, "unsafe file path"):
            portable_launcher.unpack_once(output, self.root / "cache")

    def test_rejects_duplicate_zip_member(self):
        with zipfile.ZipFile(self.release, "a") as archive:
            archive.writestr("HebrewNotesWorkbench/HebrewNotesWorkbench.exe", b"again")
        output = self.root / "duplicate.zip"
        build_one_click.build(self.release, self.model, output)
        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            portable_launcher.unpack_once(output, self.root / "cache")

    def test_rejects_broken_cached_model(self):
        output = self.root / "one-click-payload.zip"
        build_one_click.build(self.release, self.model, output)
        cached = portable_launcher.unpack_once(output, self.root / "cache")
        (cached / "models" / "small.safetensors").write_bytes(b"changed")
        with self.assertRaisesRegex(RuntimeError, "incomplete offline cache"):
            portable_launcher.unpack_once(output, self.root / "cache")


if __name__ == "__main__":
    unittest.main()
