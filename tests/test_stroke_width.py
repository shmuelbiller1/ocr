"""Tests for CPU stroke-width measurement, 6-variant operators, and UI/worker enhancement wiring."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw

from hebrew_workbench.engine.base import OCRResult, PageResult
from hebrew_workbench.engine.photocraft_audit import (
    encode_preview_png,
    resolve_page_enhancement_enabled,
)
from hebrew_workbench.engine.stroke_width import (
    HAS_STROKE_VISION,
    STROKE_VARIANTS,
    apply_stroke_variant,
    audit_inference_stroke_compensation,
    measure_stroke_width,
)
from hebrew_workbench.plugins.registry import PluginRegistry
from hebrew_workbench.plugins.settings import PluginSettings


class StrokeCompensationAuditTests(unittest.TestCase):
    def test_source_audit_confirms_no_inference_stroke_normalization(self) -> None:
        audit = audit_inference_stroke_compensation()
        mish = audit["mishkefet"]
        self.assertEqual(mish["line_height_px"], 64)
        self.assertFalse(mish["inference_calls_stroke_augment"])
        self.assertFalse(mish["inference_calls_morph_stroke_norm"])
        self.assertTrue(mish["training_only_stroke_augment_present"])
        krk = audit["kraken"]
        self.assertFalse(krk["inference_calls_morph_stroke_norm"])


@unittest.skipUnless(HAS_STROKE_VISION, "OpenCV/NumPy vision libs required")
class StrokeWidthOperatorsTests(unittest.TestCase):
    def _make_hebrew_edge_crop(self) -> Image.Image:
        import cv2
        import numpy as np

        arr = np.full((64, 190), 245, dtype=np.uint8)
        # 'ה' with a narrow 3-px top-left gap at y=18..20, x=20..24
        arr[14:18, 20:38] = 35
        arr[14:48, 34:38] = 35
        arr[21:48, 20:24] = 35
        # 'ם' with closed interior counter loop at x=60..70, y=19..43
        arr[14:18, 55:75] = 35
        arr[44:48, 55:75] = 35
        arr[14:48, 55:59] = 35
        arr[14:48, 71:75] = 35
        # Small glyphs: 'י', gershayim '"', period '.'
        arr[14:23, 90:93] = 40
        arr[14:20, 104:106] = 45
        arr[14:20, 109:111] = 45
        arr[45:48, 122:125] = 45
        # Vertical stroke with 1-px dry skip at y=30
        arr[16:30, 145:148] = 40
        arr[30, 145:148] = 225
        arr[31:48, 145:148] = 40
        # Two adjacent distinct strokes separated by 3-px inter-letter space (x=169..171)
        arr[16:48, 165:169] = 38
        arr[16:48, 172:176] = 38
        arr = cv2.GaussianBlur(arr, (3, 3), 0.55)
        return Image.fromarray(arr)

    def test_all_six_variants_preserve_antialiasing_and_hebrew_topology(self) -> None:
        import numpy as np

        crop = self._make_hebrew_edge_crop()
        orig = np.asarray(crop)
        self.assertEqual(len(STROKE_VARIANTS), 6)

        for variant in STROKE_VARIANTS:
            out_im = apply_stroke_variant(crop, variant)
            out = np.asarray(out_im)
            self.assertEqual(out.shape, orig.shape)
            m = measure_stroke_width(out, normalize_height=64)
            # Antialiased grayscale transitions remain smooth (never harsh binary)
            self.assertGreater(m.antialias_gray_ratio, 0.20, msg=variant)
            # 'ה' top-left gap stays open (>200), never turned into 'ח'
            self.assertGreater(int(out[19, 21:24].min()), 200, msg=variant)
            # 'ם' enclosed counter loop stays bright background (>235)
            self.assertGreater(float(out[25:38, 62:68].mean()), 235.0, msg=variant)
            # Inter-letter 3-px gap stays open (>195), never joining neighbors
            self.assertGreater(int(out[30, 170]), 195, msg=variant)
            # Tiny dot and gershayim are never erased (<120)
            self.assertLess(int(out[45:48, 122:125].min()), 120, msg=variant)
            self.assertLess(int(out[14:20, 104:111].min()), 120, msg=variant)

        # original and in-band adaptive_norm are 100% bit-identical to input
        self.assertTrue(
            np.array_equal(np.asarray(apply_stroke_variant(crop, "original")), orig)
        )
        self.assertTrue(
            np.array_equal(
                np.asarray(apply_stroke_variant(crop, "adaptive_norm")), orig
            )
        )

        # faint_repair darkens the 1-px dry-pen skip along the colinear vertical stroke
        repaired = np.asarray(apply_stroke_variant(crop, "faint_repair"))
        self.assertLess(int(repaired[30, 146]), int(orig[30, 146]) - 10)

    def test_adaptive_norm_thickens_ultrafine_and_thins_heavy_bleed(self) -> None:
        import cv2
        import numpy as np

        # Ultra-fine ~2.0 px stroke at H=64
        thin_arr = np.full((64, 120), 245, dtype=np.uint8)
        thin_arr[16:48, 40:41] = 35
        thin_arr[16:48, 70:71] = 35
        thin_arr = cv2.GaussianBlur(thin_arr, (3, 3), 0.35)
        thin_im = Image.fromarray(thin_arr)
        m_thin = measure_stroke_width(thin_im, normalize_height=64)
        self.assertLess(m_thin.median_sw_px, 3.05)
        adapt_thin = np.asarray(apply_stroke_variant(thin_im, "adaptive_norm"))
        # Ink darkens/widens slightly (mean pixel intensity decreases)
        self.assertLess(float(adapt_thin.mean()), float(thin_arr.mean()) - 0.08)

        # Heavy ~7.5 px marker bleed at H=64
        thick_arr = np.full((64, 120), 245, dtype=np.uint8)
        thick_arr[14:50, 35:43] = 25
        thick_arr[14:50, 70:78] = 25
        thick_arr = cv2.GaussianBlur(thick_arr, (3, 3), 0.6)
        thick_im = Image.fromarray(thick_arr)
        m_thick = measure_stroke_width(thick_im, normalize_height=64)
        self.assertGreater(m_thick.median_sw_px, 5.35)
        adapt_thick = np.asarray(apply_stroke_variant(thick_im, "adaptive_norm"))
        # Outer flanks thin gently while keeping spine dark
        self.assertGreater(float(adapt_thick.mean()), float(thick_arr.mean()) + 0.15)
        self.assertLess(int(adapt_thick[30, 39]), 60)

    def test_hebocr_preprocess_context_manager_restores_default(self) -> None:
        from hebrew_workbench.engine.vendor.hebocr.data.transforms import (
            current_inference_stroke_variant,
            inference_stroke_variant,
            preprocess,
        )

        crop = self._make_hebrew_edge_crop()
        base_t = preprocess(crop)
        self.assertEqual(current_inference_stroke_variant(), "original")
        with inference_stroke_variant("moderate_thicken"):
            self.assertEqual(current_inference_stroke_variant(), "moderate_thicken")
            thick_t = preprocess(crop)
            self.assertGreater(float(thick_t.mean()), float(base_t.mean()))
        self.assertEqual(current_inference_stroke_variant(), "original")

    def test_benchmark_stroke_width_cli_smoke(self) -> None:
        from tools.benchmark_stroke_width import main as sw_main

        with tempfile.TemporaryDirectory() as td:
            empty_models = Path(td) / "models"
            empty_models.mkdir()
            out_json = Path(td) / "sw.json"
            rc = sw_main(["--models", str(empty_models), "--output", str(out_json)])
            self.assertEqual(rc, 0)
            payload = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["memory_measurement"], "isolated_process_per_engine"
            )
            self.assertEqual(
                payload["evaluation_normalization"],
                "hebrew_workbench.benchmark.metrics.normalise",
            )
            self.assertEqual(len(payload["variants_tested"]), 6)

    def test_page_scale_and_normalized_verified_only_benchmark_helpers(self) -> None:
        import numpy as np
        from hebrew_workbench.engine.stroke_width import measure_page_stroke_width
        from tools.benchmark_stroke_width import (
            _evaluate_predictions,
            _load_verified_corpus_pages,
        )

        # Full-page multi-line synthetic image (~120 px line height)
        page_arr = np.full((520, 700), 246, dtype=np.uint8)
        for row_y in (90, 230, 370):
            page_arr[row_y : row_y + 10, 80:620] = 28
            for gx in range(100, 600, 45):
                page_arr[row_y - 35 : row_y + 45, gx : gx + 8] = 28
        page_im = Image.fromarray(page_arr)
        m_page_sw = measure_page_stroke_width(page_im)
        self.assertGreater(m_page_sw, 1.0)
        scaled = apply_stroke_variant(page_im, "mild_thicken", page_scale=True)
        self.assertEqual(scaled.size, page_im.size)

        # _evaluate_predictions normalizes niqqud, gershayim/geresh, and repeated spaces
        metrics = _evaluate_predictions(
            [("p1", "שָׁלוֹם   בצה״ל")],
            [("שלום\nבצה\"ל", ["שלום", "בצה\"ל"], [0.9], 4.2)],
        )
        self.assertEqual(metrics["macro_cer"], 0.0)
        self.assertEqual(metrics["macro_wer"], 0.0)

        # _load_verified_corpus_pages strictly excludes unverified & [?]-incomplete pages
        with tempfile.TemporaryDirectory() as td:
            cdir = Path(td)
            for idx, (txt, ver) in enumerate(
                [
                    ("שורה מאומתת מלאה", "Independent Verifier"),
                    ("שורה עם ספק [?] באמצע", "Independent Verifier"),
                    ("טיוטה לא מאומתת", ""),
                ],
                start=1,
            ):
                Image.new("RGB", (60, 40), "white").save(cdir / f"p{idx}.png")
                (cdir / f"p{idx}.txt").write_text(txt, encoding="utf-8")
            (cdir / "corpus.json").write_text(
                json.dumps(
                    {
                        "name": "Mixed Test Corpus",
                        "target": "modern_cursive",
                        "pages": [
                            {
                                "image": "p1.png",
                                "transcript": "p1.txt",
                                "verified_by": ["Independent Verifier"],
                            },
                            {
                                "image": "p2.png",
                                "transcript": "p2.txt",
                                "verified_by": ["Independent Verifier"],
                            },
                            {
                                "image": "p3.png",
                                "transcript": "p3.txt",
                                "verified_by": [],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            loaded, total_p, meas_p = _load_verified_corpus_pages(cdir)
            self.assertEqual(total_p, 3)
            self.assertEqual(meas_p, 1)
            self.assertEqual([pid for pid, _, _ in loaded], ["p1"])


def _qt_available() -> bool:
    try:
        from PySide6.QtWidgets import QApplication  # noqa: F401

        return True
    except Exception:
        return False


class PageEnhancementSettingsAndWorkerTests(unittest.TestCase):
    def test_plugin_settings_persist_page_enhancement_and_propagate_to_ocr(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "plugins"
            reg = PluginRegistry(root=root)
            self.assertTrue(reg.page_enhancement)
            mish = reg.get("mishkefet")
            self.assertIsNotNone(mish)
            self.assertTrue(reg.options_of(mish).get("page_enhancement"))

            reg.set_page_enhancement(False)
            self.assertFalse(reg.page_enhancement)
            self.assertFalse(reg.options_of(mish).get("page_enhancement"))
            if mish.object is not None and hasattr(mish.object, "page_enhancement"):
                self.assertFalse(mish.object.page_enhancement)

            # Even if stale per-plugin options contain page_enhancement=True,
            # global settings.page_enhancement remains authoritative for KIND_OCR.
            reg.settings.options["mishkefet"] = {"page_enhancement": True}
            self.assertFalse(reg.options_of(mish).get("page_enhancement"))

            reloaded = PluginSettings.load(reg.settings_path)
            self.assertFalse(reloaded.page_enhancement)

    def test_ocr_worker_enhance_preview_cli(self) -> None:
        from ocr_worker.main import main as worker_main

        with tempfile.TemporaryDirectory() as td:
            in_png = Path(td) / "tan_red.png"
            out_png = Path(td) / "preview.png"
            im = Image.new("RGB", (420, 320), (38, 42, 48))
            draw = ImageDraw.Draw(im)
            for y in (55, 115, 175, 235):
                for x in range(30, 380, 18):
                    draw.line([(x, y - 10), (x + 10, y + 10)], fill=(235, 235, 235), width=3)
            im.save(in_png)

            rc = worker_main(
                ["--enhance-preview", str(in_png), "--output-preview", str(out_png)]
            )
            self.assertEqual(rc, 0)
            self.assertTrue(out_png.is_file())
            meta = json.loads(out_png.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertTrue(meta["enhancement_enabled"])
            if HAS_STROKE_VISION:
                self.assertTrue(meta["enhanced"])

    @unittest.skipUnless(_qt_available(), "PySide6 GUI runtime not available")
    def test_main_window_and_settings_dialog_enhancement_and_compare_controls(
        self,
    ) -> None:
        from hebrew_workbench.ui.main_window import MainWindow
        from hebrew_workbench.ui.settings_dialog import SettingsDialog
        from tests.qt_app import application, temporary_home

        app = application()
        home = temporary_home()
        try:
            td = home.name
            img_path = Path(td) / "colored_scan.png"
            im = Image.new("RGB", (280, 180), (234, 212, 178))
            draw = ImageDraw.Draw(im)
            draw.line([(30, 80), (250, 80)], fill=(190, 32, 32), width=4)
            im.save(img_path)

            win = MainWindow()
            try:
                self.assertTrue(win.toggle_page_enhancement_action.isChecked())
                self.assertFalse(win.compare_images_action.isChecked())
                win.project.add(img_path)
                win._sync_document_list()
                win.doc_list.setCurrentRow(0)

                # Switch to side-by-side comparison via action
                win.compare_images_action.setChecked(True)
                self.assertEqual(win.preview.view_mode, "compare")
                self.assertIn("השוואה", win.preview.status.text())

                # Feed an OCRResult with processed_image_png and verify preview cache
                proc_im = Image.new("RGB", (280, 180), (250, 250, 250))
                png_bytes = encode_preview_png(proc_im)
                res = OCRResult(
                    text="שלום",
                    engine_name="Test Engine",
                    pages=(
                        PageResult(
                            number=1,
                            text="שלום",
                            enhanced=True,
                            enhancement_enabled=True,
                            processed_image_png=png_bytes,
                        ),
                    ),
                )
                win._recognizing_entry = win.project[0]
                win._on_ocr_done(res)
                self.assertIn("OCR", win.preview.status.text())

                # Subsequent clean/disabled OCR run replaces stale processed snapshot
                res_clean = OCRResult(
                    text="שלום",
                    engine_name="Test Engine",
                    pages=(
                        PageResult(
                            number=1,
                            text="שלום",
                            enhanced=False,
                            enhancement_enabled=False,
                            processed_image_png=png_bytes,
                        ),
                    ),
                )
                win._recognizing_entry = win.project[0]
                win._on_ocr_done(res_clean)
                snap_key = str(Path(win.project[0].path).resolve())
                self.assertEqual(
                    win._processed_previews[snap_key][1], (None, False, False)
                )

                # Active OCR task guard prevents mutating page enhancement mid-run
                win.task = object()  # type: ignore[assignment]
                try:
                    win.set_page_enhancement_enabled(False)
                    self.assertTrue(win.plugins.page_enhancement)
                    self.assertTrue(win.toggle_page_enhancement_action.isChecked())
                finally:
                    win.task = None

                # Toggle automatic page enhancement Off via SettingsDialog
                dlg = SettingsDialog(win.plugins, win)
                dlg.changed.connect(win._on_plugins_changed)
                off_idx = dlg.page_enhancement_box.findData(False)
                dlg.page_enhancement_box.setCurrentIndex(off_idx)
                self.assertFalse(win.plugins.page_enhancement)
                self.assertFalse(win.toggle_page_enhancement_action.isChecked())
                dlg.close()
            finally:
                win.close()
                win.deleteLater()
                app.processEvents()
        finally:
            home.cleanup()


if __name__ == "__main__":
    unittest.main()
