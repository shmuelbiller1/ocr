"""Tests for 50-student school learning store, CTC-head adaptation, and shared vocab."""

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

    def test_supports_50_student_profiles_and_rejects_unsafe_ids(self) -> None:
        created_ids = set()
        for idx in range(1, 51):
            prof = self.store.create_writer(f"תלמיד שיעור א {idx}")
            created_ids.add(prof.writer_id)
        self.assertEqual(len(created_ids), 50)
        reloaded = SchoolLearningStore(self.root)
        self.assertEqual(len(reloaded.list_writers()), 50)

        with self.assertRaises(ValueError):
            self.store.create_writer("רע", writer_id="../escape")
        with self.assertRaises(ValueError):
            self.store.writer_dir("../../etc")

    def test_strictly_rejects_unverified_or_grammar_edited_lines(self) -> None:
        prof = self.store.create_writer("יוסף כהן")
        crop = _make_line_image()

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

        self.assertEqual(self.store.list_writer_samples(prof.writer_id), [])
        self.assertEqual(self.store.school_summary()["verified_lines_count"], 0)

    def test_deduplicates_reverified_lines_invalidates_feature_cache_and_exports_zip(
        self,
    ) -> None:
        s1 = self.store.create_writer("דוד לוי")
        s2 = self.store.create_writer("משה כץ")

        saved1 = self.store.record_verified_lines(
            s1.writer_id,
            "/tmp/shiur_bava_batra.png",
            [
                VerifiedLineInput(
                    crop_image=_make_line_image(seed=1),
                    diplomatic_text="אמר רבא הלכתא כוותיה דרב נחמן",
                    page_number=1,
                    line_index=0,
                    box=(10, 20, 200, 40),
                    ocr_text="אמר רכא הלכתא כוותיה דרכ נחמן",
                    ocr_confidence=0.78,
                    verified_exact_as_written=True,
                    grammar_unedited_confirmed=True,
                ),
            ],
        )
        self.assertEqual(len(saved1), 1)
        sample_id = saved1[0].sample_id

        # Simulate cached backbone feature file for this sample
        feat_dir = self.store.writer_dir(s1.writer_id) / "features"
        feat_dir.mkdir(parents=True, exist_ok=True)
        stale_feat = feat_dir / f"{sample_id}--deadbeef1234.npz"
        stale_feat.write_bytes(b"fake")
        self.assertTrue(stale_feat.is_file())

        # Re-verifying the exact same page+line updates in place & drops stale cache
        self.store.record_verified_lines(
            s1.writer_id,
            "/tmp/shiur_bava_batra.png",
            [
                VerifiedLineInput(
                    crop_image=_make_line_image(seed=2),
                    diplomatic_text="אמר רבא הלכתא כוותיה דרב יוסף",
                    page_number=1,
                    line_index=0,
                    verified_exact_as_written=True,
                    grammar_unedited_confirmed=True,
                ),
            ],
        )
        self.assertFalse(stale_feat.exists())
        samples_s1 = self.store.list_writer_samples(s1.writer_id)
        self.assertEqual(len(samples_s1), 1)
        self.assertEqual(
            samples_s1[0].diplomatic_text, "אמר רבא הלכתא כוותיה דרב יוסף"
        )

        # Second student contributes to shared school pool
        self.store.record_verified_lines(
            s2.writer_id,
            "/tmp/notes_page2.png",
            [
                VerifiedLineInput(
                    crop_image=_make_line_image(seed=3),
                    diplomatic_text="ובשו״ת מהרשד״ם סימן קכ״ד ביאר הסוגיא",
                    page_number=2,
                    line_index=1,
                    verified_exact_as_written=True,
                    grammar_unedited_confirmed=True,
                ),
            ],
        )

        summary = self.store.school_summary()
        self.assertEqual(summary["writers_count"], 2)
        self.assertEqual(summary["verified_lines_count"], 2)
        vocab = self.store.load_shared_vocab_counts()
        self.assertIn("הלכתא", vocab)
        self.assertIn('מהרשד"ם', vocab)
        self.assertEqual(vocab.get("כוותיה"), 1)

        zip_out = Path(self._tmp.name) / "school_export.zip"
        self.store.export_school_dataset_zip(zip_out)
        self.assertTrue(zip_out.is_file())
        with zipfile.ZipFile(zip_out, "r") as zf:
            names = set(zf.namelist())
            self.assertIn("README.txt", names)
            self.assertIn("writers.json", names)
            self.assertIn("lines.jsonl", names)
            self.assertIn("shared_vocab.json", names)
            lines_rows = [
                json.loads(ln)
                for ln in zf.read("lines.jsonl").decode("utf-8").splitlines()
                if ln.strip()
            ]
            self.assertEqual(len(lines_rows), 2)

    def test_crop_line_and_vocab_token_extraction(self) -> None:
        page = Image.new("RGB", (600, 800), (255, 255, 255))
        crop = crop_line_from_page(page, (50, 100, 300, 40), pad_x=4, pad_y=4)
        self.assertEqual(crop.size, (308, 48))
        tokens = extract_school_vocab_tokens("עיין ברשב״א דף כ״ג ע״א [?] א")
        self.assertIn('ברשב"א', tokens)
        self.assertNotIn("א", tokens)


class SharedVocabAndDefaultEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.learn_dir = Path(self._tmp.name) / "learning"
        self.store = SchoolLearningStore(self.learn_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_shared_school_vocab_immediately_helps_other_students_in_spelling_and_lm(
        self,
    ) -> None:
        rare_school_word = "שמעתתין"
        # Before school verification, rare coined school word is flagged
        with mock.patch.dict(
            os.environ, {"HEBREW_WORKBENCH_LEARNING_DIR": str(self.learn_dir)}
        ):
            mod_before = SpellingModule(options={"bundled": True})
            props_before = mod_before.check(rare_school_word)
            self.assertEqual(len(props_before), 1)

            # Student 1 verifies a handwritten line containing this term
            s1 = self.store.create_writer("תלמיד א")
            self.store.record_verified_lines(
                s1.writer_id,
                "daf1.png",
                [
                    VerifiedLineInput(
                        crop_image=_make_line_image(),
                        diplomatic_text=f"למדנו עם {rare_school_word} בבית המדרש",
                        page_number=1,
                        line_index=0,
                        verified_exact_as_written=True,
                        grammar_unedited_confirmed=True,
                    )
                ],
            )

            # Student 2 immediately gets zero false-positive flags on that school word
            mod_after = SpellingModule(options={"bundled": True})
            self.assertEqual(mod_after.check(rare_school_word), [])

        # Also verify in-memory WordUnigramLM boost in load_language_models
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
                Path(self._tmp.name),
                learning_dir=self.learn_dir,
            )
        self.assertIsInstance(word_lm, WordUnigramLM)
        assert word_lm is not None
        self.assertGreater(word_lm.counts.get(rare_school_word, 0), 0)
        # Underlying source dict was never mutated
        self.assertNotIn(rare_school_word, base_word_data["counts"])

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
            self.assertIsNotNone(active)
            assert active is not None
            self.assertEqual(active.id, "mishkefet-worker")

            # Explicit user selection of Kraken is still respected
            reg.set_active(KIND_OCR, "kraken-worker")
            active_explicit = reg.active(KIND_OCR)
            assert active_explicit is not None
            self.assertEqual(active_explicit.id, "kraken-worker")

            # Active student writer ID persists across reloads
            reg.set_active_writer_id("student-01")
            reg2 = PluginRegistry(root=plugins_root)
            self.assertEqual(reg2.active_writer_id, "student-01")

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
        self.assertEqual(len(loaded.documents), 1)
        d0 = loaded.documents[0]
        self.assertEqual(d0.writer_id, "yosef-cohen")
        self.assertEqual(d0.diplomatic_transcription, "שלום עולם")
        self.assertEqual(len(d0.recognized_pages), 1)
        self.assertEqual(
            d0.recognized_pages[0]["lines"][0]["box"], [12.0, 24.0, 180.0, 36.0]
        )

    def test_graceful_fallback_when_numpy_is_missing_in_gui_process(self) -> None:
        from hebrew_workbench.engine import writer_adaptation

        s1 = self.store.create_writer("תלמיד")
        dummy_model = Path(self._tmp.name) / "fake_mishkefet.pt"
        dummy_model.write_bytes(b"stub")
        with mock.patch(
            "hebrew_workbench.engine.mishkefet.mishkefet_importable",
            return_value=False,
        ), mock.patch(
            "hebrew_workbench.engine.worker.worker_path", return_value=None
        ):
            report = writer_adaptation.run_writer_training(
                s1.writer_id,
                model_path=dummy_model,
                store_root=self.learn_dir,
            )
        self.assertFalse(report.accepted)
        self.assertIn("נשמרו במאגר", report.message)


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
        label = [2, 4, 4, 1]  # includes repeated token requiring blank separation
        loss, grad = ctc_loss_grad(logits, label)
        self.assertGreater(loss, 0.0)
        self.assertEqual(grad.shape, logits.shape)

        eps = 1e-4
        for t in (0, 4, 8):
            for c in range(6):
                lp = logits.astype(np.float64).copy()
                lm = logits.astype(np.float64).copy()
                lp[t, c] += eps
                lm[t, c] -= eps
                fp, _ = ctc_loss_grad(lp, label)
                fm, _ = ctc_loss_grad(lm, label)
                num_grad = (fp - fm) / (2.0 * eps)
                self.assertAlmostEqual(
                    float(grad[t, c]), float(num_grad), places=4
                )

        # Impossible alignment (T=2 < needed=5 for [2, 2, 2]) -> zero_infinity
        imp_loss, imp_grad = ctc_loss_grad(
            np.zeros((2, 5), dtype=np.float32), [2, 2, 2]
        )
        self.assertEqual(imp_loss, 0.0)
        self.assertTrue(np.all(imp_grad == 0.0))

    def test_per_student_head_adapts_to_personal_letter_shift_and_switches_cleanly(
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

        # Realistic LayerNorm(512)-scale unit directions (||f|| ≈ sqrt(512) ≈ 22.6)
        protos = rng.normal(0.0, 1.0, size=(vocab_size, feat_dim)).astype(
            np.float32
        )
        protos /= np.linalg.norm(protos, axis=-1, keepdims=True) + 1e-8
        w0 = (0.35 * protos).astype(np.float32)
        b0 = np.zeros((vocab_size,), dtype=np.float32)
        b0[0] = 2.5

        # Student writes 'ב' in a way that looks like 'ר' to the base model,
        # and 'ד' in a way that looks like 'ו'!
        id_bet = charset.encode("ב")[0]
        id_dalet = charset.encode("ד")[0]
        id_resh = charset.encode("ר")[0]
        id_vav = charset.encode("ו")[0]
        student_bet_dir = (0.85 * protos[id_resh] + 0.35 * protos[id_bet])
        student_bet_dir /= np.linalg.norm(student_bet_dir)
        student_dalet_dir = (0.85 * protos[id_vav] + 0.35 * protos[id_dalet])
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
        inputs = []
        feats_by_line = {}
        for idx, phrase in enumerate(phrases):
            inputs.append(
                VerifiedLineInput(
                    crop_image=_make_line_image(seed=idx),
                    diplomatic_text=phrase,
                    page_number=1,
                    line_index=idx,
                    verified_exact_as_written=True,
                    grammar_unedited_confirmed=True,
                )
            )
            feats_by_line[idx] = _synth_student_features(phrase)

        saved = self.store.record_verified_lines(
            student.writer_id, "notebook1.png", inputs
        )
        dummy_model = Path(self._tmp.name) / "mishkefet.pt"
        dummy_model.write_bytes(b"fake-weights")
        model_sha = "1234567890abcdef" * 4

        feat_dir = self.store.writer_dir(student.writer_id) / "features"
        feat_dir.mkdir(parents=True, exist_ok=True)
        for smp in saved:
            np.savez(
                feat_dir / f"{smp.sample_id}--{model_sha[:12]}.npz",
                plain=feats_by_line[smp.line_index].astype(np.float16),
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
        self.assertGreater(report.train_samples, 0)
        self.assertGreater(report.held_out_samples, 0)
        assert report.held_out_cer_before is not None
        assert report.held_out_cer_after is not None
        self.assertLess(report.held_out_cer_after, report.held_out_cer_before)
        self.assertLess(report.held_out_cer_after, 0.05)

        active_head = self.store.active_head_path(
            student.writer_id, model_sha256=model_sha
        )
        self.assertIsNotNone(active_head)
        assert active_head is not None
        w_adapted, b_adapted = load_writer_head_npz(active_head)
        self.assertEqual(w_adapted.shape, (vocab_size, feat_dim))
        self.assertEqual(b_adapted.shape, (vocab_size,))
        # Adapted head fails closed if model SHA mismatches
        self.assertIsNone(
            self.store.active_head_path(
                student.writer_id, model_sha256="f" * 64
            )
        )

    def test_heldout_regression_gate_rejects_corrupted_labels(self) -> None:
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
        from hebrew_workbench.training.store import is_held_out_sample

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
        inputs = [
            VerifiedLineInput(
                crop_image=_make_line_image(seed=i),
                diplomatic_text="שלום עולם",
                page_number=1,
                line_index=i,
                verified_exact_as_written=True,
                grammar_unedited_confirmed=True,
            )
            for i in range(10)
        ]
        saved = self.store.record_verified_lines(
            student.writer_id, "test_gate.png", inputs
        )
        dummy_model = Path(self._tmp.name) / "mishkefet.pt"
        dummy_model.write_bytes(b"fake-weights")
        model_sha = "abcdef1234567890" * 4

        feat_dir = self.store.writer_dir(student.writer_id) / "features"
        feat_dir.mkdir(parents=True, exist_ok=True)

        # Corrupt NON-held-out training labels while keeping held-out features truthful
        for smp in saved:
            true_feats = _clean_features("שלום עולם")
            if not is_held_out_sample(smp.sample_id):
                self.store.record_verified_lines(
                    student.writer_id,
                    "test_gate.png",
                    [
                        VerifiedLineInput(
                            crop_image=_make_line_image(seed=smp.line_index),
                            diplomatic_text="תתתתתתתתת",
                            page_number=1,
                            line_index=smp.line_index,
                            verified_exact_as_written=True,
                            grammar_unedited_confirmed=True,
                        )
                    ],
                )
            np.savez(
                feat_dir / f"{smp.sample_id}--{model_sha[:12]}.npz",
                plain=true_feats.astype(np.float16),
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
        self.assertFalse(self.store.writer_head_path(student.writer_id).exists())


if __name__ == "__main__":
    unittest.main()
