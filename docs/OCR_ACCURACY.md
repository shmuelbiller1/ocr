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

The numbers in this section are produced by the `ocr-engine` job of the
build: the job measures the accuracy on the pages of the corpus and
uploads the report as the artefact `ocr-accuracy-report` and the page
with the numbers as the artefact `ocr-accuracy-document`.  The numbers
below are the ones of that measurement, taken from the report of the
build of the 27th of October 2026 (commit `4a69fa1`).

<!-- RESULTS:BEGIN -->

Measured with kraken PP-OCRv6 (Apache-2.0) on 8 pages of The Pinkas Dataset:

| | |
| --- | --- |
| Character error rate | **56.3%** |
| Word error rate | **92.1%** |
| Seconds per page | 17.18 |
| Pages | 8 |
| Characters of the ground truth | 20049 |
| Words of the ground truth | 4045 |

| Page | Characters in the ground truth | Character error rate | Word error rate | Seconds |
| --- | --- | --- | --- | --- |
| Page 105_1.jpg | 2862 | 64.6% | 98.6% | 23.62 |
| Page 105_2.jpg | 3008 | 75.6% | 100.3% | 19.41 |
| Page 107_1.jpg | 2287 | 35.3% | 82.2% | 15.21 |
| Page 112_1.jpg | 2641 | 48.8% | 90.9% | 16.69 |
| Page 112_2.jpg | 1617 | 57.8% | 94.0% | 12.82 |
| Page 113_1.jpg | 3157 | 28.3% | 69.1% | 19.24 |
| Page 113_2.jpg | 1895 | 73.0% | 99.2% | 13.34 |
| Page 114_2.jpg | 2582 | 71.7% | 106.8% | 17.10 |

The rate of the corpus is the number of the characters that were not
read right over the number of the characters of the ground truth of the
whole corpus, and not the average of the rates of the pages, so that a
page with few characters does not count as much as a page with many.

The numbers were produced by `tools/benchmark_ocr.py` in the `ocr-engine` job of the build, and the report they come from is uploaded as the artefact `ocr-accuracy-report`.

<!-- RESULTS:END -->

### What these numbers mean

**The engine works, and it is not accurate enough to be used as it is.**
The numbers are the ones that were measured on real handwritten pages
with a published transcription, and they are much worse than the numbers
that the authors of the model published for their own test set (6.5%
character error rate against the 56.3% that was measured here).

Three things are known to make the measurement worse, and they are
named here so that nobody has to guess:

1. **The corpus is hard.**  The pages are early modern cursive of
   1500-1800, written with a quill pen in a script that few people can
   read today.  The model is a general multilingual model of modern
   handwriting.
2. **The engine reads the whole page, and the ground truth is the text
   of the lines.**  The engine also reads the numbers and the notes in
   the margin of the page, and they are not part of the ground truth,
   so every one of them counts as an error.
3. **The order of the lines of the page and the order of the lines of
   the ground truth are not always the same**, and a line that is out
   of place makes every character of it wrong.

So the numbers are an honest measure of the *engine on this corpus*,
and they say that the text of a historical page has to be read and
corrected by a person.  That is what the program does: the recognition
result is written into the editor as a starting point, and the program
says right after it that every line has to be checked before it is
exported or printed.  **The program never changes the text by itself,
and it never presents a recognition result as finished.**

The ground truth of every page was checked before the measurement: the
report says how many lines the file holds, how many of them have a
text, and how many were read from the words alone, so that a number
that comes from an incomplete ground truth can be seen and not
believed.  In this measurement **the ground truth of one page is not
complete**: the file of `Page 113_1.jpg` holds 45 lines, and one of
them has no text at all.  The rate of the corpus therefore holds a
little text that the engine was never asked to read.  The report says
which pages are like that, and the numbers of the other seven pages
are not affected by it.

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
