# Optional Mishkefet decoding — experimental, not a promised accuracy gain

## In the Windows app

1. In **Settings / plugins**, select **Mishkefet-v1** (prefer the separate-process
   worker in the packaged app).
2. Choose a decoding profile for that plugin:
   - **Raw** (default): greedy, one scale, no language model.
   - **Beam**: beam width 12, three horizontal scales, no language model.
   - **Assisted**: beam width 12, three scales, character LM weight 0.4 and
     word-prior weight 0.2. This is an explicitly language-assisted pipeline,
     not a raw-model benchmark.
3. **All Models — Noncommercial** already includes the character and word
   language-model files: no additional download is needed for assisted mode.
   **Lite / regular ZIP** users must first install Mishkefet and choose
   **Install optional language models** in Settings. The confirmation displays
   sources, sizes and the **CC-BY-NC-SA-4.0** terms before downloading.
   No scan is uploaded. The remove button deletes only the two optional files;
   if removed, they must be restored before assisted decoding can run offline.
4. Run OCR normally. The editor and original OCR text receive **raw text**.
   The **Raw / assisted comparison** dock displays both readings side by side.
   To use the alternative, click its button and confirm. Replacement is undoable;
   the original raw text remains available through restore-original.
5. Both readings and the profile are saved in the project. Selecting another
   document shows only that document's readings. Missing or changed LM files
   fail explicitly; there is no silent fallback to another decoding profile.

The alternative can change abbreviations, uncommon names, Yiddish/Aramaic and
specialised terms. Read every line. Grammar, spelling and לשון הספר remain
separate optional reviewable modules. Raw remains the default; there is no
automatic default selection based on unverified author benchmarks.

## Files and integrity

Model repository revision: `16380452d62839f369c36f17312c94d5d1af1768`.
Metadata checked using the author's [file tree API](https://huggingface.co/api/models/itayinbar/Mishkefet-v1/tree/main?recursive=true&expand=false)
and [model card](https://huggingface.co/itayinbar/Mishkefet-v1/blob/16380452d62839f369c36f17312c94d5d1af1768/README.md).
The card's CC-BY-NC-SA-4.0 applies to the model repository; the upstream code
is MIT. The All Models — Noncommercial EXE redistributes the unmodified data
files with attribution and a licence link. Lite and the regular ZIP do not
include them; their optional installation uses the download flow below.

| File | Bytes | Published LFS SHA-256 |
| --- | ---: | --- |
| `hebrew_char6.pkl` | 28,241,531 | `60e6b974e797c74e2c543b27bfe1f9b02e8e8960594cfde7dc452553e4be2161` |
| `hebrew_words.pkl` | 3,796,006 | `39f8ed30114125d53a47d4c383e48338bd5f8ffce21ae981e5fd7f99ade08874` |

Downloads use immutable-revision URLs and the existing temporary-file,
size/digest verification and cancellation flow. Before loading the data,
the exact byte buffer is checked again, then deserialized with all pickle
class/global lookups forbidden. The upstream general-purpose pickle loaders
are **not** used. The additional MIT scoring modules were copied unchanged;
see `engine/vendor/README.md` for provenance.

## Compare the same page without contaminating raw benchmarks

```sh
python tools/download_model.py --model mishkefet-char-lm --target .cache/models
python tools/download_model.py --model mishkefet-word-lm --target .cache/models
python tools/compare_mishkefet.py \
  --document benchmark/smoke_test/pages/scan-2026-10-28-221624.pdf \
  --model .cache/models/mishkefet-v1.pt \
  --output build/decoding-comparison
```

The diagnostic writes separate exact raw and alternative text files and a JSON
report. Timings are **raw-only runtime** and **comparison runtime including both
raw and alternative inference** (including each run's model loading); they are
not pure decoder timings. The comparison also saves its own raw pass, using
the same crops as the alternative.

Without an independently checked transcript: **accuracy unverified**, no CER
or WER. For a checked transcript add `--transcript page.txt --verified-by NAME`.
This is an explicit user attestation, not an automatic verification. The
comparison uses exact-character CER (including points, punctuation and line
breaks), and whitespace-separated WER; no spelling correction or text
normalisation. It is a separate diagnostic, never inserted into the raw-engine
accuracy reports. Correction-time measurement still requires staff review.

CI exercises the supplied scan with assisted decoding and verifies nonempty
raw/alternative output from the packaged Windows worker. It does **not** claim
an accuracy improvement without ground truth. Author benchmark numbers are
not measurements of this app or of your scan.
