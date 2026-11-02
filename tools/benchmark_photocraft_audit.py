"""Systematic benchmark of PhotoCraft-derived document audit & selective cleanup.

Evaluates both unmodified verified modern cursive Hebrew scans
(``benchmark/modern_cursive``) and deterministic optical multi-color / regional
variants derived from those exact verified pages (preserving human-verified
ground-truth transcripts without fabrication):

1. ``unmodified`` — original verified scans (clean B&W, faint pencil, aged tan,
   creased yellowed paper, and 18-MP camera notebook photo);
2. ``red_pen_on_tan_paper`` — red ballpoint on warm tan paper (BT.601 luma
   collision where naive ``convert("L")`` loses almost all stroke contrast);
3. ``pink_card_red_ink`` — red/burgundy pen on pink/salmon card stock;
4. ``yellow_legal_pad`` — yellow legal pad with cyan rules and blue ink;
5. ``pastel_blue_paper`` — pastel blue stationery with dark blue ink;
6. ``mint_green_paper`` — mint green notebook paper with dark green ink;
7. ``dark_slate_light_ink`` — light strokes on dark slate ground (inverted polarity);
8. ``regional_corner_shadow`` — strong diagonal camera shadow across bottom-left;
9. ``regional_highlighter_and_red_note`` — clean white page with yellow & pink
   highlighter bands over middle lines and red-pen notes at bottom;
10. ``cyan_graph_grid`` — 5 mm cyan squared grid behind dark cursive ink.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from hebrew_workbench.console import use_utf8  # noqa: E402

use_utf8()

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageOps  # noqa: E402

from hebrew_workbench.benchmark.corpus import load_corpus  # noqa: E402
from hebrew_workbench.benchmark.metrics import (  # noqa: E402
    character_error_rate,
    levenshtein,
    line_alignment_metrics,
    normalise,
    process_memory_mb,
    word_error_rate,
)
from hebrew_workbench.engine.photocraft_audit import prepare_page_for_ocr  # noqa: E402
from hebrew_workbench.engine.vendor.hebocr.page.segment import segment_page  # noqa: E402
from tools.benchmark_ocr import resolve_engines  # noqa: E402

ALL_SUITES: tuple[str, ...] = (
    "unmodified",
    "red_pen_on_tan_paper",
    "pink_card_red_ink",
    "yellow_legal_pad",
    "pastel_blue_paper",
    "mint_green_paper",
    "dark_slate_light_ink",
    "regional_corner_shadow",
    "regional_highlighter_and_red_note",
    "cyan_graph_grid",
)

KRAKEN_SUITES: tuple[str, ...] = (
    "unmodified",
    "red_pen_on_tan_paper",
    "dark_slate_light_ink",
    "regional_highlighter_and_red_note",
    "cyan_graph_grid",
)


def extract_ink_matte(im: Image.Image) -> np.ndarray:
    """Extract deterministic normalized ink alpha matte [0..1] from a page."""
    im = ImageOps.exif_transpose(im) or im
    gray = np.asarray(im.convert("L"), dtype=np.float32) / 255.0
    bg = cv2.GaussianBlur(gray, (0, 0), sigmaX=max(gray.shape) / 25.0)
    ink = np.clip((bg - gray) / np.maximum(bg, 0.1), 0.0, 1.0)
    hi = max(float(np.percentile(ink, 99.0)), 0.15)
    return np.clip((ink - 0.03) / (hi - 0.03), 0.0, 1.0)


def synthesize_color_variant(
    im: Image.Image, suite: str, max_side: int = 1200
) -> tuple[Image.Image, np.ndarray]:
    """Render a deterministic optical paper/ink/ruling/lighting variant."""
    im = ImageOps.exif_transpose(im) or im
    if suite == "unmodified":
        return im, extract_ink_matte(im)

    if max(im.size) > max_side:
        s = max_side / float(max(im.size))
        im = im.resize(
            (max(16, int(round(im.width * s))), max(16, int(round(im.height * s)))),
            Image.Resampling.BILINEAR,
        )
    matte_2d = extract_ink_matte(im)
    matte = matte_2d[:, :, None]
    h, w = matte_2d.shape
    rng = np.random.default_rng(42)
    grain = rng.normal(0.0, 0.008, size=(h, w, 3)).astype(np.float32)

    if suite == "yellow_legal_pad":
        paper = np.full((h, w, 3), [0.97, 0.91, 0.54], dtype=np.float32) + grain
        for y in range(28, h - 10, 32):
            paper[y : y + 2, :, :] = [0.48, 0.68, 0.88]
        paper[:, int(w * 0.88) : int(w * 0.88) + 2, :] = [0.88, 0.42, 0.45]
        ink_col = np.array([0.08, 0.14, 0.48], dtype=np.float32)
        rgb = paper * (1.0 - matte) + ink_col * matte
    elif suite == "pastel_blue_paper":
        paper = np.full((h, w, 3), [0.70, 0.84, 0.96], dtype=np.float32) + grain
        ink_col = np.array([0.10, 0.15, 0.42], dtype=np.float32)
        rgb = paper * (1.0 - matte) + ink_col * matte
    elif suite == "pink_card_red_ink":
        paper = np.full((h, w, 3), [0.95, 0.76, 0.79], dtype=np.float32) + grain
        ink_col = np.array([0.92, 0.50, 0.52], dtype=np.float32)
        rgb = paper * (1.0 - matte) + ink_col * matte
    elif suite == "red_pen_on_tan_paper":
        paper = np.full((h, w, 3), [0.76, 0.73, 0.68], dtype=np.float32) + grain
        ink_col = np.array([0.94, 0.59, 0.54], dtype=np.float32)
        rgb = paper * (1.0 - matte) + ink_col * matte
    elif suite == "mint_green_paper":
        paper = np.full((h, w, 3), [0.74, 0.92, 0.77], dtype=np.float32) + grain
        ink_col = np.array([0.08, 0.36, 0.22], dtype=np.float32)
        rgb = paper * (1.0 - matte) + ink_col * matte
    elif suite == "dark_slate_light_ink":
        paper = np.full((h, w, 3), [0.16, 0.19, 0.25], dtype=np.float32) + grain
        ink_col = np.array([0.90, 0.92, 0.95], dtype=np.float32)
        rgb = paper * (1.0 - matte) + ink_col * matte
    elif suite == "regional_corner_shadow":
        yy, xx = np.meshgrid(
            np.linspace(0, 1, h), np.linspace(0, 1, w), indexing="ij"
        )
        light = np.clip(
            0.28 + 0.85 * ((1.0 - yy) * 0.55 + xx * 0.45), 0.26, 0.98
        )[:, :, None]
        paper = light * np.array([0.98, 0.97, 0.95], dtype=np.float32) + grain
        ink_col = light * np.array([0.14, 0.14, 0.18], dtype=np.float32)
        rgb = paper * (1.0 - matte) + ink_col * matte
    elif suite == "regional_highlighter_and_red_note":
        paper = np.full((h, w, 3), [0.98, 0.98, 0.97], dtype=np.float32) + grain
        paper[
            int(h * 0.28) : int(h * 0.42), int(w * 0.12) : int(w * 0.88), :
        ] = [0.98, 0.95, 0.32]
        paper[
            int(h * 0.46) : int(h * 0.58), int(w * 0.15) : int(w * 0.85), :
        ] = [0.98, 0.66, 0.80]
        ink_map = np.broadcast_to(
            np.array([0.15, 0.15, 0.18], dtype=np.float32), (h, w, 3)
        ).copy()
        ink_map[int(h * 0.65) :, :, :] = [0.88, 0.32, 0.30]
        rgb = paper * (1.0 - matte) + ink_map * matte
    elif suite == "cyan_graph_grid":
        paper = np.full((h, w, 3), [0.97, 0.98, 0.99], dtype=np.float32) + grain
        step = max(18, min(h, w) // 22)
        for y in range(step, h, step):
            paper[y : y + 2, :, :] = [0.46, 0.72, 0.93]
        for x in range(step, w, step):
            paper[:, x : x + 2, :] = [0.46, 0.72, 0.93]
        ink_col = np.array([0.16, 0.16, 0.20], dtype=np.float32)
        rgb = paper * (1.0 - matte) + ink_col * matte
    else:
        raise ValueError(f"Unknown suite: {suite}")

    out = Image.fromarray(np.clip(rgb * 255.0, 0, 255).astype(np.uint8))
    return out, matte_2d


def _signed_stroke_snr(im: Image.Image, matte: np.ndarray) -> float:
    gray = np.asarray(im.convert("L"), dtype=np.float32) / 255.0
    if gray.shape != matte.shape:
        matte = cv2.resize(
            matte, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_AREA
        )
    ink_m = matte > 0.35
    bg_m = matte < 0.05
    if not np.any(ink_m) or not np.any(bg_m):
        return 0.0
    return round(
        float(gray[bg_m].mean() - gray[ink_m].mean())
        / max(float(gray[bg_m].std()), 0.01),
        2,
    )


def run_segmentation_benchmark(corpus_dir: Path) -> list[dict[str, Any]]:
    corpus = load_corpus(corpus_dir)
    loaded = []
    for page in corpus.pages:
        if not (page.complete and page.verified and page.text.strip()):
            continue
        im = Image.open(page.image)
        im.load()
        gt_lines = [ln for ln in page.text.splitlines() if ln.strip()]
        loaded.append((page.image.stem, im, page.text, len(gt_lines)))

    results: list[dict[str, Any]] = []
    for suite in ALL_SUITES:
        gt_total = base_lines = pc_lines = base_abs_err = pc_abs_err = 0
        adj_pages = 0
        audit_ms_list: list[float] = []
        snr_base_list: list[float] = []
        snr_pc_list: list[float] = []

        for _pid, orig_im, _gt_text, gt_n in loaded:
            vim, matte = synthesize_color_variant(orig_im, suite)
            gt_total += gt_n

            c_b, _, _ = segment_page(vim, deskew=False, straighten=False)

            t0 = time.perf_counter()
            vim_pc, aud = prepare_page_for_ocr(vim, enabled=True)
            audit_ms_list.append((time.perf_counter() - t0) * 1000.0)
            if aud is not None and aud.needs_adjustment:
                adj_pages += 1

            c_p, _, _ = segment_page(vim_pc, deskew=False, straighten=False)
            base_lines += len(c_b)
            pc_lines += len(c_p)
            base_abs_err += abs(len(c_b) - gt_n)
            pc_abs_err += abs(len(c_p) - gt_n)
            snr_base_list.append(_signed_stroke_snr(vim, matte))
            snr_pc_list.append(_signed_stroke_snr(vim_pc, matte))

        row = {
            "suite": suite,
            "pages": len(loaded),
            "adjusted_pages": adj_pages,
            "gt_lines": gt_total,
            "baseline_detected_lines": base_lines,
            "photocraft_detected_lines": pc_lines,
            "baseline_line_count_abs_error": base_abs_err,
            "photocraft_line_count_abs_error": pc_abs_err,
            "baseline_mean_snr": round(float(np.mean(snr_base_list)), 2),
            "photocraft_mean_snr": round(float(np.mean(snr_pc_list)), 2),
            "mean_audit_prepare_ms": round(float(np.mean(audit_ms_list)), 2),
            "peak_rss_mb": process_memory_mb(),
        }
        results.append(row)
        print(
            f"[SEG] {suite:34s} adj={adj_pages}/{len(loaded)} "
            f"lines={base_lines:3d}-> {pc_lines:3d} (GT={gt_total}, |err| {base_abs_err:3d}->{pc_abs_err:2d}) "
            f"SNR={row['baseline_mean_snr']:6.1f}->{row['photocraft_mean_snr']:5.1f} "
            f"cpu={row['mean_audit_prepare_ms']:5.1f}ms",
            flush=True,
        )
    return results


def _build_engines(
    engine_ids: list[str], models_dir: Path
) -> list[tuple[Any, str]]:
    engines, warnings = resolve_engines(engine_ids, models_dir)
    for w in warnings:
        print(f"[WARN] {w}", flush=True)
    if not engines:
        raise RuntimeError(
            f"No requested OCR models ({engine_ids}) found in {models_dir}"
        )
    return engines


def run_neural_ocr_comparison(
    corpus_dir: Path,
    models_dir: Path,
    engine_ids: list[str],
    *,
    resolved_engines: list[tuple[Any, str]] | None = None,
    suites_override: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    corpus = load_corpus(corpus_dir)
    loaded = []
    for page in corpus.pages:
        if not (page.complete and page.verified and page.text.strip()):
            continue
        im = Image.open(page.image)
        im.load()
        loaded.append((page.image.stem, im, page.text))

    engine_pairs = (
        resolved_engines
        if resolved_engines is not None
        else _build_engines(engine_ids, models_dir)
    )
    comparisons: list[dict[str, Any]] = []
    old_env = os.environ.get("HEBREW_WORKBENCH_PHOTOCRAFT_AUDIT")
    try:
        for engine, engine_id in engine_pairs:
            # Untimed 1-page warm-up so checkpoint verification / model loading
            # does not bias `baseline_off` vs `photocraft_on` timing comparisons.
            if loaded:
                os.environ["HEBREW_WORKBENCH_PHOTOCRAFT_AUDIT"] = "0"
                engine._recognize_page_now(0, loaded[0][1])

            mode = getattr(engine, "mode", None) or getattr(
                engine, "decoding_mode", "raw"
            )
            suites = (
                suites_override
                if suites_override is not None
                else (
                    ALL_SUITES
                    if engine_id.startswith("mishkefet")
                    else KRAKEN_SUITES
                )
            )
            for suite in suites:
                suite_variants = [
                    (pid, synthesize_color_variant(im, suite)[0], gt)
                    for pid, im, gt in loaded
                ]
                mode_stats: dict[str, dict[str, Any]] = {}
                for label, flag in (("baseline_off", "0"), ("photocraft_on", "1")):
                    os.environ["HEBREW_WORKBENCH_PHOTOCRAFT_AUDIT"] = flag
                    char_ed = char_tot = word_ed = word_tot = 0
                    det_lines = gt_lines_tot = missing_tot = extra_tot = 0
                    elapsed_s: list[float] = []
                    per_page: list[dict[str, Any]] = []
                    for idx, (pid, vim, gt) in enumerate(suite_variants, start=1):
                        t0 = time.perf_counter()
                        page_res = engine._recognize_page_now(idx, vim)
                        dt = time.perf_counter() - t0
                        pred_text = (
                            page_res.assisted_text
                            if mode != "raw"
                            and getattr(page_res, "assisted_text", None) is not None
                            else page_res.text
                        )

                        ref_norm = normalise(gt)
                        hyp_norm = normalise(pred_text)
                        ref_words = ref_norm.split()
                        hyp_words = hyp_norm.split()

                        cer = character_error_rate(ref_norm, hyp_norm)
                        wer = word_error_rate(ref_norm, hyp_norm)
                        ce = levenshtein(list(ref_norm), list(hyp_norm))
                        cl = len(ref_norm)
                        we = levenshtein(ref_words, hyp_words)
                        wl = len(ref_words)
                        lalign = line_alignment_metrics(gt, pred_text)

                        char_ed += ce
                        char_tot += cl
                        word_ed += we
                        word_tot += wl
                        det_lines += lalign["lines_hypothesis"]
                        gt_lines_tot += lalign["lines_reference"]
                        missing_tot += lalign["missing_lines"]
                        extra_tot += lalign["extra_lines"]
                        elapsed_s.append(dt)
                        per_page.append(
                            {
                                "id": pid,
                                "cer": round(cer, 4),
                                "wer": round(wer, 4),
                                "pred_lines": lalign["lines_hypothesis"],
                                "ref_lines": lalign["lines_reference"],
                                "seconds": round(dt, 3),
                            }
                        )

                    agg_cer = round(char_ed / max(char_tot, 1), 4)
                    agg_wer = round(word_ed / max(word_tot, 1), 4)
                    mode_stats[label] = {
                        "cer": agg_cer,
                        "wer": agg_wer,
                        "char_edits": char_ed,
                        "ref_chars": char_tot,
                        "word_edits": word_ed,
                        "ref_words": word_tot,
                        "predicted_lines": det_lines,
                        "reference_lines": gt_lines_tot,
                        "missing_lines": missing_tot,
                        "extra_lines": extra_tot,
                        "mean_seconds_per_page": round(float(np.mean(elapsed_s)), 3),
                        "peak_rss_mb": process_memory_mb(),
                        "pages": per_page,
                    }

                b = mode_stats["baseline_off"]
                p = mode_stats["photocraft_on"]
                delta_cer_pp = round((p["cer"] - b["cer"]) * 100.0, 2)
                delta_wer_pp = round((p["wer"] - b["wer"]) * 100.0, 2)
                entry = {
                    "engine": engine_id,
                    "suite": suite,
                    "baseline": b,
                    "photocraft": p,
                    "delta_cer_pp": delta_cer_pp,
                    "delta_wer_pp": delta_wer_pp,
                }
                comparisons.append(entry)
                print(
                    f"[OCR] {engine_id:21s} | {suite:34s} | "
                    f"CER {b['cer']*100:6.2f}% -> {p['cer']*100:6.2f}% ({delta_cer_pp:+6.2f} pp) | "
                    f"WER {b['wer']*100:6.2f}% -> {p['wer']*100:6.2f}% ({delta_wer_pp:+6.2f} pp) | "
                    f"lines {b['predicted_lines']:3d}->{p['predicted_lines']:3d}/{b['reference_lines']} | "
                    f"{b['mean_seconds_per_page']:.2f}s->{p['mean_seconds_per_page']:.2f}s",
                    flush=True,
                )
    finally:
        if old_env is None:
            os.environ.pop("HEBREW_WORKBENCH_PHOTOCRAFT_AUDIT", None)
        else:
            os.environ["HEBREW_WORKBENCH_PHOTOCRAFT_AUDIT"] = old_env

    return comparisons


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=REPO_ROOT / "benchmark" / "modern_cursive",
    )
    parser.add_argument("--models", type=Path, default=None)
    parser.add_argument(
        "--engines",
        nargs="*",
        default=["mishkefet-v1", "kraken-ppocrv6-small"],
    )
    parser.add_argument("--segmentation-only", action="store_true")
    parser.add_argument("--skip-segmentation", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--in-process", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    cv2.setNumThreads(1)
    seg_rows = (
        []
        if args.skip_segmentation
        else run_segmentation_benchmark(args.corpus)
    )
    ocr_rows: list[dict[str, Any]] = []
    if not args.segmentation_only and args.models is not None:
        engine_list = list(args.engines)
        if not args.in_process and len(engine_list) > 1:
            import subprocess
            import tempfile

            for eng_id in engine_list:
                with tempfile.TemporaryDirectory(prefix="pc-bench-iso-") as td:
                    tmp_out = Path(td) / "eng.json"
                    cmd = [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--corpus",
                        str(args.corpus),
                        "--models",
                        str(args.models),
                        "--engines",
                        eng_id,
                        "--skip-segmentation",
                        "--in-process",
                        "--output",
                        str(tmp_out),
                    ]
                    proc = subprocess.run(cmd, check=False)
                    if proc.returncode != 0 or not tmp_out.is_file():
                        raise RuntimeError(
                            f"Isolated PhotoCraft benchmark failed for {eng_id} "
                            f"(exit code {proc.returncode})"
                        )
                    sub = json.loads(tmp_out.read_text(encoding="utf-8"))
                    ocr_rows.extend(sub.get("neural_ocr_before_vs_after", []))
        else:
            ocr_rows = run_neural_ocr_comparison(
                args.corpus, args.models, engine_list
            )

    payload = {
        "corpus": str(args.corpus),
        "segmentation_and_snr": seg_rows,
        "neural_ocr_before_vs_after": ocr_rows,
    }
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
