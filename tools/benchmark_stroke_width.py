"""Systematic CPU benchmark of handwriting stroke-width variants & real scans.

Evaluates the six stroke-width variants implemented in
``hebrew_workbench.engine.stroke_width`` across ``Mishkefet-v1`` and ``Kraken``:

1. ``original``        — Original image, unchanged.
2. ``mild_thicken``    — Very mild antialiased stroke thickening (gap-guarded).
3. ``moderate_thicken``— Moderate antialiased stroke thickening (gap-guarded).
4. ``slight_thin``     — Slight antialiased stroke thinning (core/dot-guarded).
5. ``adaptive_norm``   — Adaptive stroke-width normalisation using measured
                         ridge ink thickness (deadband ``[3.05, 5.35] px``).
6. ``faint_repair``    — Selective directional repair of faint/broken strokes.

Methodology:
- Runs each OCR engine in an **isolated child Python process** so ``peak_rss_mb``
  reflects true per-model memory rather than cumulative single-process RSS.
- **Experiment A (Line-Crop Recognition at Model-Input Resolution)**:
  Segments each page once (both WITH and WITHOUT PhotoCraft page enhancement),
  then evaluates all 6 stroke-width variants directly on line crops at actual
  neural-network input height (``H=64`` inside ``hebocr.data.transforms.preprocess``
  for Mishkefet; ``H=96`` inside ``ImageInputTransforms`` for Kraken PP-OCRv6)
  across 8 multi-writer / pen-type / paper-color / DPI regimes on human-verified
  ``PDM-1.0`` cursive pages.
- **Experiment B (Separate Line-Segmentation Effect)**:
  Applies all 6 variants at page level before line segmentation to test whether
  stroke-width adjustment helps or hurts line detection and end-to-end CER/WER.
- **Experiment C (Real Contemporary & Multi-Era Scans — No Fabricated GT)**:
  Evaluates real unverified contemporary scans (``scan-2026-10-28-221624.pdf``
  plus ``--extra-scan`` files and optional temporary public ``HeOCR/hash``
  scans) without fabricating CER/WER ground truth.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import cv2  # type: ignore[import-not-found]
    import numpy as np  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - GUI-only env without worker libs
    cv2 = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
from PIL import Image  # noqa: E402

from hebrew_workbench.benchmark.corpus import load_corpus  # noqa: E402
from hebrew_workbench.benchmark.metrics import (  # noqa: E402
    character_error_rate,
    levenshtein,
    line_alignment_metrics,
    normalise,
    process_memory_mb,
    word_error_rate,
)
from hebrew_workbench.engine.models import models_directory  # noqa: E402
from hebrew_workbench.engine.photocraft_audit import (  # noqa: E402
    audit_document_page,
    prepare_page_for_ocr,
)
from hebrew_workbench.engine.stroke_width import (  # noqa: E402
    STROKE_VARIANT_DESCRIPTIONS,
    STROKE_VARIANTS,
    apply_stroke_variant,
    audit_inference_stroke_compensation,
    measure_stroke_width,
)
from hebrew_workbench.preview.loader import DocumentPreview  # noqa: E402
from tools.benchmark_ocr import (  # noqa: E402
    _filter_installed_engine_ids,
    resolve_engines,
)

DEFAULT_CORPUS = ROOT / "benchmark" / "modern_cursive"
DEFAULT_SMOKE_SCAN = (
    ROOT / "benchmark" / "smoke_test" / "pages" / "scan-2026-10-28-221624.pdf"
)

WRITER_BY_PAGE_ID: dict[str, str] = {
    "commons__begani_netatikha__p0001": "Rachel Bluwstein",
    "commons__bialik_el_hazippor__p0001": "H. N. Bialik",
    "commons__hatikvah_imber_manuscript__p0001": "N. H. Imber",
    "commons__rachel_aqara_1928__p0001": "Rachel Bluwstein",
    "commons__rachel_gan_naul__p0001": "Rachel Bluwstein",
    "commons__rachel_rak_al_atzmi__p0001": "Rachel Bluwstein",
}

REGIME_SPECS: tuple[tuple[str, str], ...] = (
    ("verified_native_300dpi", "Original verified cursive pages (4 writers, 2.0–5.6 px strokes)"),
    ("pen_fine_nib", "Simulated extra-fine ballpoint / fine dip nib (~1.8–2.4 px strokes)"),
    ("pen_faint_broken", "Simulated dry / skipping ballpoint with faint strokes & 1-px micro-breaks"),
    ("pen_heavy_marker", "Simulated heavy felt-tip / bleeding fountain pen (~5.5–6.8 px strokes)"),
    ("paper_warm_yellow", "Simulated warm yellow legal-pad paper (RGB ~ [248, 234, 162])"),
    ("paper_red_ink_tan", "Simulated red ink on warm tan notebook paper"),
    ("dpi_150_lowres", "Low-resolution 150 DPI scan (0.50x optical downsample)"),
    ("dpi_110_coarse", "Coarse 110 DPI scan (0.37x optical downsample)"),
)

SEGMENTATION_REGIMES: tuple[str, ...] = (
    "verified_native_300dpi",
    "pen_fine_nib",
    "pen_faint_broken",
    "dpi_150_lowres",
)

# Public on-demand real archival scans from HeOCR/hash (1939–1990) for temporary
# non-GT runtime validation only — never stored in repository.
PUBLIC_REAL_SCANS: tuple[tuple[str, str, str], ...] = (
    (
        "wosner_1981_cream_responsa.pdf",
        "Rabbi Shmuel HaLevi Wosner handwritten responsum (1981, cream paper)",
        "https://api.github.com/repos/HeOCR/hash/contents/data/scans/commons__wosner_halachic_ruling_1981/commons__wosner_halachic_ruling_1981__p0001.pdf",
    ),
    (
        "wosner_1986_halakhah_letter.jpg",
        "Rabbi Shmuel HaLevi Wosner handwritten letter (1986, fine ballpoint)",
        "https://api.github.com/repos/HeOCR/hash/contents/data/scans/commons__wosner_letter_halakhah_yomit_1986/commons__wosner_letter_halakhah_yomit_1986__p0001.jpg",
    ),
    (
        "wosner_1990_fine_ballpoint.pdf",
        "Rabbi Shmuel HaLevi Wosner letterhead letter (1990, fine ballpoint)",
        "https://api.github.com/repos/HeOCR/hash/contents/data/scans/commons__wosner_support_letter_1990/commons__wosner_support_letter_1990__p0001.pdf",
    ),
)


def _cap_working_image(im: Image.Image, max_side: int = 2100) -> Image.Image:
    rgb = im.convert("RGB")
    w, h = rgb.size
    longest = max(w, h)
    if longest <= max_side:
        return rgb
    scale = max_side / float(longest)
    resample = getattr(Image, "Resampling", Image).LANCZOS
    return rgb.resize(
        (max(16, int(round(w * scale))), max(16, int(round(h * scale)))),
        resample=resample,
    )


def _synthesize_regime(orig_im: Image.Image, regime: str, seed: int) -> Image.Image:
    """Create deterministic pen/paper/DPI variants while keeping GT identical."""
    if regime == "verified_native_300dpi":
        return orig_im.convert("RGB")

    base = _cap_working_image(orig_im, max_side=2100)
    arr = np.asarray(base, dtype=np.float32) / 255.0
    h, w, _ = arr.shape
    luma = 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
    p92 = max(float(np.percentile(luma, 92.0)), 0.25)
    p02 = min(float(np.percentile(luma, 2.0)), p92 - 0.15)
    ink = np.clip((p92 - luma) / max(p92 - p02, 0.15), 0.0, 1.0).astype(np.float32)

    if regime == "pen_fine_nib":
        cross = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
        ero = cv2.erode(arr, cross)
        # Brightening dark strokes with morphological max (dilate on luminance)
        # thins ink smoothly while preserving grayscale antialiasing!
        dil_bright = cv2.dilate(arr, cross)
        out = 0.38 * arr + 0.62 * dil_bright
        return Image.fromarray(np.rint(np.clip(out * 255.0, 0, 255)).astype(np.uint8))

    if regime == "pen_faint_broken":
        rng = np.random.default_rng(seed)
        # Low-contrast dry ballpoint + sparse 1-px horizontal/vertical skip lines
        fade = 0.52 + 0.20 * cv2.GaussianBlur(
            rng.random((max(4, h // 12), max(4, w // 12)), dtype=np.float32),
            (5, 5),
            0,
        )
        fade_full = cv2.resize(fade, (w, h), interpolation=cv2.INTER_LINEAR)
        # Sparse 1-px dry skips across ~6% of rows
        skip_rows = rng.random(h) < 0.06
        fade_full[skip_rows, :] *= 0.28
        paper = np.percentile(arr.reshape(-1, 3), 90.0, axis=0).astype(np.float32)
        out = paper[None, None, :] - (paper[None, None, :] - arr) * fade_full[..., None]
        return Image.fromarray(np.rint(np.clip(out * 255.0, 0, 255)).astype(np.uint8))

    if regime == "pen_heavy_marker":
        box = np.ones((3, 3), dtype=np.uint8)
        darker = cv2.erode(arr, box)
        out = 0.30 * arr + 0.70 * darker
        return Image.fromarray(np.rint(np.clip(out * 255.0, 0, 255)).astype(np.uint8))

    if regime == "paper_warm_yellow":
        yellow_paper = np.array([0.972, 0.918, 0.635], dtype=np.float32)
        ink_rgb = np.array([0.11, 0.12, 0.18], dtype=np.float32)
        out = yellow_paper[None, None, :] * (1.0 - ink[..., None]) + ink_rgb[
            None, None, :
        ] * ink[..., None]
        return Image.fromarray(np.rint(np.clip(out * 255.0, 0, 255)).astype(np.uint8))

    if regime == "paper_red_ink_tan":
        tan_paper = np.array([0.925, 0.855, 0.735], dtype=np.float32)
        red_ink = np.array([0.74, 0.14, 0.15], dtype=np.float32)
        out = tan_paper[None, None, :] * (1.0 - ink[..., None]) + red_ink[
            None, None, :
        ] * ink[..., None]
        return Image.fromarray(np.rint(np.clip(out * 255.0, 0, 255)).astype(np.uint8))

    if regime == "dpi_150_lowres":
        resample = getattr(Image, "Resampling", Image).BILINEAR
        return base.resize(
            (max(32, int(round(w * 0.50))), max(32, int(round(h * 0.50)))),
            resample=resample,
        )

    if regime == "dpi_110_coarse":
        resample = getattr(Image, "Resampling", Image).BILINEAR
        return base.resize(
            (max(32, int(round(w * 0.37))), max(32, int(round(h * 0.37)))),
            resample=resample,
        )

    raise ValueError(f"Unknown regime: {regime!r}")


@contextmanager
def _kraken_model_input_stroke_hook(variant: str):
    """Inject ``apply_stroke_variant`` at Kraken's exact model-input PIL stage."""
    if variant == "original":
        yield
        return

    from kraken.lib import dataset as kraken_dataset
    from torchvision.transforms import v2

    orig_create = kraken_dataset.ImageInputTransforms._create_transforms

    def patched_create(self) -> None:
        orig_create(self)
        insert_at = len(self.transforms)
        for idx, step in enumerate(self.transforms):
            if isinstance(step, (v2.Pad, v2.PILToTensor)):
                insert_at = idx
                break
        self.transforms.insert(
            insert_at,
            lambda pil_im: apply_stroke_variant(pil_im, variant),  # type: ignore[arg-type]
        )

    kraken_dataset.ImageInputTransforms._create_transforms = patched_create  # type: ignore[method-assign]
    try:
        yield
    finally:
        kraken_dataset.ImageInputTransforms._create_transforms = orig_create  # type: ignore[method-assign]


