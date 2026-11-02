"""Line segmentation and baseline straightening for full-page handwritten Hebrew.

Every threshold here is derived from the image's own measured stroke size and
line pitch rather than fixed pixel constants, with safeguards for:
1. Low-DPI or faint pencil/aged-ink scans (`min_side` upscaling + adaptive C fallback),
2. Short 3-6 line notes (`estimate_line_pitch` lags up to half-page height),
3. Steeply tilted phone photographs (`estimate_skew` coarse-to-fine up to +-44 deg),
4. Dense multi-line cursive paragraphs where descenders touch across >12 lines
   (density-gated `find_lines` + `split_tall`), and
5. Curved or sagging handwritten lines (`straighten_line` 2-pass quadratic fit).
"""

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageOps


@dataclass
class LineBox:
    """One detected text line, in page pixel coordinates."""

    x: int
    y: int
    w: int
    h: int

    @property
    def area(self) -> int:
        return self.w * self.h

    def crop(self, image: Image.Image, pad: float = 0.12) -> Image.Image:
        """Crop with a little vertical padding for ascenders and descenders."""
        py = int(self.h * pad)
        px = int(self.h * 0.05)
        return image.crop(
            (
                max(self.x - px, 0),
                max(self.y - py, 0),
                min(self.x + self.w + px, image.width),
                min(self.y + self.h + py, image.height),
            )
        )


def _flatten(gray: np.ndarray) -> np.ndarray:
    """Remove the lighting gradient a phone camera leaves across a page."""
    sigma = max(gray.shape) / 30.0
    background = cv2.GaussianBlur(gray, (0, 0), sigma)
    flat = gray.astype(np.float32) / np.maximum(background.astype(np.float32), 1.0)
    return np.clip(flat * 128.0, 0, 255).astype(np.uint8)


def binarize(
    image: Image.Image,
    max_side: int = 2000,
    min_side: int = 900,
) -> tuple[np.ndarray, float]:
    """Page -> binary ink mask (255 = ink), plus the scale it was worked at.

    Downscaling large scans keeps adaptive-threshold windows wider than single
    pen strokes; upscaling low-resolution scans (`min_side`) prevents thin
    cursive strokes from being erased by thresholding and speckle opening.
    """
    gray = np.asarray(image.convert("L"), dtype=np.uint8)
    longest = max(gray.shape)
    shortest = max(1, min(gray.shape))
    if longest > max_side:
        scale = max_side / float(longest)
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    elif shortest < min_side:
        scale = min(max_side / float(longest), min_side / float(shortest))
        if scale > 1.05:
            gray = cv2.resize(
                gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC
            )
        else:
            scale = 1.0
    else:
        scale = 1.0

    flat = _flatten(gray)
    block = max(15, (min(flat.shape) // 40) | 1)  # odd, and scaled to the page
    binary = cv2.adaptiveThreshold(
        flat, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, block, 12
    )
    opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))

    # Faint-ink fallback: aged pencil or washed-out scans can lose nearly all
    # strokes under C=12 + 2x2 opening. Re-threshold gently only when needed.
    if float((opened > 0).mean()) < 0.008:
        gentle = cv2.adaptiveThreshold(
            flat, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, block, 6
        )
        gentle_open = cv2.morphologyEx(
            gentle, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8)
        )
        if float((gentle_open > 0).mean()) >= 0.004:
            return gentle_open, scale
        if float((gentle > 0).mean()) > float((opened > 0).mean()):
            return gentle, scale
    return opened, scale


def _oriented_line_kernel(length: int, angle_deg: float) -> np.ndarray:
    """A one-pixel-wide straight line of `length`, drawn at `angle_deg`."""
    drop = int(round(np.tan(np.radians(angle_deg)) * (length - 1)))
    height = abs(drop) + 1
    kernel = np.zeros((height, length), np.uint8)
    y0 = 0 if drop >= 0 else height - 1
    cv2.line(kernel, (0, y0), (length - 1, y0 + drop), 1, 1)
    return kernel


def remove_rules(
    binary: np.ndarray,
    pitch: float,
    angles=(-2.0, -1.0, -0.4, 0.0, 0.4, 1.0, 2.0),
) -> np.ndarray:
    """Erase thin printed horizontal and vertical rules after deskewing."""
    length = max(40, int(pitch * 2.0))
    thickness = max(3, int(pitch * 0.28))

    horizontal = np.zeros_like(binary)
    for angle in angles:
        horizontal = cv2.bitwise_or(
            horizontal,
            cv2.morphologyEx(
                binary, cv2.MORPH_OPEN, _oriented_line_kernel(length, angle)
            ),
        )
    vertical = np.zeros_like(binary)
    for angle in angles:
        kernel = np.ascontiguousarray(_oriented_line_kernel(length, angle).T)
        vertical = cv2.bitwise_or(
            vertical, cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
        )

    out = binary
    for runs, thin_kernel in ((horizontal, (1, thickness)), (vertical, (thickness, 1))):
        thick = cv2.morphologyEx(
            runs, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, thin_kernel)
        )
        rules = cv2.subtract(runs, thick)
        out = cv2.subtract(out, cv2.dilate(rules, np.ones((3, 3), np.uint8)))
    return out


