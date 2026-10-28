"""Measuring the accuracy of the recognition, on the material that matters.

The program is made for **contemporary handwritten Hebrew-script school
notes**.  The corpora of this package say what is measured, on which
pages, and whether the ground truth of every page was verified by
somebody who is not the one who wrote it down.

* `hebrew_workbench.benchmark.corpus` - the corpora and their pages;
* `hebrew_workbench.benchmark.metrics` - the character and the word
  error rate, with no dictionary and no language model in them.

The recognition is measured as it is.  Nothing that the program does to
the text afterwards - the proposals of the spelling, of the grammar or
of the scholarly style - is ever part of a measurement.
"""

from __future__ import annotations

from .corpus import (
    Corpus,
    Page,
    load_corpus,
    pinkas_pages,
    read_page_xml_report,
    read_transcript,
)
from .metrics import (
    character_error_rate,
    levenshtein,
    normalise,
    word_error_rate,
)

__all__ = [
    "Corpus",
    "Page",
    "load_corpus",
    "pinkas_pages",
    "read_transcript",
    "read_page_xml_report",
    "character_error_rate",
    "word_error_rate",
    "levenshtein",
    "normalise",
]
