"""Benchmark per-student CTC-head adaptation, shared vocabulary & offline resource usage.

Measures:
1. **50-student local store, bounded-RAM page streaming & online-export benchmark**
   (pure Python + SQLite + Pillow + NumPy): CPU time, peak RSS RAM, and disk usage
   across 50 profiles, admin vocabulary approval, backup/restore, and anonymized
   online-training ZIP export.
2. **Real handwritten pages 4-way & cross-writer evaluation** (when ``mishkefet-v1``
   weights are present in ``--models``, e.g. on Windows CI ``ocr-engine``):
   - Evaluates a recurring real cursive author (Rachel Bluwstein, PDM-1.0) trained
     ONLY on verified lines from training pages and tested on a **strictly unseen
     held-out page** (``commons__rachel_rak_al_atzmi__p0001.jpg``) across all 4
     conditions:
       (1) Base model before adaptation
       (2) Base model + student's personal adapter (handwriting head only)
       (3) Base model + approved shared vocabulary assistance
       (4) Combined personal adapter + approved shared vocabulary assistance
   - Evaluates other writers' pages (Bialik, Imber) to verify 0.00% drift under
     profile routing and quantify cross-writer specificity.
   - Verifies update -> held-out validation -> disk persistence -> fresh reload ->
     one-click rollback back to the exact base model reading.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from hebrew_workbench.console import use_utf8  # noqa: E402

use_utf8()

from hebrew_workbench.benchmark.metrics import (  # noqa: E402
    character_error_rate,
    levenshtein,
    normalise,
    process_memory_mb,
    word_error_rate,
)
from hebrew_workbench.training import (  # noqa: E402
    STATUS_UNCERTAIN,
    STATUS_VERIFIED,
    SchoolLearningStore,
    VerifiedLineInput,
    extract_school_vocab_tokens,
)


def _dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _align_crops_to_reference_lines(
    crops: list[Image.Image],
    boxes: list,
    ocr_lines: list[str],
    ref_lines: list[str],
    max_cer: float = 0.72,
) -> list[tuple[int, Image.Image, tuple[float, float, float, float], str, str]]:
    """Monotone DP alignment pairing detected line crops with ground-truth lines.

    Skips margin shelfmarks / archival stamps whose normalized edit distance to
    any reference line exceeds ``max_cer``, mimicking human Stage-A review where
    stamps are marked 'Skip' and real lines receive their exact diplomatic text.
    """
    n_c = len(crops)
    n_r = len(ref_lines)
    if n_c == 0 or n_r == 0:
        return []

    norm_ocr = [normalise(t) for t in ocr_lines]
    norm_ref = [normalise(t) for t in ref_lines]

    cost = [[1.0] * n_r for _ in range(n_c)]
    for i in range(n_c):
        for j in range(n_r):
            r = norm_ref[j]
            h = norm_ocr[i]
            if not r:
                cost[i][j] = 1.0
            elif not h:
                cost[i][j] = 0.95
            else:
                cost[i][j] = levenshtein(h, r) / max(1, len(r))

    skip_crop_penalty = 0.55
    skip_ref_penalty = 0.65
    dp = [[0.0] * (n_r + 1) for _ in range(n_c + 1)]
    back: list[list[tuple[int, int, str] | None]] = [
        [None] * (n_r + 1) for _ in range(n_c + 1)
    ]
    for i in range(1, n_c + 1):
        dp[i][0] = i * skip_crop_penalty
        back[i][0] = (i - 1, 0, "skip_c")
    for j in range(1, n_r + 1):
        dp[0][j] = j * skip_ref_penalty
        back[0][j] = (0, j - 1, "skip_r")

    for i in range(1, n_c + 1):
        for j in range(1, n_r + 1):
            c_match = dp[i - 1][j - 1] + cost[i - 1][j - 1]
            c_sc = dp[i - 1][j] + skip_crop_penalty
            c_sr = dp[i][j - 1] + skip_ref_penalty
            best = min(c_match, c_sc, c_sr)
            dp[i][j] = best
            if best == c_match:
                back[i][j] = (i - 1, j - 1, "match")
            elif best == c_sc:
                back[i][j] = (i - 1, j, "skip_c")
            else:
                back[i][j] = (i, j - 1, "skip_r")

    pairs: list[tuple[int, int]] = []
    ci, rj = n_c, n_r
    while ci > 0 or rj > 0:
        step = back[ci][rj]
        if step is None:
            break
        pi, pj, kind = step
        if kind == "match" and cost[pi][pj] <= max_cer:
            pairs.append((pi, pj))
        ci, rj = pi, pj
    pairs.reverse()

    aligned = []
    for crop_idx, ref_idx in pairs:
        bx = boxes[crop_idx]
        box_t = (float(bx.x), float(bx.y), float(bx.w), float(bx.h))
        aligned.append(
            (
                crop_idx,
                crops[crop_idx],
                box_t,
                ocr_lines[crop_idx],
                ref_lines[ref_idx],
            )
        )
    return aligned


def run_low_memory_50_student_benchmark() -> dict:
    """Measure 50-student SQLite store, backup/restore, export & 2-page LRU RAM."""
    t0 = time.perf_counter()
    rss_start = process_memory_mb() or 0.0
    with tempfile.TemporaryDirectory(prefix="hw-bench-50-") as td:
        root = Path(td) / "school_learning"
        store = SchoolLearningStore(root)
        store.set_vocab_sharing_enabled(True)

        # 1. Create 50 student profiles + 3 verified lines & 1 uncertain line each
        writers = [store.create_writer(f"תלמיד {i:02d}") for i in range(1, 51)]
        sample_crop = Image.new("RGB", (320, 48), (249, 248, 244))
        draw = ImageDraw.Draw(sample_crop)
        draw.line((15, 24, 300, 24), fill=(30, 30, 40), width=3)

        for idx, prof in enumerate(writers):
            doc_p = Path(td) / f"notebook_{idx:02d}.png"
            inputs = [
                VerifiedLineInput(
                    crop_image=sample_crop,
                    diplomatic_text=f"אמר רבא הלכתא בשמעתתין סימן {idx + 1}",
                    page_number=1,
                    line_index=0,
                    box=(10.0, 20.0, 320.0, 48.0),
                    page_size=(1200, 1600),
                    ocr_text=f"אמר רכא הלכתא בשמעתתין סימן {idx + 1}",
                    ocr_confidence=0.81,
                    engine_name="Mishkefet-v1",
                    engine_version="1.0",
                    model_id="mishkefet-v1",
                    preprocessing={"page_enhancement_enabled": True, "render_dpi": 300},
                    review_status=STATUS_VERIFIED,
                    verified_exact_as_written=True,
                    grammar_unedited_confirmed=True,
                ),
                VerifiedLineInput(
                    crop_image=sample_crop,
                    diplomatic_text="שורה עם אות לא ברורה [?] באמצע",
                    page_number=1,
                    line_index=1,
                    review_status=STATUS_UNCERTAIN,
                ),
            ]
            store.record_reviewed_lines(prof.writer_id, doc_p, inputs)

        # Admin approves 'שמעתתין'
        store.approve_vocab_term("שמעתתין", note="Approved school benchmark term")

        # Export online training bundle & local backup
        export_zip = Path(td) / "online_bundle.zip"
        backup_zip = Path(td) / "local_backup.zip"
        store.export_online_training_bundle_zip(export_zip, anonymize_writers=True)
        store.backup_database_zip(backup_zip)

        # Restore into clean directory
        restored_store = SchoolLearningStore(Path(td) / "restored_learning")
        restored_store.restore_database_zip(backup_zip)

        # Simulate 25-page high-res document navigation with strict 2-page LRU cache
        lru: OrderedDict[int, Image.Image] = OrderedDict()
        max_cached_pages = 0
        for pnum in range(1, 26):
            lru[pnum] = Image.new("RGB", (2480, 3508), (255, 255, 255))
            while len(lru) > 2:
                lru.popitem(last=False)
            max_cached_pages = max(max_cached_pages, len(lru))
        lru.clear()

        rss_peak = process_memory_mb() or rss_start
        elapsed = time.perf_counter() - t0
        summary = restored_store.school_summary()
        return {
            "students_created": len(restored_store.list_writers()),
            "verified_lines_persisted": summary["verified_lines_count"],
            "uncertain_lines_excluded_from_training": summary["uncertain_lines_count"],
            "approved_shared_vocab_words": summary["shared_vocab_words"],
            "wall_seconds": round(elapsed, 3),
            "peak_rss_mb": round(rss_peak, 2),
            "sqlite_db_kb": round(store.db_path.stat().st_size / 1024.0, 1),
            "total_store_kb": round(_dir_size_bytes(root) / 1024.0, 1),
            "online_export_zip_kb": round(export_zip.stat().st_size / 1024.0, 1),
            "backup_zip_kb": round(backup_zip.stat().st_size / 1024.0, 1),
            "lru_max_pages_retained_of_25": max_cached_pages,
        }


def _eval_page_metrics(hyp_text: str, ref_text: str) -> dict:
    hyp = normalise(hyp_text)
    ref = normalise(ref_text)
    return {
        "cer": round(character_error_rate(ref, hyp), 4),
        "wer": round(word_error_rate(ref, hyp), 4),
        "ref_chars": len(ref),
        "hyp_preview": hyp[:120],
    }


def _run_child_real_model_benchmark(models_dir: Path, corpus_dir: Path) -> dict:
    """Execute real Mishkefet-v1 4-way & cross-writer benchmark in an isolated process."""
    from hebrew_workbench.engine.mishkefet import MishkefetEngine
    from hebrew_workbench.engine.vendor.hebocr.page.segment import segment_page
    from hebrew_workbench.engine.vendor.hebocr.recognize import Recognizer
    from hebrew_workbench.engine.writer_adaptation import (
        AdaptConfig,
        train_writer_profile_in_process,
    )

    model_pt = models_dir / "mishkefet-v1.pt"
    has_lms = (models_dir / "hebrew_char6.pkl").is_file() and (
        models_dir / "hebrew_words.pkl"
    ).is_file()

    manifest = json.loads(
        (corpus_dir / "manifest.json").read_text(encoding="utf-8")
    )
    pages_by_name = {
        Path(p["image"]).name: p for p in manifest.get("pages", [])
    }

    # Strictly separate training pages vs unseen held-out test page for Rachel Bluwstein
    train_page_names = [
        "commons__begani_netatikha__p0001.jpg",
        "commons__rachel_gan_naul__p0001.jpg",
        "commons__rachel_aqara_1928__p0001.jpg",
    ]
    held_out_test_page_name = "commons__rachel_rak_al_atzmi__p0001.jpg"
    other_writer_pages = [
        ("Hayyim Nahman Bialik", "commons__bialik_el_hazippor__p0001.jpg"),
        ("Naftali Herz Imber", "commons__hatikvah_imber_manuscript__p0001.jpg"),
    ]

    def _ref_text(img_name: str) -> str:
        rel_t = pages_by_name[img_name]["transcript"]
        return (corpus_dir / rel_t).read_text(encoding="utf-8")

    def _img_path(img_name: str) -> Path:
        return corpus_dir / pages_by_name[img_name]["image"]

    with tempfile.TemporaryDirectory(prefix="hw-real-adapt-") as td:
        learn_root = Path(td) / "school_learning"
        store = SchoolLearningStore(learn_root)
        rachel = store.create_writer("Rachel Bluwstein (PDM-1.0)")

        # Collect Stage-A verified lines from Rachel's 3 training pages ONLY
        align_rec = Recognizer(str(model_pt), device="cpu")
        aligned_count_by_page: dict[str, int] = {}
        approved_terms: list[str] = []

        for p_idx, img_name in enumerate(train_page_names, start=1):
            p_path = _img_path(img_name)
            with Image.open(p_path) as raw_im:
                im = ImageOps.exif_transpose(raw_im).convert("RGB")
            crops, boxes, _ = segment_page(im)
            ocr_lines, confs = align_rec.read(crops, return_confidence=True)
            ref_lines = [
                ln.strip()
                for ln in _ref_text(img_name).splitlines()
                if ln.strip()
            ]
            matched = _align_crops_to_reference_lines(
                crops, boxes, ocr_lines, ref_lines
            )
            aligned_count_by_page[img_name] = len(matched)

            line_inputs: list[VerifiedLineInput] = []
            for l_i, (orig_idx, crop_im, box_t, ocr_t, ref_t) in enumerate(matched):
                line_inputs.append(
                    VerifiedLineInput(
                        crop_image=crop_im,
                        diplomatic_text=ref_t,
                        page_number=p_idx,
                        line_index=l_i,
                        box=box_t,
                        page_size=im.size,
                        ocr_text=ocr_t,
                        ocr_confidence=float(confs[orig_idx]),
                        engine_name="Mishkefet-v1",
                        model_id="mishkefet-v1",
                        review_status=STATUS_VERIFIED,
                        verified_exact_as_written=True,
                        grammar_unedited_confirmed=True,
                    )
                )
                for tok in extract_school_vocab_tokens(ref_t):
                    if len(tok) >= 4 and tok not in approved_terms:
                        approved_terms.append(tok)
            if line_inputs:
                store.record_reviewed_lines(rachel.writer_id, p_path, line_inputs)

        del align_rec

        # Condition 1: Base model before adaptation on unseen held-out page + other writers
        held_page_path = _img_path(held_out_test_page_name)
        held_ref = _ref_text(held_out_test_page_name)

        eng_raw = MishkefetEngine(
            model_path=model_pt,
            mode="raw",
            writer_id="",
            learning_dir=learn_root,
        )
        t_infer0 = time.perf_counter()
        base_raw_res = eng_raw.recognize(held_page_path)
        infer_sec = time.perf_counter() - t_infer0
        cond1_base = _eval_page_metrics(base_raw_res.text, held_ref)

        other_before: dict[str, dict] = {}
        for w_label, img_name in other_writer_pages:
            r_other = eng_raw.recognize(_img_path(img_name))
            other_before[w_label] = _eval_page_metrics(
                r_other.text, _ref_text(img_name)
            )

        # Train Rachel's personal CTC head on CPU (with internal validation gate)
        t_train0 = time.perf_counter()
        adapt_report = train_writer_profile_in_process(
            rachel.writer_id,
            model_pt,
            store_root=learn_root,
            cfg=AdaptConfig(steps=100, lr=1e-3, l2=0.1),
        )
        train_wall_s = time.perf_counter() - t_train0

        # Condition 2: Base model + student's personal adapter (raw greedy — no LM/vocab)
        eng_raw.writer_id = rachel.writer_id
        adapted_raw_res = eng_raw.recognize(held_page_path)
        cond2_adapted = _eval_page_metrics(adapted_raw_res.text, held_ref)

        # Cross-writer check A: Profile-isolated routing (other students use own/general profile)
        other_isolated: dict[str, dict] = {}
        eng_raw.writer_id = ""
        for w_label, img_name in other_writer_pages:
            r_iso = eng_raw.recognize(_img_path(img_name))
            m_iso = _eval_page_metrics(r_iso.text, _ref_text(img_name))
            m_iso["cer_delta_vs_base"] = round(
                m_iso["cer"] - other_before[w_label]["cer"], 6
            )
            other_isolated[w_label] = m_iso

        # Cross-writer check B: Deliberately applying Rachel's adapter to other writers
        other_cross_applied: dict[str, dict] = {}
        eng_raw.writer_id = rachel.writer_id
        for w_label, img_name in other_writer_pages:
            r_cross = eng_raw.recognize(_img_path(img_name))
            m_cross = _eval_page_metrics(r_cross.text, _ref_text(img_name))
            m_cross["cer_delta_vs_base"] = round(
                m_cross["cer"] - other_before[w_label]["cer"], 4
            )
            other_cross_applied[w_label] = m_cross

        # Conditions 3 & 4: Shared vocabulary assistance & Combined (Adapter + Shared Vocab)
        cond3_vocab = None
        cond4_combined = None
        if has_lms:
            store.set_vocab_sharing_enabled(True)
            for term in approved_terms[:40]:
                try:
                    store.approve_vocab_term(term, enable_sharing=True)
                except ValueError:
                    pass
            eng_assist = MishkefetEngine(
                model_path=model_pt,
                mode="assisted",
                writer_id="",
                learning_dir=learn_root,
            )
            res_vocab_only = eng_assist.recognize(held_page_path)
            cond3_vocab = _eval_page_metrics(
                res_vocab_only.assisted_text or res_vocab_only.text, held_ref
            )

            eng_assist.writer_id = rachel.writer_id
            res_combined = eng_assist.recognize(held_page_path)
            cond4_combined = _eval_page_metrics(
                res_combined.assisted_text or res_combined.text, held_ref
            )
            del eng_assist

        # Persistence + fresh reload + one-click rollback verification
        fresh_eng = MishkefetEngine(
            model_path=model_pt,
            mode="raw",
            writer_id=rachel.writer_id,
            learning_dir=learn_root,
        )
        reloaded_res = fresh_eng.recognize(held_page_path)
        reload_matches = reloaded_res.text == adapted_raw_res.text

        store.rollback_writer_adapter(rachel.writer_id, target_round=0)
        after_rollback_res = fresh_eng.recognize(held_page_path)
        rollback_matches_base = after_rollback_res.text == base_raw_res.text

        head_files = list((store.writer_dir(rachel.writer_id) / "heads").glob("*.npz"))
        adapter_kb = (
            round(head_files[0].stat().st_size / 1024.0, 1) if head_files else 0.0
        )
        feat_dir = store.writer_dir(rachel.writer_id) / "features"
        features_kb = round(_dir_size_bytes(feat_dir) / 1024.0, 1)

        return {
            "target_writer": "Rachel Bluwstein (PDM-1.0)",
            "training_pages": train_page_names,
            "aligned_verified_lines_by_page": aligned_count_by_page,
            "unseen_held_out_test_page": held_out_test_page_name,
            "adaptation_gate_report": adapt_report.to_dict(),
            "four_way_unseen_page_comparison": {
                "1_base_model_raw": cond1_base,
                "2_base_plus_student_adapter_raw": cond2_adapted,
                "3_base_plus_approved_shared_vocab": cond3_vocab,
                "4_combined_adapter_plus_shared_vocab": cond4_combined,
            },
            "other_writers_profile_isolated": other_isolated,
            "other_writers_if_misapplied_cross_writer": other_cross_applied,
            "lifecycle_verification": {
                "adapter_accepted_by_validation_gate": adapt_report.accepted,
                "fresh_engine_reload_matches_adapted": reload_matches,
                "one_click_rollback_exact_match_base": rollback_matches_base,
            },
            "resources": {
                "train_wall_seconds": round(train_wall_s, 3),
                "single_page_infer_seconds": round(infer_sec, 3),
                "peak_rss_mb": round(process_memory_mb() or 0.0, 2),
                "adapter_head_npz_kb": adapter_kb,
                "cached_backbone_features_kb": features_kb,
                "sqlite_db_kb": round(store.db_path.stat().st_size / 1024.0, 1),
            },
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        type=Path,
        default=Path(".cache/models"),
        help="Folder containing mishkefet-v1.pt and optional LMs",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=REPO_ROOT / "benchmark" / "modern_cursive",
        help="Verified modern cursive corpus directory",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("writer-adaptation-benchmark.json"),
        help="Output JSON report path",
    )
    parser.add_argument(
        "--low-memory-only",
        action="store_true",
        help="Run only the 50-student store, backup/restore, export & bounded-RAM check",
    )
    parser.add_argument(
        "--child-real-eval",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)

    if args.child_real_eval:
        res = _run_child_real_model_benchmark(
            args.models.resolve(), args.corpus.resolve()
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(res, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return 0

    report: dict[str, object] = {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "fifty_student_store_and_low_memory": run_low_memory_50_student_benchmark(),
        "real_handwriting_evaluation": None,
    }

    model_pt = args.models / "mishkefet-v1.pt"
    if not args.low_memory_only and model_pt.is_file():
        with tempfile.TemporaryDirectory(prefix="hw-child-out-") as td:
            child_json = Path(td) / "real_eval.json"
            env = dict(os.environ)
            env["PYTHONUTF8"] = "1"
            env["PYTHONIOENCODING"] = "utf-8:replace"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--child-real-eval",
                    "--models",
                    str(args.models),
                    "--corpus",
                    str(args.corpus),
                    "--output",
                    str(child_json),
                ],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=600,
            )
            if proc.returncode != 0 or not child_json.is_file():
                err = proc.stderr.decode("utf-8", errors="replace")
                print(err, file=sys.stderr)
                raise SystemExit(
                    f"Real-model writer adaptation benchmark failed (rc={proc.returncode})"
                )
            report["real_handwriting_evaluation"] = json.loads(
                child_json.read_text(encoding="utf-8")
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
