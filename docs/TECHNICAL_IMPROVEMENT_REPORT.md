# Technical Improvement Report: Hebrew Notes Workbench (`arena/79dcb59d-ocr`)

**Date:** 2026-11-01  
**Baseline commit (`main`):** `d01686c6f971a1b662e0963b77c0806eea24d611` (`v0.4.0` + post-release Qt6 printer patch)  
**Pull Request:** `#22` (`arena/79dcb59d-ocr`)

> **Epistemic discipline:** Throughout this report, **[Measured Fact]** denotes quantities measured directly in this repository or its GitHub Actions Linux/Windows CI runners on pinned artifacts; **[External Published Claim]** denotes results reported by upstream model/dataset authors on external benchmarks not run inside this repository; and **[Engineering Hypothesis]** denotes reasoned expectations awaiting human-consented modern school pages (`benchmark/modern_school`) or physical Windows printer inspection.

---

## 1. Current System Findings

**[Measured Fact]** Direct code, packaging, and CI inspection of `main` (`d01686c`) established the following architecture and bottlenecks:

1. **Two-process desktop architecture (`app.py` + `ocr_worker/main.py`):**
   - The PySide6 GUI (`PySide6-Essentials==6.9.1`, `pillow==11.3.0`, `pypdfium2==4.30.0`, `python-docx==1.2.0`) runs in `HebrewNotesWorkbench.exe` without importing `torch`, `kraken`, `numpy`, or `cv2`.
   - Heavy ML inference runs in a standalone PyInstaller worker (`dist/ocr-worker/ocr-worker.exe`, `818.4 MB` unpacked / `288.2 MiB` zipped), invoked via JSON files with explicit cancellation/timeout handling and an offline socket guard during verification.
2. **Existing OCR engines & critical defects found in code:**
   - **Kraken `7.1.1` + PP-OCRv6 (`small.safetensors` `15.5 MB`, `medium.safetensors` `51.6 MB`, Apache-2.0):** Trained by `HTR-School-Vienna/2025-hebrew` on medieval `Mishneh-Torah` and manuscript corpora using a **43-script multilingual CTC vocabulary**. On noisy strokes and ink marks in contemporary Hebrew scans (`scan-2026-10-28-221624.pdf`), unmasked argmax decoding leaked Hangul (`품`), Georgian (`Ⴀ`), Cyrillic (`Ж`), and Arabic characters. Auditing `kraken/models/ctc.py` also uncovered an upstream queue-flush bug when `batch_size > 1` if a trailing line crop is blank (`max == min`), dropping up to `batch_size - 1` lines; `batch_size=1` must therefore be preserved.
   - **Mishkefet-v1 (`mishkefet-v1.pt` `120.9 MB`, `hebrew_char6.pkl` `28.2 MB`, `hebrew_words.pkl` `3.8 MB`, CC-BY-NC-SA-4.0 weights / MIT `hebocr` code):** Purpose-built 30.2M CNN+ViT+CTC recognizer for modern Hebrew cursive, but severely bottlenecked by its vendored v1 `hebocr/page/segment.py`:
     - `h > 12 * pitch` unconditionally discarded tall connected components, **silently dropping an entire 13-line middle paragraph** on the supplied contemporary handwritten scan (`22` lines / `1,397` chars instead of `35` lines / `2,427` chars).
     - Autocorrelation pitch estimation searched only up to `min(n // 3, 250)`, breaking on large-hand spacing (`bialik_el_hazippor`: fragmented `4` lines into `51` fragments; `big-lines`: `5` lines into `77`).
     - Deskew searched only `±5°` and line crops were extracted as axis-aligned rectangles without baseline straightening, failing on tilted camera photos and curved notebook lines.
     - Margin punch-holes/speckles (`≤3` chars with low confidence `<0.90`) leaked single-letter garbage lines, and `beam`/`assisted` modes ran `Recognizer.read(crops)` (`scale=1.0`) twice per page (once for raw greedy output and a second identical ViT forward pass inside `read_tta`), wasting 25% of neural CPU compute.
