# The benchmark of modern school handwriting

This is the corpus that matters.  The program is made for
**contemporary handwritten Hebrew-script school notes**: the notes that
students write in class, with a pen, in a notebook or on a sheet of
paper.

There are no pages here yet.  The tools that build this corpus and that
measure the recognition on it are ready, and the accuracy of the
recognition **on this material is not verified** until real pages are
added.  `docs/OCR_ACCURACY.md` says so, and the report of every
measurement says so as well.

## What belongs here

* A scan or a photo of a page that a student wrote in class.
* The transcript of the page: every line of the page, in the order of
  the page, one line per line of the file.
* The name of the writer (a code is enough, e.g. `7a-01`), the date,
  and the name of the person who checked the transcript.

## The rules of the transcript

The transcript is what the page says, and nothing else:

* the spelling of the writer is kept, even when it is wrong;
* abbreviations are written as they are written, not as they should be;
* the order of the lines is the order of the page;
* nothing is added, and nothing is left out - a line that cannot be
  read is marked `[?]`, and the page is then **not** measured;
* a line that was not read at all is not a line of the transcript.

The transcript is the ground truth of the measurement, and the
measurement is of the recognition alone.  A dictionary, a language
model or a proposal of the spelling is never part of it, because then
the number would not be the number of the mistakes of the engine.

## The verification

A transcript is only used when somebody who is **not** the one who
wrote it down checked it - a teacher of the class, for example.  The
name of that person is written in the `verified_by` of the page.  A
page without a verification is not measured, and a corpus in which no
page was verified is not a measurement of the recognition.

## The agreement of the school

The pages of the students are personal.  Before a page is put here, the
school has to agree to it, in writing, and the agreement is described
in the `license` of `corpus.json`.  A page of a pupil may not be put
here without that agreement, and the agreement has to allow the use of
the page for measuring the recognition.

## The form of the corpus

`corpus.json` describes the corpus:

```json
{
  "name": "Modern school handwriting",
  "description": "Pages written by students in class, 2026.",
  "target": "modern",
  "license": "the agreement of the school, of the 3rd of March 2026",
  "pages": [
    {
      "image": "pages/class7a_page01.jpg",
      "transcript": "transcripts/class7a_page01.txt",
      "writer": "7a-01",
      "date": "2026-03-12",
      "verified_by": ["the name of the teacher"],
      "notes": "the abbreviations of the pupil were kept"
    }
  ]
}
```

The transcript of a page may also be a file in the PAGE XML form of the
Pinkas dataset; the two forms are read the same way.

## How the pages are measured

```
python tools/build_benchmark.py --corpus benchmark/modern_school
python tools/benchmark_ocr.py --corpus benchmark/modern_school \
    --engines kraken-ppocrv6-small kraken-ppocrv6-medium
```

The first command checks the corpus and writes the manifest of it (the
digest of every page, so that the same pages are measured every time).
The second command measures every engine on the **same** pages, and
writes the rates of every engine into a report.

The engines are compared with the rate of the errors and with the time
that a teacher needs to correct the text - not with the order in which
they are listed.
