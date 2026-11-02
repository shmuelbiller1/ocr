"""Regression tests for handwritten page segmentation, curved-line straightening,
margin-speckle filtering, and Kraken multilingual CTC script masking."""

from __future__ import annotations

import types
import unittest
from pathlib import Path

from PIL import Image

from hebrew_workbench.engine.kraken_local import (
    disallowed_ctc_labels,
    script_masked_decoder,
)
from hebrew_workbench.engine.mishkefet import _is_margin_speckle

try:
    import cv2
    import numpy as np
    from hebrew_workbench.engine.vendor.hebocr.page.segment import (
        estimate_skew,
        find_lines,
        segment_page,
        split_tall,
        straighten_line,
    )

    _HAS_WORKER_VISION = True
except ImportError:
    cv2 = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    _HAS_WORKER_VISION = False

REPO_ROOT = Path(__file__).resolve().parents[1]
CURSIVE_DIR = REPO_ROOT / "benchmark" / "modern_cursive" / "pages"


@unittest.skipUnless(_HAS_WORKER_VISION, "opencv-python and numpy live in worker-venv")
class HandwrittenSegmentationTests(unittest.TestCase):
    def test_short_four_line_poem_is_not_oversegmented(self) -> None:
        img = Image.open(CURSIVE_DIR / "commons__bialik_el_hazippor__p0001.jpg")
        crops, boxes, _angle = segment_page(img)
        self.assertEqual(len(crops), 4)
        self.assertEqual(len(boxes), 4)

    def test_faint_low_dpi_scan_recovers_all_poem_lines(self) -> None:
        img = Image.open(CURSIVE_DIR / "commons__rachel_rak_al_atzmi__p0001.jpg")
        crops, _boxes, _angle = segment_page(img)
        self.assertGreaterEqual(len(crops), 12)
        self.assertLessEqual(len(crops), 20)

    def test_tall_multi_line_paragraph_is_split_not_dropped(self) -> None:
        pitch = 40.0
        binary = np.zeros((720, 800), dtype=np.uint8)
        for row in range(15):
            y0 = 50 + row * 40
            binary[y0 : y0 + 10, 120:680] = 255
        binary[50 : 50 + 15 * 40, 400:403] = 255

        boxes = find_lines(binary, pitch)
        self.assertEqual(len(boxes), 1)
        split = split_tall(binary, boxes, pitch)
        self.assertGreaterEqual(len(split), 13)

    def test_solid_dark_block_taller_than_12_pitches_is_rejected(self) -> None:
        pitch = 30.0
        binary = np.zeros((600, 600), dtype=np.uint8)
        binary[40:500, 80:480] = 255
        self.assertEqual(find_lines(binary, pitch), [])

    def test_wide_skew_estimation_recovers_steep_phone_tilt(self) -> None:
        canvas = np.zeros((700, 700), dtype=np.uint8)
        for row in range(8):
            y = 180 + row * 45
            canvas[y : y + 8, 140:560] = 255
        m = cv2.getRotationMatrix2D((350.0, 350.0), 18.0, 1.0)
        tilted = cv2.warpAffine(canvas, m, (700, 700), flags=cv2.INTER_NEAREST)
        estimated = estimate_skew(tilted, limit=44.0, step=0.5)
        self.assertAlmostEqual(estimated, -18.0, delta=1.5)

    def test_straighten_line_keeps_level_line_untouched_and_flattens_arc(self) -> None:
        straight = np.full((64, 320, 3), 245, dtype=np.uint8)
        straight[28:35, 20:300] = 25
        straight_im = Image.fromarray(straight)
        out_straight = straighten_line(straight_im)
        self.assertEqual(list(straight_im.getdata()), list(out_straight.getdata()))

        arched = np.full((80, 360, 3), 245, dtype=np.uint8)
        xs = np.arange(20, 340)
        norm_x = (xs - 180.0) / 160.0
        arc_y = (22.0 + 22.0 * (1.0 - norm_x**2)).astype(int)
        for x, y in zip(xs, arc_y):
            arched[y : y + 7, x] = 20
        arched_im = Image.fromarray(arched)
        flattened = np.asarray(straighten_line(arched_im).convert("L"))
        ink = flattened < 128
        cols = np.where(ink.sum(axis=0) > 0)[0]
        ys = np.arange(80, dtype=np.float32)[:, None]
        centres = (ink[:, cols] * ys).sum(axis=0) / ink[:, cols].sum(axis=0)
        self.assertLess(float(np.ptp(centres)), 8.0)


