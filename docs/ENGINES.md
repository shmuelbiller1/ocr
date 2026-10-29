# The handwriting engines: what exists, and what was chosen

This page records the search for an open model that can read the
handwriting the program is made for, and the reasons behind the choice.
It was written on 2026-10-28 and it says what was checked and when.

## What the program needs

The material is **contemporary handwritten Hebrew script**: school notes,
cursive, with abbreviations, with Yiddish and Aramaic words, with terms of
the trade of the school.  The engine has to run on the processor of an
ordinary computer, offline, without sending anything anywhere.

Three rules follow from that, and they decide what is acceptable:

1. **No cloud.** A model that runs on somebody else's server is not an
   option, however good it is.
2. **No training.** The program uses models that somebody else trained.
3. **The licence has to be checked.** A model whose licence forbids the
   use that the user makes of it, or that nobody wrote down, is not used.
   A model that is not bundled and is fetched by the user, with its
   licence shown before the download, is a different case: the user
   decides, and the conditions of the licence are written down.

## The models that were looked at

| Model | What it is | Licence | Verdict |
| --- | --- | --- | --- |
| **Mishkefet-v1** (`itayinbar/Mishkefet-v1`, code in `itayinbarr/heb-ocr`) | A 30-million-parameter CTC recogniser written **for modern Hebrew cursive**. On the public Hebrew handwriting leaderboard it has the **best page error rate** of the board (0.331) and is **second of nine** in the line mode (a median error rate of 0.175). The only model ahead of it in the line mode is a cloud model of a company, which this program may not use. It runs on the processor. | Weights: **CC-BY-NC-SA-4.0** (not commercial). Code: MIT. | **Used**, as the second engine. The code is shipped with the program; the weights are fetched by the user, on request, and checked against a digest. The licence is shown before the download. |
| **kraken + PP-OCRv6** (small and medium) | A multilingual recogniser that reads 43 languages, among them Hebrew. | Apache-2.0 (code and weights) | **Used**, as the first engine. The weights are fetched by the user and checked against two digests. |
| `cyttic/hebrew-ocr-android` | ONNX models of a TrOCR line recogniser for Hebrew, with a detector and a character language model. | **No licence is written on the model files.** | **Not used.** A file without a licence is a file that nobody may redistribute, and the conditions of the use are unknown. |
| `sivan22/testing-trOCR-hebrew-handwritten` | A TrOCR fine-tuned for Hebrew handwriting. | **No licence is written on the model.** | **Not used**, for the same reason. |
| `johnlockejrr/ppocrv6-sam-heb` | PP-OCRv6 recognisers for **Samaritan** Hebrew manuscripts. | Apache-2.0 | **Not used for the target.** The script is Samaritan and not the modern Hebrew script of the school notes. It stays a candidate for a corpus of Samaritan manuscripts. |
| Tesseract with `heb.traineddata` | A printed-Hebrew recogniser. | Apache-2.0 | **Not used for the target.** It reads print, not a cursive hand. It stays a candidate for printed documents. |
| Gemini, GPT and the other cloud models | The best numbers on the Hebrew handwriting leaderboard. | — | **Not used.** The program never sends a page anywhere. |

## What was chosen, and why

The two engines that are in the program are the two that answer the
question "what is the best open model for this material?":

* **Mishkefet-v1** is the only open model that was *written for modern
  Hebrew cursive*, and it is the best of them on the public benchmark.
* **kraken + PP-OCRv6** has a permissive licence and a much smaller
  model, and it reads many languages.

The program does not decide which one is better.  Every build measures
every engine on the **same pages** and writes the numbers into
`docs/OCR_ACCURACY.md`, and the default engine is the one with the fewest
measured errors and the shortest correction time for the person who reads
the page.  That rule is written down and it is not yet carried out: the
corpus of the modern school handwriting has no page in it yet.

## A warning that belongs with every number of the second engine

Mishkefet-v1 was trained on the 943 published lines of real Hebrew
cursive of the Pinkas corpus, and on synthetic Hebrew writing.  The
diagnostic corpus of this program **is** the Pinkas corpus.  Its numbers
on that corpus are therefore optimistic, and they are **not** a clean
comparison with the numbers of kraken, which was not trained on it.

The clean comparison is the corpus of the modern school handwriting, and
that corpus is still empty.  This is written in `docs/OCR_ACCURACY.md` as
well, next to the numbers.

## What the decoding does to the numbers

The numbers of the leaderboard are read with a character language model, a
word language model, a beam of twelve candidates and three or five readings
of every line at different widths.  The default/raw benchmark profile reads the **best path
alone**, because a measurement with a dictionary in it measures the
dictionary and not the engine, and because the program never rewrites the
text of a recognition.  The author of the model publishes the greedy
number as well: **0.261** against the **0.175** of the full reading.  The
rate that this program measures is therefore the greedy rate, and it is
higher than the number of the leaderboard.

## The material that could be measured

| Corpus | What it is | Licence | Use |
| --- | --- | --- | --- |
| `benchmark/modern_school/` | The pages of the school, with a transcript that somebody else checked. | — | **The corpus of the program. It has no page in it yet.** |
| Pinkas | 30 pages of early modern (1500–1800) community records, with a ground truth for every line. | CC-BY-4.0 | A diagnostic of the old handwriting. Not the material of the program. |
| `ivrit-ai/hebrew-handwriting-ocr-benchmark` | The public benchmark of Hebrew handwriting. | ivrit.ai licence, gated | The benchmark of the leaderboard. The program does not download it. |
| `cyttic/diffusionpen-hebrew-handwriting` | 116,000 synthetic Hebrew lines in 491 hands. | CC-BY-4.0 | A possible third diagnostic, of *modern-style* writing. It is generated, not written by a person, and it is not in the program yet. |
| `sivan22/hebrew-handwritten-dataset` | 25,000 lines composed from real handwritten Hebrew glyphs. | CC-BY-3.0 | The same, and the same reservation. |

The two synthetic corpora are worth adding as a diagnostic of *modern*
writing, because the only real material of the program does not exist yet.
They are not a substitute for it: a generated page does not have the
errors of a real hand.

## How the licence of a model is checked before it is fetched

* The licence, the size, the place of the download and the digest of
  every known model are in `hebrew_workbench/engine/models.py`.
* The program shows the licence of the model before it starts the
  download.
* The file that arrives is checked against the SHA-256 that this project
  pinned, and against the MD5 that the author published when there is
  one.  A file that does not match is deleted and is never used.
* The weights of a model with a non-commercial licence are not bundled
  with the program and are not redistributed by it.

## Optional experimental decoding

The app now exposes beam/TTA and language-assisted profiles separately from
raw recognition. Both retain the raw reading and require explicit approval
to use the alternative. See [ASSISTED_DECODING.md](ASSISTED_DECODING.md) for
settings, licence/integrity details and same-page comparisons. No improvement
on modern school handwriting is claimed without a checked transcript.