def _evaluate_predictions(
    pages_gt: list[tuple[str, str]],
    preds: list[tuple[str, list[str], list[float], float]],
) -> dict[str, object]:
    """Compute macro CER, WER, missing/extra lines, confidence, and per-writer CER."""
    cers: list[float] = []
    wers: list[float] = []
    confs: list[float] = []
    sws: list[float] = []
    missing_total = 0
    extra_total = 0
    by_writer: dict[str, list[float]] = {}
    per_page: list[dict[str, object]] = []

    for (page_id, ref_text), (hyp_text, hyp_lines, line_confs, page_sw) in zip(
        pages_gt, preds
    ):
        ref_norm = normalise(ref_text)
        hyp_norm = normalise(hyp_text)
        cer = character_error_rate(ref_norm, hyp_norm)
        wer = word_error_rate(ref_norm, hyp_norm)
        clean_hyp_lines = [ln for ln in hyp_lines if ln.strip()]
        line_stats = line_alignment_metrics(ref_text, hyp_text)
        miss = int(line_stats["missing_lines"])
        extra = int(line_stats["extra_lines"])
        missing_total += miss
        extra_total += extra
        cers.append(cer)
        wers.append(wer)
        if line_confs:
            confs.append(float(np.mean(line_confs)))
        if page_sw > 0.0:
            sws.append(page_sw)
        writer = WRITER_BY_PAGE_ID.get(page_id, "other")
        by_writer.setdefault(writer, []).append(cer)
        per_page.append(
            {
                "id": page_id,
                "writer": writer,
                "cer": round(cer, 4),
                "wer": round(wer, 4),
                "missing_lines": miss,
                "extra_lines": extra,
                "detected_lines": len(clean_hyp_lines),
                "measured_sw_px": round(page_sw, 2),
                "mean_confidence": round(float(np.mean(line_confs)), 4)
                if line_confs
                else None,
            }
        )

    return {
        "macro_cer": round(float(np.mean(cers)) if cers else 0.0, 4),
        "macro_wer": round(float(np.mean(wers)) if wers else 0.0, 4),
        "missing_lines_total": missing_total,
        "extra_lines_total": extra_total,
        "mean_confidence": round(float(np.mean(confs)), 4) if confs else None,
        "mean_measured_sw_px": round(float(np.mean(sws)), 2) if sws else 0.0,
        "by_writer_cer": {
            w: round(float(np.mean(vals)), 4) for w, vals in sorted(by_writer.items())
        },
        "pages": per_page,
    }


