"""Headless Qt UI tests for Stage-A verification, draft non-verification, LRU & admin dialogs."""

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

    def test_editing_or_saving_draft_never_marks_line_verified_until_explicitly_confirmed(
        self,
    ) -> None:
        from hebrew_workbench.engine.writer_adaptation import AdaptationReport
        from hebrew_workbench.training import (
            STATUS_NOT_REVIEWED,
            STATUS_UNCERTAIN,
            STATUS_VERIFIED,
        )
        from hebrew_workbench.ui.training_dialog import DiplomaticVerificationDialog

        entry = self.window._shown_entry
        assert entry is not None
        self.assertTrue(self.window.diplomatic_banner.isHidden())

        self._simulate_ocr_result()
        self.assertFalse(self.window.diplomatic_banner.isHidden())

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
        self.assertEqual(dlg.verified_cards(), [])
        self.assertFalse(dlg.save_and_train_btn.isEnabled())

        # CRITICAL INVARIANT: Editing line 0 does NOT mark it verified!
        cards[0].text_edit.setText("אמר רבא הלכתא כוותיה")
        cards[0].text_edit.textEdited.emit("אמר רבא הלכתא כוותיה")
        self.assertEqual(cards[0].review_status, STATUS_NOT_REVIEWED)
        self.assertEqual(dlg.verified_cards(), [])
        self.assertFalse(dlg.save_and_train_btn.isEnabled())

        # Saving draft progress persists the edit locally WITHOUT turning it into training data!
        dlg._on_save_draft_clicked()
        self.assertEqual(
            self.window.learning_store.list_writer_samples(student.writer_id), []
        )
        saved_drafts = self.window.learning_store.list_document_lines(
            student.writer_id, entry.file_path
        )
        self.assertEqual(saved_drafts[(1, 0)].diplomatic_text, "אמר רבא הלכתא כוותיה")
        self.assertEqual(saved_drafts[(1, 0)].review_status, STATUS_NOT_REVIEWED)
        dlg.close()

        # Reopen dialog -> draft edit is restored! Now explicitly confirm line 0 (Ctrl+Enter),
        # mark line 1 uncertain (Alt+U), and skip line 2:
        dlg2 = DiplomaticVerificationDialog(
            entry,
            self.window.learning_store,
            initial_writer_id=student.writer_id,
            parent=self.window,
        )
        cards2 = dlg2._all_cards()
        self.assertEqual(cards2[0].diplomatic_text, "אמר רבא הלכתא כוותיה")
        self.assertEqual(cards2[0].review_status, STATUS_NOT_REVIEWED)

        # Quick confirm line 0 (verify_and_advance) + uncertain line 1 + skip line 2
        dlg2._on_verify_and_advance(0)
        self.assertEqual(cards2[0].review_status, STATUS_VERIFIED)
        dlg2._on_uncertain_and_advance(1)
        self.assertEqual(cards2[1].review_status, STATUS_UNCERTAIN)
        cards2[2].skip_check.setChecked(True)

        dlg2.confirm_exact_checkbox.setChecked(True)
        self.assertTrue(dlg2.save_and_train_btn.isEnabled())

        fake_report = AdaptationReport(
            writer_id=student.writer_id,
            writer_name=student.name,
            accepted=False,
            status="insufficient_evidence",
            active_round=0,
            samples_total=1,
            train_samples=1,
            held_out_samples=0,
            held_out_cer_before=None,
            held_out_cer_after=None,
            train_cer_before=0.0,
            train_cer_after=0.0,
            message="נשמרה שורה מאומתת 1 (נדרשות לפחות 8 להוכחת שיפור)",
        )
        with mock.patch(
            "hebrew_workbench.ui.training_dialog.run_writer_training",
            return_value=fake_report,
        ):
            dlg2._on_save_and_train_clicked()
            deadline = time.monotonic() + 5.0
            while dlg2._train_task is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.02)
            self.app.processEvents()

        # ONLY line 0 (explicitly verified) is in training samples; uncertain & skipped are excluded!
        verified_samples = self.window.learning_store.list_writer_samples(
            student.writer_id
        )
        self.assertEqual(len(verified_samples), 1)
        self.assertEqual(verified_samples[0].diplomatic_text, "אמר רבא הלכתא כוותיה")

        # MainWindow receives non-skipped diplomatic text so user doesn't retype fixes
        with mock.patch(
            "hebrew_workbench.ui.training_dialog.DiplomaticVerificationDialog"
        ) as mock_dlg_cls:
            mock_dlg_cls.Accepted = DiplomaticVerificationDialog.Accepted
            mock_dlg_cls.return_value = dlg2
            dlg2.exec = mock.Mock(return_value=DiplomaticVerificationDialog.Accepted)
            self.window.open_diplomatic_verification()

        self.assertEqual(
            self.window.editor.toPlainText(),
            "אמר רבא הלכתא כוותיה\nבגלל שהסוגיא מפורשת בגמרא",
        )
        dlg2.close()

    def test_stage2_grammar_edits_never_overwrite_stage1_training_labels(self) -> None:
        from hebrew_workbench.ui.training_dialog import DiplomaticVerificationDialog

        entry = self.window._shown_entry
        assert entry is not None
        self._simulate_ocr_result()

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
        self.assertEqual(cards[1].diplomatic_text, "בגלל שהסוגיא מפורשת בגמרא")
        dlg.close()

    def test_admin_vocab_dialog_and_adapter_rollback_dialog(self) -> None:
        from hebrew_workbench.ui.training_dialog import (
            AdapterHistoryDialog,
            SchoolVocabularyDialog,
        )

        # Admin vocabulary dialog
        vdlg = SchoolVocabularyDialog(self.window.learning_store, self.window)
        self.assertFalse(vdlg.sharing_check.isChecked())
        vdlg.sharing_check.setChecked(True)
        self.assertTrue(self.window.learning_store.vocab_sharing_enabled())
        self.window.learning_store.approve_vocab_term("שמעתתין")
        vdlg._refresh_lists()
        self.assertEqual(vdlg.approved_list.count(), 1)
        vdlg.approved_list.setCurrentRow(0)
        vdlg._remove_selected_approved()
        self.assertEqual(vdlg.approved_list.count(), 0)
        vdlg.close()

        # Adapter history & one-click rollback dialog
        student = self.window.learning_store.create_writer("בדיקת שחזור")
        rel_h = f"writers/{student.writer_id}/heads/head-r0001.npz"
        abs_h = self.learn_dir.joinpath(*rel_h.split("/"))
        abs_h.parent.mkdir(parents=True, exist_ok=True)
        abs_h.write_bytes(b"stub")
        self.window.learning_store.record_adapter_version(
            student.writer_id,
            round_number=1,
            head_relpath=rel_h,
            model_sha256="a" * 64,
            samples_total=10,
            train_samples=8,
            held_out_samples=2,
            held_out_chars=40,
            held_out_cer_before=0.25,
            held_out_cer_after=0.14,
            activate=True,
        )
        hdlg = AdapterHistoryDialog(
            self.window.learning_store, student.writer_id, self.window
        )
        self.assertEqual(hdlg.version_list.count(), 2)
        hdlg._rollback_one_step()
        prof_after = self.window.learning_store.get_writer(student.writer_id)
        assert prof_after is not None
        self.assertEqual(prof_after.active_round, 0)
        hdlg.close()

    def test_reopen_draft_save_preserves_previously_verified_lines_and_esc_blocked_during_train(
        self,
    ) -> None:
        from hebrew_workbench.training import STATUS_NOT_REVIEWED, STATUS_VERIFIED
        from hebrew_workbench.ui.training_dialog import DiplomaticVerificationDialog

        entry = self.window._shown_entry
        assert entry is not None
        self._simulate_ocr_result()

        student = self.window.learning_store.create_writer("שמירת אימות קודם")
        self.window._apply_active_writer(student.writer_id, update_entry=True)

        # Round 1: Verify line 0 with confirmation gate ticked
        dlg1 = DiplomaticVerificationDialog(
            entry,
            self.window.learning_store,
            initial_writer_id=student.writer_id,
            parent=self.window,
        )
        dlg1._active_page_cards[0].set_review_status(STATUS_VERIFIED)
        dlg1.confirm_exact_checkbox.setChecked(True)
        dlg1._persist_all_reviewed_states(grammar_confirmed_for_verified=True)
        dlg1.close()
        self.assertEqual(
            len(self.window.learning_store.list_writer_samples(student.writer_id)),
            1,
        )

        # Round 2: Reopen dialog; confirm_exact_checkbox starts unchecked.
        # User marks line 1 as verified WITHOUT ticking confirm_exact_checkbox and clicks Save Draft.
        # Previously verified untouched line 0 MUST stay STATUS_VERIFIED, while unconfirmed line 1 stays draft!
        dlg2 = DiplomaticVerificationDialog(
            entry,
            self.window.learning_store,
            initial_writer_id=student.writer_id,
            parent=self.window,
        )
        self.assertFalse(dlg2.confirm_exact_checkbox.isChecked())
        self.assertEqual(
            dlg2._active_page_cards[0].review_status, STATUS_VERIFIED
        )
        dlg2._active_page_cards[1].set_review_status(STATUS_VERIFIED)
        dlg2._on_save_draft_clicked()

        samples_after = self.window.learning_store.list_writer_samples(
            student.writer_id
        )
        self.assertEqual(len(samples_after), 1)
        self.assertEqual(samples_after[0].line_index, 0)
        doc_map = self.window.learning_store.list_document_lines(
            student.writer_id, entry.file_path
        )
        self.assertEqual(doc_map[(1, 0)].review_status, STATUS_VERIFIED)
        self.assertEqual(doc_map[(1, 1)].review_status, STATUS_NOT_REVIEWED)

        # Verify Esc / reject() is ignored while _train_task is running
        dlg2._train_task = mock.Mock(isRunning=mock.Mock(return_value=True))
        dlg2.setResult(0)
        dlg2.reject()
        self.assertEqual(dlg2.result(), 0)
        dlg2._train_task = None
        dlg2.close()


if __name__ == "__main__":
    unittest.main()
