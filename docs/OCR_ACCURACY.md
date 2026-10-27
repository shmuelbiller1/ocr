# Accuracy of the handwriting engine

This page reports what the recognition engine actually achieves, on real
handwritten pages, with a known transcription.

**Nothing on this page is an estimate.** Every number was produced by
`tools/benchmark_ocr.py` on the pages of a public corpus, and the job that
produced it is part of the continuous integration build
(`.github/workflows/windows.yml`, job `ocr-engine`).

## The engine

| | |
| --- | --- |
| Engine | [kraken](https://kraken.re) 7.1.1 - Apache-2.0 |
| Weights | PP-OCRv6 (small) multilingual handwriting model - Apache-2.0, Zenodo record 21788405, <https://doi.org/10.5281/zenodo.21788405> |
| Script | Hebrew among 43 other languages |
| Device | CPU only, no GPU and no cloud service |
| Published results of the model authors | Hebrew character error rate 6.5%, word error rate 18.5% on their own test set |

The model file is never bundled with the application.  The user installs
it explicitly, and the file is checked against the MD5 digest published
by the model authors and against the SHA-256 digest pinned in
`hebrew_workbench/engine/models.py`.

## The test corpus

| | |
| --- | --- |
| Corpus | *The Pinkas Dataset* |
| Authors | Irina Rabaev, Berat Kurar Barakat, Jihad El-Sana |
| Publication | *The Pinkas Dataset*, ICDAR 2019 |
| DOI | <https://doi.org/10.5281/zenodo.3569694> |
| License | CC-BY-4.0 - attribution required, commercial use allowed |
| Content | 30 pages of early modern (1500-1800) European Jewish community records in Hebrew and Yiddish, with a line level ground truth |

The corpus is downloaded by the benchmark with its published MD5 digest
(`802f14fbdb400efab9cb0808c3620be8`) and is never committed to this
repository.

### What this corpus does and does not tell us

The Pinkas pages are **early modern cursive** written by professional
community scribes around 1500-1800.  They are the largest corpus of real
Hebrew handwriting with a published line level ground truth, and they are
therefore the honest test that was available.

They are **not** modern school handwriting.  A page written by a pupil in
2026 with a ballpoint pen looks different from a 17th century quill
pen, and the numbers below should be read as what they are: the accuracy
of a general multilingual handwriting model on real historical Hebrew
cursive.

## Measured results

The numbers in this section are filled in by the `ocr-engine` job of the
build itself: the job measures the accuracy, writes the result of the
measurement into this file and sends it back to the branch.  The numbers
are therefore always the ones that were measured, and never numbers that
somebody wrote by hand.  The report they come from is also uploaded as
the artefact `ocr-accuracy-report`.

<!-- RESULTS -->

## Reproducing the measurement

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.14.0" "torchvision==0.29.0"
pip install --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple "kraken==7.1.1" "pillow==11.3.0"
python tools/download_model.py --model kraken-ppocrv6-small --target .cache/models
python tools/benchmark_ocr.py --model .cache/models/small.safetensors --download --cache .cache/pinkas --pages 10
```

The pair of `torch` and `torchvision` has to be a matching pair from the
same place: `kraken` asks for `torch<=2.14`, and the `torchvision` that
belongs to `torch` 2.14.1 asks for `torch` 2.14.1, so the two do not fit
together and the recognition dies with `operator torchvision::nms does
not exist`.  `python tools/check_engine.py` says whether the pair works.

## How the numbers are computed

* The ground truth of a page is the concatenation of the line
  transcriptions of its PAGE XML file, in reading order.
* Both sides are normalised the same way: Unicode NFC, Hebrew vowel
  points removed, whitespace collapsed.  A second pair of numbers is
  computed with the vowel points left in place.
* The character error rate is the Levenshtein distance between the two
  strings, divided by the length of the ground truth.
* The word error rate is the same measure on whitespace separated words.
  The rate of the whole corpus is the number of the words that were not
  read right over the number of the words of the ground truth, and not
  the average of the rates of the pages, so that a page with few words
  does not count as much as a page with many.
* Nothing is post-processed: the text the engine produced is compared as
  it is.