def estimate_line_pitch(binary: np.ndarray) -> float:
    """Distance from one text line to the next, by autocorrelating row ink.

    Searches lags up to half the page height (`len(profile) // 2`) so short
    3-6 line notes find their true inter-line spacing rather than intra-line
    stroke texture.
    """
    profile = binary.sum(axis=1, dtype=np.float64)
    profile = profile - profile.mean()
    if not np.any(profile):
        return 30.0

    corr = np.correlate(profile, profile, mode="full")[len(profile) - 1 :]
    lo = max(12, int(len(profile) * 0.012))
    hi = min(len(corr) - 1, max(lo + 4, len(profile) // 2))
    if hi <= lo + 2:
        return 30.0

    window = corr[lo:hi]
    min_prominence = max(0.0, float(corr[0]) * 0.05)
    peaks = [
        i
        for i in range(1, len(window) - 1)
        if window[i] > window[i - 1]
        and window[i] >= window[i + 1]
        and window[i] > min_prominence
    ]
    if not peaks:
        peaks = [
            i
            for i in range(1, len(window) - 1)
            if window[i] > window[i - 1] and window[i] >= window[i + 1] and window[i] > 0
        ]
    return float(lo + (peaks[0] if peaks else int(np.argmax(window))))


def _projection_score(binary: np.ndarray, valid_mask: np.ndarray, angle: float) -> float:
    h, w = binary.shape
    center = (w / 2.0, h / 2.0)
    m = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(binary, m, (w, h), flags=cv2.INTER_NEAREST)
    rot_valid = cv2.warpAffine(valid_mask, m, (w, h), flags=cv2.INTER_NEAREST)
    valid_cols = (rot_valid > 0).sum(axis=1, dtype=np.float64)
    keep = valid_cols >= (w * 0.35)
    if int(keep.sum()) < 8:
        return -1.0
    norm_profile = np.zeros(h, dtype=np.float64)
    norm_profile[keep] = (
        rotated[keep].sum(axis=1, dtype=np.float64) / valid_cols[keep]
    )
    active = norm_profile[keep]
    return float(np.var(np.diff(active)))


def estimate_skew(binary: np.ndarray, limit: float = 44.0, step: float = 0.5) -> float:
    """Find the rotation that makes the horizontal ink projection most peaked.

    Uses a coarse-to-fine search when `limit > 10` so steeply rotated phone
    captures (up to +-44 deg) are deskewed accurately without slowing down
    level scans.
    """
    if limit > 10.0:
        coarse_scale = min(1.0, 500.0 / max(1, max(binary.shape)))
        coarse = (
            cv2.resize(
                binary,
                None,
                fx=coarse_scale,
                fy=coarse_scale,
                interpolation=cv2.INTER_AREA,
            )
            if coarse_scale < 1.0
            else binary
        )
        coarse_valid = np.full_like(coarse, 255)
        coarse_angle, coarse_best = 0.0, -1.0
        for angle in np.arange(-limit, limit + 2.0, 2.0):
            score = _projection_score(coarse, coarse_valid, float(angle))
            if score > coarse_best:
                coarse_angle, coarse_best = float(angle), score
        lo = max(-limit, coarse_angle - 3.0)
        hi = min(limit, coarse_angle + 3.0)
    else:
        lo, hi = -limit, limit

    fine_scale = 0.5 if max(binary.shape) > 700 else 1.0
    small = (
        cv2.resize(
            binary, None, fx=fine_scale, fy=fine_scale, interpolation=cv2.INTER_AREA
        )
        if fine_scale < 1.0
        else binary
    )
    valid = np.full_like(small, 255)
    best_angle, best_score = 0.0, -1.0
    for angle in np.arange(lo, hi + step * 0.5, step):
        score = _projection_score(small, valid, float(angle))
        if score > best_score:
            best_angle, best_score = float(angle), score
    return round(best_angle, 2)


def _rotate(image: np.ndarray, angle: float, fill: int = 0) -> np.ndarray:
    if abs(angle) < 1e-3:
        return image
    h, w = image.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(
        image,
        m,
        (w, h),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=fill,
    )


def find_lines(binary: np.ndarray, pitch: float) -> list[LineBox]:
    """Group ink into text lines by run-length smearing."""
    smear_x = max(8, int(pitch * 0.55))
    smear_y = max(1, int(pitch * 0.05))
    smeared = cv2.dilate(
        binary, cv2.getStructuringElement(cv2.MORPH_RECT, (smear_x, smear_y))
    )
    smeared = cv2.morphologyEx(
        smeared, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (smear_x, 1))
    )

    n, _, stats, _ = cv2.connectedComponentsWithStats(smeared, connectivity=8)
    boxes = []
    for i in range(1, n):
        x, y, w, h, area = (
            stats[i, cv2.CC_STAT_LEFT],
            stats[i, cv2.CC_STAT_TOP],
            stats[i, cv2.CC_STAT_WIDTH],
            stats[i, cv2.CC_STAT_HEIGHT],
            stats[i, cv2.CC_STAT_AREA],
        )
        if w < pitch * 0.8 or h < pitch * 0.25:
            continue
        # Only discard >12-pitch components when their unsmeared ink density
        # indicates a solid dark block (`raw_fill >= 0.35`) or a narrow
        # vertical border/binding (`w < 2 * pitch`). Sparse wide multi-line
        # cursive paragraphs (`raw_fill ~ 0.05-0.20`) are sliced by `split_tall`.
        if h > pitch * 12.0:
            raw_fill = float((binary[y : y + h, x : x + w] > 0).mean())
            if raw_fill >= 0.35 or w < pitch * 2.0:
                continue
        if area < pitch * pitch * 0.12:
            continue
        boxes.append(LineBox(int(x), int(y), int(w), int(h)))
    # Defensive cap against pathological background noise (e.g. un-inverted
    # dark ground when preprocessing is disabled) so O(N^2) overlap merging
    # remains bounded in milliseconds on CPU.
    if len(boxes) > 500:
        boxes.sort(key=lambda b: b.w * b.h, reverse=True)
        boxes = boxes[:500]
    return boxes


def split_tall(binary: np.ndarray, boxes: list[LineBox], pitch: float) -> list[LineBox]:
    """Cut components that swallowed more than one text line."""
    out: list[LineBox] = []
    for box in boxes:
        n = int(round(box.h / pitch))
        if n <= 1:
            out.append(box)
            continue

        roi = binary[box.y : box.y + box.h, box.x : box.x + box.w]
        profile = roi.sum(axis=1, dtype=np.float64)
        smooth = cv2.GaussianBlur(profile.reshape(-1, 1), (1, 5), 0).ravel()

        cuts = [0]
        for k in range(1, n):
            centre = int(k * box.h / n)
            lo = max(cuts[-1] + 2, centre - int(pitch * 0.35))
            hi = min(box.h - 2, centre + int(pitch * 0.35))
            if hi > lo:
                cuts.append(lo + int(np.argmin(smooth[lo:hi])))
        cuts.append(box.h)

        for top, bottom in zip(cuts, cuts[1:]):
            band = roi[top:bottom]
            rows = np.where(band.sum(axis=1) > 0)[0]
            cols = np.where(band.sum(axis=0) > 0)[0]
            if len(rows) == 0 or len(cols) == 0:
                continue
            out.append(
                LineBox(
                    x=box.x + int(cols[0]),
                    y=box.y + top + int(rows[0]),
                    w=int(cols[-1] - cols[0] + 1),
                    h=int(rows[-1] - rows[0] + 1),
                )
            )
    return out


def merge_overlapping(boxes: list[LineBox], pitch: float) -> list[LineBox]:
    """Join fragments of one line that the smear left separate."""
    if not boxes:
        return []
    boxes = sorted(boxes, key=lambda b: (b.y, b.x))
    merged: list[LineBox] = []
    for box in boxes:
        placed = False
        for i, other in enumerate(merged):
            v_overlap = min(box.y + box.h, other.y + other.h) - max(box.y, other.y)
            shorter = min(box.h, other.h)
            h_gap = max(box.x, other.x) - min(box.x + box.w, other.x + other.w)
            if v_overlap > shorter * 0.5 and h_gap < pitch * 1.2:
                x0 = min(box.x, other.x)
                y0 = min(box.y, other.y)
                x1 = max(box.x + box.w, other.x + other.w)
                y1 = max(box.y + box.h, other.y + other.h)
                merged[i] = LineBox(x0, y0, x1 - x0, y1 - y0)
                placed = True
                break
        if not placed:
            merged.append(box)
    return merged


def reading_order(boxes: list[LineBox], pitch: float) -> list[LineBox]:
    """Sort into Hebrew reading order: rows top to bottom, then right to left."""
    if not boxes:
        return []
    ordered = sorted(boxes, key=lambda b: b.y + b.h / 2)
    rows: list[list[LineBox]] = [[ordered[0]]]
    for box in ordered[1:]:
        centre = box.y + box.h / 2
        row_centre = np.mean([b.y + b.h / 2 for b in rows[-1]])
        if abs(centre - row_centre) < pitch * 0.45:
            rows[-1].append(box)
        else:
            rows.append([box])
    return [b for row in rows for b in sorted(row, key=lambda b: -(b.x + b.w))]


def straighten_line(crop: Image.Image) -> Image.Image:
    """Flatten curved or locally tilted handwritten baselines via 2-pass quadratic fit.

    Leaves already-straight lines (`max|deviation| < 0.15 * h`) untouched so
    crisp horizontal lines incur zero resampling blur.
    """
    arr = np.asarray(crop)
    gray = (
        cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        if arr.ndim == 3
        else arr.astype(np.uint8)
    )
    h, w = gray.shape
    if h < 20 or w < max(40, h * 2):
        return crop

    bg = cv2.GaussianBlur(gray, (0, 0), max(h / 4.0, 3.0))
    flat = np.clip(
        gray.astype(np.float32) / np.maximum(bg.astype(np.float32), 1.0) * 128.0,
        0,
        255,
    ).astype(np.uint8)
    _, ink_mask = cv2.threshold(
        flat, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )
    weights = (ink_mask > 0).astype(np.float32)
    col_mass = weights.sum(axis=0)
    valid_x = np.where(col_mass >= 2.0)[0]
    if len(valid_x) < max(12, w // 12):
        return crop

    ys = np.arange(h, dtype=np.float32)[:, None]
    centroids = (weights[:, valid_x] * ys).sum(axis=0) / col_mass[valid_x]
    xs = valid_x.astype(np.float32)

    poly = np.polyfit(xs, centroids, 2)
    resid = np.abs(centroids - np.polyval(poly, xs))
    sigma = max(float(np.median(resid)) * 1.4826, 2.0)
    band = max(2.5 * sigma, 0.22 * h)
    inliers = resid <= band
    if int(inliers.sum()) >= max(10, len(xs) // 2):
        poly = np.polyfit(xs[inliers], centroids[inliers], 2)

    all_x = np.arange(w, dtype=np.float32)
    # Clamp polynomial outside observed ink span so margins never extrapolate wildly.
    clamped_x = np.clip(all_x, float(xs[0]), float(xs[-1]))
    curve = np.polyval(poly, clamped_x).astype(np.float32)
    centre_y = float(np.median(curve))
    deviation = curve - centre_y
    max_dev = float(np.max(np.abs(deviation)))
    if max_dev < max(4.0, 0.15 * h) or max_dev > 0.85 * h:
        return crop

    grid_y, grid_x = np.meshgrid(
        np.arange(h, dtype=np.float32), all_x, indexing="ij"
    )
    map_y = (grid_y + deviation[None, :]).astype(np.float32)
    border_val = (
        tuple(int(v) for v in np.median(arr[[0, -1], :], axis=(0, 1)))
        if arr.ndim == 3
        else int(np.median(np.concatenate([arr[0], arr[-1]])))
    )
    warped = cv2.remap(
        arr,
        grid_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=border_val,
    )
    return Image.fromarray(warped)


def segment_page(
    image: Image.Image,
    max_side: int = 2000,
    deskew: bool = True,
    straighten: bool = True,
):
    """Page image -> (line crops in reading order, their boxes, skew angle)."""
    image = ImageOps.exif_transpose(image) or image
    binary, scale = binarize(image, max_side=max_side)

    angle = estimate_skew(binary) if deskew else 0.0
    if abs(angle) > 1e-3:
        binary = _rotate(binary, angle)
        fill = (255, 255, 255) if image.mode == "RGB" else 255
        work_image = image.rotate(angle, resample=Image.BICUBIC, fillcolor=fill)
    else:
        work_image = image

    pitch = estimate_line_pitch(binary)
    binary = remove_rules(binary, pitch)
    pitch = estimate_line_pitch(binary)

    boxes = find_lines(binary, pitch)
    boxes = split_tall(binary, boxes, pitch)
    boxes = merge_overlapping(boxes, pitch)
    boxes = reading_order(boxes, pitch)

    inv = 1.0 / scale if scale > 0 else 1.0
    full = [
        LineBox(
            int(round(b.x * inv)),
            int(round(b.y * inv)),
            max(1, int(round(b.w * inv))),
            max(1, int(round(b.h * inv))),
        )
        for b in boxes
    ]
    crops = [b.crop(work_image) for b in full]
    if straighten:
        crops = [straighten_line(c) for c in crops]
    return crops, full, angle
