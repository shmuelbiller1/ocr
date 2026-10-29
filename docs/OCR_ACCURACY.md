# Accuracy of the handwriting engine

This page reports what the recognition engine actually achieves, on real
handwritten pages, with a known transcription.

**Nothing on this page is an estimate.** Every number was produced by
`tools/benchmark_ocr.py` on the pages of a corpus, and the job that
produced it is part of the continuous integration build
(`.github/workflows/windows.yml`, job `ocr-engine`).

The program is made for **contemporary handwritten Hebrew-script school
notes**.  That is the material whose accuracy decides whether the
program is useful, and it is the first section of this page.  The
pages of old handwriting come after it, as a *diagnostic*: they show
that the engine reads real Hebrew handwriting at all, but they are not
the material the program is meant for, and they do not decide which
engine is the better one.

## The material that matters: modern school handwriting

The corpus of the modern school handwriting is described in
`benchmark/modern_school/README.md`, and the strategy around it in
`docs/MODERN_SCHOOL_BENCHMARK.md`.

**The accuracy of the recognition on this material is not verified
yet.**  The corpus has no page in it: the tools that build it and that
measure the engines on it are ready, and the pages - with a transcript
that was checked by somebody who is not the one who wrote it down -
have to be added by the school.  Until then, the numbers of this
section are empty, and the build says so on every run.

<!-- RESULTS:BEGIN -->
<!-- RESULTS:END -->

### What is measured, and what is not

* The measurement is of the **raw recognition** of the engine.  No
  dictionary, no language model and no proposal of the spelling, of the
  grammar or of the scholarly style is ever part of it: a number that
  was made better by a correction would not be the number of the
  mistakes of the engine.
* The transcript of a page keeps the spelling of the writer, the
  abbreviations as they are written, and the order of the lines of the
  page.  The program itself never changes the text of a recognition:
  every proposal is shown to the user, and the user accepts or refuses
  it.
* A page is measured only when its transcript was checked by somebody
  who is not the one who wrote it down.  A page without that check is
  left out of the rate and is named in the report.

### A real page that is read but not measured

There is one **real** page in the repository:
`benchmark/smoke_test/pages/scan-2026-10-28-221624.pdf` is a scan of
contemporary handwritten Hebrew that was given to the project so that
the program could be tried on the material it is made for.

Every build reads that page with every engine and publishes what each
of them read, as the artefact `smoke-test-readings`.  **No rate is
calculated from it.**  The page has no transcript that somebody else
checked, and a rate without such a transcript is not a measurement of
the engine - it would be a measurement of the transcript.  The accuracy
of the recognition on modern school handwriting therefore stays
**unverified** until a page with a checked transcript is added to
`benchmark/modern_school/`.

The readings are published so that the engines can be compared on real
material, and so that a person can look at what the program reads on a
page and judge it.

## The diagnostic corpus: the old handwriting

The corpus is the *Pinkas dataset*: 30 pages of early modern
(1500-1800) European Jewish community records written in Hebrew and
Yiddish, with a ground truth transcription for every line.

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
Hebrew handwriting with a published line level ground truth, and they
are therefore the honest test that was available.

They are **not** modern school handwriting.  A page written by a pupil in
2026 with a ballpoint pen looks different from a 17th century quill
pen, and the numbers below should be read as what they are: the accuracy
of a general multilingual handwriting model on real historical Hebrew
cursive.

<!-- DIAGNOSTIC:BEGIN -->
The numbers of the last measurement of the build.  The build reads the
first **5** pages of the dataset (`--pages 5`), and 4 of them have a
ground truth that is complete and was verified.  The rates below are of
those 4 pages, and the report names the page that was left out.

| Engine | Pages measured | Character error rate | Word error rate | Seconds per page |
| --- | --- | --- | --- | --- |
| PP-OCRv6 (small) | 4 | **57.6%** | **93.8%** | 22.43 |
| PP-OCRv6 (medium) | 4 | **55.7%** | **90.3%** | 39.06 |

The ground truth of those pages holds 10,798 characters and 2,176 words.
The engines were measured on the **same** pages, and the rates above
are the rates over those pages, so that they can be compared with one
another.

The build measures every engine that is installed on the same pages,
and writes the fresh numbers into this block.  The numbers here are
the ones of the last build; the block in the artifact of the build is
the one that was measured last.
<!-- DIAGNOSTIC:END -->

## The engines

There are two engines in the program, and every build measures both of
them on the same pages.

### The first engine: kraken and PP-OCRv6

