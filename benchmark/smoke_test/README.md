# The smoke test page

This folder holds a **real** page: a scan of contemporary handwritten
Hebrew that was given to the project so that the program could be
tested on the material it is made for.  It is not a synthetic sample -
the handwriting is real, and it is the writing of a student.

The page was given by the person who asked for it.  It is a page of
somebody's own writing, and it can be taken out of the repository on
request.

## What it is used for

* to check that the program opens a real scan, renders it at the right
  resolution and hands it to the engines;
* to publish what every engine reads on a real page, so that the
  engines can be compared on the same material and not only on the
  diagnostic corpus of the old handwriting.

## What it is not used for

The page has **no transcript that somebody else checked**, and that is
why the accuracy of the recognition on modern school handwriting is
still **not verified**.  `docs/OCR_ACCURACY.md` says so, and so does
the report of every measurement.

A page without a verified transcript is never counted in a rate: the
number would then be the number of the mistakes of the transcript, and
not the number of the mistakes of the engine.

To make this page part of the measured corpus, a transcript has to be
written and checked by somebody who is not the one who wrote it, and
the page has to be put in `benchmark/modern_school/` with its
transcript.  The rules of the transcript are in the README of that
folder.

## The file

* `pages/scan-2026-10-28-221624.pdf` - the scan as it was given: one
  page, A4, without a text layer, so that the program has to read the
  picture and not the words of the file.

## How it is read

    python tools/smoke_test.py \
        --document benchmark/smoke_test/pages/scan-2026-10-28-221624.pdf \
        --models .cache/models \
        --engines kraken-ppocrv6-small kraken-ppocrv6-medium mishkefet-v1 \
        --output build/smoke

The build runs it and publishes the readings as the artefact
`smoke-test-readings`.  Every engine writes the text it read, and the
report says that the accuracy is not verified.
