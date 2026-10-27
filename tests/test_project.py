"""Tests for the workspace/project model."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hebrew_workbench.project import PROJECT_SUFFIX, Project


class ProjectTests(unittest.TestCase):
    def test_add_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scan.png"
            path.write_bytes(b"png")
            project = Project()
            project.add(path)
            project.add(path)
            self.assertEqual(len(project), 1)

    def test_transcription_is_kept_per_document(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / "a.png"
            second = Path(folder) / "b.png"
            first.write_bytes(b"a")
            second.write_bytes(b"b")
            project = Project()
            project.add(first).transcription = "ראשון"
            project.add(second).transcription = "שני"
            self.assertEqual(project[0].transcription, "ראשון")
            self.assertEqual(project[1].transcription, "שני")

    def test_save_and_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            scan = Path(folder) / "scan.png"
            scan.write_bytes(b"png")
            project = Project()
            project.add(scan).transcription = "טקסט לשמירה"
            target = project.save(Path(folder) / "session")
            self.assertTrue(target.exists())
            self.assertEqual(target.suffix, PROJECT_SUFFIX)

            loaded = Project.load(target)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].transcription, "טקסט לשמירה")
            self.assertEqual(loaded[0].path, str(scan.resolve()))

    def test_saved_file_is_utf8_json(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            scan = Path(folder) / "scan.png"
            scan.write_bytes(b"png")
            project = Project()
            project.add(scan).transcription = "עברית"
            target = project.save(Path(folder) / "session.hwproj")
            raw = target.read_text(encoding="utf-8")
            self.assertIn("עברית", raw)
            self.assertIn(json.loads(raw)["schema_version"], (1,))

    def test_newer_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "future.hwproj"
            target.write_text(
                json.dumps({"schema_version": 99, "documents": []}), encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                Project.load(target)

    def test_remove_and_clear(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            scan = Path(folder) / "scan.png"
            scan.write_bytes(b"png")
            project = Project()
            project.add(scan)
            project.remove(0)
            self.assertEqual(len(project), 0)
            project.add(scan)
            project.clear()
            self.assertEqual(len(project), 0)


if __name__ == "__main__":
    unittest.main()