3. **Existing spelling, grammar, and benchmark gaps:**
   - Built-in `spelling-hebrew` shipped **no Hebrew word list** (`available() == False` out-of-the-box; `0/27` errors detected on `DEFAULT_SUITE`). Optional `hunspell-hebrew` (AGPL-3.0, Hspell 1.4 pre-2017 rules) and `modern-hebrew-spelling` required separate C++/CMake builds and manual ZIP installation, and `modern_spelling.py` intentionally performed no prefix stripping.
   - Built-in `grammar-hebrew` checked only 4 basic ASCII/comma spacing regexes (`3/27` errors detected on `DEFAULT_SUITE`), with zero Hebrew morphosyntactic rules.
   - `benchmark/modern_school` held `0` pages, leaving modern cursive completely unmeasured in CI (only 1500–1800 Pinkas scribes were measured).

---

## 2. Candidate Technologies Evaluated

| Layer | Candidate | Target Domain | License | Measured / Published Finding | Decision |
| --- | --- | --- | --- | --- | --- |
| **OCR** | **Mishkefet-v1** + upgraded `hebocr` segmentation (`itayinbar/Mishkefet-v1` + `barakplasma/mishkefet-app` techniques) | **Modern handwritten Hebrew cursive** | MIT code; CC-BY-NC-SA-4.0 weights | **[External Published Claim]** `0.331` full-page CER on `ivrit-ai` benchmark (`0.175` line median CER with TTA+LM). **[Measured Fact]** **`41.37%` CER** on `benchmark/modern_cursive` (`2.7–4.7 s/page` CPU) vs Kraken's `83.18%–84.89%`; recovers `35/35` lines on contemporary scan. | **Selected** for **All Models (Noncommercial)** & opt-in install; segmentation + TTA cache upgraded in core. |
| **OCR** | **Kraken PP-OCRv6 (`small` / `medium`)** + CTC script mask | Medieval/early-modern Hebrew manuscripts; permissive fallback | Apache-2.0 | **[Measured Fact]** `55.68%` (`medium`) / `57.58%` (`small`) CER on Pinkas (1500–1800), `83.18%–84.89%` CER on modern cursive; CTC script mask eliminates **100%** of Hangul/Georgian/Cyrillic/Arabic leakage. | **Retained** as Apache-2.0 permissive baseline in **Lite** & **All Models**, with CTC script masking. |
| **OCR** | **Rivok / PaddleOCR-Hebrew ONNX** (`Rivok/paddleocr-hebrew` `mobile-word/rec.onnx` + `word-det/det.onnx`) | **Printed** modern Hebrew | Apache-2.0 | **[External Published Claim]** `0.35%–7.56%` CER on printed Hebrew. **[Measured Fact]** Directly benchmarked in ONNX Runtime on all 6 `modern_cursive` pages: **`92.8%` CER / `100.0%` WER** (`1.48s` total) — completely unusable on cursive handwriting. | **Rejected** (print-only model; fails on modern handwriting). |
| **OCR** | Vision-Language LLMs (Qwen2.5-VL / Gemma-3 / GPT-4o / Gemini) | General multimodal | Mixed / Cloud | **[External Published Claim]** `0.21–0.49` CER on `HebOCRBench`, but requires multi-GB weights + GPU or cloud APIs and hallucinates/normalizes student text. | **Rejected** (violates offline lightweight CPU & exact-text constraints). |
| **Spelling** | **Bundled CC0-1.0 `hebrew-words-db` (`196,227` words) + prefix/suffix morphology + handwritten-OCR confusion ranker** | Modern Hebrew + rabbinic/classroom notes | **CC0-1.0** data + MIT code | **[Measured Fact]** `492.8 KB` gzipped; `10/10` (`100%`) top-1 accuracy on `DEFAULT_SUITE` spelling targets, **`0` false positives** on abbreviations/Aramaic/names/ktiv-male, `~3 ms/word` CPU, `<35 MB` RAM. | **Selected & bundled** out-of-the-box in all editions (`Lite`, `All Models`, `ZIP`). |
| **Spelling** | **Hunspell 1.7.6 + LibreOffice/Hspell 1.4 (`optional_plugins/hunspell_hebrew`)** | Classical/pre-2017 Hebrew affix dictionary | **AGPL-3.0-only** (`he_IL`) + LGPL/GPL/MPL | **[Measured Fact]** Flags 7/16 valid Academy-2017 ktiv-male words unless supplemented; requires AGPL source bundle compliance. | **Retained as optional external plugin** (`hunspell-hebrew-win64.zip`). |
| **Grammar** | **Deterministic offline Hebrew morphosyntax + punctuation engine (`GrammarModule` v2)** | Modern Hebrew student & post-OCR drafts | **MIT** | **[Measured Fact]** `17/17` (`100%`) top-1 detection on `DEFAULT_SUITE` grammar/punctuation targets with **`0` false suggestions** in `23.1 ms` and `0 MB` extra model footprint. | **Selected & bundled** out-of-the-box as toggleable `grammar-hebrew`. |
| **Grammar** | **DictaBERT / neural seq2seq / LanguageTool / Dikduk** | Masked LM / GEC | CC-BY-4.0 / LGPL / AGPL | **[Measured Fact]** LanguageTool has **no Hebrew module**; `dikduk` calls cloud LLMs for grammar; no open offline Hebrew neural GEC model exists; DictaBERT (`~500–740 MB`) is an MLM, not a calibrated GEC, and would add ~0.7 GB + slow CPU latency without verified precision. | **Rejected**; limitation documented transparently. |

