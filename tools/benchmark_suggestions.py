"""Measure offline Hebrew spelling and grammar modules without double-counting.

Evaluates post-OCR suggestion layers independently (spelling only, grammar
only, and combined) on:
1. A realistic modern Hebrew classroom, rabbinic/scholarly, abbreviation,
   OCR-confusion, and student-grammar benchmark suite, and/or
2. Real OCR hypotheses paired with verified corpus transcripts from an
   ``ocr-accuracy.json`` report produced by ``tools/benchmark_ocr.py``.

Multiple proposals or ranked alternatives covering the same character span
are grouped by span before counting, so a single error is never counted
more than once.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from hebrew_workbench.benchmark.metrics import (  # noqa: E402
    character_error_rate,
    levenshtein,
    normalise,
    process_memory_mb,
    word_error_rate,
)
from hebrew_workbench.console import use_utf8  # noqa: E402
from hebrew_workbench.plugins import PluginRegistry  # noqa: E402
from hebrew_workbench.suggestions import (  # noqa: E402
    KIND_GRAMMAR,
    KIND_SPELLING,
    Suggestion,
    SuggestionRegistry,
    SuggestionSession,
)

__all__ = [
    "BenchmarkCase",
    "DEFAULT_SUITE",
    "evaluate_cases",
    "evaluate_ocr_report",
    "group_by_span",
    "target_error_spans",
    "main",
]


@dataclass(frozen=True)
class BenchmarkCase:
    """One paired noisy/erroneous Hebrew text and its verified target text."""

    id: str
    category: str
    noisy: str
    reference: str
    engine: str = ""


DEFAULT_SUITE: tuple[BenchmarkCase, ...] = (
    # Clean sentences testing false-positive resistance on prefixes, Aramaic,
    # rabbinic acronyms, geresh abbreviations, ketiv variants, and English/numbers.
    BenchmarkCase(
        id="clean_prefixes_modern",
        category="clean_valid",
        noisy="ובירושלים למדנו מהתלמידים שהדברים ברורים וכשראינו זאת שמחנו מאוד.",
        reference="ובירושלים למדנו מהתלמידים שהדברים ברורים וכשראינו זאת שמחנו מאוד.",
    ),
    BenchmarkCase(
        id="clean_rabbinic_and_abbreviations",
        category="clean_valid",
        noisy='בס"ד מח\' רש"י ותוס\' ע"פ הגמרא והמשנה: סברא דאורייתא או דרבנן, וכו\'.',
        reference='בס"ד מח\' רש"י ותוס\' ע"פ הגמרא והמשנה: סברא דאורייתא או דרבנן, וכו\'.',
    ),
    BenchmarkCase(
        id="clean_mixed_english_digits_quotes",
        category="clean_valid",
        noisy='בשנת 2026 נפתחה התוכנית "מדעי המחשב" בתיכון English 101 בהצלחה.',
        reference='בשנת 2026 נפתחה התוכנית "מדעי המחשב" בתיכון English 101 בהצלחה.',
    ),
    BenchmarkCase(
        id="clean_idiomatic_reduplication_and_participles",
        category="clean_valid",
        noisy="אני יכול ואני יודע שצריך להתקדם לאט לאט יום יום.",
        reference="אני יכול ואני יודע שצריך להתקדם לאט לאט יום יום.",
    ),
    # Handwritten OCR visual-confusion & final-letter spelling errors
    BenchmarkCase(
        id="ocr_final_and_double_yod",
        category="spelling_ocr",
        noisy="שלומ לכל תלמיידים בכיתה.",
        reference="שלום לכל תלמידים בכיתה.",
    ),
    BenchmarkCase(
        id="ocr_vav_yod_dalet_resh",
        category="spelling_ocr",
        noisy="בירישלים למדו התלמירים בשיעיר היסטוריה.",
        reference="בירושלים למדו התלמידים בשיעור היסטוריה.",
    ),
    BenchmarkCase(
        id="ocr_bet_kaf_samekh_memsofit",
        category="spelling_ocr",
        noisy="המחכרת כוללת מםפר תרגילים של הכתיכה.",
        reference="המחברת כוללת מספר תרגילים של הכתיבה.",
    ),
    BenchmarkCase(
        id="ocr_runon_and_compound_prefix",
        category="spelling_ocr",
        noisy="מהתלמירים הגיעו אל ביתהספר בבוקר.",
        reference="מהתלמידים הגיעו אל בית הספר בבוקר.",
    ),
    # Modern Israeli Hebrew grammar & punctuation errors
    BenchmarkCase(
        id="grammar_first_person_future",
        category="grammar",
        noisy="מחר אני ילך לספרייה ואני יכתוב את הסיכום.",
        reference="מחר אני אלך לספרייה ואני אכתוב את הסיכום.",
    ),
    BenchmarkCase(
        id="grammar_construct_definite_article",
        category="grammar",
        noisy="הגענו אל הבית ספר ופגשנו את העורך דין.",
        reference="הגענו אל בית הספר ופגשנו את עורך הדין.",
    ),
    BenchmarkCase(
        id="grammar_number_gender_agreement",
        category="grammar",
        noisy="חיכינו שלוש ימים וקראנו שלושה פעמים את הפרק.",
        reference="חיכינו שלושה ימים וקראנו שלוש פעמים את הפרק.",
    ),
    BenchmarkCase(
        id="grammar_demonstrative_and_reduplication",
        category="grammar",
        noisy="הבעיה הזה חוזרת על על עצמה בדף הדף.",
        reference="הבעיה הזאת חוזרת על עצמה בדף.",
    ),
    BenchmarkCase(
        id="grammar_punctuation_and_quotes",
        category="grammar",
        noisy='אמר המורה ,כי  "התשובה נכונה " ( לגמרי ).',
        reference='אמר המורה, כי "התשובה נכונה" (לגמרי).',
    ),
)


def target_error_spans(noisy: str, reference: str) -> list[tuple[int, int, str]]:
    """Non-overlapping ``(start, end, target_replacement)`` edits from noisy -> reference."""
    matcher = difflib.SequenceMatcher(a=noisy, b=reference, autojunk=False)
    spans: list[tuple[int, int, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        spans.append((i1, i2, reference[j1:j2]))
    return spans


def group_by_span(suggestions: list[Suggestion]) -> list[tuple[int, int, list[Suggestion]]]:
    """Group overlapping/identical proposals into unique source character spans."""
    ordered = sorted(suggestions, key=lambda s: (s.start, s.end, s.module))
    groups: list[tuple[int, int, list[Suggestion]]] = []
    for item in ordered:
        if groups and item.start < groups[-1][1] and groups[-1][0] < item.end:
            g_start, g_end, bucket = groups[-1]
            bucket.append(item)
            groups[-1] = (min(g_start, item.start), max(g_end, item.end), bucket)
        else:
            groups.append((item.start, item.end, [item]))
    return groups


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    if a_start == a_end:
        return b_start <= a_start <= b_end
    if b_start == b_end:
        return a_start <= b_start <= a_end
    return a_start < b_end and b_start < a_end


def evaluate_cases(
    registry: SuggestionRegistry,
    cases: list[BenchmarkCase],
) -> dict:
    """Measure precision, recall, false suggestions, and net CER/WER effect."""
    total_target_errors = 0
    detected_errors = 0
    correct_top1 = 0
    correct_any_rank = 0
    false_suggestions = 0
    unwanted_changes = 0

    ref_chars_total = 0
    cer_weighted_before = 0.0
    cer_weighted_after = 0.0
    ref_words_total = 0
    wer_weighted_before = 0.0
    wer_weighted_after = 0.0

    started = time.perf_counter()
    per_case: list[dict] = []

    for case in cases:
        proposals = registry.check(case.noisy)
        span_groups = group_by_span(proposals)
        gold_spans = target_error_spans(case.noisy, case.reference)
        total_target_errors += len(gold_spans)

        matched_gold: set[int] = set()
        case_false = 0
        case_top1 = 0
        case_any = 0

        for p_start, p_end, bucket in span_groups:
            overlapping_gold = [
                idx
                for idx, (g_start, g_end, _target) in enumerate(gold_spans)
                if _overlaps(p_start, p_end, g_start, g_end)
            ]
            if not overlapping_gold:
                false_suggestions += 1
                case_false += 1
                continue

            # Claim all overlapping gold spans covered by this single proposal
            # (e.g. "הבית ספר" -> "בית הספר" resolves two character-diff spans
            # in one phrase-level suggestion, without double-counting).
            unclaimed = [idx for idx in overlapping_gold if idx not in matched_gold]
            if not unclaimed:
                continue
            n_claimed = len(unclaimed)
            for g_i in unclaimed:
                matched_gold.add(g_i)
            detected_errors += n_claimed

            # Check whether top-1 or any ranked alternative reconstructs all
            # covered gold edits cleanly across the union slice.
            primary = bucket[0]
            covered_spans = sorted(
                (gold_spans[g_i] for g_i in overlapping_gold), key=lambda x: x[0]
            )

            def _reconstructs(cand_text: str, s_obj: Suggestion) -> bool:
                u_s = min(s_obj.start, covered_spans[0][0])
                u_e = max(s_obj.end, covered_spans[-1][1])
                parts: list[str] = []
                cursor = u_s
                for gs, ge, gt in covered_spans:
                    if gs > cursor:
                        parts.append(case.noisy[cursor:gs])
                    parts.append(gt)
                    cursor = ge
                if cursor < u_e:
                    parts.append(case.noisy[cursor:u_e])
                exp = "".join(parts)
                got = (
                    case.noisy[u_s : s_obj.start]
                    + cand_text
                    + case.noisy[s_obj.end : u_e]
                )
                return normalise(got) == normalise(exp)

            if primary.replacement and _reconstructs(primary.replacement, primary):
                correct_top1 += n_claimed
                case_top1 += n_claimed
            if any(
                _reconstructs(cand, s)
                for s in bucket
                for cand in ((s.replacement,) + tuple(s.alternatives))
                if cand
            ):
                correct_any_rank += n_claimed
                case_any += n_claimed

        # Apply non-empty top-1 proposals via SuggestionSession to measure
        # unwanted text changes and net CER/WER delta.
        # Exclude non-editing dictionary warnings (`replacement == original`)
        # from applied edits while retaining them in warning/false counts above.
        session = SuggestionSession(case.noisy)
        actionable = [
            s for s in proposals if s.replacement and s.replacement != s.original
        ]
        session.set_suggestions(actionable, case.noisy)
        outcome = session.accept_many(session.pending())
        after_text = outcome[0] if outcome is not None else case.noisy

        # Count unwanted changes directly: applied non-identity changes that did
        # NOT reduce edit distance toward reference.
        norm_ref = normalise(case.reference)
        ref_chars_seq: list[str] | None = None
        s_step = SuggestionSession(case.noisy)
        s_step.set_suggestions(actionable, case.noisy)
        for proposal in list(s_step.pending()):
            prev_text = s_step.current_text
            res = s_step.accept(proposal)
            if res is None:
                continue
            next_text = res[0]
            if next_text == prev_text:
                continue
            prev_dist = character_error_rate(norm_ref, normalise(prev_text))
            next_dist = character_error_rate(norm_ref, normalise(next_text))
            if next_dist < prev_dist - 1e-9:
                continue
            if ref_chars_seq is None:
                ref_chars_seq = list(case.reference)
            prev_raw = levenshtein(ref_chars_seq, list(prev_text))
            next_raw = levenshtein(ref_chars_seq, list(next_text))
            if next_raw >= prev_raw:
                unwanted_changes += 1

        norm_before = normalise(case.noisy)
        norm_after = normalise(after_text)
        cer_b = character_error_rate(norm_ref, norm_before)
        cer_a = character_error_rate(norm_ref, norm_after)
        wer_b = word_error_rate(norm_ref, norm_before)
        wer_a = word_error_rate(norm_ref, norm_after)

        n_chars = max(1, len(norm_ref))
        n_words = max(1, len(norm_ref.split()))
        ref_chars_total += len(norm_ref)
        ref_words_total += len(norm_ref.split())
        cer_weighted_before += cer_b * n_chars
        cer_weighted_after += cer_a * n_chars
        wer_weighted_before += wer_b * n_words
        wer_weighted_after += wer_a * n_words

        per_case.append(
            {
                "id": case.id,
                "category": case.category,
                "target_errors": len(gold_spans),
                "unique_spans_proposed": len(span_groups),
                "top1_correct": case_top1,
                "any_rank_correct": case_any,
                "false_suggestions": case_false,
                "cer_before": round(cer_b, 4),
                "cer_after": round(cer_a, 4),
                "wer_before": round(wer_b, 4),
                "wer_after": round(wer_a, 4),
                "after_text": after_text,
            }
        )

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    cer_before = cer_weighted_before / max(1, ref_chars_total)
    cer_after = cer_weighted_after / max(1, ref_chars_total)
    wer_before = wer_weighted_before / max(1, ref_words_total)
    wer_after = wer_weighted_after / max(1, ref_words_total)

    return {
        "cases": len(cases),
        "total_target_errors": total_target_errors,
        "actual_errors_detected": detected_errors,
        "correct_top1_suggestions": correct_top1,
        "correct_any_rank_suggestions": correct_any_rank,
        "false_suggestions": false_suggestions,
        "unwanted_text_changes": unwanted_changes,
        "cer_before": round(cer_before, 4),
        "cer_after": round(cer_after, 4),
        "net_cer_delta": round(cer_after - cer_before, 4),
        "wer_before": round(wer_before, 4),
        "wer_after": round(wer_after, 4),
        "net_wer_delta": round(wer_after - wer_before, 4),
        "milliseconds_total": round(elapsed_ms, 2),
        "milliseconds_per_case": round(elapsed_ms / max(1, len(cases)), 2),
        "peak_rss_mb": process_memory_mb(),
        "per_case": per_case,
    }


def evaluate_ocr_report(report_path: Path, corpus_folder: Path) -> list[BenchmarkCase]:
    """Build evaluation cases from verified pages in an OCR benchmark report."""
    from hebrew_workbench.benchmark.corpus import load_corpus

    corpus = load_corpus(corpus_folder)
    ref_by_name = {
        page.image.relative_to(corpus_folder).as_posix(): page.text
        for page in corpus.measured_pages
    }
    data = json.loads(report_path.read_text(encoding="utf-8"))
    cases: list[BenchmarkCase] = []
    for engine_entry in data.get("engines", []):
        model = engine_entry.get("model") or engine_entry.get("engine", "ocr")
        for item in engine_entry.get("results", []):
            page_name = item.get("page", "")
            has_hyp = "hypothesis_text" in item or "hypothesis_sample" in item
            hyp = (
                item["hypothesis_text"]
                if "hypothesis_text" in item
                else item.get("hypothesis_sample", "")
            )
            ref = ref_by_name.get(page_name, "")
            if has_hyp and ref:
                cases.append(
                    BenchmarkCase(
                        id=f"{model}::{page_name}",
                        category="post_ocr",
                        noisy=hyp,
                        reference=ref,
                        engine=model,
                    )
                )
    return cases


def _build_registry(enable_spelling: bool, enable_grammar: bool) -> SuggestionRegistry:
    """Build deterministic benchmark modules isolated from desktop user settings."""
    from hebrew_workbench.suggestions.grammar import GrammarModule
    from hebrew_workbench.suggestions.spelling import SpellingModule

    spelling = SpellingModule()
    # Pass an explicit nonexistent personal-dictionary path inside a deterministic
    # sentinel location so user desktop preferences/words never alter measurements.
    spelling.use_bundled_lexicon(
        personal_path=REPO_ROOT / "build" / "__isolated_empty_personal_dict__.txt"
    )
    spelling._personal = set()
    spelling._personal_path = None
    grammar = GrammarModule()
    reg = SuggestionRegistry([spelling, grammar])
    reg.set_enabled(KIND_SPELLING, enable_spelling)
    reg.set_enabled(KIND_GRAMMAR, enable_grammar)
    reg.set_enabled("style", False)
    return reg


def main(argv: list[str] | None = None) -> int:
    use_utf8()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocr-report", type=Path, help="optional ocr-accuracy.json")
    parser.add_argument("--corpus", type=Path, help="corpus folder matching --ocr-report")
    parser.add_argument("--output", type=Path, default=Path("suggestions-benchmark.json"))
    args = parser.parse_args(argv)

    suite_cases = list(DEFAULT_SUITE)
    payload: dict = {
        "suite": {
            "spelling_only": evaluate_cases(
                _build_registry(enable_spelling=True, enable_grammar=False),
                suite_cases,
            ),
            "grammar_only": evaluate_cases(
                _build_registry(enable_spelling=False, enable_grammar=True),
                suite_cases,
            ),
            "spelling_and_grammar": evaluate_cases(
                _build_registry(enable_spelling=True, enable_grammar=True),
                suite_cases,
            ),
        }
    }
    if args.ocr_report and args.corpus:
        ocr_cases = evaluate_ocr_report(args.ocr_report, args.corpus)
        payload["post_ocr"] = {
            "spelling_only": evaluate_cases(
                _build_registry(enable_spelling=True, enable_grammar=False),
                ocr_cases,
            ),
            "grammar_only": evaluate_cases(
                _build_registry(enable_spelling=False, enable_grammar=True),
                ocr_cases,
            ),
            "spelling_and_grammar": evaluate_cases(
                _build_registry(enable_spelling=True, enable_grammar=True),
                ocr_cases,
            ),
        }
        by_engine: dict[str, dict] = {}
        engine_names = sorted({c.engine or c.id.split("::", 1)[0] for c in ocr_cases})
        for eng_name in engine_names:
            eng_cases = [
                c for c in ocr_cases if (c.engine or c.id.split("::", 1)[0]) == eng_name
            ]
            by_engine[eng_name] = {
                "spelling_only": evaluate_cases(
                    _build_registry(enable_spelling=True, enable_grammar=False),
                    eng_cases,
                ),
                "grammar_only": evaluate_cases(
                    _build_registry(enable_spelling=False, enable_grammar=True),
                    eng_cases,
                ),
                "spelling_and_grammar": evaluate_cases(
                    _build_registry(enable_spelling=True, enable_grammar=True),
                    eng_cases,
                ),
            }
        payload["post_ocr_by_engine"] = by_engine

    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for mode, summary in payload["suite"].items():
        print(
            f"[{mode}] detected={summary['actual_errors_detected']}/{summary['total_target_errors']} "
            f"top1={summary['correct_top1_suggestions']} any={summary['correct_any_rank_suggestions']} "
            f"false={summary['false_suggestions']} unwanted={summary['unwanted_text_changes']} "
            f"CER {summary['cer_before']*100:.2f}%->{summary['cer_after']*100:.2f}% "
            f"WER {summary['wer_before']*100:.2f}%->{summary['wer_after']*100:.2f}% "
            f"({summary['milliseconds_total']:.1f} ms)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
