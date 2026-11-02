"""Unit and regression tests for PhotoCraft-derived document audit & cleanup."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from hebrew_workbench.engine.photocraft_audit import (
    audit_document_page,
    photocraft_audit_enabled,
    prepare_page_for_ocr,
    rescale_box,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _has_worker_vision() -> bool:
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401

        return True
    except Exception:
        return False


_HAS_WORKER_VISION = _has_worker_vision()


class PhotoCraftAuditLightweightTests(unittest.TestCase):
    """Tests that run in every environment (even without OpenCV/NumPy)."""

    def test_import_does_not_eagerly_load_opencv_or_numpy(self) -> None:
        code = (
            "import sys; "
            "import hebrew_workbench.engine.photocraft_audit; "
            "assert 'cv2' not in sys.modules, 'cv2 loaded eagerly'; "
            "assert 'numpy' not in sys.modules, 'numpy loaded eagerly'"
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            self.fail("import check timed out after 60 seconds")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)

    def test_non_pil_mock_sentinel_passes_through_untouched(self) -> None:
        sentinel = object()
        out, audit = prepare_page_for_ocr(sentinel)
        self.assertIs(out, sentinel)
        self.assertIsNone(audit)

    def test_environment_toggle_controls_enabled_state(self) -> None:
        with patch.dict(os.environ, {"HEBREW_WORKBENCH_PHOTOCRAFT_AUDIT": "0"}):
            self.assertFalse(photocraft_audit_enabled())
            self.assertTrue(photocraft_audit_enabled(True))
            im = Image.new("RGB", (120, 80), (40, 45, 60))
            out, audit = prepare_page_for_ocr(im)
            self.assertIs(out, im)
            self.assertIsNone(audit)
        with patch.dict(os.environ, {"HEBREW_WORKBENCH_PHOTOCRAFT_AUDIT": "1"}):
            self.assertTrue(photocraft_audit_enabled())

    def test_rescale_box_maps_downsampled_coordinates_back_to_native(self) -> None:
        self.assertIsNone(rescale_box(None, 0.5))
        self.assertEqual(rescale_box((10, 20, 30, 40), 1.0), (10, 20, 30, 40))
        self.assertEqual(rescale_box((10, 20, 30, 40), 0.5), (20, 40, 60, 80))

    def test_photocraft_mit_license_text_is_present_and_documented(self) -> None:
        lic = REPO_ROOT / "docs" / "licences" / "PHOTOCRAFT-MIT.txt"
        self.assertTrue(lic.is_file())
        text = lic.read_text(encoding="utf-8")
        self.assertIn("MIT License", text)
        self.assertIn("PhotoCraft contributors", text)
        third_party = (REPO_ROOT / "docs" / "THIRD_PARTY.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("storytold/photocraft", third_party)
        self.assertIn("PHOTOCRAFT-MIT.txt", third_party)


@unittest.skipUnless(_HAS_WORKER_VISION, "OpenCV and NumPy required")
class PhotoCraftVisionAuditTests(unittest.TestCase):
    """Tests exercising the full chromatic, ruling-line, and regional audit."""

    @staticmethod
    def _draw_strokes(
        im: Image.Image, ink_rgb: tuple[int, int, int], rows: tuple[int, ...] = (60, 120, 180, 240)
    ) -> Image.Image:
        draw = ImageDraw.Draw(im)
        w = im.width
        for y in rows:
            for x in range(60, w - 60, 26):
                draw.line([(x, y), (x + 14, y + 6), (x + 18, y - 8)], fill=ink_rgb, width=3)
        return im

    def test_clean_black_on_white_page_fast_paths_without_pixel_changes(self) -> None:
        im = Image.new("RGB", (480, 320), (250, 250, 250))
        self._draw_strokes(im, (25, 25, 28))
        out, audit = prepare_page_for_ocr(im)
        self.assertIsNotNone(audit)
        assert audit is not None
        self.assertFalse(audit.needs_adjustment)
        self.assertIs(out, im)

    def test_red_pen_on_luma_matched_tan_paper_recovers_high_contrast(self) -> None:
        import numpy as np

        # Tan paper Y ~ 187, bright red ink Y ~ 176 (tiny BT.601 delta, large chromatic delta)
        im = Image.new("RGB", (480, 320), (194, 186, 173))
        self._draw_strokes(im, (240, 150, 138))
        out, audit = prepare_page_for_ocr(im)
        assert audit is not None
        self.assertTrue(audit.needs_adjustment)
        self.assertTrue(audit.needs_chromatic_projection)

        raw_gray = np.asarray(im.convert("L"), dtype=np.float32)
        enh_gray = np.asarray(out.convert("L"), dtype=np.float32)
        raw_span = float(np.percentile(raw_gray, 95) - np.percentile(raw_gray, 2))
        enh_span = float(np.percentile(enh_gray, 95) - np.percentile(enh_gray, 2))
        self.assertLess(raw_span, 20.0)
        self.assertGreater(enh_span, 150.0)

    def test_dark_slate_page_with_light_ink_inverts_to_dark_strokes_on_white(self) -> None:
        import numpy as np

        im = Image.new("RGB", (480, 320), (40, 48, 64))
        self._draw_strokes(im, (232, 236, 244))
        out, audit = prepare_page_for_ocr(im)
        assert audit is not None
        self.assertTrue(audit.inverted_polarity)
        self.assertTrue(audit.needs_adjustment)

        enh_gray = np.asarray(out.convert("L"), dtype=np.float32)
        # Paper majority must now be bright white (> 235) and ink dark (< 80)
        self.assertGreater(float(np.percentile(enh_gray, 50)), 235.0)
        self.assertLess(float(np.percentile(enh_gray, 1)), 80.0)

    def test_cyan_graph_grid_triggers_rule_suppression_while_preserving_ink(self) -> None:
        import numpy as np

        im = Image.new("RGB", (500, 360), (248, 250, 252))
        draw = ImageDraw.Draw(im)
        for y in range(24, 360, 24):
            draw.line([(0, y), (499, y)], fill=(118, 184, 238), width=2)
        for x in range(24, 500, 24):
            draw.line([(x, 0), (x, 359)], fill=(118, 184, 238), width=2)
        self._draw_strokes(im, (30, 30, 38), rows=(55, 115, 175, 235, 295))

        out, audit = prepare_page_for_ocr(im)
        assert audit is not None
        self.assertTrue(audit.needs_rule_suppression)
        enh_gray = np.asarray(out.convert("L"), dtype=np.float32)
        # Grid line away from handwriting (y=24) is lifted near white (>225), while stroke ink stays dark (<90)
        self.assertGreater(float(np.median(enh_gray[24, :])), 225.0)
        self.assertLess(float(np.percentile(enh_gray, 1)), 90.0)

    def test_regional_highlighter_and_red_annotation_adjusts_selectively(self) -> None:
        import numpy as np

        im = Image.new("RGB", (520, 420), (250, 250, 248))
        draw = ImageDraw.Draw(im)
        # Yellow highlighter band over row 2 (with both black AND red strokes inside)
        draw.rectangle([40, 125, 480, 165], fill=(250, 242, 82))
        self._draw_strokes(im, (32, 32, 38), rows=(65,))
        draw.line([(90, 145), (170, 145)], fill=(32, 32, 38), width=4)
        draw.line([(290, 145), (390, 145)], fill=(232, 72, 58), width=4)
        # Red low-luma-contrast annotation in bottom rows
        self._draw_strokes(im, (232, 82, 78), rows=(310, 365))

        out, audit = prepare_page_for_ocr(im)
        assert audit is not None
        self.assertTrue(audit.needs_adjustment)
        self.assertTrue(audit.needs_highlighter_suppression)
        enh = np.asarray(out.convert("L"), dtype=np.float32)
        # Yellow highlighter background away from ink is lifted near white (>235)
        self.assertGreater(float(np.percentile(enh[126:164, 40:480], 85)), 235.0)
        # Red-pen stroke INSIDE the yellow highlighter band stays visible (<145)
        self.assertLess(float(np.min(enh[140:151, 290:390])), 145.0)
        # Red-pen strokes at bottom stay dark (<120) rather than being washed out
        self.assertLess(float(np.percentile(enh[295:385, :], 2)), 120.0)

    def test_moderate_neutral_shadow_fast_paths_while_severe_occlusion_relights(
        self,
    ) -> None:
        # Moderate neutral corner shade (drop ~0.35 <= 0.58) defers to per-line normalizer
        mod_im = Image.new("RGB", (480, 360), (242, 242, 242))
        draw_mod = ImageDraw.Draw(mod_im)
        draw_mod.rectangle([0, 180, 240, 360], fill=(158, 158, 158))
        self._draw_strokes(mod_im, (30, 30, 30), rows=(70, 140, 220, 290))
        out_mod, aud_mod = prepare_page_for_ocr(mod_im)
        assert aud_mod is not None
        self.assertFalse(aud_mod.needs_shadow_relight)
        self.assertIs(out_mod, mod_im)

        # Severe near-black corner shadow across >=2 tiles (drop ~0.72 > 0.58) relights
        sev_im = Image.new("RGB", (480, 360), (246, 246, 246))
        draw_sev = ImageDraw.Draw(sev_im)
        draw_sev.rectangle([0, 180, 300, 360], fill=(62, 62, 62))
        self._draw_strokes(sev_im, (18, 18, 18), rows=(70, 140, 220, 290))
        out_sev, aud_sev = prepare_page_for_ocr(sev_im)
        assert aud_sev is not None
        self.assertTrue(aud_sev.needs_shadow_relight)
        self.assertTrue(aud_sev.needs_adjustment)
        self.assertIsNot(out_sev, sev_im)

    def test_benchmark_neural_ocr_comparison_harness(self) -> None:
        from types import SimpleNamespace

        import numpy as np

        from tools.benchmark_photocraft_audit import run_neural_ocr_comparison

        class _StubEngine:
            def _recognize_page_now(self, index: int, image: Image.Image):
                out_im, _ = prepare_page_for_ocr(image)
                gray = np.asarray(out_im.convert("L"), dtype=np.float32)
                # Dark-slate inverted pages only yield dark strokes when PhotoCraft runs
                has_dark_ink = float(np.percentile(gray, 2)) < float(np.median(gray)) - 25.0
                text = "נודי צפורי\nאשרת" if has_dark_ink else ""
                return SimpleNamespace(page=index, text=text)

        repo_root = Path(__file__).resolve().parents[1]
        rows = run_neural_ocr_comparison(
            corpus_dir=repo_root / "benchmark" / "modern_cursive",
            models_dir=repo_root,
            engine_ids=["mishkefet-v1"],
            resolved_engines=[(_StubEngine(), "mishkefet-v1")],
            suites_override=("dark_slate_light_ink",),
        )
        self.assertEqual(len(rows), 1)
        self.assertLess(rows[0]["delta_cer_pp"], 0.0)
        self.assertGreater(rows[0]["photocraft"]["predicted_lines"], 0)

    def test_chromatic_vertical_margin_rule_removed_without_touching_black_ink(
        self,
    ) -> None:
        import numpy as np
        from hebrew_workbench.engine.photocraft_audit import (
            resolve_page_enhancement_enabled,
        )

        # White notebook page with a narrow pink vertical margin rule at x=36..38
        im = Image.new("RGB", (420, 320), (250, 250, 250))
        draw = ImageDraw.Draw(im)
        draw.rectangle([36, 0, 38, 319], fill=(247, 178, 200))
        self._draw_strokes(im, (22, 22, 22), rows=(65, 130, 195, 260))

        out, audit = prepare_page_for_ocr(im, enabled=True)
        assert audit is not None
        self.assertTrue(audit.needs_adjustment)
        self.assertTrue(audit.needs_rule_suppression)
        out_arr = np.asarray(out)
        orig_arr = np.asarray(im)
        # Pink margin line away from ink is lifted to neutral white paper (>242)
        self.assertGreater(float(out_arr[20:45, 36:39].mean()), 242.0)
        # Black ink strokes stay completely dark and untouched
        dark_mask = orig_arr.max(axis=2) < 60
        self.assertTrue(np.array_equal(out_arr[dark_mask], orig_arr[dark_mask]))

        # Explicit enabled=False returns the exact original image untouched
        off_out, _ = prepare_page_for_ocr(im, enabled=False)
        self.assertIs(off_out, im)
        self.assertFalse(resolve_page_enhancement_enabled(False))


if __name__ == "__main__":
    unittest.main()