---

## 3. Benchmarks Built and Used

**[Measured Fact]** Never fabricating ground truth and never scoring unverified scans, we established and ran four strictly separated evaluation tiers:

1. **`benchmark/modern_cursive/` (NEW — Verified Modern Hebrew Cursive Corpus, `PDM-1.0`):**
   - 6 real 20th-century modern Hebrew cursive manuscript pages sourced from Wikimedia Commons via `HeOCR/hash` (`CC0-1.0` metadata), each restricted strictly to `PDM-1.0` public-domain works with **independent human-verified transcriptions** (`62` lines, `224` words, `1,112` normalized chars; SHA-256 pinned in `manifest.json`; all 4 GPT-4o `created_by: "ocr"` entries in `HeOCR/hash` were audited and excluded):
     - `commons__rachel_aqara_1928__p0001.jpg` (Rachel Bluwstein, 1928 — 17 lines, ink cross-outs & edits)
     - `commons__rachel_gan_naul__p0001.jpg` (Rachel Bluwstein, 1928 — 9 lines on grid/graph notebook paper)
     - `commons__rachel_rak_al_atzmi__p0001.jpg` (Rachel Bluwstein, 1930 — 12 lines, low-resolution faint scan)
     - `commons__begani_netatikha__p0001.jpg` (Rachel Bluwstein, 1930 — 10 lines, cursive poetic layout)
     - `commons__hatikvah_imber_manuscript__p0001.jpg` (N. H. Imber, 1908 — 10 lines, aged browned paper & signature)
     - `commons__bialik_el_hazippor__p0001.jpg` (H. N. Bialik — 4 lines, wide-pitch expressive cursive)
2. **`tools/benchmark_suggestions.py` (NEW — Span-Deduplicated Spelling & Grammar Benchmark):**
   - **Controlled suite (`DEFAULT_SUITE`, 13 documents / 27 target errors: 10 spelling + 17 grammar/punctuation)** covering classroom Hebrew, Talmudic/Aramaic terms (`סברא`, `דאורייתא`, `דרבנן`, `נפק״מ`, `רש״י`, `אלקים`), dates/acronyms (`תשפ״ו`, `צה״ל`, `דו״ח`), Academy 2017 ktiv male (`תוכנית`, `אונייה`, `יוזמה`, `לעיתים`), handwritten OCR confusions (`התלמיריס`, `ביתהספר`), and Hebrew morphosyntactic errors (`אני ילך`, `הבית ספר`, `שלושה בנות`, `הבעיה הזה`, `על על`, `בדף הדף`), plus **real post-OCR evaluation** on all 5 engine outputs from `ocr-accuracy-cursive.json`. Groups overlapping proposals by character span so multiple candidates never double-count an error.
3. **`benchmark/smoke_test/pages/scan-2026-10-28-221624.pdf` (Unverified Contemporary Scan — Qualitative & Line-Recovery Only):**
   - Real contemporary handwritten Talmudic notes page. Published in CI (`smoke-test-readings` & `mishkefet-decoding-comparison`) with **no fabricated accuracy score**.
4. **Pinkas Dataset (`CC-BY-4.0`, 1500–1800 Scribal Cursive Diagnostic) & `benchmark/modern_school/`:**
   - 5 Pinkas pages (`4` with complete ground truth, `160` lines) run in CI as a historical regression check; `benchmark/modern_school` remains honestly marked **unverified (`0` pages)** until consented student notebook pages are added.

