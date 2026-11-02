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
                         (strict deadband ``[2.45, 5.40] px`` leaves normal
                         strokes bit-identical; gently thickens ultra-fine nibs
                         ``< 2.45 px`` and gently thins heavy bleed ``> 5.40 px``).
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

    Verifies directly from code — rather than assuming — whether training-time
    stroke-width augmentation (``Augment._stroke``) or any morphological stroke
    normalisation runs during inference.
    """
    from .vendor.hebocr.data import transforms as heb_transforms

    preprocess_src = inspect.getsource(heb_transforms.preprocess)
    augment_cls = getattr(heb_transforms, "Augment", None)
    stroke_src = (
        inspect.getsource(augment_cls._stroke)
        if augment_cls is not None and hasattr(augment_cls, "_stroke")
        else ""
    )
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
            "line_height_px": int(getattr(heb_transforms, "LINE_HEIGHT", 64)),
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
        for cid in range(1, num_bg):
            x0 = int(bg_stats[cid, cv2.CC_STAT_LEFT])
            y0 = int(bg_stats[cid, cv2.CC_STAT_TOP])
            cw = int(bg_stats[cid, cv2.CC_STAT_WIDTH])
            ch = int(bg_stats[cid, cv2.CC_STAT_HEIGHT])
            area = int(bg_stats[cid, cv2.CC_STAT_AREA])
            touches_border = (
                x0 == 0 or y0 == 0 or (x0 + cw) >= w or (y0 + ch) >= h
            )
            if not touches_border and 2 <= area <= int(0.15 * h * w):
                hole_mask[bg_labels == cid] = 1.0
        if float(np.max(hole_mask)) > 0.0:
            hole_mask = cv2.dilate(hole_mask, k3) * np.clip(
                (0.55 - ink) / 0.35, 0.0, 1.0
            )

    # 3. Clean inter-word whitespace columns
    col_p95 = np.percentile(ink, 95.0, axis=0).astype(np.float32)
    space_cols = np.clip((0.12 - col_p95) / 0.08, 0.0, 1.0)[None, :]

    return np.clip(
        np.maximum(np.maximum(narrow_valley, hole_mask), space_cols), 0.0, 1.0
    )


def _core_and_small_glyph_protection(ink: "np.ndarray") -> "np.ndarray":
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
    h = ink.shape[0]
    scale2 = max(0.35, (h / float(MODEL_LINE_HEIGHT)) ** 2)
    small_area_cap = max(8, int(round(34.0 * scale2)))
    small_dim_cap = max(5, int(round(11.0 * (h / float(MODEL_LINE_HEIGHT)))))

    num_cc, labels, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    if num_cc > 1:
        for cid in range(1, num_cc):
            area = int(stats[cid, cv2.CC_STAT_AREA])
            cw = int(stats[cid, cv2.CC_STAT_WIDTH])
            ch = int(stats[cid, cv2.CC_STAT_HEIGHT])
            if area <= small_area_cap or (cw <= small_dim_cap and ch <= small_dim_cap):
                comp = (labels == cid).astype(np.float32)
                protect = np.maximum(protect, cv2.dilate(comp, k3))

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


def _apply_soft_thin(ink: "np.ndarray", alpha: float) -> "np.ndarray":
    """Antialiased core-and-punctuation-guarded stroke thinning by ``alpha``."""
    if alpha <= 1e-3:
        return ink
    cross = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    ero = cv2.erode(ink, cross)
    protect = _core_and_small_glyph_protection(ink)
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
) -> tuple["np.ndarray", float]:
    """Apply one of the 6 stroke-width variants to an ``uint8`` image array.

    Returns ``(output_u8, effective_measured_sw_px)``.
    """
    if variant not in STROKE_VARIANTS:
        raise ValueError(f"Unknown stroke variant: {variant!r}")
    if not HAS_STROKE_VISION or arr_u8.size == 0 or variant == "original":
        sw = float(measured_sw_px) if measured_sw_px is not None else 0.0
        return arr_u8.copy(), sw

    ink, _bg, denom_signed, _rgb = _extract_inkness(arr_u8)

    if variant == "mild_thicken":
        ink_new = _apply_soft_thicken(ink, alpha=0.32, isotropic=False)
        sw = float(measured_sw_px or 0.0)
    elif variant == "moderate_thicken":
        ink_new = _apply_soft_thicken(ink, alpha=0.65, isotropic=True)
        sw = float(measured_sw_px or 0.0)
    elif variant == "slight_thin":
        ink_new = _apply_soft_thin(ink, alpha=0.32)
        sw = float(measured_sw_px or 0.0)
    elif variant == "adaptive_norm":
        sw = (
            float(measured_sw_px)
            if measured_sw_px is not None
            else measure_stroke_width(arr_u8, normalize_height=MODEL_LINE_HEIGHT).median_sw_px
        )
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
            ink_new = _apply_soft_thin(ink, alpha=alpha)
    elif variant == "faint_repair":
        ink_new = _apply_faint_repair(ink)
        sw = float(measured_sw_px or 0.0)
    else:  # pragma: no cover
        return arr_u8.copy(), 0.0

    out_u8 = _reconstruct_from_inkness(arr_u8, ink, ink_new, denom_signed)
    return out_u8, sw


def apply_stroke_variant(
    crop: Image.Image,
    variant: StrokeVariant = "original",
    *,
    at_model_height: int | None = None,
) -> Image.Image:
    """Apply ``variant`` to a PIL crop (optionally resized to ``at_model_height``).

    When ``variant == 'original'`` and ``at_model_height is None``, returns ``crop``
    unchanged with zero copy overhead.
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
    out_arr, _ = apply_stroke_variant_array(arr, variant)
    return Image.fromarray(out_arr)
