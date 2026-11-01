"""Tests for the verified public-domain modern cursive benchmark and metrics."""

from __future__ import annotations

import unittest
from pathlib import Path

from hebrew_workbench.benchmark.corpus import load_corpus
from hebrew_workbench.benchmark.metrics import (
    line_alignment_metrics,
    process_memory_mb,
)
from hebrew_workbench.suggestions import (
    KIND_SPELLING,
    Suggestion,
    SuggestionModule,
    SuggestionRegistry,
)
from tools.benchmark_ocr import check_against_the_manifest
from tools.benchmark_suggestions import BenchmarkCase, evaluate_cases

REPO_ROOT = Path(__file__).resolve().parents[1]


class ModernCursiveCorpusTests(unittest.TestCase):
    def test_modern_cursive_corpus_is_complete_verified_and_matches_manifest(self) -> None:
        folder = REPO_ROOT / "benchmark" / "modern_cursive"
        corpus = load_corpus(folder)
        self.assertEqual(corpus.errors, [])
        self.assertEqual(len(corpus.pages), 6)
        self.assertEqual(len(corpus.measured_pages), 6)
        self.assertTrue(corpus.verified)
        self.assertEqual(check_against_the_manifest(folder, corpus.pages), [])

    def test_modern_school_corpus_remains_untouched_pending_school_consent(self) -> None:
        folder = REPO_ROOT / "benchmark" / "modern_school"
        corpus = load_corpus(folder)
        self.assertEqual(corpus.errors, [])
        self.assertEqual(len(corpus.pages), 0)
        self.assertFalse(corpus.verified)


class LineAlignmentMetricsTests(unittest.TestCase):
    def test_detects_missing_duplicated_extra_and_reordered_lines(self) -> None:
        reference = "שלום לכל התלמידים\nהיום נלמד היסטוריה\nפרק ראשון בספר\nסיכום השיעור"
        hypothesis = (
            "היום נלמד היסטוריה\n"
            "שלום לכל התלמידים\n"
            "שלום לכל התלמידים\n"
            "כתם שוליים אקראי 999\n"
            "סיכום השיעור"
        )
        stats = line_alignment_metrics(reference, hypothesis)
        self.assertEqual(stats["lines_reference"], 4)
        self.assertEqual(stats["lines_hypothesis"], 5)
        self.assertEqual(stats["matched_lines"], 3)
        self.assertEqual(stats["missing_lines"], 1)  # "פרק ראשון בספר"
        self.assertEqual(stats["duplicated_lines"], 1)  # repeated first line
        self.assertEqual(stats["extra_lines"], 1)  # margin noise
        self.assertEqual(stats["reading_order_inversions"], 1)  # line 2 before line 1

    def test_process_memory_mb_returns_non_negative_float(self) -> None:
        mem = process_memory_mb()
        self.assertIsInstance(mem, float)
        self.assertGreaterEqual(mem, 0.0)


class SuggestionBenchmarkNoDoubleCountingTests(unittest.TestCase):
    def test_multiple_proposals_for_same_span_count_once(self) -> None:
        class _TwoProposalsSameWord(SuggestionModule):
            id = "dup-test"
            name = "Dup test"
            kind = KIND_SPELLING

            def check(self, text: str) -> list[Suggestion]:
                idx = text.find("שלומ")
                if idx < 0:
                    return []
                return [
                    Suggestion(
                        module=KIND_SPELLING,
                        original="שלומ",
                        replacement="שלום",
                        alternatives=("שלוש", "שלוח"),
                        start=idx,
                        end=idx + 4,
                    ),
                    Suggestion(
                        module=KIND_SPELLING,
                        original="שלומ",
                        replacement="שלוש",
                        start=idx,
                        end=idx + 4,
                    ),
                ]

        registry = SuggestionRegistry([_TwoProposalsSameWord()])
        cases = [
            BenchmarkCase(
                id="single_error",
                category="spelling_ocr",
                noisy="שלומ עולם",
                reference="שלום עולם",
            )
        ]
        summary = evaluate_cases(registry, cases)
        self.assertEqual(summary["total_target_errors"], 1)
        self.assertEqual(summary["actual_errors_detected"], 1)
        self.assertEqual(summary["correct_top1_suggestions"], 1)
        self.assertEqual(summary["false_suggestions"], 0)
        self.assertEqual(summary["cer_after"], 0.0)


if __name__ == "__main__":
    unittest.main()