def _run_mishkefet_experiments(
    engine,
    corpus_pages: list[tuple[str, Image.Image, str]],
    real_scans: list[tuple[str, str, Image.Image]],
    ci_fast: bool = False,
) -> dict[str, object]:
    from hebrew_workbench.engine.vendor.hebocr.data.transforms import (
        inference_stroke_variant,
    )
    from hebrew_workbench.engine.vendor.hebocr.page.segment import segment_page

    recognizer = engine._load_recognizer()
    line_crop_results: dict[str, dict[str, dict[str, object]]] = {
        "with_photocraft": {},
        "without_photocraft": {},
    }

    # Experiment A: Line-crop recognition at H=64 with fixed segmentation
    if corpus_pages:
        for pc_enabled, pc_key in (
            (True, "with_photocraft"),
            (False, "without_photocraft"),
        ):
            if ci_fast:
                regimes_for_pass = (
                    (
                        REGIME_SPECS[0],  # verified_native_300dpi
                        REGIME_SPECS[1],  # pen_fine_nib
                        REGIME_SPECS[3],  # pen_faint_broken
                        REGIME_SPECS[6],  # dpi_150_lowres
                    )
                    if pc_enabled
                    else (REGIME_SPECS[0],)
                )
            else:
                regimes_for_pass = REGIME_SPECS
            for reg_idx, (regime, reg_desc) in enumerate(regimes_for_pass):
                segmented_pages: list[tuple[str, str, list[Image.Image], float]] = []
                for p_idx, (page_id, orig_im, ref_text) in enumerate(corpus_pages):
                    reg_im = _synthesize_regime(
                        orig_im, regime, seed=100 * reg_idx + p_idx
                    )
                    prep_im, _ = prepare_page_for_ocr(reg_im, enabled=pc_enabled)
                    crops, _boxes, _skew = segment_page(prep_im)
                    sw_vals = [
                        measure_stroke_width(c, normalize_height=64).median_sw_px
                        for c in crops
                        if c.size[0] >= 16 and c.size[1] >= 8
                    ]
                    sw_vals = [v for v in sw_vals if v > 0.0]
                    med_sw = float(np.median(sw_vals)) if sw_vals else 0.0
                    segmented_pages.append((page_id, ref_text, crops, med_sw))

                variant_out: dict[str, object] = {}
                pages_gt = [(pid, ref) for pid, ref, _, _ in segmented_pages]
                orig_cer = 0.0
                orig_wer = 0.0
                for variant in STROKE_VARIANTS:
                    t0 = time.perf_counter()
                    preds: list[tuple[str, list[str], list[float], float]] = []
                    with inference_stroke_variant(variant):
                        for _pid, _ref, crops, med_sw in segmented_pages:
                            if not crops:
                                preds.append(("", [], [], med_sw))
                                continue
                            raw_texts, raw_confs = recognizer.read(
                                crops, return_confidence=True
                            )
                            lines = [
                                (txt or "").strip()
                                for txt in raw_texts
                                if (txt or "").strip()
                            ]
                            confs = [
                                float(c)
                                for txt, c in zip(raw_texts, raw_confs)
                                if (txt or "").strip() and c is not None
                            ]
                            preds.append(("\n".join(lines), lines, confs, med_sw))
                    wall_ms = (time.perf_counter() - t0) * 1000.0
                    metrics = _evaluate_predictions(pages_gt, preds)
                    metrics["model_input_height_px"] = 64
                    metrics["wall_ms"] = round(wall_ms, 1)
                    metrics["ms_per_page"] = round(
                        wall_ms / max(1, len(segmented_pages)), 1
                    )
                    if variant == "original":
                        orig_cer = float(metrics["macro_cer"])
                        orig_wer = float(metrics["macro_wer"])
                    metrics["delta_cer_pp_vs_original"] = round(
                        (float(metrics["macro_cer"]) - orig_cer) * 100.0, 2
                    )
                    metrics["delta_wer_pp_vs_original"] = round(
                        (float(metrics["macro_wer"]) - orig_wer) * 100.0, 2
                    )
                    variant_out[variant] = metrics
                    print(
                        f"[CROP][mishkefet-v1][{pc_key}][{regime}][{variant}] "
                        f"CER={metrics['macro_cer']*100:.2f}% ({metrics['delta_cer_pp_vs_original']:+.2f}pp) "
                        f"conf={metrics['mean_confidence']} sw={metrics['mean_measured_sw_px']:.2f} "
                        f"{wall_ms:.0f}ms",
                        flush=True,
                    )
                line_crop_results[pc_key][regime] = {
                    "description": reg_desc,
                    "variants": variant_out,
                }

    # Experiment B: Page-level stroke variant BEFORE line segmentation
    seg_results: dict[str, object] = {}
    seg_regimes = (
        SEGMENTATION_REGIMES[:1] if ci_fast else SEGMENTATION_REGIMES
    )
    if not corpus_pages:
        seg_regimes = ()
    for reg_idx, regime in enumerate(seg_regimes):
        base_pages = [
            (
                pid,
                ref,
                prepare_page_for_ocr(
                    _synthesize_regime(im, regime, seed=500 + 20 * reg_idx + i),
                    enabled=True,
                )[0],
            )
            for i, (pid, im, ref) in enumerate(corpus_pages)
        ]
        pages_gt = [(pid, ref) for pid, ref, _ in base_pages]
        var_seg: dict[str, object] = {}
        orig_cer = 0.0
        for variant in STROKE_VARIANTS:
            t0 = time.perf_counter()
            preds = []
            det_total = 0
            for _pid, _ref, prep_im in base_pages:
                page_var = (
                    prep_im
                    if variant == "original"
                    else apply_stroke_variant(prep_im, variant, page_scale=True)
                )
                crops, _boxes, _skew = segment_page(page_var)
                det_total += len(crops)
                if not crops:
                    preds.append(("", [], [], 0.0))
                    continue
                raw_texts, raw_confs = recognizer.read(
                    crops, return_confidence=True
                )
                lines = [
                    (txt or "").strip()
                    for txt in raw_texts
                    if (txt or "").strip()
                ]
                confs = [
                    float(c)
                    for txt, c in zip(raw_texts, raw_confs)
                    if (txt or "").strip() and c is not None
                ]
                preds.append(("\n".join(lines), lines, confs, 0.0))
            wall_ms = (time.perf_counter() - t0) * 1000.0
            metrics = _evaluate_predictions(pages_gt, preds)
            metrics["raw_segmented_boxes_total"] = det_total
            metrics["wall_ms"] = round(wall_ms, 1)
            if variant == "original":
                orig_cer = float(metrics["macro_cer"])
            metrics["delta_cer_pp_vs_original"] = round(
                (float(metrics["macro_cer"]) - orig_cer) * 100.0, 2
            )
            var_seg[variant] = metrics
        seg_results[regime] = var_seg

    # Experiment C: Real unverified contemporary & archival scans (NO fabricated GT)
    real_scan_results: list[dict[str, object]] = []
    for scan_id, scan_desc, scan_im in real_scans:
        raw_audit = audit_document_page(scan_im)

        # Time identical end-to-end workloads:
        # without_photocraft = segment_page(scan_im) + recognizer.read(...)
        # with_photocraft    = prepare_page_for_ocr(scan_im) + segment_page(prep_im) + recognizer.read(...)
        t_raw = time.perf_counter()
        raw_crops, raw_boxes, _ = segment_page(scan_im)
        t_raw_seg = time.perf_counter()
        raw_texts, _ = (
            recognizer.read(raw_crops, return_confidence=True)
            if raw_crops
            else ([], [])
        )
        raw_ms = (time.perf_counter() - t_raw) * 1000.0
        raw_seg_ms = (t_raw_seg - t_raw) * 1000.0
        raw_rec_ms = raw_ms - raw_seg_ms
        raw_nonempty = [(t or "").strip() for t in raw_texts if (t or "").strip()]
        raw_text = "\n".join(raw_nonempty)

        t_enh = time.perf_counter()
        prep_im, enh_audit = prepare_page_for_ocr(scan_im, enabled=True)
        t_enh_prep = time.perf_counter()
        enh_crops, enh_boxes, enh_skew = segment_page(prep_im)
        t_enh_seg = time.perf_counter()
        enh_texts, enh_raw_confs = (
            recognizer.read(enh_crops, return_confidence=True)
            if enh_crops
            else ([], [])
        )
        enh_ms = (time.perf_counter() - t_enh) * 1000.0
        enh_prep_ms = (t_enh_prep - t_enh) * 1000.0
        enh_seg_ms = (t_enh_seg - t_enh_prep) * 1000.0
        enh_rec_ms = enh_ms - enh_prep_ms - enh_seg_ms

        raw_margin_snaps = sum(1 for b in raw_boxes if b.x <= 220)
        enh_margin_snaps = sum(1 for b in enh_boxes if b.x <= 220)
        enh_nonempty = [(t or "").strip() for t in enh_texts if (t or "").strip()]
        enh_text = "\n".join(enh_nonempty)
        enh_confs = [
            float(c)
            for t, c in zip(enh_texts, enh_raw_confs)
            if (t or "").strip() and c is not None
        ]

        with inference_stroke_variant("adaptive_norm"):
            adapt_texts = recognizer.read(enh_crops) if enh_crops else []
        adapt_text = "\n".join(
            (t or "").strip() for t in adapt_texts if (t or "").strip()
        )

        with inference_stroke_variant("mild_thicken"):
            mild_texts = recognizer.read(enh_crops) if enh_crops else []
        mild_text = "\n".join(
            (t or "").strip() for t in mild_texts if (t or "").strip()
        )

        sw_vals = [
            measure_stroke_width(c, normalize_height=64).median_sw_px
            for c in enh_crops[:25]
            if c.size[0] >= 16 and c.size[1] >= 8
        ]
        sw_vals = [v for v in sw_vals if v > 0.0]

        real_scan_results.append(
            {
                "id": scan_id,
                "description": scan_desc,
                "ground_truth_available": False,
                "size_px": [scan_im.size[0], scan_im.size[1]],
                "measured_sw_px_at_h64": round(float(np.median(sw_vals)), 2)
                if sw_vals
                else 0.0,
                "photocraft_audit": enh_audit.to_dict() if enh_audit else None,
                "without_photocraft": {
                    "segmented_lines": len(raw_boxes),
                    "left_margin_snapped_boxes_x_le_220": raw_margin_snaps,
                    "nonempty_recognized_lines": len(raw_nonempty),
                    "char_count": len(raw_text),
                    "wall_ms": round(raw_ms, 1),
                    "segmentation_ms": round(raw_seg_ms, 1),
                    "recognition_ms": round(raw_rec_ms, 1),
                },
                "with_photocraft": {
                    "segmented_lines": len(enh_boxes),
                    "skew_deg": round(float(enh_skew), 2),
                    "left_margin_snapped_boxes_x_le_220": enh_margin_snaps,
                    "nonempty_recognized_lines": len(enh_nonempty),
                    "char_count": len(enh_text),
                    "mean_confidence": round(float(np.mean(enh_confs)), 4)
                    if enh_confs
                    else None,
                    "wall_ms": round(enh_ms, 1),
                    "enhancement_ms": round(enh_prep_ms, 1),
                    "segmentation_ms": round(enh_seg_ms, 1),
                    "recognition_ms": round(enh_rec_ms, 1),
                    "char_diff_enh_vs_unenh": levenshtein(raw_text, enh_text),
                    "char_diff_adaptive_vs_original": levenshtein(
                        enh_text, adapt_text
                    ),
                    "char_diff_mild_thicken_vs_original": levenshtein(
                        enh_text, mild_text
                    ),
                },
            }
        )

    return {
        "engine_id": "mishkefet-v1",
        "engine_name": engine.name,
        "measured": bool(corpus_pages),
        "pages_measured": len(corpus_pages),
        "peak_rss_mb": round(process_memory_mb() or 0.0, 2),
        "line_crop_recognition": line_crop_results,
        "line_segmentation_effect": seg_results,
        "real_unverified_scans": real_scan_results,
    }


