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
import unicodedata

__all__ = [
    "normalise",
    "levenshtein",
    "character_error_rate",
    "word_error_rate",
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
