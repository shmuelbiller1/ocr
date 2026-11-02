"""Lightweight CPU document audit and selective chromatic/regional preprocessing.

Adapted in Python/NumPy/OpenCV from open-source algorithms in PhotoCraft
(https://github.com/storytold/photocraft), Copyright (c) 2026 ArtCraft Team
and the PhotoCraft contributors, dual-licensed under MIT or Apache-2.0
(see ``docs/licences/PHOTOCRAFT-MIT.txt``):

* ``crates/algo/src/scancrop.rs`` — border/modal background estimation and
  separable square morphology for foreground/background separation;
* ``crates/algo/src/color_to_alpha.rs`` — per-channel background color unmixing
  opacity ``opacity(pixel, key)`` and linear threshold ``remap``;
* ``crates/algo/src/relight.rs`` & ``crates/algo/src/tone/shadows_highlights.rs``
  — coarse-grid local illumination field estimation and bilinear upsampling;
* ``crates/algo/src/tone.rs`` — ``replace_color_masked`` color-selective
  suppression on ruling/grid structures while preserving darker ink crossings;
* ``crates/compose/src/adjust/color.rs`` — signed chromatic channel projection
  (Black & White mixer) solved via class-balanced Fisher discriminant so colored
  pens, colored papers, highlighters, and colored ruling lines convert cleanly
  without amplifying paper grain noise.

Design invariants for plain everyday PCs (CPU-only, low RAM):
1. Audit runs on a small downsampled proxy (<= 540 px) in ~5-15 ms and < 6 MB.
2. Clean, well-contrasted pages trigger zero pixel modifications (exact fast-path).
3. Regional defects (partial shadows, highlighted sections, colored-pen margin
   notes) are blended selectively across a 4x4 sector grid so clean parts of
   the page remain untouched.
4. OpenCV and NumPy are imported lazily inside worker functions so the lightweight
   desktop GUI never depends on worker vision libraries.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

from PIL import Image, ImageOps

__all__ = [
    "DocumentAudit",
    "photocraft_audit_enabled",
    "audit_document_page",
    "prepare_page_for_ocr",
    "rescale_box",
]


@dataclass(frozen=True)
class DocumentAudit:
    """Diagnostic summary produced by auditing one document page image."""

    width: int
    height: int
    bg_rgb: tuple[float, float, float]
    paper_chroma: float
    illumination_spread: float
    luma_contrast: float
    chromatic_contrast: float
    snr_luma: float
    snr_chromatic: float
    inverted_polarity: bool
    needs_chromatic_projection: bool
    needs_shadow_relight: bool
    needs_rule_suppression: bool
    needs_highlighter_suppression: bool
    active_tile_fraction: float
    channel_weights: tuple[float, float, float]
    scale_factor: float = 1.0

    @property
    def needs_adjustment(self) -> bool:
        return (
            self.inverted_polarity
            or self.needs_chromatic_projection
            or self.needs_shadow_relight
            or self.needs_rule_suppression
            or self.needs_highlighter_suppression
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["needs_adjustment"] = self.needs_adjustment
        return data


def photocraft_audit_enabled(explicit: bool | None = None) -> bool:
    """Return whether PhotoCraft document audit & selective adjustment is active."""
    if explicit is not None:
        return bool(explicit)
    raw = os.environ.get("HEBREW_WORKBENCH_PHOTOCRAFT_AUDIT", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def rescale_box(
    box: tuple[int, int, int, int] | None, scale_factor: float
) -> tuple[int, int, int, int] | None:
    """Map ``(x, y, w, h)`` from prepared-image pixels back to original pixels."""
    if box is None or abs(scale_factor - 1.0) <= 1e-6 or scale_factor <= 0.0:
        return box
    inv = 1.0 / scale_factor
    x, y, w, h = box
    return (
        int(round(x * inv)),
        int(round(y * inv)),
        max(1, int(round(w * inv))),
        max(1, int(round(h * inv))),
    )


def _photocraft_color_to_alpha_opacity(px, key, np):
    """Vectorized port of PhotoCraft ``crates/algo/src/color_to_alpha.rs`` ``opacity``."""
    diff_lo = (key - px) / np.maximum(key, 0.08)
    diff_hi = (px - key) / np.maximum(1.0 - key, 0.08)
    per_ch = np.where(px < key, diff_lo, np.where(px > key, diff_hi, 0.0))
    return np.clip(np.max(per_ch, axis=2), 0.0, 1.0)


def _estimate_smooth_paper_key(rgb, inverted: bool, cv2, np, grid_max: int = 160):
    """Coarse-grid separable morphological paper-key field (PhotoCraft relight/scancrop)."""
    h, w, _ = rgb.shape
    scale = min(1.0, grid_max / float(max(h, w, 1)))
    sw = max(8, int(round(w * scale)))
    sh = max(8, int(round(h * scale)))
    small = (
        cv2.resize(rgb, (sw, sh), interpolation=cv2.INTER_AREA)
        if scale < 1.0
        else rgb.copy()
    )
    if not inverted:
        # Prevent bright-channel colored rules (e.g. cyan B=0.88 on yellow paper B=0.54)
        # from dilating across tinted paper during morphological closing.
        cap = np.percentile(small.reshape(-1, 3), 85, axis=0) + 0.03
        small = np.minimum(small, cap[None, None, :]).astype(np.float32)
    k = max(7, (min(sh, sw) // 8) | 1)
    rk = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    bg = cv2.morphologyEx(
        small, cv2.MORPH_OPEN if inverted else cv2.MORPH_CLOSE, rk
    )
    bg = cv2.GaussianBlur(bg, (0, 0), sigmaX=max(2.0, k * 0.45))
    if (sh, sw) != (h, w):
        return cv2.resize(bg, (w, h), interpolation=cv2.INTER_LINEAR)
    return bg


def _detect_periodic_lines(alpha, cv2, np, min_len_div: int = 5):
    """Detect interior periodic horizontal/vertical ruling or graph-grid lines."""
    ph, pw = alpha.shape
    my, mx = max(2, ph // 25), max(2, pw // 25)
    cand = (alpha > 0.06).astype(np.uint8) * 255
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, pw // min_len_div), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, ph // min_len_div)))
    h_lines = cv2.morphologyEx(cand, cv2.MORPH_OPEN, hk) > 0
    v_lines = cv2.morphologyEx(cand, cv2.MORPH_OPEN, vk) > 0
    interior = np.zeros_like(h_lines)
    interior[my : ph - my, mx : pw - mx] = (h_lines | v_lines)[
        my : ph - my, mx : pw - mx
    ]

    h_prof = np.flatnonzero(interior.sum(axis=1) > pw * 0.16)
    v_prof = np.flatnonzero(interior.sum(axis=0) > ph * 0.16)
    h_peaks = (
        (1 + int(np.sum(np.diff(h_prof) >= max(4, ph // 60))))
        if h_prof.size
        else 0
    )
    v_peaks = (
        (1 + int(np.sum(np.diff(v_prof) >= max(4, pw // 60))))
        if v_prof.size
        else 0
    )
    is_periodic = (h_peaks >= 4 or v_peaks >= 4) and int(interior.sum()) >= 50
    return (h_lines | v_lines), is_periodic


def _solve_class_balanced_weights(
    delta, ink_mask, paper_mask, np, line_mask=None
):
    """Solve unit-norm chromatic channel weights (PhotoCraft Black & White mixer).

    Uses class-balanced regularized Fisher discriminant so colored pens are
    separated from colored paper, grain, and periodic ruling lines without
    amplifying single-channel background noise.
    """
    luma_unit = np.array([-0.299, -0.587, -0.114], dtype=np.float32)
    luma_unit /= float(np.linalg.norm(luma_unit))

    ink_pts = delta[ink_mask]
    bg_pts = delta[paper_mask]
    if ink_pts.shape[0] < 16 or bg_pts.shape[0] < 32:
        return luma_unit

    mu_ink = np.median(ink_pts, axis=0)
    mu_bg = np.median(bg_pts, axis=0)
    signal = mu_ink - mu_bg
    sn = float(np.linalg.norm(signal))
    if sn < 1e-4:
        return luma_unit

    c_bg = bg_pts - mu_bg
    cov = (c_bg.T @ c_bg) / max(bg_pts.shape[0], 1)

    if line_mask is not None and int(line_mask.sum()) >= 25:
        l_pts = delta[line_mask] - mu_bg
        mu_line = np.median(l_pts, axis=0)
        ln = float(np.linalg.norm(mu_line))
        if ln > 0.03:
            cos_li = abs(float(np.dot(mu_line, signal)) / (ln * sn + 1e-6))
            if cos_li < 0.96:
                cov = cov + 8.0 * ((l_pts.T @ l_pts) / max(l_pts.shape[0], 1))

    reg = max(float(np.trace(cov)) * 0.015, 8e-5)
    w = np.linalg.solve(cov + np.eye(3, dtype=np.float32) * reg, signal)
    wn = float(np.linalg.norm(w))
    w = (signal / sn) if wn < 1e-6 else (w / wn)
    if float(np.dot(w, signal)) < 0.0:
        w = -w
    return w.astype(np.float32)


def audit_document_page(
    image: Image.Image, proxy_max_side: int = 540
) -> DocumentAudit:
    """Audit a page image on a lightweight CPU proxy without modifying pixels."""
    _, audit = prepare_page_for_ocr(
        image, proxy_max_side=proxy_max_side, _audit_only=True
    )
    assert audit is not None
    return audit


def prepare_page_for_ocr(
    image: Any,
    *,
    enabled: bool | None = None,
    proxy_max_side: int = 540,
    work_max_side: int = 2200,
    _audit_only: bool = False,
) -> tuple[Any, DocumentAudit | None]:
    """Audit a document page and selectively adjust problem regions/channels.

    Returns ``(prepared_image, audit)``. Non-PIL sentinel objects used in unit
    test mocks pass through unchanged as ``(image, None)``. When disabled or
    when the page is already clean and well-contrasted, the EXIF-oriented
    original image is returned without touching its pixels.
    """
    if not isinstance(image, Image.Image):
        return image, None

    if not photocraft_audit_enabled(enabled) and not _audit_only:
        return image, None

    try:
        import cv2
        import numpy as np
    except ImportError:
        return image, None

    exif_orient = image.getexif().get(274, 1)
    im = (ImageOps.exif_transpose(image) or image) if exif_orient not in (None, 1) else image
    w, h = im.size
    if w < 16 or h < 16:
        luma_u = (-0.4532, -0.8897, -0.1728)
        return im, DocumentAudit(
            width=w,
            height=h,
            bg_rgb=(1.0, 1.0, 1.0),
            paper_chroma=0.0,
            illumination_spread=0.0,
            luma_contrast=0.0,
            chromatic_contrast=0.0,
            snr_luma=0.0,
            snr_chromatic=0.0,
            inverted_polarity=False,
            needs_chromatic_projection=False,
            needs_shadow_relight=False,
            needs_rule_suppression=False,
            needs_highlighter_suppression=False,
            active_tile_fraction=0.0,
            channel_weights=luma_u,
            scale_factor=1.0,
        )

    # 1. Build small proxy directly via PIL resize so clean 18MP photos cost ~10-25ms
    rgb_im = im if im.mode == "RGB" else im.convert("RGB")
    ps = min(1.0, proxy_max_side / float(max(w, h, 1)))
    pw, ph = max(16, int(round(w * ps))), max(16, int(round(h * ps)))
    proxy_pil = (
        rgb_im.resize((pw, ph), Image.Resampling.BILINEAR) if ps < 1.0 else rgb_im
    )
    proxy = np.asarray(proxy_pil, dtype=np.float32) * (1.0 / 255.0)
    ph, pw, _ = proxy.shape

    luma = (
        0.299 * proxy[:, :, 0]
        + 0.587 * proxy[:, :, 1]
        + 0.114 * proxy[:, :, 2]
    )
    med_luma = float(np.median(luma))
    p92_luma = float(np.percentile(luma, 92))
    p08_luma = float(np.percentile(luma, 8))
    p992_luma = float(np.percentile(luma, 99.2))
    p008_luma = float(np.percentile(luma, 0.8))
    inverted = (
        med_luma < 0.42
        and (p992_luma - med_luma) > max(0.10, (med_luma - p008_luma) * 1.1)
    )

    bg_sel = (
        (luma <= np.percentile(luma, 75))
        if inverted
        else (luma >= np.percentile(luma, 35))
    )
    bg_rgb_arr = np.median(proxy[bg_sel], axis=0)
    paper_chroma = float(np.max(bg_rgb_arr) - np.min(bg_rgb_arr))

    # 4x4 sector illumination check first for ultra-fast exit on clean monochrome scans
    gh, gw = 4, 4
    tile_paper_luma = np.zeros((gh, gw), dtype=np.float32)
    q_bg = 15 if inverted else 85
    for gy in range(gh):
        y0, y1 = (gy * ph) // gh, ((gy + 1) * ph) // gh
        for gx in range(gw):
            x0, x1 = (gx * pw) // gw, ((gx + 1) * pw) // gw
            tile_paper_luma[gy, gx] = float(
                np.percentile(luma[y0:y1, x0:x1], q_bg)
            )
    ref_luma = float(np.percentile(tile_paper_luma, 10 if inverted else 90))
    illum_spread = float(
        np.percentile(tile_paper_luma, 90) - np.percentile(tile_paper_luma, 10)
    )
    max_shadow_drop = (
        float(ref_luma - np.min(tile_paper_luma)) if not inverted else 0.0
    )

    px_chroma = np.max(proxy, axis=2) - np.min(proxy, axis=2)
    p98_chroma = float(np.percentile(px_chroma, 98))

    luma_unit = np.array([-0.299, -0.587, -0.114], dtype=np.float32)
    luma_unit /= float(np.linalg.norm(luma_unit))

    # Ultra-fast clean monochrome exit (~4ms): neutral gray, upright, no severe occlusion!
    # Moderate neutral shadows (shadow_drop <= 0.58) are left to hebocr's native
    # local Gaussian ratio + per-line normalization, which empirically outperforms
    # global shadow flattening on aged parchment scans.
    if (
        not inverted
        and (im.mode == "L" or p98_chroma < 0.045)
        and max_shadow_drop <= 0.58
    ):
        lc_fast = max(0.0, float(p92_luma - p08_luma))
        snr_fast = round(lc_fast / 0.02, 2)
        audit = DocumentAudit(
            width=w,
            height=h,
            bg_rgb=tuple(round(float(x), 4) for x in bg_rgb_arr),
            paper_chroma=round(paper_chroma, 4),
            illumination_spread=round(illum_spread, 4),
            luma_contrast=round(lc_fast, 4),
            chromatic_contrast=round(lc_fast, 4),
            snr_luma=snr_fast,
            snr_chromatic=snr_fast,
            inverted_polarity=False,
            needs_chromatic_projection=False,
            needs_shadow_relight=False,
            needs_rule_suppression=False,
            needs_highlighter_suppression=False,
            active_tile_fraction=0.0,
            channel_weights=tuple(round(float(x), 4) for x in luma_unit),
            scale_factor=1.0,
        )
        return im, audit

    # Detect broad neon/pastel highlighter bands on otherwise low-chroma paper
    px_max = np.max(proxy, axis=2)
    hl_fill = np.zeros((ph, pw), dtype=bool)
    if (not inverted) and im.mode != "L" and paper_chroma < 0.08:
        bk = cv2.getStructuringElement(
            cv2.MORPH_RECT, (max(6, min(ph, pw) // 32),) * 2
        )
        hl_cand = (px_chroma > paper_chroma + 0.25) & (px_max > 0.72)
        hl_fill = (
            cv2.morphologyEx(
                hl_cand.astype(np.uint8) * 255, cv2.MORPH_OPEN, bk
            )
            > 0
        )
    has_hl = 0.008 < float(hl_fill.mean()) < 0.55

    if has_hl:
        clean_paper = (
            np.median(proxy[bg_sel & (~hl_fill)], axis=0)
            if np.any(bg_sel & (~hl_fill))
            else bg_rgb_arr
        )
        paper_key = np.broadcast_to(
            clean_paper.astype(np.float32), proxy.shape
        ).copy()
    else:
        paper_key = _estimate_smooth_paper_key(
            proxy, inverted, cv2, np, grid_max=160
        )

    alpha = _photocraft_color_to_alpha_opacity(proxy, paper_key, np)
    long_lines, periodic_lines = _detect_periodic_lines(alpha, cv2, np)

    stroke_thresh = max(float(np.percentile(alpha, 95)), 0.08)
    pure_hl = hl_fill & (np.min(proxy, axis=2) > 0.42)
    ink_mask = (alpha >= stroke_thresh) & (~long_lines) & (~pure_hl)
    if int(ink_mask.sum()) < 24:
        ink_mask = alpha >= stroke_thresh
    paper_mask = (alpha < stroke_thresh * 0.45) & (~long_lines) & (~hl_fill)
    if int(paper_mask.sum()) < 64:
        paper_mask = ~ink_mask

    delta = proxy - paper_key
    has_colored_rules = False
    ink_color_norm = 0.0
    if (
        im.mode != "L"
        and periodic_lines
        and not inverted
        and int(ink_mask.sum()) >= 24
    ):
        mu_line = np.median(delta[long_lines], axis=0)
        mu_ink = np.median(delta[ink_mask], axis=0)
        ln = float(np.linalg.norm(mu_line))
        inorm = float(np.linalg.norm(mu_ink))
        line_chr = float(np.max(mu_line) - np.min(mu_line))
        ink_chr = float(np.max(mu_ink) - np.min(mu_ink))
        if ln > 0.03 and inorm > 0.05:
            cos_li = abs(float(np.dot(mu_line, mu_ink)) / (ln * inorm + 1e-6))
            if (cos_li < 0.94 and (line_chr > 0.05 or ink_chr > 0.06)) or (
                line_chr > 0.12 and ln < 0.78 * inorm
            ):
                has_colored_rules = True
                ink_color_norm = inorm

    w_global = _solve_class_balanced_weights(
        delta,
        ink_mask,
        paper_mask,
        np,
        line_mask=long_lines if has_colored_rules else None,
    )

    sig_luma = np.tensordot(delta, luma_unit, axes=([2], [0]))
    sig_chrom = np.tensordot(delta, w_global, axes=([2], [0]))

    eval_bg = paper_mask | (long_lines if has_colored_rules else False)
    if int(ink_mask.sum()) >= 16:
        luma_contrast = float(
            np.median(sig_luma[ink_mask]) - np.median(sig_luma[eval_bg])
        )
        chrom_contrast = float(
            np.median(sig_chrom[ink_mask]) - np.median(sig_chrom[eval_bg])
        )
    else:
        luma_contrast = 0.0
        chrom_contrast = 0.0
    snr_luma = luma_contrast / max(float(sig_luma[eval_bg].std()), 0.015)
    snr_chrom = chrom_contrast / max(float(sig_chrom[eval_bg].std()), 0.015)

    # 4x4 Regional Sector Audit ("audit the doc to change parts of it")
    tile_mode = np.zeros((gh, gw), dtype=np.int8)  # 0=clean, 1=shadow, 2=chromatic
    tile_weights = np.broadcast_to(w_global, (gh, gw, 3)).copy()

    # Require genuine luma-contrast deficit or polarity inversion before global chromatic unmixing:
    # aged brown/amber ink that already has strong Rec.601 contrast stays untouched!
    needs_global_chrom = bool(
        inverted
        or (
            im.mode != "L"
            and chrom_contrast > luma_contrast * 1.28 + 0.03
            and snr_chrom > snr_luma * 1.25
        )
    )
    any_chrom = needs_global_chrom
    any_shadow = False

    for gy in range(gh):
        y0, y1 = (gy * ph) // gh, ((gy + 1) * ph) // gh
        for gx in range(gw):
            x0, x1 = (gx * pw) // gw, ((gx + 1) * pw) // gw
            shadow_drop = (
                (ref_luma - tile_paper_luma[gy, gx]) if not inverted else 0.0
            )
            if needs_global_chrom or has_colored_rules or has_hl:
                tile_mode[gy, gx] = 2
                if (not needs_global_chrom) and im.mode != "L":
                    t_ink = ink_mask[y0:y1, x0:x1]
                    t_pap = paper_mask[y0:y1, x0:x1]
                    if int(t_ink.sum()) >= 20 and int(t_pap.sum()) >= 40:
                        tile_weights[gy, gx] = _solve_class_balanced_weights(
                            delta[y0:y1, x0:x1],
                            t_ink,
                            t_pap,
                            np,
                            line_mask=(
                                long_lines[y0:y1, x0:x1]
                                if has_colored_rules
                                else None
                            ),
                        )
            else:
                t_ink = ink_mask[y0:y1, x0:x1]
                t_pap = paper_mask[y0:y1, x0:x1]
                if (
                    im.mode != "L"
                    and int(t_ink.sum()) >= 20
                    and int(t_pap.sum()) >= 40
                ):
                    tw = _solve_class_balanced_weights(
                        delta[y0:y1, x0:x1], t_ink, t_pap, np
                    )
                    ts_l = sig_luma[y0:y1, x0:x1]
                    ts_c = np.tensordot(
                        delta[y0:y1, x0:x1], tw, axes=([2], [0])
                    )
                    lc_t = float(
                        np.median(ts_l[t_ink]) - np.median(ts_l[t_pap])
                    )
                    cc_t = float(
                        np.median(ts_c[t_ink]) - np.median(ts_c[t_pap])
                    )
                    # Only trigger regional chromatic projection when standard Rec.601
                    # genuinely loses ink contrast; on aged amber/parchment paper
                    # (paper_chroma > 0.15) require a stronger chromatic gain so warm
                    # paper stains in a border corner are not mistaken for colored pen.
                    gain_req = 1.65 if paper_chroma > 0.15 else 1.40
                    margin_req = 0.055 if paper_chroma > 0.15 else 0.035
                    if lc_t < 0.22 and cc_t > lc_t * gain_req + margin_req:
                        tile_mode[gy, gx] = 2
                        tile_weights[gy, gx] = tw
                        any_chrom = True
                        continue
                if shadow_drop > 0.58:
                    tile_mode[gy, gx] = 1
                    any_shadow = True

    # Ignore a single isolated dark/stained border corner tile (1/16 = 6.25%)
    # unless low-chroma clean paper shows a genuine colored-pen margin annotation.
    if not inverted and not needs_global_chrom and not has_colored_rules and not has_hl:
        if int((tile_mode == 1).sum()) < 2:
            tile_mode[tile_mode == 1] = 0
            any_shadow = False
        if paper_chroma > 0.15 and int((tile_mode == 2).sum()) < 2:
            tile_mode[tile_mode == 2] = 0
            any_chrom = False

    scale_factor = (
        work_max_side / float(max(w, h)) if max(w, h) > work_max_side else 1.0
    )
    active_frac = float((tile_mode > 0).mean())
    audit = DocumentAudit(
        width=w,
        height=h,
        bg_rgb=tuple(round(float(x), 4) for x in bg_rgb_arr),
        paper_chroma=round(paper_chroma, 4),
        illumination_spread=round(illum_spread, 4),
        luma_contrast=round(luma_contrast, 4),
        chromatic_contrast=round(chrom_contrast, 4),
        snr_luma=round(snr_luma, 2),
        snr_chromatic=round(snr_chrom, 2),
        inverted_polarity=inverted,
        needs_chromatic_projection=any_chrom,
        needs_shadow_relight=any_shadow,
        needs_rule_suppression=has_colored_rules,
        needs_highlighter_suppression=has_hl,
        active_tile_fraction=round(active_frac, 4),
        channel_weights=tuple(round(float(x), 4) for x in w_global),
        scale_factor=scale_factor if active_frac > 0.0 or inverted else 1.0,
    )

    if _audit_only or not audit.needs_adjustment or not photocraft_audit_enabled(enabled):
        return im, audit

    # 2. Selective Enhancement at working resolution (capped at work_max_side for plain-PC speed)
    if scale_factor < 1.0:
        ww = max(16, int(round(w * scale_factor)))
        wh = max(16, int(round(h * scale_factor)))
        work_pil = rgb_im.resize((ww, wh), Image.Resampling.BILINEAR)
    else:
        work_pil = rgb_im
    work_u8 = np.asarray(work_pil, dtype=np.uint8)
    wh, ww, _ = work_u8.shape

    rgb = work_u8.astype(np.float32) * (1.0 / 255.0)
    if has_hl:
        key_full = np.broadcast_to(
            clean_paper.astype(np.float32), (wh, ww, 3)
        ).copy()
    else:
        key_full = _estimate_smooth_paper_key(
            rgb, inverted, cv2, np, grid_max=192
        )

    # Selective Stage A: PhotoCraft `replace_color_masked` on periodic colored rules
    if has_colored_rules:
        alpha_w = _photocraft_color_to_alpha_opacity(rgb, key_full, np)
        cand_w = (alpha_w > 0.05).astype(np.uint8) * 255
        hk_w = cv2.getStructuringElement(cv2.MORPH_RECT, (max(24, ww // 10), 1))
        vk_w = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(24, wh // 10)))
        line_struct = cv2.bitwise_or(
            cv2.morphologyEx(cand_w, cv2.MORPH_OPEN, hk_w),
            cv2.morphologyEx(cand_w, cv2.MORPH_OPEN, vk_w),
        )
        line_struct = cv2.dilate(line_struct, np.ones((3, 3), np.uint8)) > 0
        delta_w = rgb - key_full
        mu_ink_px = np.median(delta[ink_mask], axis=0)
        dist_to_ink = np.linalg.norm(delta_w - mu_ink_px[None, None, :], axis=2)
        suppress_w = np.clip(
            (dist_to_ink - 0.14) / max(ink_color_norm * 0.45, 0.12), 0.0, 1.0
        )
        mask_rule = line_struct.astype(np.float32) * suppress_w
        rgb = rgb + (key_full - rgb) * mask_rule[:, :, None]

    # Selective Stage B: Spatially varying chromatic channel projection across 4x4 sectors
    w_grid = np.where(
        (tile_mode == 2)[:, :, None], tile_weights, luma_unit[None, None, :]
    ).astype(np.float32)
    w_grid = cv2.GaussianBlur(w_grid, (0, 0), sigmaX=0.65)
    w_grid /= np.maximum(np.linalg.norm(w_grid, axis=2, keepdims=True), 1e-5)
    w_field = cv2.resize(w_grid, (ww, wh), interpolation=cv2.INTER_LINEAR)

    diff = rgb - key_full
    if any_shadow and not inverted:
        # PhotoCraft `relight.rs` multiplicative Beer-Lambert illumination gain
        # so strokes inside a dark camera shadow match unshadowed stroke contrast.
        key_luma = (
            0.299 * key_full[:, :, 0]
            + 0.587 * key_full[:, :, 1]
            + 0.114 * key_full[:, :, 2]
        )
        ref_l = max(float(np.percentile(key_luma, 85)), 0.35)
        diff = diff * (ref_l / np.maximum(key_luma, 0.20))[:, :, None]

    proj = np.sum(diff * w_field, axis=2)

    # Selective Stage C: Broad neon/pastel highlighter pass-band neutralization
    # + multi-hue pen preservation (black + red/blue/green pens on the same page)
    if has_hl:
        rgb_chroma = np.max(rgb, axis=2) - np.min(rgb, axis=2)
        rgb_max = np.max(rgb, axis=2)
        bk_w = cv2.getStructuringElement(
            cv2.MORPH_RECT, (max(10, min(wh, ww) // 28),) * 2
        )
        hl_open = cv2.morphologyEx(
            ((rgb_chroma > paper_chroma + 0.22) & (rgb_max > 0.70)).astype(
                np.uint8
            )
            * 255,
            cv2.MORPH_OPEN,
            bk_w,
        )
        hl_dil = cv2.dilate(hl_open, np.ones((5, 5), np.uint8))
        hl_px = cv2.GaussianBlur(
            hl_dil.astype(np.float32) * (1.0 / 255.0), (0, 0), sigmaX=2.0
        )
        # Preserve multi-color pen ink (absorbs >=2 RGB channels) outside highlighter wash
        proj = np.maximum(proj, np.median(-diff, axis=2))
        passband_ink = np.clip(float(np.max(key_full[0, 0])) - rgb_max, 0.0, 1.0)
        proj = proj * (1.0 - hl_px) + passband_ink * hl_px

    # Linear noise-safe tone remap onto clean paper ground (252)
    sub = proj[::2, ::2]
    p50 = float(np.percentile(sub, 50))
    mad = float(np.median(np.abs(sub - p50))) * 1.4826
    floor = p50 + max(2.8 * mad, 0.022)
    p995 = max(float(np.percentile(sub, 99.6)), floor + 0.14)
    norm_ink = np.clip((proj - floor) / (p995 - floor), 0.0, 1.0)
    enhanced_gray = 252.0 - norm_ink * 232.0

    # Selective Stage D: Feather regional blend mask so clean sectors remain untouched
    # (when `any_shadow` is active, smooth `key_full` relight avoids tile-step boundaries)
    if active_frac < 0.999 and not inverted and not any_shadow:
        act = cv2.dilate(
            (tile_mode > 0).astype(np.float32), np.ones((2, 2), np.uint8)
        )
        act = cv2.GaussianBlur(act, (0, 0), sigmaX=0.8)
        mask_full = np.clip(
            cv2.resize(act, (ww, wh), interpolation=cv2.INTER_LINEAR), 0.0, 1.0
        )
        orig_gray = (
            0.299 * work_u8[:, :, 0].astype(np.float32)
            + 0.587 * work_u8[:, :, 1].astype(np.float32)
            + 0.114 * work_u8[:, :, 2].astype(np.float32)
        )
        final_gray = orig_gray * (1.0 - mask_full) + enhanced_gray * mask_full
    else:
        final_gray = enhanced_gray

    out_u8 = np.clip(np.round(final_gray), 0, 255).astype(np.uint8)
    out_pil = Image.fromarray(out_u8).convert("RGB")
    return out_pil, audit