---

## 4. Before-vs-After Results

### 4A. OCR Recognition Accuracy, Line Alignment & Resource Use

**[Measured Fact]** Measured in GitHub Actions `ocr-engine` (`ubuntu-latest` CPU, Python 3.12, PyTorch 2.14.0+cpu, runs `41357412484` & `41359483902`) vs `main` (`d01686c`):

| Benchmark & Profile | CER | WER | Lines (Hyp / Ref) | Missing / Extra / Dup / Order Inv | Speed (`sec/page`) | Peak RSS RAM | Exotic Script Leakage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Contemporary Scan (`scan-2026-10-28-221624.pdf`, unverified GT)** | | | | | | | |
| `mishkefet-v1` — **Before (`main`)** | *unverified* | *unverified* | `22` lines (`1,397` chars) | **Dropped 13-line middle paragraph** | `16.4s` | — | `0` chars |
| `mishkefet-v1` — **After (PR #22)** | *unverified* | *unverified* | **`35` lines (`2,427` chars, `+73.7%`)** | **Middle paragraph fully recovered** | `19.60s` | — | `0` chars |
| `kraken-ppocrv6-small` — **Before (`main`)** | *unverified* | *unverified* | `34` lines | — | `~17s` | — | Hangul / Georgian / Cyrillic |
| `kraken-ppocrv6-small` — **After (PR #22)** | *unverified* | *unverified* | `34` lines (`2,166` chars) | — | `17.39s` | — | **`0` chars (`100%` eliminated)** |
| **Verified Modern Cursive (`benchmark/modern_cursive`, 6 pages, 62 lines, `PDM-1.0`)** | | | | | | | |
| `kraken-ppocrv6-small` (`raw`, CTC-masked) | `83.18%` | `96.43%` | `41 / 62` | `54 / 32 / 1 / 0` | `8.48–13.74s` | `2,562 MB` | `0` |
| `kraken-ppocrv6-medium` (`raw`, CTC-masked) | `84.89%` | `95.54%` | `36 / 62` | `54 / 27 / 1 / 3` | `8.49–14.13s` | `2,656 MB` | `0` |
| **`mishkefet-v1` (`raw` greedy)** | **`41.37%`** | `91.96%` | **`74 / 62`** | **`6 / 18 / 0 / 0`** | **`2.70–4.74s`** | `2,656 MB` | `0` |
| **`mishkefet-v1:beam` (12-beam + 3-scale TTA)** | `42.62%` | **`91.07%`** | `74 / 62` | `7 / 19 / 0 / 0` | `12.40s` | `2,656 MB` | `0` |
| `mishkefet-v1:assisted` (beam + TTA + char/word LMs) | `43.62%` | `94.20%` | `75 / 62` | `7 / 20 / 0 / 0` | `12.97s` | `2,656 MB` | `0` |
| **Pinkas Historical Cursive Diagnostic (1500–1800, `CC-BY-4.0`, 4 complete GT pages)** | | | | | | | |
| `mishkefet-v1` — **Before (`main`)** | `73.00%` | — | — | Severe line bisection | — | — | `0` |
| `mishkefet-v1` — **After (PR #22)** | **`62.31%` (`-10.69 pp`)** | `100.87%` | `324 / 160` | `42 / 192 / — / —` | `27.62s` | `3,707 MB` | `0` |
| `kraken-ppocrv6-small` — **Before / After** | `57.58%` (unchanged) | `93.75%` | `160 / 160` | `18 / 18` | `13.52s` | `1,737 MB` | `0` |
| `kraken-ppocrv6-medium` — **Before / After** | `55.68%` (unchanged) | `90.30%` | `159 / 160` | `21 / 20` | `21.98s` | `1,768 MB` | `0` |

**Key empirical takeaways:**
- On verified modern cursive, `Mishkefet-v1` cuts character error rate **more than in half** (`41.37%` vs `83.18%–84.89%`), reduces missing lines by **9x** (`6/62` vs `54/62`), produces **0 reading-order inversions** and **0 duplicated lines**, and runs **3x faster** (`2.70–4.74 s/page` vs `8.48–14.13 s/page`). Best per-page CER reaches **`32.1%` CER / `68.8%` WER** (`rachel_aqara_1928`) and **`34.9%` CER** (`bialik_el_hazippor`, `0` missing/`0` extra lines).
- On poetic 1908–1930 texts with archaic/defective spellings (`בגני נטעתיך`, `אל־הרך`), `mishkefet-v1:beam` achieves the best word error rate (`91.07%`), whereas modern-prose language models (`assisted`) improve standard-vocabulary pages (`rachel_rak_al_atzmi`: `WER 96.3% -> 88.9%`, `-7.4 pp`) and contemporary rabbinic prose (`scan-2026-10-28-221624.pdf`), confirming why **raw recognition must remain the default and assisted decoding an explicit reviewable alternative**.

### 4B. Offline Spelling & Grammar Accuracy (`tools/benchmark_suggestions.py`)

**[Measured Fact]** Controlled 13-document / 27-error benchmark (`10` spelling + `17` grammar/punctuation) and real post-OCR evaluation:

| Mode | Metric | Before (`main` `d01686c`) | After (PR #22) | Improvement |
| --- | --- | --- | --- | --- |
| **`spelling_only`** | Target errors detected | `0 / 27` (`0/10` spelling) | **`10 / 27` (`10/10` spelling, `100%`)** | **`+10` (`+100 pp`)** |
| **`spelling_only`** | Correct top-1 suggestion | `0` | **`10 / 10` (`100%`)** | **`+10`** |
| **`spelling_only`** | False suggestions on valid words | `0` | **`0`** | Zero false flags preserved |
| **`spelling_only`** | Net CER / WER (`DEFAULT_SUITE`) | `5.67% -> 5.67%` / `30.61% -> 30.61%` | **`5.67% -> 3.90%` / `30.61% -> 19.39%`** | **`-1.77 pp` CER / `-11.22 pp` WER (`37.8 ms`)** |
| **`grammar_only`** | Target errors detected & top-1 | `3 / 27` (`2` top-1) | **`17 / 27` (`17/17` grammar, `100%` top-1)** | **`+14` detected / `+15` top-1** |
| **`grammar_only`** | False suggestions on valid words | `0` | **`0`** | Zero false flags on participles/teens/idioms |
| **`grammar_only`** | Net CER / WER (`DEFAULT_SUITE`) | `5.67% -> 5.32%` / `30.61% -> 28.57%` | **`5.67% -> 1.95%` / `30.61% -> 13.27%`** | **`-3.72 pp` CER / `-17.34 pp` WER (`23.1 ms`)** |
| **`spelling_and_grammar`** | Total errors detected & top-1 | `3 / 27` (`2` top-1) | **`27 / 27` (`100%` detected & `100%` top-1)** | **`+24` detected / `+25` top-1** |
| **`spelling_and_grammar`** | Net CER / WER (`DEFAULT_SUITE`) | `5.67% -> 5.32%` / `30.61% -> 28.57%` | **`5.67% -> 0.18%` / `30.61% -> 2.04%`** | **`-5.49 pp` CER (`-96.8%` rel.) / `-28.57 pp` WER (`75.5 ms`, `67.8 MB` RSS)** |
| **Post-OCR blind `accept_all` (`mishkefet-v1` on `modern_cursive`)** | Net WER / CER without human review | unchanged | **WER `91.96% -> 91.07%` (`-0.89 pp`)** (`beam`: `91.07% -> 90.62%`); CER `41.37% -> 42.18%` (`+0.81 pp`) | Empirically proves why human review (`קבל`/`דחה`) is mandatory when raw OCR CER > 35% |

### 4C. Windows One-Click Offline Packaging & Startup Telemetry

**[Measured Fact]** Measured on GitHub Actions `windows-2022` (`test-and-package` & `ocr-worker-windows`, run `41359483902`):

| Artifact / Metric | Baseline (`v0.4.0` / `d01686c`) | After (PR #22) | Notes |
| --- | --- | --- | --- |
| `HebrewNotesWorkbench-0.4.0-win64.zip` | `341.8 MiB` | **`342.25 MiB` (`358,870,046 B`)** | `+0.47 MiB` for bundled CC0-1.0 Hebrew lexicon (`492.8 KB`) + license |
| `HebrewNotesWorkbench-0.4.0-one-click.exe` (**Lite**, Apache-2.0) | `358.8 MiB` | **`359.26 MiB` (`376,711,735 B`)** | Single-file offline EXE; **cold first launch + 8-stage selftest: `15.84s`**; **subsequent launch + selftest: `4.18s`** |
| `HebrewNotesWorkbench-0.4.0-all-models-noncommercial-one-click.exe` (**All Models**, CC-BY-NC-SA-4.0) | `533.3 MiB` | **`533.74 MiB` (`559,664,052 B`)** | Single-file offline EXE with all 5 model/LM files; **cold first launch + selftest: `17.61s`**; **subsequent launch + selftest: `5.58s`** |
| Packaged `ocr-worker` (`inference` vs `baseline` profile) | `780.3 MiB` | **`780.50 MiB` (`818,415,411 B` vs `849,994,435 B` baseline)** | Saves `31.6 MB` unpacked / `13.5 MB` zipped; verified 100% offline with socket guard across all 5 OCR cases |

---

## 5. Architectural Changes Made

 Organized as clean, reviewable commits on `arena/79dcb59d-ocr` (PR #22), growing the automated test suite from **520 to 550 passing tests**:

1. **Verified Modern Cursive Benchmark & Metrics (`benchmark/modern_cursive/`, `hebrew_workbench/benchmark/metrics.py`, `tools/benchmark_ocr.py`, `tools/benchmark_suggestions.py`):**
   - Added 6 SHA-256-verified `PDM-1.0` modern cursive pages + transcripts, DP line-alignment metrics (`missing_lines`, `extra_lines`, `duplicated_lines`, `reading_order_inversions`), CPU/RSS telemetry, inline `mishkefet-v1:beam` & `mishkefet-v1:assisted` profiling, and span-grouped suggestion benchmarking.
2. **Handwritten Page Segmentation, Margin Speckle Filter, TTA Logit Reuse & Kraken Script Masking (`hebrew_workbench/engine/vendor/hebocr/page/segment.py`, `recognize.py`, `mishkefet.py`, `kraken_local.py`):**
   - Upgraded `segment_page` with wide-range coarse-to-fine deskew (`±44°`), autocorrelation pitch search up to `n // 2` + median fallback, density-gated tall-component valley splitting (`unsmeared ink fill < 0.35`, recovering dense paragraphs while filtering vertical margin lines), and quadratic baseline straightening (`straighten_line`) for curved handwriting.
   - Filtered margin punch-hole/speckle artifacts in `MishkefetEngine._is_margin_speckle` (`≤3` chars, confidence `<0.90`, narrow outer-margin box).
   - Added single-batch object-identity logit caching in `Recognizer._forward_lines` so `read(crops)` + `read_tta(crops)` reuses `scale=1.0` encoder logits (eliminating 1 of 4 ViT passes in `beam`/`assisted` modes with bit-for-bit identical output).
   - Added CTC non-target script masking (`disallowed_ctc_labels` + `script_masked_decoder`) in `KrakenEngine` to suppress non-Hebrew/non-ASCII scripts before greedy decoding.
3. **Out-of-the-Box CC0-1.0 Offline Hebrew Spellchecker (`hebrew_workbench/suggestions/hebrew_lexicon.py`, `spelling.py`, `data/hebrew_words_cc0.txt.gz`, `selftest.py`):**
   - Bundled pinned `roni5604/hebrew-words-db` (`CC0-1.0`, `196,227` words, verified by uncompressed SHA-256 at load) with conservative `בכל״ם`+`ו`+`ש` prefix validation, plural-possessive suffix recognition (`-ותיך`/`-ותיו`/`-ותיה`/`-ותינו`), false-positive exemptions for acronyms/geresh/Aramaic/rabbinic terms, handwritten-cursive visual confusion ranking (`ד↔ר↔ב`, `ה↔ח↔ת`, `ו↔י↔ז↔ן`, `ב↔כ↔ג`, `ס↔ם`, `צ↔ע↔ז`, `ג↔ק`, run-on splits), and persistent `personal_dictionary.txt`. Added `bundled-hebrew-spelling` stage to `--selftest`.
4. **Deterministic Offline Hebrew Grammar Checker & Independent 4-Layer UI Toggles (`hebrew_workbench/suggestions/grammar.py`, `ui/suggestions_pane.py`, `ui/main_window.py`):**
   - Added high-precision rules for 1st-person singular future `א-` prefix (`אני ילך -> אני אלך`, excluding present participles like `יכול`/`יודע`), construct definite article (`הבית ספר -> בית הספר`), 3–10 numeral gender agreement (including 2-letter `שש`, skipping teen numerals 11–19 and homograph `שמונה`), demonstrative gender agreement (`הבעיה הזה -> הבעיה הזאת`), accidental word/article-echo duplication (`על על -> על`, `בדף הדף -> בדף`, preserving Hebrew reduplicative idioms), and bracket/quote/comma spacing.
   - Added one-click checkboxes (`איות`, `דקדוק וניסוח`, `לשון הספר`) in `SuggestionsPane` and `"הצעות תיקון"` menu synchronized with `PluginRegistry` and invalidating stale per-document sessions when toggled.
5. **Windows Packaging, License Compliance & CI Verification (`.github/workflows/windows.yml`, `tools/build_release.py`, `docs/`):**
   - Bundled `hebrew_workbench/suggestions/data` in PyInstaller, shipped official Creative Commons `CC0-1.0.txt` legal code in `LICENCES/`, kept noncommercial `CC-BY-NC-SA-4.0` Mishkefet weights strictly isolated to the `All Models — Noncommercial` edition and opt-in download, and kept AGPL Hspell isolated to the optional plugin.

---

## 6. Remaining Limitations

1. **Consented contemporary classroom benchmark (`benchmark/modern_school`) is still empty (`0` pages):** **[Measured Fact]** While `benchmark/modern_cursive` provides 6 verified 20th-century modern cursive pages (`41.37%` CER with `Mishkefet-v1`), modern ballpoint student notebooks (`benchmark/modern_school`) still require school-consented scans and doubly checked transcripts before classroom CER/WER can be certified.
2. **Handwritten cursive OCR remains a human-reviewed draft, not zero-error transcription:** **[Measured Fact]** Even the best open modern cursive recognizer (`Mishkefet-v1`) has `32.1%–58.1%` CER (`41.37%` aggregate) on challenging poetic cursive pages with cross-outs, graph paper, and aged scans; users must review transcriptions line-by-line.
3. **Offline grammar is intentionally rule-based, not full syntactic parsing:** **[Measured Fact]** No compact, permissive, reliable offline neural Hebrew GEC model exists today. Our deterministic `GrammarModule` achieves `0` false positives on tested cases, but does not catch arbitrary open-vocabulary subject–verb gender/number mismatches across long clauses.
4. **Licensing split between Lite (Apache-2.0) and All Models (CC-BY-NC-SA-4.0):** **[Measured Fact]** `Mishkefet-v1` and its LM priors are noncommercial (`CC-BY-NC-SA-4.0`), so commercial deployments must either use the permissive `Lite` edition (`Kraken PP-OCRv6`) or obtain commercial licensing from `Mishkefet-v1`'s author.
5. **`לשון הספר` scholarly style rules and physical Windows printer QA:** **[Measured Fact]** `StyleModule` remains a disabled frame awaiting approved Academy rule specifications, and physical paper output from a Windows printer driver still requires human visual sign-off beyond automated PDF rendering in `--selftest`.

---

## 7. Recommended Next Steps

1. **Populate `benchmark/modern_school/` with 15–30 consented student notebook pages** (ballpoint/pencil on lined & grid paper across 5+ student hands, double-transcribed) and run `tools/benchmark_ocr.py` + `tools/benchmark_suggestions.py` in CI to establish certified modern classroom CER/WER.
2. **Fine-tune an Apache-2.0 / MIT Hebrew cursive CTC checkpoint or INT8 ONNX export:** **[Engineering Hypothesis]** Exporting `Mishkefet-v1` (for noncommercial users) to ONNX Runtime INT8/FP16 on CPU is expected to cut `beam`/`assisted` latency by ~2x (`~12s -> ~5–6s/page`) and worker bundle size by >300 MB if Kraken is made optional, while fine-tuning PP-OCRv6 or SVTRv2 on permissively licensed modern handwriting would remove the `CC-BY-NC-SA-4.0` restriction for commercial schools.
3. **Confidence-highlighted OCR tokens in the editor:** **[Engineering Hypothesis]** Surfacing per-line / per-token CTC confidence from `MishkefetEngine` as subtle background tinting in the RTL editor would focus teacher/student review directly on uncertain words without altering raw text.
4. **Curated `לשון הספר` rule implementation:** Once the school/editorial team approves specific Academy style rules with positive/negative test sentences, implement them inside `StyleModule` behind its existing independent `לשון הספר` toggle.
