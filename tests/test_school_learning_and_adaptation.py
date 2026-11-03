"""Tests for SQLite 50-student store, opt-in vocab, rollback, export & CTC adaptation."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

from hebrew_workbench.engine.mishkefet_decoding import load_language_models
from hebrew_workbench.engine.vendor.hebocr.wordlm import WordUnigramLM
from hebrew_workbench.plugins.base import KIND_OCR, Plugin, PluginManifest
from hebrew_workbench.plugins.registry import PluginRegistry
from hebrew_workbench.project import DocumentEntry, Project
from hebrew_workbench.suggestions.spelling import SpellingModule
from hebrew_workbench.training import (
    STATUS_NOT_REVIEWED,
    STATUS_SKIPPED,
    STATUS_UNCERTAIN,
    STATUS_VERIFIED,
    VOCAB_APPROVED,
    VOCAB_PENDING,
    SchoolLearningStore,
    VerifiedLineInput,
    crop_line_from_page,
    extract_school_vocab_tokens,
)

try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:  # pragma: no cover - GUI-only CI job
    np = None  # type: ignore[assignment]
    HAS_NUMPY = False


def _make_line_image(width: int = 220, height: int = 44, seed: int = 0) -> Image.Image:
    im = Image.new("RGB", (width, height), (250, 249, 245))
    draw = ImageDraw.Draw(im)
    for idx in range(5):
        x0 = 18 + idx * 36 + (seed % 7)
        draw.line((x0, 10, x0 + 18, 32), fill=(25, 25, 35), width=2)
    return im


class SchoolLearningStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "school_learning"
        self.store = SchoolLearningStore(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_supports_50_students_deletion_and_rejects_unsafe_ids(self) -> None:
        created = [
            self.store.create_writer(f"תלמיד שיעור א {idx}")
            for idx in range(1, 51)
        ]
        self.assertEqual(len( {p.writer_id for p in created} ), 50)
        reloaded = SchoolLearningStore(self.root)
        self.assertEqual(len(reloaded.list_writers()), 50)

        # Duplicate student name is rejected so two students with the same name
        # are never silently merged into one personal adapter
        with self.assertRaises(ValueError):
            self.store.create_writer("תלמיד שיעור א 2")

        # Deleting one student removes only that student
        self.store.delete_writer(created[0].writer_id)
        self.assertEqual(len(self.store.list_writers()), 49)
        self.assertIsNone(self.store.get_writer(created[0].writer_id))

        with self.assertRaises(ValueError):
            self.store.create_writer("רע", writer_id="../escape")
        with self.assertRaises(ValueError):
            self.store.writer_dir("../../etc")

    def test_strictly_separates_draft_uncertain_and_verified_lines(self) -> None:
        prof = self.store.create_writer("יוסף כהן")
        crop = _make_line_image()

        # Cannot claim verified without explicit exact + pre-grammar flags
        with self.assertRaises(ValueError):
            self.store.record_verified_lines(
                prof.writer_id,
                "notebook_p1.png",
                [
                    VerifiedLineInput(
                        crop_image=crop,
                        diplomatic_text="שלום עולם",
                        page_number=1,
                        line_index=0,
                        verified_exact_as_written=False,
                        grammar_unedited_confirmed=True,
                    )
                ],
            )
        with self.assertRaises(ValueError):
            self.store.record_verified_lines(
                prof.writer_id,
                "notebook_p1.png",
                [
                    VerifiedLineInput(
                        crop_image=crop,
                        diplomatic_text="שלום עולם",
                        page_number=1,
                        line_index=0,
                        verified_exact_as_written=True,
                        grammar_unedited_confirmed=False,
                    )
                ],
            )
        # Uncertainty marker '[?]' can NEVER be marked verified
        with self.assertRaises(ValueError):
            self.store.record_reviewed_lines(
                prof.writer_id,
                "notebook_p1.png",
                [
                    VerifiedLineInput(
                        crop_image=crop,
                        diplomatic_text="שלום [?] עולם",
                        page_number=1,
                        line_index=0,
                        review_status=STATUS_VERIFIED,
                        verified_exact_as_written=True,
                        grammar_unedited_confirmed=True,
                    )
                ],
            )

        # Draft (not_reviewed), uncertain, and skipped lines save locally for the user
        # without EVER entering training samples!
        doc_path = Path(self._tmp.name) / "draft_page.png"
        crop.save(doc_path)
        self.store.record_reviewed_lines(
            prof.writer_id,
            doc_path,
            [
                VerifiedLineInput(
                    crop_image=crop,
                    diplomatic_text="תיקון חלקי שעדיין לא אומת",
                    page_number=1,
                    line_index=0,
                    review_status=STATUS_NOT_REVIEWED,
                ),
                VerifiedLineInput(
                    crop_image=crop,
                    diplomatic_text="מילה מסופקת [?]",
                    page_number=1,
                    line_index=1,
                    review_status=STATUS_UNCERTAIN,
                ),
                VerifiedLineInput(
                    crop_image=crop,
                    diplomatic_text="שורה מחוקה",
                    page_number=1,
                    line_index=2,
                    review_status=STATUS_SKIPPED,
                ),
            ],
        )
        # Zero verified training samples!
        self.assertEqual(self.store.list_writer_samples(prof.writer_id), [])
        self.assertEqual(self.store.school_summary()["verified_lines_count"], 0)
        self.assertEqual(self.store.school_summary()["uncertain_lines_count"], 1)
        self.assertEqual(self.store.school_summary()["draft_lines_count"], 1)

        # Yet local document reload restores all 3 lines so user work is preserved!
        doc_map = self.store.list_document_lines(prof.writer_id, doc_path)
        self.assertEqual(len(doc_map), 3)
        self.assertEqual(doc_map[(1, 0)].review_status, STATUS_NOT_REVIEWED)
        self.assertEqual(doc_map[(1, 1)].review_status, STATUS_UNCERTAIN)

    def test_provenance_history_anonymized_online_export_and_backup_restore(
        self,
    ) -> None:
        s1 = self.store.create_writer("דוד לוי")
        s2 = self.store.create_writer("משה כץ")

        saved1 = self.store.record_verified_lines(
            s1.writer_id,
            "/tmp/private_path_david_notebook.png",
            [
                VerifiedLineInput(
                    crop_image=_make_line_image(seed=1),
                    diplomatic_text="אמר רבא הלכתא כוותיה דרב נחמן",
                    page_number=1,
                    line_index=0,
                    box=(10, 20, 200, 40),
                    page_size=(1200, 1600),
                    ocr_text="אמר רכא הלכתא כוותיה דרכ נחמן",
                    ocr_confidence=0.78,
                    engine_name="Mishkefet",
                    engine_version="v1",
                    model_id="mishkefet-v1",
                    model_sha256="abc123",
                    preprocessing={"page_enhancement_enabled": True, "render_dpi": 300},
                    review_status=STATUS_VERIFIED,
                    verified_exact_as_written=True,
                    grammar_unedited_confirmed=True,
                ),
            ],
        )
        sample_id = saved1[0].sample_id

        # Simulate cached backbone feature file
        feat_dir = self.store.writer_dir(s1.writer_id) / "features"
        feat_dir.mkdir(parents=True, exist_ok=True)
        stale_feat_same_txt = feat_dir / f"{sample_id}--same-text.npz"
        stale_feat_same_txt.write_bytes(b"fake")

        # Re-saving EVEN WITH UNCHANGED diplomatic_text invalidates cached features
        # because the crop image was overwritten
        self.store.record_verified_lines(
            s1.writer_id,
            "/tmp/private_path_david_notebook.png",
            [
                VerifiedLineInput(
                    crop_image=_make_line_image(seed=9),
                    diplomatic_text="אמר רבא הלכתא כוותיה דרב נחמן",
                    page_number=1,
                    line_index=0,
                    review_status=STATUS_VERIFIED,
                    verified_exact_as_written=True,
                    grammar_unedited_confirmed=True,
                ),
            ],
        )
        self.assertFalse(stale_feat_same_txt.exists())

        stale_feat = feat_dir / f"{sample_id}--deadbeef1234.npz"
        stale_feat.write_bytes(b"fake")

        # Update line text -> invalidates feature cache & appends revision audit entry
        self.store.record_verified_lines(
            s1.writer_id,
            "/tmp/private_path_david_notebook.png",
            [
                VerifiedLineInput(
                    crop_image=_make_line_image(seed=2),
                    diplomatic_text="אמר רבא הלכתא כוותיה דרב יוסף",
                    page_number=1,
                    line_index=0,
                    review_status=STATUS_VERIFIED,
                    verified_exact_as_written=True,
                    grammar_unedited_confirmed=True,
                ),
            ],
        )
        self.assertFalse(stale_feat.exists())
        history = self.store.get_line_history(sample_id)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].old_text, "אמר רכא הלכתא כוותיה דרכ נחמן")
        self.assertEqual(history[1].new_text, "אמר רבא הלכתא כוותיה דרב יוסף")

        # Student 2 adds a verified line + an uncertain line
        self.store.record_reviewed_lines(
            s2.writer_id,
            "/tmp/moshe_page2.png",
            [
                VerifiedLineInput(
                    crop_image=_make_line_image(seed=3),
                    diplomatic_text='ובשו"ת מהרשד"ם סימן קכ"ד ביאר הסוגיא',
                    page_number=2,
                    line_index=1,
                    review_status=STATUS_VERIFIED,
                    verified_exact_as_written=True,
                    grammar_unedited_confirmed=True,
                ),
                VerifiedLineInput(
                    crop_image=_make_line_image(seed=4),
                    diplomatic_text="שורה מסופקת שלא תצא לאימון",
                    page_number=2,
                    line_index=2,
                    review_status=STATUS_UNCERTAIN,
                ),
            ],
        )

        # Online export ZIP: strictly verified-only AND anonymized by default!
        zip_out = Path(self._tmp.name) / "online_export.zip"
        self.store.export_online_training_bundle_zip(zip_out, anonymize_writers=True)
        with zipfile.ZipFile(zip_out, "r") as zf:
            names = set(zf.namelist())
            self.assertIn("train.jsonl", names)
            self.assertIn("val.jsonl", names)
            self.assertIn("metadata.jsonl", names)
            self.assertIn("load_dataset_example.py", names)
            raw_meta = zf.read("metadata.jsonl").decode("utf-8")
            # Private student names and OS filenames are stripped!
            self.assertNotIn("דוד לוי", raw_meta)
            self.assertNotIn("משה כץ", raw_meta)
            self.assertNotIn("private_path_david", raw_meta)
            # Uncertain line is strictly excluded!
            self.assertNotIn("שורה מסופקת", raw_meta)
            rows = [json.loads(ln) for ln in raw_meta.splitlines() if ln.strip()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["engine_name"], "Mishkefet")

        # Full SQLite backup & restore (plus tamper detection)
        backup_zip = Path(self._tmp.name) / "backup.zip"
        self.store.backup_database_zip(backup_zip)

        restored_dir = Path(self._tmp.name) / "restored"
        restored = SchoolLearningStore(restored_dir)
        restored.restore_database_zip(backup_zip)
        self.assertEqual(len(restored.list_writers()), 2)
        self.assertEqual(restored.school_summary()["verified_lines_count"], 2)
        self.assertEqual(len(restored.get_line_history(sample_id)), 2)

        # Tampered backup archive is rejected
        tampered_zip = Path(self._tmp.name) / "tampered.zip"
        with zipfile.ZipFile(backup_zip, "r") as zin, zipfile.ZipFile(
            tampered_zip, "w"
        ) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename.endswith(".png"):
                    data = data + b"corrupt"
                zout.writestr(item, data)
        with self.assertRaises(ValueError):
            SchoolLearningStore(Path(self._tmp.name) / "bad").restore_database_zip(
                tampered_zip
            )

    def test_crop_line_and_vocab_token_extraction(self) -> None:
        page = Image.new("RGB", (600, 800), (255, 255, 255))
        crop = crop_line_from_page(page, (50, 100, 300, 40), pad_x=4, pad_y=4)
        self.assertEqual(crop.size, (308, 48))
        tokens = extract_school_vocab_tokens("עיין ברשב״א דף כ״ג ע״א [?] א")
        self.assertIn('ברשב"א', tokens)
        self.assertNotIn("א", tokens)


class OptInVocabAndDefaultEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.learn_dir = Path(self._tmp.name) / "learning"
        self.store = SchoolLearningStore(self.learn_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_shared_vocab_is_opt_in_and_requires_explicit_admin_approval(self) -> None:
        school_term = "שמעתתין"
        student_typo = "הלחתא"  # Stage-A student typo that must NOT auto-enter spellcheck!

        with mock.patch.dict(
            os.environ, {"HEBREW_WORKBENCH_LEARNING_DIR": str(self.learn_dir)}
        ):
            mod = SpellingModule(options={"bundled": True})
            self.assertEqual(len(mod.check(school_term)), 1)

            # Default: sharing is OFF (opt-in)
            self.assertFalse(self.store.vocab_sharing_enabled())
            s1 = self.store.create_writer("תלמיד א")

            # Turn on opt-in candidate collection & record verified line with both a
            # real school term AND a student's Stage-A spelling mistake
            self.store.set_vocab_sharing_enabled(True)
            self.store.record_verified_lines(
                s1.writer_id,
                "daf1.png",
                [
                    VerifiedLineInput(
                        crop_image=_make_line_image(),
                        diplomatic_text=f"עסקנו ב{school_term} {school_term} וכתב {student_typo}",
                        page_number=1,
                        line_index=0,
                        review_status=STATUS_VERIFIED,
                        verified_exact_as_written=True,
                        grammar_unedited_confirmed=True,
                    )
                ],
            )

            # Candidates are PENDING ONLY — neither term nor typo was auto-injected!
            self.assertEqual(self.store.load_shared_vocab_counts(), {})
            pending_terms = {
                e.term for e in self.store.list_vocab_terms(status=VOCAB_PENDING)
            }
            self.assertIn(school_term, pending_terms)
            self.assertEqual(len(mod.check(school_term)), 1)
            self.assertEqual(len(mod.check(student_typo)), 1)

            # Administrator approves ONLY 'שמעתתין' and rejects student's typo 'הלחתא'
            self.store.approve_vocab_term(school_term, note="Aramaic yeshiva term")
            self.store.reject_vocab_term(student_typo)

            self.assertIn(school_term, self.store.load_shared_vocab_counts())
            self.assertNotIn(student_typo, self.store.load_shared_vocab_counts())
            self.assertEqual(mod.check(school_term), [])
            # Student typo is STILL caught in Stage B!
            self.assertEqual(len(mod.check(student_typo)), 1)

            # Administrator can also remove an approved word at any time
            self.store.remove_vocab_term(school_term)
            self.assertEqual(self.store.load_shared_vocab_counts(), {})
            self.assertEqual(len(mod.check(school_term)), 1)

            # Re-approve for LM word-prior check
            self.store.approve_vocab_term(school_term)

        base_word_data = {
            "oov_logprob": -12.0,
            "prefix_discount": -1.5,
            "counts": {"שלום": 10},
            "total": 10,
        }
        base_char_data = {
            "order": 3,
            "backoff": 0.4,
            "total": 100,
            "counts": [{}, {}, {}],
        }

        def _fake_load_data(_folder: Path, identifier: str) -> dict:
            if identifier == "mishkefet-char-lm":
                return dict(base_char_data)
            return {
                "oov_logprob": base_word_data["oov_logprob"],
                "prefix_discount": base_word_data["prefix_discount"],
                "counts": dict(base_word_data["counts"]),
                "total": base_word_data["total"],
            }

        with mock.patch(
            "hebrew_workbench.engine.mishkefet_decoding._load_data",
            side_effect=_fake_load_data,
        ):
            _, word_lm = load_language_models(
                Path(self._tmp.name), learning_dir=self.learn_dir
            )
        self.assertIsInstance(word_lm, WordUnigramLM)
        self.assertGreater(word_lm.counts.get(school_term, 0), 0)
        self.assertNotIn(school_term, base_word_data["counts"])

    def test_mishkefet_is_preferred_by_default_when_installed_unless_user_chose_kraken(
        self,
    ) -> None:
        class _DummyKraken:
            name = "kraken (local)"

            def available(self) -> bool:
                return True

        class _DummyMishkefet:
            name = "Mishkefet (Hebrew handwriting, worker)"

            def available(self) -> bool:
                return True

        manifests = [
            PluginManifest(
                id="kraken-worker",
                name="Kraken",
                version="1.0.0",
                kind=KIND_OCR,
                entry="x:K",
                builtin=True,
            ),
            PluginManifest(
                id="mishkefet-worker",
                name="Mishkefet",
                version="1.0.0",
                kind=KIND_OCR,
                entry="x:M",
                builtin=True,
            ),
        ]
        plugins_root = Path(self._tmp.name) / "plugins"

        def _fake_load_plugin(manifest: PluginManifest, _paths, _options) -> Plugin:
            obj = (
                _DummyKraken()
                if manifest.id == "kraken-worker"
                else _DummyMishkefet()
            )
            return Plugin(manifest=manifest, object=obj)

        with mock.patch(
            "hebrew_workbench.plugins.registry.BUILTIN_MANIFESTS", manifests
        ), mock.patch(
            "hebrew_workbench.plugins.registry.load_plugin",
            side_effect=_fake_load_plugin,
        ):
            reg = PluginRegistry(root=plugins_root)
            active = reg.active(KIND_OCR)
            assert active is not None
            self.assertEqual(active.id, "mishkefet-worker")

            reg.set_active(KIND_OCR, "kraken-worker")
            active_explicit = reg.active(KIND_OCR)
            assert active_explicit is not None
            self.assertEqual(active_explicit.id, "kraken-worker")

    def test_project_round_trips_writer_diplomatic_text_and_recognized_pages(
        self,
    ) -> None:
        proj = Project()
        doc_file = Path(self._tmp.name) / "page1.png"
        _make_line_image().save(doc_file)
        entry = DocumentEntry(
            path=str(doc_file),
            transcription="שלום עולם מתוקן",
            original_transcription="שלום עולם",
            diplomatic_transcription="שלום עולם",
            writer_id="yosef-cohen",
            recognized_pages=[
                {
                    "number": 1,
                    "lines": [
                        {
                            "text": "שלום עולם",
                            "confidence": 0.91,
                            "box": [12.0, 24.0, 180.0, 36.0],
                        }
                    ],
                }
            ],
        )
        proj.documents.append(entry)
        proj_path = Path(self._tmp.name) / "school.hwproj"
        proj.save(proj_path)

        loaded = Project.load(proj_path)
        d0 = loaded.documents[0]
        self.assertEqual(d0.writer_id, "yosef-cohen")
        self.assertEqual(d0.diplomatic_transcription, "שלום עולם")
        self.assertEqual(
            d0.recognized_pages[0]["lines"][0]["box"], [12.0, 24.0, 180.0, 36.0]
        )

    def test_honest_insufficient_evidence_for_small_sample_and_general_profile(
        self,
    ) -> None:
        from hebrew_workbench.engine import writer_adaptation

        # General / Unknown profile uses Base Model
        rep_gen = writer_adaptation.run_writer_training(
            "", store_root=self.learn_dir
        )
        self.assertFalse(rep_gen.accepted)
        self.assertEqual(rep_gen.status, "general_profile")

        # < 8 verified lines reports insufficient_evidence rather than claiming improvement
        s1 = self.store.create_writer("תלמיד חדש")
        self.store.record_verified_lines(
            s1.writer_id,
            "short.png",
            [
                VerifiedLineInput(
                    crop_image=_make_line_image(seed=i),
                    diplomatic_text=f"שורה קצרה מספר {i}",
                    page_number=1,
                    line_index=i,
                    review_status=STATUS_VERIFIED,
                    verified_exact_as_written=True,
                    grammar_unedited_confirmed=True,
                )
                for i in range(4)
            ],
        )
        rep_small = writer_adaptation.run_writer_training(
            s1.writer_id, store_root=self.learn_dir
        )
        self.assertFalse(rep_small.accepted)
        self.assertEqual(rep_small.status, "insufficient_evidence")


@unittest.skipUnless(HAS_NUMPY, "Requires numpy for CTC math & head tests")
class WriterAdaptationCTCTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.learn_dir = Path(self._tmp.name) / "learning"
        self.store = SchoolLearningStore(self.learn_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_ctc_loss_grad_matches_finite_differences_and_handles_impossible_lengths(
        self,
    ) -> None:
        from hebrew_workbench.engine.writer_adaptation import ctc_loss_grad

        rng = np.random.default_rng(42)
        logits = rng.normal(0.0, 0.8, size=(9, 6)).astype(np.float32)
        label = [2, 4, 4, 1]
        loss, grad = ctc_loss_grad(logits, label)
        self.assertGreater(loss, 0.0)

        eps = 1e-4
        for t in (0, 4, 8):
            for c in range(6):
                lp = logits.astype(np.float64).copy()
                lm = logits.astype(np.float64).copy()
                lp[t, c] += eps
                lm[t, c] -= eps
                fp, _ = ctc_loss_grad(lp, label)
                fm, _ = ctc_loss_grad(lm, label)
                self.assertAlmostEqual(
                    float(grad[t, c]), float((fp - fm) / (2.0 * eps)), places=4
                )

        imp_loss, imp_grad = ctc_loss_grad(
            np.zeros((2, 5), dtype=np.float32), [2, 2, 2]
        )
        self.assertEqual(imp_loss, 0.0)
        self.assertTrue(np.all(imp_grad == 0.0))

    def test_page_grouped_holdout_convergence_version_history_and_one_click_rollback(
        self,
    ) -> None:
        from hebrew_workbench.engine.vendor.hebocr.charset import (
            BASE_PUNCT,
            DIGITS,
            HEBREW_LETTERS,
            LATIN,
            Charset,
        )
        from hebrew_workbench.engine.writer_adaptation import (
            AdaptConfig,
            load_writer_head_npz,
            train_writer_profile_in_process,
        )

        charset = Charset(
            [""] + list(HEBREW_LETTERS + BASE_PUNCT + DIGITS + LATIN)
        )
        vocab_size = charset.n_classes
        feat_dim = 512
        rng = np.random.default_rng(7)

        protos = rng.normal(0.0, 1.0, size=(vocab_size, feat_dim)).astype(
            np.float32
        )
        protos /= np.linalg.norm(protos, axis=-1, keepdims=True) + 1e-8
        w0 = (0.35 * protos).astype(np.float32)
        b0 = np.zeros((vocab_size,), dtype=np.float32)
        b0[0] = 2.5

        id_bet = charset.encode("ב")[0]
        id_dalet = charset.encode("ד")[0]
        id_resh = charset.encode("ר")[0]
        id_vav = charset.encode("ו")[0]
        student_bet_dir = 0.85 * protos[id_resh] + 0.35 * protos[id_bet]
        student_bet_dir /= np.linalg.norm(student_bet_dir)
        student_dalet_dir = 0.85 * protos[id_vav] + 0.35 * protos[id_dalet]
        student_dalet_dir /= np.linalg.norm(student_dalet_dir)
        scale = float(np.sqrt(feat_dim))

        def _synth_student_features(text: str) -> np.ndarray:
            ids = charset.encode(text)
            steps: list[np.ndarray] = []
            for tok in ids:
                steps.append((scale * protos[0]).astype(np.float32))
                if tok == id_bet:
                    vec = scale * student_bet_dir
                elif tok == id_dalet:
                    vec = scale * student_dalet_dir
                else:
                    vec = scale * protos[tok]
                vec = vec + rng.normal(0.0, 0.08, size=(feat_dim,)).astype(
                    np.float32
                )
                steps.append(vec.astype(np.float32))
            steps.append((scale * protos[0]).astype(np.float32))
            return np.stack(steps, axis=0)

        class _FakeRecognizer:
            def __init__(self, *_a, **_kw) -> None:
                self.charset = charset

            def base_head_numpy(self):
                return w0.copy(), b0.copy()

            def extract_line_features(self, views):
                return []

        student = self.store.create_writer("שמעון ברקוביץ")
        phrases = [
            "בדבר הלכה ברורה",
            "בית דין צדק",
            "דברי רבא בבא בתרא",
            "בדק בדברי הבית",
            "דין ברור בדף",
            "בדיקת דברי רב",
            "ברכה בדבר תורה",
            "דבר ברור בבית",
            "בבא בתרא דף בד",
            "דברי הבית ברורים",
        ]
        # Record across 2 separate pages (7 lines on page 1, 3 lines on page 2)
        p1_inputs = [
            VerifiedLineInput(
                crop_image=_make_line_image(seed=i),
                diplomatic_text=phrases[i],
                page_number=1,
                line_index=i,
                review_status=STATUS_VERIFIED,
                verified_exact_as_written=True,
                grammar_unedited_confirmed=True,
            )
            for i in range(7)
        ]
        p2_inputs = [
            VerifiedLineInput(
                crop_image=_make_line_image(seed=i),
                diplomatic_text=phrases[i],
                page_number=2,
                line_index=i - 7,
                review_status=STATUS_VERIFIED,
                verified_exact_as_written=True,
                grammar_unedited_confirmed=True,
            )
            for i in range(7, 10)
        ]
        saved = self.store.record_verified_lines(
            student.writer_id, "notebook1.png", p1_inputs
        ) + self.store.record_verified_lines(
            student.writer_id, "notebook1.png", p2_inputs
        )

        dummy_model = Path(self._tmp.name) / "mishkefet.pt"
        dummy_model.write_bytes(b"fake-weights")
        model_sha = "1234567890abcdef" * 4

        feat_dir = self.store.writer_dir(student.writer_id) / "features"
        feat_dir.mkdir(parents=True, exist_ok=True)
        for idx, smp in enumerate(saved):
            np.savez(
                feat_dir / f"{smp.sample_id}--{model_sha[:12]}.npz",
                plain=_synth_student_features(phrases[idx]).astype(np.float16),
                n_aug=np.asarray([0], dtype=np.int32),
            )

        fake_art = mock.Mock(sha256=model_sha)
        with mock.patch(
            "hebrew_workbench.engine.models.MODEL_ARTIFACTS",
            {"mishkefet-v1": fake_art},
        ), mock.patch(
            "hebrew_workbench.engine.models.verify_file", return_value=None
        ):
            report = train_writer_profile_in_process(
                student.writer_id,
                dummy_model,
                store_root=self.learn_dir,
                cfg=AdaptConfig(steps=80, aug_scales=()),
                recognizer_factory=_FakeRecognizer,
            )

        self.assertTrue(report.accepted, msg=report.message)
        self.assertEqual(report.status, "accepted")
        # Held-out is strictly page 2 (3 lines), disjoint from page 1 (7 lines)!
        self.assertEqual(report.train_samples, 7)
        self.assertEqual(report.held_out_samples, 3)
        assert report.held_out_cer_before is not None
        assert report.held_out_cer_after is not None
        self.assertLess(report.held_out_cer_after, report.held_out_cer_before)
        self.assertLess(report.held_out_cer_after, 0.05)

        versions = self.store.list_adapter_versions(student.writer_id)
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0].round_number, 1)
        self.assertTrue(versions[0].is_active)

        active_head = self.store.active_head_path(
            student.writer_id, model_sha256=model_sha
        )
        assert active_head is not None
        w_adapted, _ = load_writer_head_npz(active_head)
        self.assertEqual(w_adapted.shape, (vocab_size, feat_dim))

        # One-click rollback to Base Model (round 0)
        rolled = self.store.rollback_writer_adapter(
            student.writer_id, target_round=0
        )
        self.assertEqual(rolled.active_round, 0)
        self.assertIsNone(
            self.store.active_head_path(student.writer_id, model_sha256=model_sha)
        )
        # Re-activating round 1 from preserved version history works in one click!
        restored = self.store.rollback_writer_adapter(
            student.writer_id, target_round=1
        )
        self.assertEqual(restored.active_round, 1)
        self.assertIsNotNone(
            self.store.active_head_path(student.writer_id, model_sha256=model_sha)
        )

    def test_heldout_validation_gate_rejects_non_improving_or_corrupted_updates(
        self,
    ) -> None:
        from hebrew_workbench.engine.vendor.hebocr.charset import (
            BASE_PUNCT,
            DIGITS,
            HEBREW_LETTERS,
            LATIN,
            Charset,
        )
        from hebrew_workbench.engine.writer_adaptation import (
            AdaptConfig,
            train_writer_profile_in_process,
        )

        charset = Charset(
            [""] + list(HEBREW_LETTERS + BASE_PUNCT + DIGITS + LATIN)
        )
        vocab_size = charset.n_classes
        feat_dim = 512
        rng = np.random.default_rng(19)
        protos = rng.normal(0.0, 1.0, size=(vocab_size, feat_dim)).astype(
            np.float32
        )
        protos /= np.linalg.norm(protos, axis=-1, keepdims=True) + 1e-8
        w0 = (0.35 * protos).astype(np.float32)
        b0 = np.zeros((vocab_size,), dtype=np.float32)
        b0[0] = 2.5
        scale = float(np.sqrt(feat_dim))

        def _clean_features(text: str) -> np.ndarray:
            rows = [(scale * protos[0]).astype(np.float32)]
            for tok in charset.encode(text):
                rows.append((scale * protos[tok]).astype(np.float32))
                rows.append((scale * protos[0]).astype(np.float32))
            return np.stack(rows, axis=0)

        class _FakeRecognizer:
            def __init__(self, *_a, **_kw) -> None:
                self.charset = charset

            def base_head_numpy(self):
                return w0.copy(), b0.copy()

            def extract_line_features(self, views):
                return []

        student = self.store.create_writer("בדיקת הגנה")
        # Page 1 (7 train lines) has poisoned labels; Page 2 (3 held-out lines) has truthful labels
        p1 = [
            VerifiedLineInput(
                crop_image=_make_line_image(seed=i),
                diplomatic_text="תתתתתתתתת",
                page_number=1,
                line_index=i,
                review_status=STATUS_VERIFIED,
                verified_exact_as_written=True,
                grammar_unedited_confirmed=True,
            )
            for i in range(7)
        ]
        p2 = [
            VerifiedLineInput(
                crop_image=_make_line_image(seed=i + 7),
                diplomatic_text="שלום עולם",
                page_number=2,
                line_index=i,
                review_status=STATUS_VERIFIED,
                verified_exact_as_written=True,
                grammar_unedited_confirmed=True,
            )
            for i in range(3)
        ]
        saved = self.store.record_verified_lines(
            student.writer_id, "gate.png", p1
        ) + self.store.record_verified_lines(student.writer_id, "gate.png", p2)

        dummy_model = Path(self._tmp.name) / "mishkefet.pt"
        dummy_model.write_bytes(b"fake-weights")
        model_sha = "abcdef1234567890" * 4
        feat_dir = self.store.writer_dir(student.writer_id) / "features"
        feat_dir.mkdir(parents=True, exist_ok=True)
        for smp in saved:
            np.savez(
                feat_dir / f"{smp.sample_id}--{model_sha[:12]}.npz",
                plain=_clean_features("שלום עולם").astype(np.float16),
                n_aug=np.asarray([0], dtype=np.int32),
            )

        fake_art = mock.Mock(sha256=model_sha)
        with mock.patch(
            "hebrew_workbench.engine.models.MODEL_ARTIFACTS",
            {"mishkefet-v1": fake_art},
        ), mock.patch(
            "hebrew_workbench.engine.models.verify_file", return_value=None
        ):
            report = train_writer_profile_in_process(
                student.writer_id,
                dummy_model,
                store_root=self.learn_dir,
                cfg=AdaptConfig(steps=80, aug_scales=()),
                recognizer_factory=_FakeRecognizer,
            )
        self.assertFalse(report.accepted)
        self.assertEqual(report.status, "kept_previous")
        self.assertFalse(self.store.writer_head_path(student.writer_id).exists())


if __name__ == "__main__":
    unittest.main()
