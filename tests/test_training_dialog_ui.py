"""Headless Qt UI tests for the side-by-side Stage-1 diplomatic verification dialog."""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

if sys.platform.startswith("linux"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _qt_available() -> bool:
    try:
        from PySide6.QtWidgets import QApplication  # noqa: F401

        return True
    except (ImportError, OSError):
        return False


def _make_handwritten_scan(path: Path) -> None:
    im = Image.new("RGB", (900, 1200), (251, 249, 243))
    draw = ImageDraw.Draw(im)
    for idx, y in enumerate((120, 220, 320)):
        draw.rectangle((90, y, 800, y + 54), outline=(220, 220, 225), width=1)
        for step in range(8):
            x = 130 + step * 75 + idx * 5
            draw.line((x, y + 14, x + 32, y + 40), fill=(30, 30, 45), width=3)
    im.save(path, format="PNG")


@unittest.skipUnless(_qt_available(), "PySide6 GUI runtime not available")
class DiplomaticVerificationUITests(unittest.TestCase):
    def setUp(self) -> None:
        from hebrew_workbench.training import SchoolLearningStore
        from hebrew_workbench.ui.main_window import MainWindow
        from tests.qt_app import application, temporary_home

        self.app = application()
        self.home = temporary_home()
        self.learn_dir = Path(self.home.name) / "school_learning"
        self.env_patch = mock.patch.dict(
            os.environ, {"HEBREW_WORKBENCH_LEARNING_DIR": str(self.learn_dir)}
        )
        self.env_patch.start()

        self.page_path = Path(self.home.name) / "student_page1.png"
        _make_handwritten_scan(self.page_path)

        self.window = MainWindow()
        self.window.learning_store = SchoolLearningStore(self.learn_dir)
        self.window.project.add(self.page_path)
        self.window._sync_document_list()
        self.window.doc_list.setCurrentRow(0)

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.env_patch.stop()
        self.home.cleanup()

    def _simulate_ocr_result(self) -> None:
        from hebrew_workbench.engine.base import LineResult, OCRResult, PageResult

        page_text = (
            "אמר רכא הלכתא כוותיה\n"
            "בגלל שהסוגיא מפורשת בגמרא\n"
            "שורה מחוקה בכתב יד"
        )
        res = OCRResult(
            text=page_text,
            engine_name="Mishkefet (Hebrew handwriting)",
            duration_seconds=0.8,
            pages=(
                PageResult(
                    number=1,
                    text=page_text,
                    lines=(
                        LineResult(
                            text="אמר רכא הלכתא כוותיה",
                            confidence=0.74,
                            box=(90.0, 120.0, 710.0, 54.0),
                        ),
                        LineResult(
                            text="בגלל שהסוגיא מפורשת בגמרא",
                            confidence=0.93,
                            box=(90.0, 220.0, 710.0, 54.0),
                        ),
                        LineResult(
                            text="שורה מחוקה בכתב יד",
                            confidence=0.41,
                            box=(90.0, 320.0, 710.0, 54.0),
                        ),
                    ),
                ),
            ),
        )
        self.window._on_ocr_done(res, self.window._shown_entry)
        self.app.processEvents()

    def test_stage1_banner_double_confirmation_gate_and_editor_transfer(self) -> None:
        from hebrew_workbench.engine.writer_adaptation import AdaptationReport
        from hebrew_workbench.ui.training_dialog import DiplomaticVerificationDialog

        entry = self.window._shown_entry
        assert entry is not None
        self.assertTrue(self.window.diplomatic_banner.isHidden())

        self._simulate_ocr_result()
        self.assertFalse(self.window.diplomatic_banner.isHidden())
        self.assertIn("שלב 1", self.window.diplomatic_banner_label.text())
        self.assertEqual(len(entry.recognized_pages), 1)
        self.assertEqual(len(entry.recognized_pages[0]["lines"]), 3)

        student = self.window.learning_store.create_writer("אברהם מזרחי")
        self.window._apply_active_writer(student.writer_id, update_entry=True)

        dlg = DiplomaticVerificationDialog(
            entry,
            self.window.learning_store,
            initial_writer_id=student.writer_id,
            parent=self.window,
        )
        cards = dlg._all_cards()
        self.assertEqual(len(cards), 3)

        # Unverified raw OCR lines are NEVER checked by default, and Save is disabled
        self.assertEqual(dlg.verified_cards(), [])
        self.assertFalse(dlg.save_and_train_btn.isEnabled())

        # Editing line 0 to fix an OCR misread ('רכא' -> 'רבא') auto-checks line 0
        cards[0].text_edit.setText("אמר רבא הלכתא כוותיה")
        cards[0].text_edit.textEdited.emit("אמר רבא הלכתא כוותיה")
        self.assertTrue(cards[0].verified_check.isChecked())
        # Still disabled until explicit bottom confirmation checkbox is ticked!
        self.assertFalse(dlg.save_and_train_btn.isEnabled())

        # Visually verify line 1 as written (keeping student's unedited 'בגלל ש...')
        cards[1].verified_check.setChecked(True)
        # Skip crossed-out line 2
        cards[2].skip_check.setChecked(True)
        self.assertFalse(cards[2].verified_check.isChecked())

        # Tick confirmation gate -> Save & Train unlocks
        dlg.confirm_exact_checkbox.setChecked(True)
        self.assertTrue(dlg.save_and_train_btn.isEnabled())

        fake_report = AdaptationReport(
            writer_id=student.writer_id,
            writer_name=student.name,
            accepted=True,
            active_round=1,
            samples_total=2,
            train_samples=2,
            held_out_samples=0,
            held_out_cer_before=None,
            held_out_cer_after=None,
            train_cer_before=0.18,
            train_cer_after=0.0,
            message="עודכן פרופיל התלמיד בהצלחה",
        )
        with mock.patch(
            "hebrew_workbench.ui.training_dialog.run_writer_training",
            return_value=fake_report,
        ):
            dlg._on_save_and_train_clicked()
            deadline = time.monotonic() + 5.0
            while dlg._train_task is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.02)
            self.app.processEvents()

        self.assertEqual(dlg.result(), DiplomaticVerificationDialog.Accepted)
        # Strictly the 2 verified non-skipped lines were saved!
        saved = self.window.learning_store.list_writer_samples(student.writer_id)
        self.assertEqual(len(saved), 2)
        self.assertEqual(saved[0].diplomatic_text, "אמר רבא הלכתא כוותיה")
        self.assertEqual(saved[1].diplomatic_text, "בגלל שהסוגיא מפורשת בגמרא")

        # Simulate MainWindow receiving the accepted dialog result
        with mock.patch(
            "hebrew_workbench.ui.training_dialog.DiplomaticVerificationDialog"
        ) as mock_dlg_cls:
            mock_dlg_cls.Accepted = DiplomaticVerificationDialog.Accepted
            mock_dlg_cls.return_value = dlg
            dlg.exec = mock.Mock(return_value=DiplomaticVerificationDialog.Accepted)
            self.window.open_diplomatic_verification()

        # Verified diplomatic text was carried into the main editor without retyping
        self.assertEqual(
            self.window.editor.toPlainText(),
            "אמר רבא הלכתא כוותיה\nבגלל שהסוגיא מפורשת בגמרא",
        )
        self.assertIn("שלב 1 הושלם", self.window.diplomatic_banner_label.text())
        dlg.close()

    def test_stage2_grammar_edits_never_poison_diplomatic_training_lines(self) -> None:
        from hebrew_workbench.ui.training_dialog import DiplomaticVerificationDialog

        entry = self.window._shown_entry
        assert entry is not None
        self._simulate_ocr_result()

        # Suppose Stage-1 diplomatic text had student's original phrasing ("בגלל ש..."),
        # and then in Stage 2 the user accepted a style/grammar edit ("משום ש...") in the editor!
        entry.diplomatic_transcription = (
            "אמר רבא הלכתא כוותיה\nבגלל שהסוגיא מפורשת בגמרא\nשורה שלישית"
        )
        entry.transcription = (
            "אמר רבא הלכתא כוותיה\nמשום שהסוגיא מפורשת בגמרא\nשורה שלישית"
        )
        entry.changes = [
            {
                "original": "בגלל ש",
                "replacement": "משום ש",
                "position": 21,
                "before": "אמר רבא הלכתא כוותיה\n",
                "after": "הסוגיא מפורשת בגמרא",
                "batch": 1,
                "identifier": 1,
            }
        ]

        dlg = DiplomaticVerificationDialog(entry, self.window.learning_store)
        cards = dlg._all_cards()
        # Dialog loads the pre-grammar diplomatic text ("בגלל..."), NOT the Stage-2 rewrite ("משום...")!
        self.assertEqual(cards[1].diplomatic_text, "בגלל שהסוגיא מפורשת בגמרא")
        dlg.close()


if __name__ == "__main__":
    unittest.main()
