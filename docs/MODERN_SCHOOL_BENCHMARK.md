# The benchmark of the modern school handwriting

The program is made for **contemporary handwritten Hebrew-script school
notes**: the notes that students write in class, with a pen, in a
notebook or on a sheet of paper.

This page says what is measured on that material, how the ground truth
of a page is made trustworthy, how the engines are compared, and what
is still missing.  The rules of the corpus itself are in
`benchmark/modern_school/README.md`; the numbers are in
`docs/OCR_ACCURACY.md`.

## The state of things

| | |
| --- | --- |
| The corpus of the modern school handwriting | **Empty** - there is no page in it yet |
| The tools that build the corpus and measure the engines on it | **Ready** - `tools/build_benchmark.py` and `tools/benchmark_ocr.py` |
| The measurement of the engines on the same pages | **Ready** - every engine is measured on the same pages |
| The accuracy of the recognition on the material of the program | **Not verified** - there is nothing to measure it on yet |

The last line is the honest state of the work, and it is written in
the same words in the report that every build produces.  Nothing in
this repository claims a number for the recognition of modern school
handwriting, because there is no page with a verified transcript to
measure it on.

## Why the historical pages are only a diagnostic

The *Pinkas dataset* (early modern Hebrew and Yiddish records of
1500-1800) is the largest corpus of real Hebrew handwriting with a
published line level ground truth that was available, and it is
measured on every build.  It is kept for what it is good for:

* it shows that the engine reads real Hebrew handwriting and not only
  synthetic pages;
* it catches a change that makes the engine worse, over and over
  again, on the same pages.

It is **not** the material the program is made for.  A page written by
a pupil with a ballpoint pen in 2026 is a different kind of writing,
and the numbers of the old pages do not say anything about it.  The
engines are therefore **not** chosen by the numbers of the old pages.

## How the ground truth of a page is made trustworthy

1. The transcript of a page is written line by line, in the order of
   the page, with the spelling of the writer, the abbreviations and the
   unusual terms kept as they are.
2. A line that cannot be read is marked `[?]`, and the page is then not
   measured: a line that is missing from the ground truth would be
   counted as a mistake of the engine.
3. The transcript is checked by somebody who is **not** the one who
   wrote it down - a teacher of the class, for example - and the name
   of that person is written in the `verified_by` of the page.
4. Only a verified page is measured.  A corpus in which no page was
   verified is not a measurement of the recognition, and the report of
   the build says so.

The rules of the transcripts are in `benchmark/modern_school/README.md`,
so that a teacher who writes a transcript does not have to read the
code of the program.

## What is measured, and what is not

The measurement is of the **raw recognition**.  No dictionary, no
language model and no proposal of the spelling, of the grammar or of
the scholarly style is ever part of it.  The program proposes changes
to the text, and the user accepts or refuses every one of them; a
number that was made better by a proposal would not be the number of
the mistakes of the engine, and it would not be comparable between two
engines.

The measurement keeps the original spelling, the abbreviations, the
order of the lines and the unusual terms of the writer, because those
are part of what the teacher has to check.

## How the engines are compared

Every engine is measured on the **same** pages, with the same ground
truth, in the same run:

```bash
python tools/benchmark_ocr.py --corpus benchmark/modern_school \
    --engines kraken-ppocrv6-small kraken-ppocrv6-medium
```

The report holds, for every engine: the character error rate, the word
error rate, the seconds per page, and the rate for every page, so that
a page on which one engine is better than the other can be seen.

**The default engine is not the first one in the list - that is the plan,
and it is not what the program does yet.**  Today the program restores
the engine that the user chose, and when there is no such choice it
takes the first engine that it finds.  The decision has two halves, and
both of them have to be measured:

* the number of the errors of the engine;
* the time that a teacher needs to correct the text of the engine.

The second half is a measurement of people, and it belongs to the
school.  Until it is made, the default is the engine with the fewest
errors in the measurement, and the user can choose another engine in
the settings screen at any time - the engines are plugins, the choice
is remembered, and a choice of the user is never overridden.

## How the corpus is filled

The corpus is a folder with a `corpus.json` in it, and the pages are
added to it one at a time:

```json
{
  "image": "pages/class7a_page01.jpg",
  "transcript": "transcripts/class7a_page01.txt",
  "writer": "7a-01",
  "date": "2026-03-12",
  "verified_by": ["the name of the teacher"]
}
```

```bash
python tools/build_benchmark.py --corpus benchmark/modern_school
```

The command checks every page, writes the digest of every image into
the manifest of the corpus and says which pages are not verified.  The
measurement checks the images against that manifest before it measures
anything: when an image was changed, the measurement is of a different
corpus than the one that was built, and it is not published, so that
the same pages are measured every time.

Before a page is put in the corpus, the school has to agree to it in
writing, and the agreement has to allow the use of the page for
measuring the recognition.  The agreement is described in the `license`
of the corpus.

## What comes next

* The school adds pages with verified transcripts, and the build
  measures the engines on them.
* The rate of the errors and the time of the correction are written
  into `docs/OCR_ACCURACY.md` on every build.
* The engine with the best measurement becomes the default, and the
  choice of the user is always one click away.