def _run_kraken_experiments(
    engine,
    corpus_pages: list[tuple[str, Image.Image, str]],
    real_scans: list[tuple[str, str, Image.Image]],
    ci_fast: bool = False,
) -> dict[str, object]:
    import kraken.lib.ctc_decoder
    from kraken.configs import RecognitionInferenceConfig, SegmentationInferenceConfig
    from hebrew_workbench.engine.kraken_local import (
        _mean_confidence,
        script_masked_decoder,
    )

    engine._load_models()
    seg_cfg = SegmentationInferenceConfig(text_direction="horizontal-rl")
    decoder = kraken.lib.ctc_decoder.greedy_decoder
    if engine.restrict_script and engine._disallowed_labels:
        decoder = script_masked_decoder(decoder, engine._disallowed_labels)
    rec_cfg = RecognitionInferenceConfig(
        bidi_reordering=True,
        padding=16,
        num_line_workers=0,
        batch_size=1,
        decoder=decoder,
    )
    model_h = int(getattr(engine._recognition_model.net, "input", (1, 3, 96, 0))[2] or 96)

    line_crop_results: dict[str, dict[str, dict[str, object]]] = {
        "with_photocraft": {},
        "without_photocraft": {},
    }

    # Experiment A: Fixed blla segmentation, 6 stroke variants at exact Kraken model height
    if corpus_pages:
        for pc_enabled, pc_key in (
            (True, "with_photocraft"),
            (False, "without_photocraft"),
        ):
            if ci_fast:
                regimes_for_pass = REGIME_SPECS[:2] if pc_enabled else ()
            else:
                regimes_for_pass = REGIME_SPECS
            for reg_idx, (regime, reg_desc) in enumerate(regimes_for_pass):
                segmented_pages = []
                for p_idx, (page_id, orig_im, ref_text) in enumerate(corpus_pages):
                    reg_im = _synthesize_regime(
                        orig_im, regime, seed=100 * reg_idx + p_idx
                    )
                    prep_im, _ = prepare_page_for_ocr(reg_im, enabled=pc_enabled)
                    seg = engine._segmentation_model.predict(im=prep_im, config=seg_cfg)
                    segmented_pages.append((page_id, ref_text, prep_im, seg))

                variant_out: dict[str, object] = {}
                pages_gt = [(pid, ref) for pid, ref, _, _ in segmented_pages]
                orig_cer = 0.0
                orig_wer = 0.0
                for variant in STROKE_VARIANTS:
                    t0 = time.perf_counter()
                    preds: list[tuple[str, list[str], list[float], float]] = []
                    with _kraken_model_input_stroke_hook(variant):
                        for _pid, _ref, prep_im, seg in segmented_pages:
                            recs = list(
                                engine._recognition_model.predict(
                                    im=prep_im, segmentation=seg, config=rec_cfg
                                )
                            )
                            lines = [
                                (getattr(r, "prediction", "") or "").strip()
                                for r in recs
                                if (getattr(r, "prediction", "") or "").strip()
                            ]
                            confs = [
                                float(c)
                                for r in recs
                                if (getattr(r, "prediction", "") or "").strip()
                                for c in [_mean_confidence(r)]
                                if c is not None
                            ]
                            preds.append(("\n".join(lines), lines, confs, 0.0))
                    wall_ms = (time.perf_counter() - t0) * 1000.0
                    metrics = _evaluate_predictions(pages_gt, preds)
                    metrics["model_input_height_px"] = model_h
                    metrics["wall_ms"] = round(wall_ms, 1)
                    metrics["ms_per_page"] = round(
                        wall_ms / max(1, len(segmented_pages)), 1
                    )
                    if variant == "original":
                        orig_cer = float(metrics["macro_cer"])
                        orig_wer = float(metrics["macro_wer"])
                    metrics["delta_cer_pp_vs_original"] = round(
                        (float(metrics["macro_cer"]) - orig_cer) * 100.0, 2
                    )
                    metrics["delta_wer_pp_vs_original"] = round(
                        (float(metrics["macro_wer"]) - orig_wer) * 100.0, 2
                    )
                    variant_out[variant] = metrics
                    print(
                        f"[CROP][{engine.artifact_id}][{pc_key}][{regime}][{variant}] "
                        f"CER={metrics['macro_cer']*100:.2f}% ({metrics['delta_cer_pp_vs_original']:+.2f}pp) "
                        f"conf={metrics['mean_confidence']} {wall_ms:.0f}ms",
                        flush=True,
                    )
                line_crop_results[pc_key][regime] = {
                    "description": reg_desc,
                    "variants": variant_out,
                }

    # Experiment B: Page-level stroke variant BEFORE Kraken blla segmentation
    # Evaluate on verified_native_300dpi and pen_fine_nib to keep CPU time bounded
    seg_results: dict[str, object] = {}
    kraken_seg_regimes = (
        ("verified_native_300dpi",)
        if ci_fast
        else ("verified_native_300dpi", "pen_fine_nib")
    )
    if not corpus_pages:
        kraken_seg_regimes = ()
    for reg_idx, regime in enumerate(kraken_seg_regimes):
        base_pages = [
            (
                pid,
                ref,
                prepare_page_for_ocr(
                    _synthesize_regime(im, regime, seed=800 + 20 * reg_idx + i),
                    enabled=True,
                )[0],
            )
            for i, (pid, im, ref) in enumerate(corpus_pages)
        ]
        pages_gt = [(pid, ref) for pid, ref, _ in base_pages]
        var_seg: dict[str, object] = {}
        orig_cer = 0.0
        for variant in STROKE_VARIANTS:
            t0 = time.perf_counter()
            preds = []
            det_total = 0
            for _pid, _ref, prep_im in base_pages:
                page_var = (
                    prep_im
                    if variant == "original"
                    else apply_stroke_variant(prep_im, variant, page_scale=True)
                )
                seg = engine._segmentation_model.predict(im=page_var, config=seg_cfg)
                det_total += len(getattr(seg, "lines", []))
                recs = list(
                    engine._recognition_model.predict(
                        im=page_var, segmentation=seg, config=rec_cfg
                    )
                )
                lines = [
                    (getattr(r, "prediction", "") or "").strip()
                    for r in recs
                    if (getattr(r, "prediction", "") or "").strip()
                ]
                confs = [
                    float(c)
                    for r in recs
                    if (getattr(r, "prediction", "") or "").strip()
                    for c in [_mean_confidence(r)]
                    if c is not None
                ]
                preds.append(("\n".join(lines), lines, confs, 0.0))
            wall_ms = (time.perf_counter() - t0) * 1000.0
            metrics = _evaluate_predictions(pages_gt, preds)
            metrics["raw_segmented_boxes_total"] = det_total
            metrics["wall_ms"] = round(wall_ms, 1)
            if variant == "original":
                orig_cer = float(metrics["macro_cer"])
            metrics["delta_cer_pp_vs_original"] = round(
                (float(metrics["macro_cer"]) - orig_cer) * 100.0, 2
            )
            var_seg[variant] = metrics
        seg_results[regime] = var_seg

    # Experiment C: Real unverified scans (first 2 to bound Kraken blla time)
    real_scan_results: list[dict[str, object]] = []
    for scan_id, scan_desc, scan_im in real_scans[:2]:
        prep_im, enh_audit = prepare_page_for_ocr(scan_im, enabled=True)
        t0 = time.perf_counter()
        seg = engine._segmentation_model.predict(im=prep_im, config=seg_cfg)
        recs = list(
            engine._recognition_model.predict(
                im=prep_im, segmentation=seg, config=rec_cfg
            )
        )
        wall_ms = (time.perf_counter() - t0) * 1000.0
        lines = [
            (getattr(r, "prediction", "") or "").strip()
            for r in recs
            if (getattr(r, "prediction", "") or "").strip()
        ]
        real_scan_results.append(
            {
                "id": scan_id,
                "description": scan_desc,
                "ground_truth_available": False,
                "segmented_lines": len(getattr(seg, "lines", [])),
                "nonempty_recognized_lines": len(lines),
                "char_count": len("\n".join(lines)),
                "wall_ms": round(wall_ms, 1),
                "photocraft_enhanced": bool(
                    enh_audit is not None and enh_audit.needs_adjustment
                ),
            }
        )

    return {
        "engine_id": engine.artifact_id,
        "engine_name": engine.name,
        "measured": bool(corpus_pages),
        "pages_measured": len(corpus_pages),
        "peak_rss_mb": round(process_memory_mb() or 0.0, 2),
        "line_crop_recognition": line_crop_results,
        "line_segmentation_effect": seg_results,
        "real_unverified_scans": real_scan_results,
    }