| | |
| --- | --- |
| Engine | [kraken](https://kraken.re) 7.1.1 - Apache-2.0 |
| Weights | PP-OCRv6 (small) multilingual handwriting model - Apache-2.0, Zenodo record 21788405, <https://doi.org/10.5281/zenodo.21788405> |
| Weights, the larger model | PP-OCRv6 (medium) - Apache-2.0, Zenodo record 21788410 |
| Script | Hebrew among 43 other languages |
| Device | CPU only, no GPU and no cloud service |
| Published results of the model authors | Hebrew character error rate 6.5% (small) and 5.1% (medium), word error rate 18.5% and 14.2%, on their own test set |

The model file is never bundled with the application.  The user installs
it explicitly, and the file is checked against the MD5 digest published
by the model authors and against the SHA-256 digest pinned in
`hebrew_workbench/engine/models.py`.

### The second engine: Mishkefet-v1

| | |
| --- | --- |
| Engine | [heb-ocr](https://github.com/itayinbarr/heb-ocr) 0.1.0 - MIT (the code is shipped with the program) |
| Weights | Mishkefet-v1 - **CC-BY-NC-SA-4.0, not a commercial licence**, <https://huggingface.co/itayinbar/Mishkefet-v1> |
| Script | Hebrew, modern cursive - the material of the program |
| Device | CPU only, no GPU and no cloud service |
| Size of the model | 115.3 MB, checked against the SHA-256 `0dfb82e4…f6fd850b88` |
| Published results of the model authors | A median character error rate of 0.175 on the lines of the public Hebrew handwriting benchmark (second of nine, behind a cloud model alone) and the best page error rate of that benchmark, 0.331.  The same numbers with the best path alone, without the language models and without the beam, are 0.261 - and those are the numbers this program measures |

The weights of this model are **not** bundled with the program and are not
redistributed by it: the user fetches them, on request, from the place
where the author published them, after the licence has been shown.  The
licence forbids commercial use, so a user who needs a commercial licence
has to ask the author of the model.

**The numbers of this engine on the pages of the Pinkas corpus are not a
clean measurement.**  The model was trained on the published lines of
real Hebrew cursive of that same corpus, and on synthetic Hebrew
writing.  Its rates on the Pinkas pages are therefore optimistic, and
they cannot be compared with the rates of the first engine, which was not
trained on that corpus.  The clean comparison is the corpus of the
modern school handwriting, and it has no page in it yet.

The engine decodes greedily: no dictionary, no language model and no
spelling rule is added to the result.  The model itself writes the
folded punctuation of its own vocabulary, and it keeps the niqqud, the
te'amim and the final letter forms of the Hebrew.

**The numbers that the author published are not the numbers of this
program, and the difference is on purpose.**  The author reads with a
character language model, a word language model, a beam of twelve
candidates and three or five readings of every line at different widths.
This program reads with the best path alone, because a measurement with a
dictionary in it does not measure the engine, and the rule of this project
is that no word list and no language model take part in a measurement.  The
rate of the errors of this program is therefore **higher** than the rate
that the author published, and it is the rate of the engine and not of the
dictionary.

The page segmentation of this engine has a caveat of its own: its author
wrote it against the only real pages that exist, which are the pages of
the public benchmark, and says so.  The rate of the whole page is
therefore also to be read with that in mind.

The search that led to this engine, and the models that were not used and
why, are in `docs/ENGINES.md`.

**Choosing the default engine by the measurement is the plan, and it is
not what the program does yet.**  Today the program restores the engine
that the user chose, and when there is no such choice it takes the
first engine that it finds.  The engines are measured on the same
pages, and the one with the fewer errors - with the time that a teacher
needs to correct the text taken into account - is the one to make the
default.  The engines are plugins: the user can choose the engine in
the settings screen at any time, the choice is remembered, and a choice
of the user is never overridden.

### What the numbers of the old pages mean

**The engine works, and it is not accurate enough to be used as it is.**
The numbers are much worse than the numbers that the authors of the
model published for their own test set (6.5% character error rate
against the 57.6% that was measured on the pages of the old
handwriting).

Three things are known to make that measurement worse, and they are
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
and they say that the text of a page has to be read and corrected by a
person.  That is what the program does: the recognition result is
written into the editor as a starting point, and the program says
right after it that every line has to be checked before it is exported
or printed.  **The program never changes the text by itself, and it
never presents a recognition result as finished.**

The ground truth of every page was checked before the measurement: the
report says how many lines the file holds, how many of them have a
text, and how many were read from the words alone, so that a number
that comes from an incomplete ground truth can be seen and not
believed.  A page whose ground truth is not complete is left out of
the rate of the corpus, and the report says which pages are like that.

## Reproducing the measurement

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.14.0" "torchvision==0.29.0"
pip install --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple "kraken==7.1.1" "pillow==11.3.0"
python tools/download_model.py --model kraken-ppocrv6-small --target .cache/models
python tools/download_model.py --model kraken-ppocrv6-medium --target .cache/models
# the material the program is made for:
python tools/build_benchmark.py --corpus benchmark/modern_school
python tools/benchmark_ocr.py --corpus benchmark/modern_school \
    --engines kraken-ppocrv6-small kraken-ppocrv6-medium
# the diagnostic corpus of the old handwriting:
python tools/benchmark_ocr.py --pinkas --download --cache .cache/pinkas --pages 5 \
    --engines kraken-ppocrv6-small kraken-ppocrv6-medium
```

The pair of `torch` and `torchvision` has to be a matching pair from the
same place: `kraken` asks for `torch<=2.14`, and the `torchvision` that
belongs to `torch` 2.14.1 asks for torch 2.14.1, so the two do not fit
together and the recognition dies with `operator torchvision::nms does
not exist`.  `python tools/check_engine.py` says whether the pair works.

## How the numbers are computed

* The ground truth of a page is the concatenation of the line
  transcriptions of its file, in reading order.
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
