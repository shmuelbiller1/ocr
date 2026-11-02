"""How the accuracy of a recognition is counted.

The measurement is deliberately simple: the text of the engine and the
text of the ground truth are put in the same form, and the number of
the edits that turn one into the other is counted.  Nothing else is
done to the text - no dictionary, no language model, no correction of
spelling.  The number that comes out is the number of the mistakes of
the recognition and nothing else.
"""

from __future__ import annotations

import re
import sys
import unicodedata

__all__ = [
    "normalise",
    "levenshtein",
    "character_error_rate",
    "word_error_rate",
    "line_alignment_metrics",
    "process_memory_mb",
    "POINTS",
    "SPACE",
]

# Hebrew vowel points and cantillation marks.
POINTS = re.compile(r"[֑-ֽֿׁ-ׂׄ-ׇ]")
SPACE = re.compile(r"\s+")


def normalise(text: str, keep_points: bool = False) -> str:
    """Normalise text the same way for the engine and for the ground truth."""
    text = unicodedata.normalize("NFC", text)
    if not keep_points:
        text = POINTS.sub("", text)
    text = text.replace("״", '"').replace("׳", "'")
    return SPACE.sub(" ", text).strip()


def levenshtein(first: list[str], second: list[str]) -> int:
    """Edit distance between two sequences."""
    if len(first) < len(second):
        first, second = second, first
    previous = list(range(len(second) + 1))
    for index1, item1 in enumerate(first, start=1):
        current = [index1]
        for index2, item2 in enumerate(second, start=1):
            insert = current[index2 - 1] + 1
            delete = previous[index2] + 1
            replace = previous[index2 - 1] + (item1 != item2)
            current.append(min(insert, delete, replace))
        previous = current
    return previous[-1]


def character_error_rate(reference: str, hypothesis: str) -> float:
    if not reference:
        return 0.0 if not hypothesis else 1.0
    distance = levenshtein(list(reference), list(hypothesis))
    return distance / len(reference)


def word_error_rate(reference: str, hypothesis: str) -> float:
    reference_words = reference.split()
    hypothesis_words = hypothesis.split()
    if not reference_words:
        return 0.0 if not hypothesis_words else 1.0
    distance = levenshtein(reference_words, hypothesis_words)
    return distance / len(reference_words)


def _line_similarity(first: str, second: str) -> float:
    """Normalized edit similarity in [0.0, 1.0] between two normalized lines."""
    if not first and not second:
        return 1.0
    if not first or not second:
        return 0.0
    denom = max(len(first), len(second))
    return max(0.0, 1.0 - levenshtein(list(first), list(second)) / denom)


def line_alignment_metrics(
    reference_text: str,
    hypothesis_text: str,
    match_threshold: float = 0.35,
    duplicate_threshold: float = 0.85,
) -> dict[str, int]:
    """Count missing lines, extra lines, duplicated lines, and order inversions.

    Each non-empty line is normalized without vowel points.  First, a
    one-to-one greedy alignment by highest character similarity (>=
    ``match_threshold``) matches reference lines with hypothesis lines so
    that genuine line reordering can be detected.  Unmatched reference
    lines are counted as ``missing_lines``; unmatched hypothesis lines
    are classified as ``duplicated_lines`` when they strongly match an
    already-covered reference line or an earlier hypothesis line (>=
    ``duplicate_threshold``), and otherwise as ``extra_lines``.
    """
    ref_lines = [
        normalise(line) for line in reference_text.splitlines() if normalise(line)
    ]
    hyp_lines = [
        normalise(line) for line in hypothesis_text.splitlines() if normalise(line)
    ]
    n_ref = len(ref_lines)
    n_hyp = len(hyp_lines)
    if n_ref == 0 or n_hyp == 0:
        return {
            "lines_reference": n_ref,
            "lines_hypothesis": n_hyp,
            "matched_lines": 0,
            "missing_lines": n_ref,
            "extra_lines": n_hyp,
            "duplicated_lines": 0,
            "reading_order_inversions": 0,
        }

    candidates: list[tuple[float, int, int]] = []
    for r_idx, r_line in enumerate(ref_lines):
        for h_idx, h_line in enumerate(hyp_lines):
            sim = _line_similarity(r_line, h_line)
            if sim >= match_threshold:
                # Prefer closer relative position when two identical lines exist.
                pos_bias = 1e-4 * (1.0 - abs(r_idx / max(n_ref, 1) - h_idx / max(n_hyp, 1)))
                candidates.append((sim + pos_bias, r_idx, h_idx))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))

    matched_ref: set[int] = set()
    matched_hyp: dict[int, int] = {}
    for _score, r_idx, h_idx in candidates:
        if r_idx in matched_ref or h_idx in matched_hyp:
            continue
        matched_ref.add(r_idx)
        matched_hyp[h_idx] = r_idx

    missing_lines = n_ref - len(matched_ref)
    duplicated_lines = 0
    extra_lines = 0
    for h_idx, h_line in enumerate(hyp_lines):
        if h_idx in matched_hyp:
            continue
        is_dup = any(
            _line_similarity(h_line, ref_lines[r_idx]) >= duplicate_threshold
            for r_idx in matched_ref
        ) or any(
            _line_similarity(h_line, hyp_lines[prev_idx]) >= duplicate_threshold
            for prev_idx in range(h_idx)
        )
        if is_dup:
            duplicated_lines += 1
        else:
            extra_lines += 1

    ordered_pairs = sorted(matched_hyp.items())  # sorted by hyp line index
    inversions = 0
    for i in range(len(ordered_pairs)):
        for j in range(i + 1, len(ordered_pairs)):
            if ordered_pairs[i][1] > ordered_pairs[j][1]:
                inversions += 1

    return {
        "lines_reference": n_ref,
        "lines_hypothesis": n_hyp,
        "matched_lines": len(matched_ref),
        "missing_lines": missing_lines,
        "extra_lines": extra_lines,
        "duplicated_lines": duplicated_lines,
        "reading_order_inversions": inversions,
    }


def process_memory_mb() -> float:
    """Best-effort peak resident / working-set memory in MiB without extra deps."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb
            )
            if ok:
                return round(counters.PeakWorkingSetSize / (1024.0 * 1024.0), 2)
        except Exception:
            return 0.0
        return 0.0
    try:
        import resource

        self_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        child_rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        total = max(self_rss, child_rss)
        if sys.platform == "darwin":
            return round(total / (1024.0 * 1024.0), 2)
        return round(total / 1024.0, 2)
    except Exception:
        return 0.0