def _load_real_scans(
    extra_scan_paths: list[str], fetch_public: bool, temp_dir: Path
) -> list[tuple[str, str, Image.Image]]:
    scans: list[tuple[str, str, Image.Image]] = []
    candidates: list[tuple[str, str, Path]] = []
    if DEFAULT_SMOKE_SCAN.is_file():
        candidates.append(
            (
                DEFAULT_SMOKE_SCAN.stem,
                "Contemporary Yeshiva cursive Hebrew notebook scan (unverified)",
                DEFAULT_SMOKE_SCAN,
            )
        )
    for raw_p in extra_scan_paths:
        p = Path(raw_p)
        if p.is_file():
            candidates.append(
                (p.stem, f"Supplied contemporary scan ({p.name}, unverified)", p)
            )

    if fetch_public:
        for scan_id, desc, api_url in PUBLIC_REAL_SCANS:
            try:
                req = urllib.request.Request(
                    api_url,
                    headers={
                        "Accept": "application/vnd.github.raw+json",
                        "User-Agent": "hebrew-notes-workbench-benchmark",
                    },
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()
                dst = temp_dir / scan_id
                dst.write_bytes(data)
                candidates.append((Path(scan_id).stem, desc, dst))
            except Exception as exc:
                print(
                    f"[WARN] Could not fetch optional real scan {scan_id}: {exc}",
                    file=sys.stderr,
                )

    for scan_id, desc, path in candidates:
        try:
            with DocumentPreview(path) as prev:
                im = prev.render(1, dpi=300).image.convert("RGB")
                im.load()
                scans.append((scan_id, desc, im))
        except Exception as exc:
            print(
                f"[WARN] Could not render real scan {path}: {exc}",
                file=sys.stderr,
            )
    return scans


def _load_verified_corpus_pages(
    corpus_dir: Path,
) -> tuple[list[tuple[str, Image.Image, str]], int, int]:
    """Load only verified, ground-truth-complete pages for CER/WER measurement."""
    corpus = load_corpus(corpus_dir)
    total_pages = len(corpus.pages)
    measured = corpus.measured_pages
    loaded: list[tuple[str, Image.Image, str]] = []
    for page in measured:
        im = Image.open(page.image).convert("RGB")
        im.load()
        loaded.append((page.image.stem, im, page.text))
    return loaded, total_pages, len(measured)


def _run_child_engine(
    engine_id: str,
    corpus_dir: Path,
    models_folder: Path,
    extra_scans: list[str],
    fetch_public: bool,
    ci_fast: bool = False,
    child_timeout: int = 3600,
) -> dict[str, object]:
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--in-process",
        "--engines",
        engine_id,
        "--models",
        str(models_folder),
        "--corpus",
        str(corpus_dir),
    ]
    for s in extra_scans:
        cmd.extend(["--extra-scan", s])
    if fetch_public:
        cmd.append("--fetch-public-real-scans")
    if ci_fast:
        cmd.append("--ci-fast")

    with tempfile.NamedTemporaryFile(
        prefix=f"sw-bench-{engine_id}-", suffix=".json", delete=False
    ) as tmp:
        out_path = Path(tmp.name)
    cmd.extend(["--single-engine-output", str(out_path)])
    try:
        subprocess.run(cmd, check=True, timeout=child_timeout)
        return json.loads(out_path.read_text(encoding="utf-8"))
    finally:
        out_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument(
        "--models",
        help="folder containing downloaded model weights (default: models_directory())",
    )
    parser.add_argument("--output", help="write full JSON report to this path")
    parser.add_argument(
        "--engines",
        nargs="+",
        default=[],
        help="engine artifact IDs to benchmark (default: mishkefet-v1 kraken-ppocrv6-small)",
    )
    parser.add_argument(
        "--engine-id",
        action="append",
        default=[],
        help="alias for --engines",
    )
    parser.add_argument(
        "--extra-scan",
        action="append",
        default=[],
        help="additional real unverified scan path(s) (PDF/PNG/JPG) for non-GT diagnostics",
    )
    parser.add_argument(
        "--fetch-public-real-scans",
        action="store_true",
        help="temporarily fetch 3 public HeOCR/hash archival scans into a temp dir for non-GT diagnostics",
    )
    parser.add_argument(
        "--ci-fast",
        action="store_true",
        help="run representative regime subset on Kraken/unenhanced passes for fast CI turnaround",
    )
    parser.add_argument(
        "--child-timeout",
        type=int,
        default=3600,
        help="timeout in seconds per isolated engine child process (default: 3600)",
    )
    parser.add_argument(
        "--in-process",
        action="store_true",
        help="run inside current process (used internally by isolated child-process runner)",
    )
    parser.add_argument(
        "--single-engine-output",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)

    corpus_dir = Path(args.corpus)
    models_folder = Path(args.models) if args.models else models_directory()
    requested_ids = (
        list(args.engines) + list(args.engine_id)
    ) or ["mishkefet-v1", "kraken-ppocrv6-small"]
    installed_ids, warnings = _filter_installed_engine_ids(
        requested_ids, models_folder
    )

    if args.single_engine_output:
        if len(installed_ids) != 1:
            raise SystemExit(
                f"Expected 1 installed engine for child run, got {installed_ids}"
            )
        corpus_pages, _total_p, _meas_p = _load_verified_corpus_pages(corpus_dir)

        with tempfile.TemporaryDirectory(prefix="real-scans-") as td:
            real_scans = _load_real_scans(
                args.extra_scan, args.fetch_public_real_scans, Path(td)
            )
            engines_with_labels, _ = resolve_engines(installed_ids, models_folder)
            if not engines_with_labels:
                raise SystemExit(f"Engine {installed_ids[0]} unavailable")
            eng = engines_with_labels[0][0]
            if getattr(eng, "artifact_id", "") == "mishkefet-v1":
                res = _run_mishkefet_experiments(
                    eng, corpus_pages, real_scans, ci_fast=args.ci_fast
                )
            else:
                res = _run_kraken_experiments(
                    eng, corpus_pages, real_scans, ci_fast=args.ci_fast
                )
        Path(args.single_engine_output).write_text(
            json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return 0

    corpus_meta_pages, total_corpus_pages, measured_corpus_pages = (
        _load_verified_corpus_pages(corpus_dir)
    )
    report: dict[str, object] = {
        "benchmark": "stroke_width_and_real_scans",
        "evaluation_normalization": "hebrew_workbench.benchmark.metrics.normalise",
        "corpus": {
            "path": str(corpus_dir),
            "pages_total": total_corpus_pages,
            "pages_measured": measured_corpus_pages,
            "accuracy_available": measured_corpus_pages > 0,
        },
        "memory_measurement": (
            "in_process" if args.in_process else "isolated_process_per_engine"
        ),
        "inference_stroke_compensation_audit": audit_inference_stroke_compensation(),
        "variants_tested": [
            {"id": v, "description": STROKE_VARIANT_DESCRIPTIONS[v]}
            for v in STROKE_VARIANTS
        ],
        "regimes_tested": [
            {"id": r, "description": d} for r, d in REGIME_SPECS
        ],
        "warnings": warnings,
        "engines": {},
        "engine_failures": {},
    }
    if measured_corpus_pages == 0:
        report["accuracy_note"] = (
            "Corpus contains 0 verified ground-truth-complete pages; "
            "CER/WER experiments skipped."
        )

    if not installed_ids:
        report["note"] = (
            "No recognition model weights installed locally; inference audit and "
            "deterministic stroke-width operators verified."
        )
    elif args.in_process:
        with tempfile.TemporaryDirectory(prefix="real-scans-") as td:
            real_scans = _load_real_scans(
                args.extra_scan, args.fetch_public_real_scans, Path(td)
            )
            engines_with_labels, _ = resolve_engines(installed_ids, models_folder)
            for eng, label in engines_with_labels:
                eid = getattr(eng, "artifact_id", label)
                if eid == "mishkefet-v1":
                    report["engines"][eid] = _run_mishkefet_experiments(  # type: ignore[index]
                        eng, corpus_meta_pages, real_scans, ci_fast=args.ci_fast
                    )
                else:
                    report["engines"][eid] = _run_kraken_experiments(  # type: ignore[index]
                        eng, corpus_meta_pages, real_scans, ci_fast=args.ci_fast
                    )
    else:
        del corpus_meta_pages
        for eid in installed_ids:
            try:
                report["engines"][eid] = _run_child_engine(  # type: ignore[index]
                    eid,
                    corpus_dir,
                    models_folder,
                    args.extra_scan,
                    args.fetch_public_real_scans,
                    ci_fast=args.ci_fast,
                    child_timeout=args.child_timeout,
                )
            except subprocess.TimeoutExpired:
                msg = f"Isolated benchmark child timed out after {args.child_timeout}s"
                print(f"[ERROR] {eid}: {msg}", file=sys.stderr, flush=True)
                report["engine_failures"][eid] = msg  # type: ignore[index]
            except Exception as exc:
                msg = f"Isolated benchmark child failed: {exc}"
                print(f"[ERROR] {eid}: {msg}", file=sys.stderr, flush=True)
                report["engine_failures"][eid] = msg  # type: ignore[index]

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        print(f"Wrote stroke-width benchmark report to {out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
