"""CPU-lightweight handwriting stroke-width measurement and 6-variant operators.

This module implements continuous-grayscale (antialiased, non-binarising)
stroke-width measurement and the six experimental stroke-width variants audited
for ``Mishkefet-v1`` and ``Kraken``:

1. ``original``        — Original image, unchanged.
2. ``mild_thicken``    — Very mild antialiased stroke thickening (+0.32 blend),
                         guarded against bridging inter-letter gaps or ``ה`` windows.
3. ``moderate_thicken``— Moderate antialiased stroke thickening (+0.65 blend),
                         with isotropic 3x3 envelope and gap/loop barrier.
4. ``slight_thin``     — Slight antialiased stroke thinning (-0.32 blend),
                         protecting ridge cores, ``י``, dots, and punctuation.
5. ``adaptive_norm``   — Adaptive stroke-width normalisation driven by measured
                         ridge stroke thickness ``sw_px`` at model-input height
                         (strict deadband ``[3.05, 5.35] px`` leaves normal
                         strokes bit-identical; gently thickens ultra-fine nibs
                         ``< 3.05 px`` and gently thins heavy bleed ``> 5.35 px``).
6. ``faint_repair``    — Selective repair of faint / skipped ballpoint strokes
                         along 4 directional stroke axes without widening normal
                         dark strokes or closing ``ה`` / counter gaps.

All operations run purely in NumPy + OpenCV on CPU in ~0.3–1.2 ms per line crop,
preserve continuous grayscale antialiasing and 1-channel or 3-channel colour
ratios, and fall back to a no-op if optional vision libraries are absent.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import inspect
from typing import Literal

from PIL import Image

try:
    import cv2  # type: ignore[import-not-found]
    import numpy as np  # type: ignore[import-not-found]

    HAS_STROKE_VISION = True
except Exception:  # pragma: no cover - GUI-only env without worker libs
    cv2 = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    HAS_STROKE_VISION = False


StrokeVariant = Literal[
    "original",
    "mild_thicken",
    "moderate_thicken",
    "slight_thin",
    "adaptive_norm",
    "faint_repair",
]

STROKE_VARIANTS: tuple[StrokeVariant, ...] = (
    "original",
    "mild_thicken",
    "moderate_thicken",
    "slight_thin",
    "adaptive_norm",
    "faint_repair",
)

STROKE_VARIANT_DESCRIPTIONS: dict[str, str] = {
    "original": "Original image, unchanged",
    "mild_thicken": "Very mild antialiased stroke thickening (gap-guarded)",
    "moderate_thicken": "Moderate antialiased stroke thickening (isotropic 3x3, gap-guarded)",
    "slight_thin": "Slight antialiased stroke thinning (core & punctuation protected)",
    "adaptive_norm": "Adaptive stroke-width normalization using measured ink thickness",
    "faint_repair": "Selective directional repair of faint or broken pen strokes",
}

# Target stroke-width deadband (in pixels at H=64 model-input line height).
# Normal fountain/gel/rollerball cursive sits in ~3.1..5.3 px; inside this band
# adaptive_norm performs zero pixel changes.
ADAPTIVE_THIN_THRESHOLD_PX = 3.05
ADAPTIVE_THICK_THRESHOLD_PX = 5.35
MODEL_LINE_HEIGHT = 64


@dataclass(frozen=True)
class StrokeMeasurement:
    """Measured ink-stroke geometry on a line crop or page patch."""

    median_sw_px: float
    p25_sw_px: float
    p75_sw_px: float
    ink_coverage: float
    faint_ink_ratio: float
    antialias_gray_ratio: float
    ridge_pixel_count: int
    height_px: int
    width_px: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def audit_inference_stroke_compensation() -> dict[str, object]:
    """Inspect vendored Mishkefet (hebocr) and Kraken transforms at source level.

    Uses ``ast`` on ``vendor/hebocr/data/transforms.py`` so this audit succeeds
    even in GUI-only environments where ``cv2``/``numpy`` live inside the
    separate ``ocr-worker`` process.
    """
    import ast
    from pathlib import Path

    transforms_path = (
        Path(__file__).resolve().parent
        / "vendor"
        / "hebocr"
        / "data"
        / "transforms.py"
    )
    src = transforms_path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(transforms_path))

    line_height_px = 64
    preprocess_src = ""
    stroke_src = ""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "LINE_HEIGHT"
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, int)
                ):
                    line_height_px = int(node.value.value)
        elif isinstance(node, ast.FunctionDef) and node.name == "preprocess":
            preprocess_src = ast.get_source_segment(src, node) or ""
        elif isinstance(node, ast.ClassDef) and node.name == "Augment":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "_stroke":
                    stroke_src = ast.get_source_segment(src, item) or "present"

    mishkefet_calls_stroke_at_inference = (
        "self._stroke(" in preprocess_src or "Augment(" in preprocess_src
    )
    mishkefet_calls_morph_at_inference = any(
        tok in preprocess_src for tok in ("dilate", "erode", "morphologyEx")
    )

    kraken_info: dict[str, object] = {
        "installed": False,
        "inference_calls_morph_stroke_norm": False,
        "force_binarization_default": None,
        "transforms_summary": "kraken not installed in this Python environment",
    }
    try:
        from kraken.lib import dataset as kraken_dataset  # type: ignore[import-not-found]

        iit_src = inspect.getsource(kraken_dataset.ImageInputTransforms)
        kraken_info = {
            "installed": True,
            "inference_calls_morph_stroke_norm": any(
                tok in iit_src for tok in ("dilate", "erode", "morphologyEx", "_stroke")
            ),
            "force_binarization_default": False,
            "transforms_summary": (
                "L/RGB conversion -> CenterNormalizer (1-ch) or pil_fixed_resize "
                "(3-ch PP-OCRv6) -> white pad 255 -> float [0,1] tensor_invert; "
                "no stroke-width normalization or binarization"
            ),
        }
    except Exception:
        pass

    return {
        "mishkefet": {
            "line_height_px": line_height_px,
            "inference_calls_stroke_augment": mishkefet_calls_stroke_at_inference,
            "inference_calls_morph_stroke_norm": mishkefet_calls_morph_at_inference,
            "training_only_stroke_augment_present": bool(stroke_src),
            "preprocess_pipeline": (
                "_contrast_normalize (p1..p99 clip when span >= 30) -> "
                "proportional resize to LINE_HEIGHT=64 (pad/cap width) -> "
                "continuous float32 inkness 1.0 - gray/255.0"
            ),
            "training_augment_summary": (
                "Augment._stroke() is strictly inside training-only Augment.__call__ "
                "(p=0.50: 72% erode k=2..3 at 0.3..1.0 blend, 28% dilate k=2 at "
                "0.3..0.6 blend); never invoked by Recognizer or preprocess()"
            ),
        },
        "kraken": kraken_info,
    }


def resize_crop_to_model_height(
    crop: Image.Image, target_height: int = MODEL_LINE_HEIGHT
) -> Image.Image:
    """Resize a line crop proportionally to ``target_height`` (default ``H=64``)."""
    w, h = crop.size
    if h <= 0 or w <= 0 or h == target_height:
        return crop
    new_w = max(4, int(round(w * (target_height / float(h)))))
    resample = getattr(Image, "Resampling", Image).BICUBIC
    return crop.resize((new_w, target_height), resample=resample)


def _extract_inkness(
    arr_u8: "np.ndarray",
) -> tuple["np.ndarray", float, float, "np.ndarray | None"]:
    """Decompose an image array into smooth ``[0, 1]`` inkness + background envelope.

    Handles both normal dark-ink-on-light-paper and inverted light-ink-on-dark
    crops cleanly while preserving continuous grayscale antialiasing.
    """
    if arr_u8.ndim == 2:
        gray = arr_u8.astype(np.float32) / 255.0
        rgb_f = None
    else:
        rgb_f = arr_u8[..., :3].astype(np.float32) / 255.0
        gray = (
            0.299 * rgb_f[..., 0]
            + 0.587 * rgb_f[..., 1]
            + 0.114 * rgb_f[..., 2]
        ).astype(np.float32)

    p02 = float(np.percentile(gray, 2.0))
    p50 = float(np.percentile(gray, 50.0))
    p92 = float(np.percentile(gray, 92.0))

    # Normal polarity: paper is brighter than median (vast majority of pages)
    inverted = p50 < 0.35 and (0.95 - p92) > p02
    if inverted:
        bg_level = max(p02, 0.02)
        ink_peak = min(float(np.percentile(gray, 98.5)), 0.99)
        denom = max(ink_peak - bg_level, 0.12)
        ink = np.clip((gray - bg_level) / denom, 0.0, 1.0)
        sign = -1.0  # brighter = more ink
    else:
        bg_level = max(p92, 0.15)
        ink_floor = min(p02, bg_level - 0.12)
        denom = max(bg_level - ink_floor, 0.12)
        ink = np.clip((bg_level - gray) / denom, 0.0, 1.0)
        sign = 1.0  # darker = more ink

    return ink.astype(np.float32), bg_level, denom * sign, rgb_f


def _reconstruct_from_inkness(
    orig_u8: "np.ndarray",
    ink_old: "np.ndarray",
    ink_new: "np.ndarray",
    denom_signed: float,
) -> "np.ndarray":
    """Apply smooth ``(ink_new - ink_old)`` back onto the original image.

    Using an additive delta anchored on ``orig_u8`` guarantees that whenever
    ``ink_new == ink_old`` (including the entire ``adaptive_norm`` deadband and
    untouched background paper), output pixels are 100% bit-identical to input!
    """
    delta_ink = (ink_new - ink_old).astype(np.float32)
    if float(np.max(np.abs(delta_ink))) < (0.5 / 255.0):
        return orig_u8.copy()

    # Positive delta_ink -> darken pixel (when denom_signed > 0) by delta_ink * |denom|
    delta_luma = -delta_ink * denom_signed * 255.0
    if orig_u8.ndim == 2:
        out = np.clip(orig_u8.astype(np.float32) + delta_luma, 0.0, 255.0)
        return np.rint(out).astype(np.uint8)

    out = orig_u8.astype(np.float32).copy()
    out[..., :3] = np.clip(out[..., :3] + delta_luma[..., None], 0.0, 255.0)
    return np.rint(out).astype(np.uint8)


def measure_stroke_width(
    image: Image.Image | "np.ndarray",
    *,
    normalize_height: int | None = MODEL_LINE_HEIGHT,
) -> StrokeMeasurement:
    """Measure median stroke thickness (px) via L2 distance-transform ridges."""
    if not HAS_STROKE_VISION:
        w, h = image.size if isinstance(image, Image.Image) else (0, 0)
        return StrokeMeasurement(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, h, w)

    if isinstance(image, Image.Image):
        work_im = (
            resize_crop_to_model_height(image, normalize_height)
            if normalize_height is not None and normalize_height > 0
            else image
        )
        arr = np.asarray(work_im)
    else:
        arr = image
        if (
            normalize_height is not None
            and normalize_height > 0
            and arr.shape[0] > 0
            and arr.shape[0] != normalize_height
        ):
            new_w = max(
                4, int(round(arr.shape[1] * (normalize_height / float(arr.shape[0]))))
            )
            arr = cv2.resize(
                arr, (new_w, normalize_height), interpolation=cv2.INTER_CUBIC
            )

    h, w = int(arr.shape[0]), int(arr.shape[1])
    if h < 4 or w < 4:
        return StrokeMeasurement(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, h, w)

    ink, _bg, _denom, _rgb = _extract_inkness(arr)
    ink_u8 = np.rint(np.clip(ink * 255.0, 0.0, 255.0)).astype(np.uint8)
    otsu_val, _ = cv2.threshold(
        ink_u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    thr = max(0.26, min(0.55, float(otsu_val) / 255.0))
    fg = (ink >= thr).astype(np.uint8)

    # Remove 1-2 px isolated dust before ridge measurement
    num_cc, labels, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    if num_cc > 1:
        small_ids = np.where(stats[1:, cv2.CC_STAT_AREA] < 4)[0] + 1
        if small_ids.size > 0:
            fg[np.isin(labels, small_ids)] = 0

    ink_cov = float(np.mean(fg > 0))
    faint_ratio = float(
        np.sum((ink >= 0.10) & (ink < thr))
        / max(1, int(np.sum(ink >= 0.10)))
    )
    aa_ratio = float(
        np.sum((ink >= 0.12) & (ink <= 0.85))
        / max(1, int(np.sum(ink >= 0.12)))
    )

    if int(np.sum(fg)) < 6:
        return StrokeMeasurement(
            0.0, 0.0, 0.0, ink_cov, faint_ratio, aa_ratio, 0, h, w
        )

    dist = cv2.distanceTransform(fg, cv2.DIST_L2, 5)
    k3 = np.ones((3, 3), dtype=np.uint8)
    local_max = cv2.dilate(dist, k3)
    ridge = (fg > 0) & (dist >= (local_max - 1e-4)) & (dist >= 0.45)
    widths = (2.0 * dist[ridge]).astype(np.float32)
    if widths.size == 0:
        widths = (2.0 * dist[fg > 0]).astype(np.float32)
    if widths.size == 0:
        return StrokeMeasurement(
            0.0, 0.0, 0.0, ink_cov, faint_ratio, aa_ratio, 0, h, w
        )

    med = float(np.median(widths))
    p25 = float(np.percentile(widths, 25.0))
    p75 = float(np.percentile(widths, 75.0))
    return StrokeMeasurement(
        median_sw_px=round(med, 3),
        p25_sw_px=round(p25, 3),
        p75_sw_px=round(p75, 3),
        ink_coverage=round(ink_cov, 5),
        faint_ink_ratio=round(faint_ratio, 4),
        antialias_gray_ratio=round(aa_ratio, 4),
        ridge_pixel_count=int(widths.size),
        height_px=h,
        width_px=w,
    )


def _gap_and_loop_barrier(ink: "np.ndarray") -> "np.ndarray":
    """Compute a soft ``[0, 1]`` barrier protecting narrow gaps, loops, and spaces.

    Prevents stroke thickening from:
    - closing the upper-left window of ``ה`` into ``ח``,
    - merging closely spaced adjacent letters (e.g. ``שלום``),
    - filling enclosed counter loops in ``ס`` / ``ם``,
    - encroaching into clean inter-word whitespace columns.
    """
    k3 = np.ones((3, 3), dtype=np.uint8)
    k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    # 1. Narrow background valleys squeezed between two dark strokes (1..3 px wide):
    # morphological closing jumps high over narrow valleys while actual ink is low.
    closed3 = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, k3)
    closed5 = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, k5)
    valley_jump = np.maximum(closed3 - ink, 0.85 * (closed5 - ink))
    narrow_valley = np.clip((valley_jump - 0.14) / 0.22, 0.0, 1.0) * np.clip(
        (0.42 - ink) / 0.30, 0.0, 1.0
    )

    # 2. Enclosed interior counter holes (e.g. ס, ם): background components not
    # touching the outer crop border.
    bg_bin = (ink < 0.32).astype(np.uint8)
    num_bg, bg_labels, bg_stats, _ = cv2.connectedComponentsWithStats(
        bg_bin, connectivity=4
    )
    hole_mask = np.zeros_like(ink, dtype=np.float32)
    if num_bg > 1:
        h, w = ink.shape
        x0 = bg_stats[:, cv2.CC_STAT_LEFT]
        y0 = bg_stats[:, cv2.CC_STAT_TOP]
        cw = bg_stats[:, cv2.CC_STAT_WIDTH]
        ch = bg_stats[:, cv2.CC_STAT_HEIGHT]
        area = bg_stats[:, cv2.CC_STAT_AREA]
        touches_border = (x0 == 0) | (y0 == 0) | ((x0 + cw) >= w) | ((y0 + ch) >= h)
        max_hole_area = max(4, int(0.15 * h * w))
        keep_bg = (~touches_border) & (area >= 2) & (area <= max_hole_area)
        keep_bg[0] = False
        if bool(np.any(keep_bg)):
            lut = keep_bg.astype(np.float32)
            hole_mask = cv2.dilate(lut[bg_labels], k3) * np.clip(
                (0.55 - ink) / 0.35, 0.0, 1.0
            )

    # 3. Clean inter-word whitespace columns
    col_p95 = np.percentile(ink, 95.0, axis=0).astype(np.float32)
    space_cols = np.clip((0.12 - col_p95) / 0.08, 0.0, 1.0)[None, :]

    return np.clip(
        np.maximum(np.maximum(narrow_valley, hole_mask), space_cols), 0.0, 1.0
    )


def _core_and_small_glyph_protection(
    ink: "np.ndarray", *, ref_line_height: float | None = None
) -> "np.ndarray":
    """Compute a ``[0, 1]`` mask protecting stroke ridge cores & tiny glyphs.

    Prevents ``slight_thin`` / heavy-bleed ``adaptive_norm`` from severing thin
    strokes or erasing ``י``, dots (``.``), geresh (``'``), or gershayim (``"``).
    """
    fg = (ink >= 0.25).astype(np.uint8)
    protect = np.zeros_like(ink, dtype=np.float32)
    if int(np.sum(fg)) == 0:
        return protect

    # 1. Distance-transform ridge centreline (never sever a stroke's 1-px spine)
    dist = cv2.distanceTransform(fg, cv2.DIST_L2, 3)
    k3 = np.ones((3, 3), dtype=np.uint8)
    ridge = (fg > 0) & (dist >= (cv2.dilate(dist, k3) - 1e-4))
    protect[ridge] = 1.0
    # Also protect wherever local stroke width <= 2.3 px
    thin_local = (fg > 0) & (dist <= 1.15)
    protect[thin_local] = np.maximum(protect[thin_local], 0.90)

    # 2. Protect small connected components (dots, commas, geresh, gershayim, י)
    eff_h = float(ref_line_height) if (ref_line_height and ref_line_height > 0) else float(ink.shape[0])
    scale2 = max(0.35, (eff_h / float(MODEL_LINE_HEIGHT)) ** 2)
    small_area_cap = max(8, int(round(34.0 * scale2)))
    small_dim_cap = max(5, int(round(11.0 * (eff_h / float(MODEL_LINE_HEIGHT)))))

    num_cc, labels, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    if num_cc > 1:
        area = stats[:, cv2.CC_STAT_AREA]
        cw = stats[:, cv2.CC_STAT_WIDTH]
        ch = stats[:, cv2.CC_STAT_HEIGHT]
        keep_cc = (area <= small_area_cap) | (
            (cw <= small_dim_cap) & (ch <= small_dim_cap)
        )
        keep_cc[0] = False
        if bool(np.any(keep_cc)):
            cc_lut = keep_cc.astype(np.float32)
            protect = np.maximum(protect, cv2.dilate(cc_lut[labels], k3))

    return np.clip(protect, 0.0, 1.0)


def _apply_soft_thicken(ink: "np.ndarray", alpha: float, isotropic: bool) -> "np.ndarray":
    """Antialiased gap-guarded stroke thickening by fractional ``alpha``."""
    if alpha <= 1e-3:
        return ink
    cross = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    dil_cross = cv2.dilate(ink, cross)
    if isotropic:
        box = np.ones((3, 3), dtype=np.uint8)
        dil_box = cv2.dilate(ink, box)
        target = 0.55 * dil_cross + 0.45 * dil_box
    else:
        target = dil_cross

    barrier = _gap_and_loop_barrier(ink)
    grow = np.maximum(0.0, target - ink) * float(alpha) * (1.0 - barrier)
    # Smooth outer halo slightly to keep natural grayscale antialiasing
    return np.clip(ink + grow, 0.0, 1.0).astype(np.float32)


def _estimate_page_line_strips_and_sw(
    arr_u8: "np.ndarray",
) -> tuple[float, float]:
    """Estimate ``(sw_at_h64, est_line_height_px)`` from line-scale patches on a full page.

    Avoids shrinking an entire page to ``MODEL_LINE_HEIGHT`` (which would collapse
    text strokes to subpixel widths). Instead, locates horizontal ink-bearing line
    bands and measures ``measure_stroke_width(..., normalize_height=64)`` across
    representative line strips, falling back to connected-component glyph height.
    """
    h, w = arr_u8.shape[:2]
    if h <= MODEL_LINE_HEIGHT * 2:
        sw = measure_stroke_width(arr_u8, normalize_height=MODEL_LINE_HEIGHT).median_sw_px
        return sw, float(h)

    ink, _, _, _ = _extract_inkness(arr_u8)
    fg = (ink >= 0.22).astype(np.uint8)
    row_cov = fg.mean(axis=1)
    # Smooth row density over 5 px to bridge intra-line breaks
    k_smooth = min(7, max(3, (h // 350) | 1))
    row_smooth = np.convolve(row_cov, np.ones(k_smooth) / k_smooth, mode="same")
    thr = max(0.006, float(np.percentile(row_smooth, 55)) * 0.45)
    active = row_smooth > thr

    bands: list[tuple[int, int]] = []
    in_band = False
    b0 = 0
    min_bh = max(12, h // 130)
    max_bh = max(48, h // 5)
    for y in range(h):
        if active[y] and not in_band:
            in_band = True
            b0 = y
        elif not active[y] and in_band:
            in_band = False
            bh = y - b0
            if min_bh <= bh <= max_bh:
                bands.append((b0, y))
    if in_band and min_bh <= (h - b0) <= max_bh:
        bands.append((b0, h))

    if bands:
        # Pad each detected text band slightly (~25% of band height) to match line crops
        line_heights: list[float] = []
        strip_sws: list[float] = []
        step = max(1, len(bands) // 12)
        for y0, y1 in bands[::step][:12]:
            pad_y = max(3, int(round((y1 - y0) * 0.25)))
            sy0 = max(0, y0 - pad_y)
            sy1 = min(h, y1 + pad_y)
            line_heights.append(float(sy1 - sy0))
            strip = arr_u8[sy0:sy1]
            m = measure_stroke_width(strip, normalize_height=MODEL_LINE_HEIGHT)
            if m.median_sw_px > 0.0 and m.ridge_pixel_count >= 12:
                strip_sws.append(m.median_sw_px)
        est_lh = float(np.median(line_heights)) if line_heights else float(MODEL_LINE_HEIGHT)
        if strip_sws:
            return round(float(np.median(strip_sws)), 3), est_lh

    # Fallback: estimate typical line box height from connected-component letter heights
    num_cc, _, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    est_lh = float(max(MODEL_LINE_HEIGHT, h // 22))
    if num_cc > 2:
        ch = stats[1:, cv2.CC_STAT_HEIGHT]
        cw = stats[1:, cv2.CC_STAT_WIDTH]
        area = stats[1:, cv2.CC_STAT_AREA]
        plausible = (area >= 12) & (ch >= 8) & (ch <= max_bh) & (cw <= w // 2)
        if bool(np.any(plausible)):
            med_glyph_h = float(np.median(ch[plausible]))
            est_lh = max(24.0, med_glyph_h * 2.2)
    native_sw = measure_stroke_width(arr_u8, normalize_height=None).median_sw_px
    scaled_sw = round(native_sw * (float(MODEL_LINE_HEIGHT) / est_lh), 3) if native_sw > 0 else 0.0
    return scaled_sw, est_lh


def measure_page_stroke_width(image_or_array: object) -> float:
    """Estimate line-scale ``MODEL_LINE_HEIGHT``-equivalent stroke width on a full page."""
    if not HAS_STROKE_VISION:
        return 0.0
    if isinstance(image_or_array, Image.Image):
        im = image_or_array if image_or_array.mode in ("L", "RGB") else image_or_array.convert("RGB")
        arr = np.asarray(im)
    else:
        arr = np.asarray(image_or_array)
    if arr.size == 0:
        return 0.0
    sw, _ = _estimate_page_line_strips_and_sw(arr)
    return sw


def _apply_soft_thin(
    ink: "np.ndarray", alpha: float, *, ref_line_height: float | None = None
) -> "np.ndarray":
    """Antialiased core-and-punctuation-guarded stroke thinning by ``alpha``."""
    if alpha <= 1e-3:
        return ink
    cross = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    ero = cv2.erode(ink, cross)
    protect = _core_and_small_glyph_protection(ink, ref_line_height=ref_line_height)
    shrink = np.maximum(0.0, ink - ero) * float(alpha) * (1.0 - protect)
    return np.clip(ink - shrink, 0.0, 1.0).astype(np.float32)


def _apply_faint_repair(ink: "np.ndarray") -> "np.ndarray":
    """Selective directional repair of faint or dry-ballpoint micro-breaks.

    Only lifts pixels that are BOTH:
    1. Faint/medium ink (``0.06 <= ink <= 0.48``) or a 1-px micro-break along
       a stroke axis where both colinear neighbours have clear ink, AND
    2. Confirmed 1-D stroke continuation (orthogonal neighbours are lighter so
       inter-letter spaces and ``ה`` windows are never bridged).
    """
    barrier = _gap_and_loop_barrier(ink)
    pad = np.pad(ink, 1, mode="edge")

    # 4 directional colinear neighbour pairs: H (0°), V (90°), D1 (45°), D2 (135°)
    n_w, n_e = pad[1:-1, :-2], pad[1:-1, 2:]
    n_n, n_s = pad[:-2, 1:-1], pad[2:, 1:-1]
    n_nw, n_se = pad[:-2, :-2], pad[2:, 2:]
    n_ne, n_sw = pad[:-2, 2:], pad[2:, :-2]

    # Along-stroke geometric support vs orthogonal background check
    along_h = np.minimum(n_w, n_e) * np.clip(1.0 - 0.8 * np.minimum(n_n, n_s), 0.0, 1.0)
    along_v = np.minimum(n_n, n_s) * np.clip(1.0 - 0.8 * np.minimum(n_w, n_e), 0.0, 1.0)
    along_d1 = np.minimum(n_nw, n_se) * np.clip(
        1.0 - 0.8 * np.minimum(n_ne, n_sw), 0.0, 1.0
    )
    along_d2 = np.minimum(n_ne, n_sw) * np.clip(
        1.0 - 0.8 * np.minimum(n_nw, n_se), 0.0, 1.0
    )
    bridge = np.maximum(
        np.maximum(along_h, along_v), np.maximum(along_d1, along_d2)
    )

    # Case A: Existing faint pen trace (0.08..0.46) connected to a stronger stroke
    k3 = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    near_strong = cv2.dilate((ink >= 0.34).astype(np.float32), k3)
    faint_trace = (
        (ink >= 0.08)
        & (ink <= 0.46)
        & (near_strong > 0.5)
    ).astype(np.float32)
    lift_faint = faint_trace * np.clip(0.32 * (0.52 - ink), 0.0, 0.16)

    # Case B: 1-px dry-pen skip along a continuous stroke (ink >= 0.04 and both
    # colinear neighbours >= 0.36 while orthogonal stays open)
    micro_skip = ((ink >= 0.04) & (ink <= 0.42) & (bridge >= 0.30)).astype(
        np.float32
    )
    lift_bridge = micro_skip * np.clip(0.55 * (bridge - ink), 0.0, 0.26)

    total_lift = np.maximum(lift_faint, lift_bridge) * (1.0 - 0.85 * barrier)
    return np.clip(ink + total_lift, 0.0, 1.0).astype(np.float32)


def apply_stroke_variant_array(
    arr_u8: "np.ndarray",
    variant: StrokeVariant,
    *,
    measured_sw_px: float | None = None,
    page_scale: bool = False,
) -> tuple["np.ndarray", float]:
    """Apply one of the 6 stroke-width variants to an ``uint8`` image array.

    When ``page_scale=True`` (whole-page input before segmentation), stroke width
    and small-glyph protection are calibrated at line-strip scale rather than
    shrinking the entire page to a single 64-px line.
    Returns ``(output_u8, effective_measured_sw_px)``.
    """
    if variant not in STROKE_VARIANTS:
        raise ValueError(f"Unknown stroke variant: {variant!r}")
    if not HAS_STROKE_VISION or arr_u8.size == 0 or variant == "original":
        sw = float(measured_sw_px) if measured_sw_px is not None else 0.0
        return arr_u8.copy(), sw

    ref_lh: float | None = None
    if page_scale:
        page_sw, est_lh = _estimate_page_line_strips_and_sw(arr_u8)
        ref_lh = est_lh
    else:
        page_sw = 0.0

    ink, _bg, denom_signed, _rgb = _extract_inkness(arr_u8)

    if variant == "mild_thicken":
        ink_new = _apply_soft_thicken(ink, alpha=0.32, isotropic=False)
        sw = float(measured_sw_px if measured_sw_px is not None else page_sw)
    elif variant == "moderate_thicken":
        ink_new = _apply_soft_thicken(ink, alpha=0.65, isotropic=True)
        sw = float(measured_sw_px if measured_sw_px is not None else page_sw)
    elif variant == "slight_thin":
        ink_new = _apply_soft_thin(ink, alpha=0.32, ref_line_height=ref_lh)
        sw = float(measured_sw_px if measured_sw_px is not None else page_sw)
    elif variant == "adaptive_norm":
        if measured_sw_px is not None:
            sw = float(measured_sw_px)
        elif page_scale:
            sw = page_sw
        else:
            sw = measure_stroke_width(
                arr_u8, normalize_height=MODEL_LINE_HEIGHT
            ).median_sw_px
        if sw <= 0.0 or (
            ADAPTIVE_THIN_THRESHOLD_PX <= sw <= ADAPTIVE_THICK_THRESHOLD_PX
        ):
            # Inside comfortable band -> exact identity!
            return arr_u8.copy(), sw
        if sw < ADAPTIVE_THIN_THRESHOLD_PX:
            # Proportional gentle thickening for fine ballpoint / dip nibs (cap alpha at 0.45)
            alpha = min(
                0.45, max(0.0, (3.15 - sw) / 1.80)
            )
            ink_new = _apply_soft_thicken(ink, alpha=alpha, isotropic=False)
        else:
            # Proportional gentle thinning for heavy bleeding markers (cap alpha at 0.35)
            alpha = min(
                0.35, max(0.0, (sw - ADAPTIVE_THICK_THRESHOLD_PX) / 2.80)
            )
            ink_new = _apply_soft_thin(ink, alpha=alpha, ref_line_height=ref_lh)
    elif variant == "faint_repair":
        ink_new = _apply_faint_repair(ink)
        sw = float(measured_sw_px if measured_sw_px is not None else page_sw)
    else:  # pragma: no cover
        return arr_u8.copy(), 0.0

    out_u8 = _reconstruct_from_inkness(arr_u8, ink, ink_new, denom_signed)
    return out_u8, sw


def apply_stroke_variant(
    crop: Image.Image,
    variant: StrokeVariant = "original",
    *,
    at_model_height: int | None = None,
    page_scale: bool = False,
) -> Image.Image:
    """Apply ``variant`` to a PIL crop or page (optionally resized to ``at_model_height``).

    When ``variant == 'original'`` and ``at_model_height is None``, returns ``crop``
    unchanged with zero copy overhead. Pass ``page_scale=True`` when ``crop`` is an
    unsegmented full page so ``adaptive_norm`` measures stroke width at line scale.
    """
    if variant not in STROKE_VARIANTS:
        raise ValueError(f"Unknown stroke variant: {variant!r}")
    work = (
        resize_crop_to_model_height(crop, at_model_height)
        if at_model_height is not None and at_model_height > 0
        else crop
    )
    if variant == "original" or not HAS_STROKE_VISION:
        return work

    if work.mode not in ("L", "RGB"):
        work = work.convert("RGB")
    arr = np.asarray(work)
    out_arr, _ = apply_stroke_variant_array(arr, variant, page_scale=page_scale)
    return Image.fromarray(out_arr)