class MarginSpeckleAndKrakenMaskTests(unittest.TestCase):
    def test_margin_speckle_filter_is_conservative(self) -> None:
        tiny_box = types.SimpleNamespace(x=5, y=5, w=14, h=24)
        wide_box = types.SimpleNamespace(x=5, y=5, w=180, h=30)
        self.assertTrue(_is_margin_speckle("י", 0.32, tiny_box))
        self.assertFalse(_is_margin_speckle("12", 0.85, tiny_box))
        self.assertFalse(_is_margin_speckle('בס"ד', 0.40, tiny_box))
        self.assertFalse(_is_margin_speckle("י", 0.32, wide_box))

    def test_kraken_ctc_mask_blocks_foreign_scripts_and_preserves_hebrew_latin(self) -> None:
        codec = types.SimpleNamespace(
            l2c={
                (1,): "א",
                (2,): "ש",
                (3,): "A",
                (4,): "7",
                (5,): ",",
                (6,): "품",  # Hangul
                (7,): "Ⴀ",  # Georgian
                (8,): "Ж",  # Cyrillic
                (9,): "ق",  # Arabic
            }
        )
        disallowed = disallowed_ctc_labels(codec)
        self.assertEqual(disallowed, [6, 7, 8, 9])

        # Shape (1, 10, 2): frame 0 prefers Hangul (6) at 0.60 over Shin (2) at 0.30;
        # frame 1 prefers CTC blank (0) at 0.90.
        probs = [[[0.0, 0.0] for _ in range(10)]]
        probs[0][6][0] = 0.60
        probs[0][2][0] = 0.30
        probs[0][0][1] = 0.90

        captured = {}

        def fake_greedy(data, seq_lens=None):
            frame0 = [data[0][c][0] for c in range(10)]
            frame1 = [data[0][c][1] for c in range(10)]
            best0 = max(range(10), key=lambda c: frame0[c])
            best1 = max(range(10), key=lambda c: frame1[c])
            captured["argmax"] = [best0, best1]
            return [[(best0, 0, 0, frame0[best0])]]

        wrapped = script_masked_decoder(fake_greedy, disallowed)
        res = wrapped(probs)
        self.assertEqual(captured["argmax"], [2, 0])
        self.assertEqual(res[0][0][0], 2)


def _has_torch() -> bool:
    try:
        import torch  # noqa: F401
        return True
    except Exception:
        return False


@unittest.skipUnless(_has_torch() and _HAS_WORKER_VISION, "torch/numpy/opencv required")
class MishkefetLogitCacheTests(unittest.TestCase):
    def test_recognizer_reuses_scale_1_logits_between_read_and_read_tta(self) -> None:
        import torch
        from PIL import Image
        from hebrew_workbench.engine.vendor.hebocr.charset import Charset
        from hebrew_workbench.engine.vendor.hebocr.recognize import Recognizer

        rec = Recognizer.__new__(Recognizer)
        rec.charset = Charset(chars=["", "א", "ב", " "])
        rec.device = torch.device("cpu")
        rec.lm = None
        rec.lm_weight = 0.4
        rec.beam_width = 0
        rec.length_bonus = 0.6
        rec.tta = 3
        rec.word_lm = None
        rec.word_weight = 0.0
        rec._last_logit_cache = None

        forward_calls = []

        class FakeModel:
            def __call__(self, x):
                forward_calls.append(tuple(x.shape))
                b = x.shape[0]
                t = max(2, x.shape[-1] // 16)
                out = torch.full((b, t, 4), -8.0)
                out[:, 0, 1] = -0.01  # 'א'
                out[:, 1:, 0] = -0.01  # blank
                return out

            def output_lengths(self, widths):
                return torch.clamp(widths // 16, min=2)

        rec.model = FakeModel()
        crops = [Image.new("RGB", (128, 32), "white"), Image.new("RGB", (160, 32), "white")]

        raw_texts, raw_confs = rec.read(crops, return_confidence=True)
        self.assertEqual(len(forward_calls), 1)
        self.assertEqual(raw_texts, ["א", "א"])
        self.assertEqual(len(raw_confs), 2)

        # Switching to beam + 3-scale TTA reuses scale=1.0 logits and only
        # evaluates the two resized scales (0.82 and 1.22), totaling 3 calls
        # instead of 4.
        rec.beam_width = 4
        tta_texts = rec.read_tta(crops)
        self.assertEqual(tta_texts, ["א", "א"])
        self.assertEqual(len(forward_calls), 3)


if __name__ == "__main__":
    unittest.main()
