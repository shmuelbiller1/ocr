# Technical Improvement Report: Hebrew Notes Workbench (`arena/a4b6d552-ocr`)

**Date:** 2026-11-02  
**Baseline commits (`main`):** `d01686c6f971a1b662e0963b77c0806eea24d611` (`v0.4.0` + Qt6 printer patch) $\rightarrow$ `6b30cde96bcbd93cf268ddb86f770fd6c3bc3b90` (merged PR `#22`)  
**Pull Request:** `#23` (`arena/a4b6d552-ocr`)

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
| **OCR** | **Mishkefet-v1** + upgraded `hebocr` segmentation (`itayinbar/Mishkefet-v1` + `barakplasma/mishkefet-app` techniques) | **Modern handwritten Hebrew cursive** | MIT code; CC-BY-NC-SA-4.0 weights | **[External Published Claim]** `0.331` full-page CER on `ivrit-ai` benchmark (`0.175` line median CER with TTA+LM). **[Measured Fact]** **`38.22%` CER** (`41.37%` before PhotoCraft audit) on `benchmark/modern_cursive` (`4.2–5.0 s/page` CPU) vs Kraken's `80.49%–81.57%`; recovers `35/35` lines on contemporary scan. | **Selected** for **All Models (Noncommercial)** & opt-in install; segmentation + TTA cache upgraded in core. |
| **OCR** | **Kraken PP-OCRv6 (`small` / `medium`)** + CTC script mask | Medieval/early-modern Hebrew manuscripts; permissive fallback | Apache-2.0 | **[Measured Fact]** `55.68%` (`medium`) / `57.58%` (`small`) CER on Pinkas (1500–1800), `80.49%–81.57%` CER (`83.18%–84.89%` before PhotoCraft audit) on modern cursive; CTC script mask eliminates **100%** of Hangul/Georgian/Cyrillic/Arabic leakage. | **Retained** as Apache-2.0 permissive baseline in **Lite** & **All Models**, with CTC script masking. |
| **Page Audit & Color Cleanup** | **`storytold/photocraft`-derived CPU document audit & selective 4×4 regional/chromatic adapter (`photocraft_audit.py`)** | Arbitrary paper hues, colored pens, colored ruling/grids, highlighters, dark/inverted grounds | **MIT** (`MIT OR Apache-2.0` upstream; pure NumPy/OpenCV port, `0` new dependencies) | **[Measured Fact]** `4–126 ms/page` audit (`~205 ms` max with grid/highlighter cleanup), `0` extra wheels (`+37.6 KB` EXE delta), fast-paths clean B&W/pastel pages untouched (`0.00 pp`), improves unmodified `modern_cursive` by **`-3.15 pp` CER** (`41.37% -> 38.22%`) and multi-color/grid/inverted suites by **`-0.90 pp` to `-63.31 pp` CER** on `Mishkefet-v1` (`-2.69 pp` to `-23.83 pp` on `Kraken`). | **Selected & integrated** into both `MishkefetEngine` and `KrakenEngine` (`HEBREW_WORKBENCH_PHOTOCRAFT_AUDIT=1` default, toggleable). |
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
   - **Controlled suite (`CONTROLLED_CASES`, 13 documents / 27 target errors: 10 spelling + 17 grammar/punctuation)** covering classroom Hebrew, Talmudic/Aramaic terms (`סברא`, `דאורייתא`, `דרבנן`, `נפק״מ`, `רש״י`, `אלקים`), dates/acronyms (`תשפ״ו`, `צה״ל`, `דו״ח`), Academy 2017 ktiv male (`תוכנית`, `אונייה`, `יוזמה`, `לעיתים`), handwritten OCR confusions (`התלמיריס`, `ביתהספר`), and Hebrew morphosyntactic errors (`אני ילך`, `הבית ספר`, `שלושה בנות`, `הבעיה הזה`, `על על`, `בדף הדף`), plus **real post-OCR evaluation** on all 5 engine outputs from `ocr-accuracy-cursive.json`. Groups overlapping proposals by character span so multiple candidates never double-count an error.
3. **`benchmark/smoke_test/pages/scan-2026-10-28-221624.pdf` (Unverified Contemporary Scan — Qualitative & Line-Recovery Only):**
   - Real contemporary handwritten Talmudic notes page. Published in CI (`smoke-test-readings` & `mishkefet-decoding-comparison`) with **no fabricated accuracy score**.
4. **Pinkas Dataset (`CC-BY-4.0`, 1500–1800 Scribal Cursive Diagnostic) & `benchmark/modern_school/`:**
   - 5 Pinkas pages (`4` with complete ground truth, `160` lines) run in CI as a historical regression check; `benchmark/modern_school` remains honestly marked **unverified (`0` pages)** until consented student notebook pages are added.
5. **`tools/benchmark_photocraft_audit.py` (Systematic 15-Suite Multi-Color & Regional Page Audit Benchmark):**
   - Evaluates `HEBREW_WORKBENCH_PHOTOCRAFT_AUDIT=0` vs `=1` across **15 optical suites** (`90` pages per engine in isolated child processes: `unmodified` + 14 deterministic optical paper/ink/ruling/margin-line/highlighter/shadow/dark-paper conditions derived directly from the 6 human-verified `benchmark/modern_cursive` pages, preserving exact human ground truth without fabrication).
6. **`tools/benchmark_stroke_width.py` (6-Variant Handwriting Stroke-Width & Real-Scan Diagnostic Benchmark):**
   - Audits inference-time stroke compensation via AST/source inspection and evaluates all 6 continuous-grayscale stroke-width variants (`original`, `mild_thicken`, `moderate_thicken`, `slight_thin`, `adaptive_norm`, `faint_repair`) across 8 pen/paper/DPI regimes **with and without** PhotoCraft preprocessing, on both **line crops at exact model-input height** (`H=64` Mishkefet, `H=96` Kraken) and **page-level segmentation**, plus non-GT diagnostics on contemporary & 1981–1990 `HeOCR/hash` archival scans.

---

## 4. Before-vs-After Results

### 4A. OCR Recognition Accuracy, Line Alignment & Isolated-Process Resource Use

**[Measured Fact]** Measured in GitHub Actions `ocr-engine` (`ubuntu-latest` CPU, Python 3.12, PyTorch 2.14.0+cpu, **isolated child process per engine/profile** in run `41483720777` / `ea65682`) vs `main` (`d01686c`):

| Benchmark & Profile | CER | WER | Lines (Hyp / Ref) | Missing / Extra / Dup / Order Inv | Speed (`sec/page`) | Isolated Peak RSS RAM | Exotic Script Leakage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Contemporary Scan (`scan-2026-10-28-221624.pdf`, unverified — excluded from CER/WER; see `docs/BAVA_BATRA_PROVISIONAL_WORKSHEET.md`)** | | | | | | | |
| `mishkefet-v1` — **Before (`main` `d01686c`)** | *not measured (unverified)* | *not measured (unverified)* | `22` lines (`1,397` chars) | **Dropped 13-line middle paragraph** | `16.4s` | — | `0` chars |
| `mishkefet-v1` — **After (PR #22 / #23)** | *not measured (unverified)* | *not measured (unverified)* | **`35` lines (`2,427` chars, `+73.7%`)** | **Middle paragraph fully recovered** | `19.6–32.1s` | — | `0` chars |
| `kraken-ppocrv6-small` — **Before (`main` `d01686c`)** | *not measured (unverified)* | *not measured (unverified)* | `34` lines | — | `~17s` | — | Hangul / Georgian / Cyrillic |
| `kraken-ppocrv6-small` / `-medium` — **After (PR #22 / #23)** | *not measured (unverified)* | *not measured (unverified)* | `34` lines (`2,166` / `2,278` chars) | — | `29.6s` / `45.7s` | — | **`0` chars (`100%` eliminated)** |
| **Verified Modern Cursive (`benchmark/modern_cursive`, 6 pages, 62 lines, `PDM-1.0`)** | | | | | | | |
| `kraken-ppocrv6-small` (`raw`, CTC-masked + PhotoCraft audit) | **`80.49%`** (`83.18%` pre-audit) | **`95.09%`** (`96.43%`) | `46 / 62` (`41 / 62`) | `50 / 33 / 1 / 0` | `11.57–14.21s` | **`2,631.6 MB`** | `0` |
| `kraken-ppocrv6-medium` (`raw`, CTC-masked + PhotoCraft audit) | **`81.57%`** (`84.89%` pre-audit) | **`94.64%`** (`95.54%`) | `43 / 62` (`36 / 62`) | `51 / 31 / 1 / 2` | `12.79–15.46s` | **`2,647.7 MB`** | `0` |
| **`mishkefet-v1` (`raw` greedy + PhotoCraft audit)** | **`38.22%`** (`41.37%` pre-audit) | **`89.73%`** (`91.96%`) | **`72 / 62`** (`74 / 62`) | **`6 / 16 / 0 / 0`** | **`4.29–5.25s`** | **`1,404.9–1,429.8 MB`** | `0` |
| **`mishkefet-v1:beam` (12-beam + 3-scale TTA + PhotoCraft audit)** | **`39.39%`** (`42.62%` pre-audit) | **`88.39%`** (`91.07%`) | `72 / 62` | `7 / 17 / 0 / 0` | `10.61–12.88s` | **`1,526.3–1,565.7 MB`** | `0` |
| `mishkefet-v1:assisted` (beam + TTA + char/word LMs + PhotoCraft audit) | **`39.66%`** (`43.62%` pre-audit) | **`91.07%`** (`94.20%`) | `73 / 62` | `7 / 18 / 0 / 0` | `11.21–13.54s` | **`1,781.0–1,818.6 MB`** | `0` |
| **Pinkas Historical Cursive Diagnostic (1500–1800, `CC-BY-4.0`, 4 complete GT pages)** | | | | | | | |
| `mishkefet-v1` — **Before (`main` `d01686c`)** | `73.00%` | — | — | Severe line bisection | — | — | `0` |
| `mishkefet-v1` — **After (PR #22 / #23)** | **`62.31%` (`-10.69 pp`)** | `100.87%` | `324 / 160` | `42 / 192 / 14 / 456` | `45.56s` | **`3,268.2 MB`** | `0` |
| `kraken-ppocrv6-small` — **Before / After** | `57.58%` (unchanged) | `93.75%` | `160 / 160` | `18 / 18 / 0 / 613` | `23.59s` | **`1,771.1 MB`** | `0` |
| `kraken-ppocrv6-medium` — **Before / After** | `55.68%` (unchanged) | `90.30%` | `159 / 160` | `21 / 20 / 0 / 562` | `40.73s` | **`1,936.0 MB`** | `0` |

*\*Epistemic note on the contemporary Yeshiva scan (`scan-2026-10-28-221624.pdf`):* Because the available draft transcription contains `[?]`-marked graphic ambiguities, an eye-skip boundary, superscript insertions, and crossed-out margin notes without independent second-reader verification, **it is strictly excluded from CER/WER calculations** (`benchmark/modern_school` remains at `0` certified pages). Instead, all 35 physical handwriting zones, verbatim engine outputs (`kraken-ppocrv6-medium`, `mishkefet-v1` raw, `mishkefet-v1:assisted`), and per-line uncertainty labels (`HIGH` / `MEDIUM` / `PROVISIONAL [?]`) are documented in `docs/BAVA_BATRA_PROVISIONAL_WORKSHEET.md` for human verification.

**Key empirical takeaways:**
- **Isolated-process RAM correction:** Running each engine/profile in a fresh child process (default in `benchmark_ocr.py`, `benchmark_photocraft_audit.py`, and `benchmark_stroke_width.py`) revealed that single-process `ru_maxrss` previously attributed Kraken's `~2.63 GB` peak RSS to Mishkefet because Mishkefet ran after Kraken. In isolation, **`mishkefet-v1` raw uses only `1,404.9–1,429.8 MB` RAM (~46% less than Kraken's `2,631.6 MB`)**, `:beam` uses `1,526.3–1,565.7 MB`, and `:assisted` uses `1,781.0–1,818.6 MB`.
- On verified late-19th and early-20th-century modern cursive (`benchmark/modern_cursive`), `Mishkefet-v1` reaches **`38.22%` CER / `89.73%` WER** (`39.39%` CER / **`88.39%` WER** with `:beam`) — cutting CER more than in half vs Kraken (`80.49%–81.57%`), reducing missing lines by **8x** (`6/62` vs `50/62`), and running **nearly 3x faster** (`4.29–5.25 s/page` vs `11.57–15.46 s/page`). On contemporary rabbinic/Yeshiva notes (`scan-2026-10-28-221624.pdf`), `Mishkefet-v1` recovers all 35 physical zones (including the 13-line middle paragraph dropped on `main`) and `Kraken PP-OCRv6` produces zero non-Hebrew script leakage.

### 4B. PhotoCraft-Derived Selective Document Audit & Multi-Color Paper/Ink Evaluation (`tools/benchmark_photocraft_audit.py`)

**[Measured Fact]** Audited `https://github.com/storytold/photocraft` (`MIT OR Apache-2.0`) and adapted four CPU-lightweight techniques into `hebrew_workbench/engine/photocraft_audit.py` (`480 px` proxy audit + 4×4 regional sector gating + working cap `2,400 px` with inverse bounding-box rescaling): (1) background-key opacity unmixing (`color_to_alpha.rs`) with unit-norm class-balanced linear Fisher projection (`||w||_2 = 1`, avoiding blue-channel noise amplification on yellow/aged paper); (2) sparse-ink (`p99.2` vs `p0.8`) dark-ground polarity inversion; (3) periodic ruling/grid masked color replacement (`replace_color_masked`); and (4) morphologically opened (`MORPH_OPEN`) highlighter pass-band neutralization with multi-hue pen preservation (`max(proj, median_channel_drop)`).

Measured in GitHub Actions `ocr-engine` (`ubuntu-latest` CPU, run `41395748886`) across 6 human-verified `modern_cursive` pages per suite (`62` reference lines, `1,112` chars, `224` words per suite):

| Optical Suite (`6` pages / `62` GT lines each) | Engine | CER (`Audit OFF` $\rightarrow$ `ON`) | $\Delta$ CER | WER (`Audit OFF` $\rightarrow$ `ON`) | Lines (`OFF` $\rightarrow$ `ON` / `62`) | Audit+Prep CPU (`ms/page`) | Total OCR (`s/page` `OFF` $\rightarrow$ `ON`) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **`unmodified` (real scans: B&W, tan, grid, 18 MP)** | `mishkefet-v1` | `41.37%` $\rightarrow$ **`38.22%`** | **`-3.15 pp`** | `91.96%` $\rightarrow$ **`89.73%`** | `74` $\rightarrow$ **`72 / 62`** | `126.0 ms` (`3/6` adj) | `4.44s` $\rightarrow$ `4.46s` |
| **`red_pen_on_tan_paper` (BT.601 luma collision)** | `mishkefet-v1` | `90.83%` $\rightarrow$ **`48.74%`** | **`-42.09 pp`** | `103.12%` $\rightarrow$ **`102.68%`** | `57` $\rightarrow$ **`83 / 62`** | `109.8 ms` (`6/6` adj) | `5.60s` $\rightarrow$ **`5.04s`** |
| **`cyan_graph_grid` (5 mm colored squared grid)** | `mishkefet-v1` | `107.91%` $\rightarrow$ **`44.60%`** | **`-63.31 pp`** | `170.54%` $\rightarrow$ **`99.11%`** | `148` $\rightarrow$ **`83 / 62`** | `176.1 ms` (`6/6` adj) | `11.69s` $\rightarrow$ **`3.86s` (`3.0x` faster)** |
| **`dark_slate_light_ink` (inverted dark ground)** | `mishkefet-v1` | `73.92%` $\rightarrow$ **`42.72%`** | **`-31.20 pp`** | `100.00%` $\rightarrow$ **`92.41%`** | `93` $\rightarrow$ **`81 / 62`** | `108.1 ms` (`6/6` adj) | `5.92s` $\rightarrow$ **`4.35s`** |
| **`yellow_legal_pad` (yellow pad + cyan rules + blue ink)** | `mishkefet-v1` | `50.81%` $\rightarrow$ **`49.46%`** | **`-1.35 pp`** | `105.80%` $\rightarrow$ **`104.02%`** | `97` $\rightarrow$ **`94 / 62`** | `102.8 ms` (`2/6` adj) | `4.92s` $\rightarrow$ `5.13s` |
| **`regional_highlighter_and_red_note` (yellow/pink bands + red pen)** | `mishkefet-v1` | `43.44%` $\rightarrow$ **`42.54%`** | **`-0.90 pp`** | `91.52%` $\rightarrow$ **`91.07%`** | `76` $\rightarrow$ **`79 / 62`** | `205.0 ms` (`6/6` adj) | `4.50s` $\rightarrow$ **`4.42s`** |
| **`pink_card_red_ink` / `pastel_blue_paper` / `mint_green_paper`** | `mishkefet-v1` | `42.81%` / `41.91%` / `42.45%` | **`0.00 pp`** | unchanged | unchanged (`0/6` adj) | `115.6–116.0 ms` | fast-path (`out is im`) |
| **`regional_corner_shadow` (moderate neutral camera shade)** | `mishkefet-v1` | `42.54%` $\rightarrow$ **`42.54%`** | **`0.00 pp`** | `94.20%` $\rightarrow$ **`94.20%`** | `84` $\rightarrow$ `84 / 62` (`0/6` adj) | `<10 ms` (gated `>0.58`) | fast-path (`out is im`) |
| **`unmodified`** | `kraken-ppocrv6-small` | `83.18%` $\rightarrow$ **`80.49%`** | **`-2.69 pp`** | `96.43%` $\rightarrow$ **`95.09%`** | `41` $\rightarrow$ **`46 / 62`** | `126.0 ms` | `13.44s` $\rightarrow$ `13.40s` |
| **`red_pen_on_tan_paper`** | `kraken-ppocrv6-small` | `99.91%` $\rightarrow$ **`77.07%`** | **`-22.84 pp`** | `100.00%` $\rightarrow$ **`95.98%`** | `1` $\rightarrow$ **`56 / 62`** | `109.8 ms` | `11.58s` $\rightarrow$ `13.90s` |
| **`dark_slate_light_ink`** | `kraken-ppocrv6-small` | `99.19%` $\rightarrow$ **`75.36%`** | **`-23.83 pp`** | `100.00%` $\rightarrow$ **`94.20%`** | `13` $\rightarrow$ **`63 / 62`** | `108.1 ms` | `12.98s` $\rightarrow$ `14.04s` |
| **`regional_highlighter_and_red_note`** | `kraken-ppocrv6-small` | `81.74%` $\rightarrow$ **`75.72%`** | **`-6.02 pp`** | `95.98%` $\rightarrow$ **`91.07%`** | `39` $\rightarrow$ **`46 / 62`** | `205.0 ms` | `13.23s` $\rightarrow$ `14.04s` |
| **`cyan_graph_grid`** | `kraken-ppocrv6-small` | `87.59%` $\rightarrow$ **`74.82%`** | **`-12.77 pp`** | `98.66%` $\rightarrow$ **`93.75%`** | `71` $\rightarrow$ **`58 / 62`** | `176.1 ms` | `16.05s` $\rightarrow$ **`14.25s`** |

**Honest ablation finding (what worked vs. what was rejected):**
- **Worked & kept (15 suites + real Yeshiva notebook margin-rule cleanup):** Across all **15 optical suites** (`90` pages per engine in isolated processes, run `41483720777`), PhotoCraft audit achieved **`<= 0.00 pp` CER delta on every single suite** (`-3.15 pp` unmodified, `-42.09 pp` red-on-tan, `-31.20 pp` dark-slate, `-63.31 pp` cyan-grid, `-0.90 pp` highlighter+red-note, and `0.00 pp` on clean/pastel/notebook suites). Adding targeted vertical chromatic margin-rule neutralization (`_suppress_vertical_chromatic_margin_rules`, `0.39%` pixels touched on `Scan2026-10-28_222637.pdf`, `0/60` triggers on `modern_cursive`) reduced left-margin pink-rule snaps from `23` to `10` boxes without clipping adjacent Hebrew ink.
- **User-facing desktop control & Original/Processed comparison UI:** Exposed `Automatic page enhancement: On / Off` (`עיבוד מקדים אוטומטי לדף`, default `On`, persisted in `plugins.json`, honoring `HEBREW_WORKBENCH_PHOTOCRAFT_AUDIT=0`) in `Settings > Plugins and engines` and the `View` menu, plus an in-UI **Original / Processed / Side-by-side** (`מקור` / `לאחר עיבוד` / `זה לצד זה`) toolbar toggle backed by `ocr-worker --enhance-preview` (`processed-page-N.png`) while keeping the original document untouched.
- **Tested & gated based on negative evidence:** Applying global morphological background subtraction to *moderate achromatic camera shadows* (`shadow_drop ~ 0.35–0.45`, `regional_corner_shadow`) degraded `Mishkefet-v1` from `42.54%` to `45.32%` CER (`+2.78 pp`) because `hebocr`'s local Gaussian ratio (`gray / GaussianBlur * 128`) and per-line contrast normalization already adapt cleanly to smooth neutral shading (`42.54%` CER), whereas morphological flattening slightly clipped faint sepia strokes on aged parchment (`hatikvah`). We therefore gated `needs_shadow_relight` strictly to severe near-black occlusion (`shadow_drop > 0.58`), eliminating that regression (`0.00 pp`) while keeping Beer–Lambert shadow recovery available for extreme shadows.

### 4C. Offline Spelling & Grammar Accuracy (`tools/benchmark_suggestions.py`)

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

### 4D. Windows One-Click Offline Packaging & Startup Telemetry

**[Measured Fact]** Measured on GitHub Actions `windows-2022` (`test-and-package` & `ocr-worker-windows`, run `41395748886`):

| Artifact / Metric | Baseline (`v0.4.0` / `d01686c`) | After (PR #23, run `41483720777`) | Notes |
| --- | --- | --- | --- |
| `HebrewNotesWorkbench-0.4.0-win64.zip` | `341.8 MiB` | **`342.33 MiB` (`358,957,745 B`)** | `+0.53 MiB` for bundled CC0-1.0 Hebrew lexicon (`492.8 KB`), PhotoCraft audit, stroke-width module, UI comparison view, and licenses (`0` new wheel dependencies) |
| `HebrewNotesWorkbench-0.4.0-one-click.exe` (**Lite**, Apache-2.0) | `358.8 MiB` | **`359.35 MiB` (`376,803,562 B`)** | Single-file offline EXE; **cold first launch + 8-stage selftest: `11.17s`**; **subsequent launch + selftest: `3.47s`** |
| `HebrewNotesWorkbench-0.4.0-all-models-noncommercial-one-click.exe` (**All Models**, CC-BY-NC-SA-4.0) | `533.3 MiB` | **`533.82 MiB` (`559,752,585 B`)** | Single-file offline EXE with all 5 model/LM files; **cold first launch + selftest: `12.69s`**; **subsequent launch + selftest: `5.32s`** |
| Packaged `ocr-worker` (`inference` vs `baseline` profile) | `780.3 MiB` | **`780.54 MiB` (`818,459,664 B`)** | Deterministic bundle across builds (`0` byte delta); zero added ML/image wheels; verified 100% offline with socket guard across all 5 OCR cases + `--enhance-preview` |

### 4E. Adaptive Handwriting Stroke-Width Normalization Investigation (`hebrew_workbench/engine/stroke_width.py`, `tools/benchmark_stroke_width.py`)

**[Measured Fact]** Direct AST/source audit (`audit_inference_stroke_compensation`) and isolated-process CPU benchmarking (CI run `41559746742` / `c899e87`, `stroke-width-benchmark.json`) answered whether stroke-width normalization improves Hebrew handwriting recognition:

1. **Inference-time audit of `Mishkefet` and `Kraken`:**
   - **Neither engine performs any stroke-width normalization at inference time.** `hebocr/data/transforms.py` `preprocess()` applies only `LANCZOS` height resize to `LINE_HEIGHT = 64`, `gray / GaussianBlur(sigma = h * 0.4) * 128`, `[2%, 99%]` contrast stretch, `[0, 1]` invert, and `PAD_VALUE = 0.05` padding; `Augment._stroke()` (`72%` erosion vs `28%` dilation) runs **exclusively during training** (`Recognizer.read()` never instantiates `Augment`). Kraken `PP-OCRv6` (`TorchSeqRecognizer` / `ImageInputTransforms`) likewise resizes line crops proportionally to `H = 96` with zero morphological stroke adjustment.
2. **Continuous-grayscale 6-variant benchmark scored with shared `metrics.normalise()` on verified-only `Corpus.measured_pages` (`mishkefet-v1` isolated RSS `3,235.6 MB`, `kraken-ppocrv6-small` isolated RSS `2,820.0 MB`):**
   - Evaluated `original`, `mild_thicken` (`α=0.45`), `moderate_thicken` (`α=0.90`), `slight_thin` (`α=0.45`), `adaptive_norm` (Euclidean distance-transform ridge width `2 * d_max` at `H=64` with conservative `[3.05, 5.35] px` deadband), and `faint_repair` (`1×3` directional gap closing gated strictly on ridge width `< 3.4 px`), preserving continuous grayscale antialiasing without binarization and normalizing both reference and hypothesis via `hebrew_workbench.benchmark.metrics.normalise`:

| Engine & Scope (Normalized CER via `metrics.normalise()`) | `original` | `mild_thicken` | `moderate_thicken` | `slight_thin` | `adaptive_norm` | `faint_repair` | Key Finding |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **`mishkefet-v1` (`verified_native_300dpi` real scans, line crops, WITH PhotoCraft)** | **`37.95%` CER** (`conf 0.9314`, `2.51 s/p`) | `38.76%` (`+0.81 pp`, `conf 0.9315`) | `39.51%` (`+1.56 pp`, `conf 0.9326`) | `38.34%` (`+0.39 pp`, `conf 0.9296`) | `38.13%` (`+0.18 pp`, `conf 0.9322`) | `38.32%` (`+0.37 pp`, `conf 0.9326`) | **`original` wins on real scans; thickening inflates CTC confidence while hurting CER (`+0.81..+1.56 pp`)** |
| **`mishkefet-v1` (`verified_native_300dpi`, WITHOUT PhotoCraft)** | `41.36%` CER (`conf 0.9324`) | `41.16%` (`-0.20 pp`) | `42.19%` (`+0.83 pp`) | `40.97%` (`-0.39 pp`) | `41.28%` (`-0.08 pp`) | **`40.68%` (`-0.68 pp`)** | Faint repair / slight thinning partly compensate only when PhotoCraft is disabled (`40.68%` still trails `37.95%` WITH PhotoCraft) |
| **`mishkefet-v1` (`dpi_150_lowres` / `pen_faint_broken` / `pen_heavy_marker`, WITH PhotoCraft)** | `52.52%` / `63.84%` / `66.99%` | `52.96%` / `64.68%` / `66.93%` | `52.92%` / **`62.74%` (`-1.10 pp`)** / `67.34%` | **`51.78%` (`-0.74 pp`)** / `62.82%` (`-1.02 pp`) / **`66.43%` (`-0.56 pp`)** | **`52.19%` (`-0.33 pp`)** / `63.64%` (`-0.20 pp`) / **`66.64%` (`-0.35 pp`)** | `51.93%` / `64.24%` / `67.11%` | Synthetic blur/break/bleed regimes favor different operators (`moderate_thicken` helps broken strokes `-1.10 pp` while hurting native scans `+1.56 pp`; `slight_thin` hurts `pen_fine_nib` `+0.48 pp`) |
| **`mishkefet-v1` (`page_before_segmentation`, WITH PhotoCraft)** | **`38.22%` CER** (`6` miss, `4.70 s/p`) | `+0.45 pp` | `+1.62 pp` (`7` miss) | `+0.63 pp` | `+0.45 pp` | `+1.17 pp` | Pre-segmentation morphology hurts CER across **all** variants and multiplies CPU runtime |
| **`kraken-ppocrv6-small` (`line_crop` `verified_native_300dpi` / `pen_fine_nib`, WITH PhotoCraft)** | `82.32%` / **`90.56%`** | `82.54%` (`+0.22 pp`) / `90.93%` | **`82.00%` (`-0.32 pp`)** / `90.68%` | `82.22%` / `90.76%` | `82.27%` / `90.76%` | `82.21%` / `90.68%` | Remains `~82–91%` CER on modern cursive regardless of stroke variant |

3. **Engineering decision:** Under exact `metrics.normalise()` scoring on verified ground-truth pages, **`original` achieves the lowest CER (`37.95%`) on real `verified_native_300dpi` cursive scans**, **thicker strokes falsely increase Mishkefet's CTC confidence (`0.9314 -> 0.9326`) while closing small Hebrew loops/gaps (`ה↔ח↔ת`, `ב↔כ`, `ס↔ם`, `ו↔י↔ן`) and degrading CER by `+0.81` to `+1.56 pp`**, and pre-segmentation morphology hurts line finding while multiplying CPU runtime. Therefore **`inference_stroke_variant = "original"` remains the production default** (with zero extra OCR passes and zero added latency), while all 6 grayscale operators remain available opt-in via `HEBREW_WORKBENCH_STROKE_VARIANT` and the full 192-cell sweep in `.github/workflows/research-benchmarks.yml`.

---

## 5. Architectural Changes Made

Organized as clean, reviewable commits across PR #22 (`6b30cde`) and PR #23 (`arena/a4b6d552-ocr`), growing the automated test suite from **520 to 580+ passing tests**:

1. **Verified Modern Cursive Benchmark, Isolated-Process RSS & Metrics (`benchmark/modern_cursive/`, `hebrew_workbench/benchmark/metrics.py`, `tools/benchmark_ocr.py`, `tools/benchmark_suggestions.py`, `tools/benchmark_photocraft_audit.py`, `tools/benchmark_stroke_width.py`):**
   - Added 6 SHA-256-verified `PDM-1.0` modern cursive pages + transcripts, DP line-alignment metrics (`missing_lines`, `extra_lines`, `duplicated_lines`, `reading_order_inversions`), **isolated child-process per-engine RSS (`peak_rss_mb`)**, inline `mishkefet-v1:beam` & `mishkefet-v1:assisted` profiling, span-grouped suggestion benchmarking, a 15-suite multi-color/regional PhotoCraft audit benchmark, and a 6-variant handwriting stroke-width & real-scan diagnostic benchmark.
2. **PhotoCraft-Derived CPU Document Audit, Crossing-Safe Margin-Rule Cleanup & Async Bounded Original/Processed UI (`hebrew_workbench/engine/photocraft_audit.py`, `ui/preview_pane.py`, `ui/main_window.py`, `plugins/registry.py`, `ocr_worker/main.py`):**
   - Adapted PhotoCraft's (`storytold/photocraft`, MIT) background-key opacity unmixing, sparse-ink dark-ground polarity inversion, periodic ruling/grid & crossing-ink-safe vertical chromatic margin-rule suppression (per-rule RGB/direction/luma matching + flanking continuity protection for blue, black, dark-red, and pastel-pink strokes), and morphologically opened highlighter pass-band neutralization into a fast lazy-imported NumPy/OpenCV preprocessor (`4–205 ms/page`, `2,400 px` working cap with `rescale_box` coordinate mapping) wired into both `MishkefetEngine` and `KrakenEngine`.
   - Added user-facing `Automatic page enhancement: On / Off` (`עיבוד מקדים אוטומטי לדף`, guarded during active OCR tasks and authoritative in `PluginRegistry`) and a non-blocking **Original / Processed / Side-by-side** (`מקור` / `לאחר עיבוד` / `זה לצד זה`) comparison view powered by background `_PreviewEnhanceThread(QThread)` (`25s` worker timeout + immediate `kill()` on document switch/close) and bounded compressed-PNG LRU caches (`MAX_LIVE_PREVIEW_CACHE_ENTRIES = 4`, `MAX_PROCESSED_DOC_SNAPSHOTS = 8`) for low-RAM PCs.
3. **Continuous-Grayscale Stroke-Width Operators, Normalized/Verified-Only Benchmarking & Parallel CI (`hebrew_workbench/engine/stroke_width.py`, `tools/benchmark_stroke_width.py`, `tools/run_tests_parallel.py`, `.github/workflows/research-benchmarks.yml`):**
   - Implemented 6 vectorized grayscale antialiasing-preserving stroke-width variants (`original`, `mild_thicken`, `moderate_thicken`, `slight_thin`, `adaptive_norm` with `DIST_L2` `[3.05, 5.35] px` deadband, `faint_repair` + `page_scale=True` line-height scaling), GUI-safe AST inference audit (`audit_inference_stroke_compensation`), shared `metrics.normalise()` + `Corpus.measured_pages` enforcement, parallel test runner (`tools/run_tests_parallel.py`), and a `workflow_dispatch` research workflow (`research-benchmarks.yml`) keeping routine PR CI fast while retaining `"original"` as the default.
4. **Handwritten Page Segmentation, Margin Speckle Filter, TTA Logit Reuse & Kraken Script Masking (`hebrew_workbench/engine/vendor/hebocr/page/segment.py`, `recognize.py`, `mishkefet.py`, `kraken_local.py`):**
   - Upgraded `segment_page` with wide-range coarse-to-fine deskew (`±44°`), autocorrelation pitch search up to `n // 2` + median fallback, density-gated tall-component valley splitting (`unsmeared ink fill < 0.35`, recovering dense paragraphs while filtering vertical margin lines), bounded component count (`<=500`) against noisy backgrounds, and quadratic baseline straightening (`straighten_line`) for curved handwriting.
   - Filtered margin punch-hole/speckle artifacts in `MishkefetEngine._is_margin_speckle` (`≤3` chars, confidence `<0.90`, narrow outer-margin box).
   - Added single-batch object-identity + stroke-variant logit caching in `Recognizer._forward_lines` so `read(crops)` + `read_tta(crops)` reuses `scale=1.0` encoder logits.
   - Added CTC non-target script masking (`disallowed_ctc_labels` + `script_masked_decoder`) in `KrakenEngine` to suppress non-Hebrew/non-ASCII scripts before greedy decoding.
5. **Out-of-the-Box CC0-1.0 Offline Hebrew & Rabbinic Spellchecker (`hebrew_workbench/suggestions/hebrew_lexicon.py`, `spelling.py`, `data/hebrew_words_cc0.txt.gz`, `selftest.py`):**
   - Bundled pinned `roni5604/hebrew-words-db` (`CC0-1.0`, `196,227` words, verified by uncompressed SHA-256 at load) with conservative `בכל״ם`+`ו`+`ש` and rabbinic/Aramaic `ד-`/`כד-`/`מד-`/`וד-` prefix validation, Mishnaic `-ין -> -ים` plural validation (`ניזוקין`, `שותפין`, `מודה במקצת`), plural-possessive suffix recognition, handwritten-cursive & keyboard confusion ranking (`ד↔ר↔ב`, `ה↔ח↔ת`, `ו↔י↔ז↔ן`, `ב↔כ↔ג`, `ס↔ם`, `צ↔ע↔מ↔ז`, `ג↔ק`, run-on splits), and persistent `personal_dictionary.txt`.
6. **Deterministic Offline Hebrew Grammar Checker & Independent 4-Layer UI Toggles (`hebrew_workbench/suggestions/grammar.py`, `ui/suggestions_pane.py`, `ui/main_window.py`):**
   - Added high-precision rules for 1st-person singular future `א-` prefix, construct definite article, 3–10 numeral & demonstrative gender agreement, accidental word/article-echo duplication, list-safe acronym gershayim punctuation (`_match_comma_acronym_pair`: flagging genuine keyboard-slip rabbinic acronyms `ע,ש -> ע"ש`, `ס,ל -> ס"ל`, `רש'י -> רש"י` while preserving all ordinary Hebrew comma lists such as `א,ב -> א, ב`, `אם,לא -> אם, לא`, `סעיפים ע,ש -> סעיפים ע, ש`, terminal geresh `תוס'`, and foreign `ג'/`/`צ'/`/`ז'`), and acronym-safe bracket/quote/comma spacing (`_count_non_acronym_quotes`).
   - Added one-click checkboxes (`איות`, `דקדוק וניסוח`, `לשון הספר`) in `SuggestionsPane` and `"הצעות תיקון"` menu synchronized with `PluginRegistry` and invalidating stale per-document sessions when toggled.
7. **Windows Packaging, License Compliance & CI Verification (`.github/workflows/windows.yml`, `tools/build_release.py`, `tools/build_worker.py`, `docs/`):**
   - Bundled `hebrew_workbench/suggestions/data` and `stroke_width` in PyInstaller, shipped official Creative Commons `CC0-1.0.txt` and `PHOTOCRAFT-MIT.txt` legal texts in `LICENCES/`, kept noncommercial `CC-BY-NC-SA-4.0` Mishkefet weights strictly isolated to the `All Models — Noncommercial` edition and opt-in download, and kept AGPL Hspell isolated to the optional plugin.

---

## 6. Remaining Limitations

1. **Consented contemporary classroom benchmark (`benchmark/modern_school`) is still empty (`0` pages):** **[Measured Fact]** While `benchmark/modern_cursive` provides 6 verified 20th-century modern cursive pages (`38.22%` CER with `Mishkefet-v1`), modern ballpoint student notebooks (`benchmark/modern_school`) still require school-consented scans and doubly checked transcripts before classroom CER/WER can be certified.
2. **Handwritten cursive OCR remains a human-reviewed draft, not zero-error transcription:** **[Measured Fact]** Even the best open modern cursive recognizer (`Mishkefet-v1`) has `24.2%–58.1%` CER (`38.22%` aggregate) on challenging poetic cursive pages with cross-outs, graph paper, and aged scans; users must review transcriptions line-by-line.
3. **Offline grammar is intentionally rule-based, not full syntactic parsing:** **[Measured Fact]** No compact, permissive, reliable offline neural Hebrew GEC model exists today. Our deterministic `GrammarModule` achieves `0` false positives on tested cases, but does not catch arbitrary open-vocabulary subject–verb gender/number mismatches across long clauses.
4. **Licensing split between Lite (Apache-2.0) and All Models (CC-BY-NC-SA-4.0):** **[Measured Fact]** `Mishkefet-v1` and its LM priors are noncommercial (`CC-BY-NC-SA-4.0`), so commercial deployments must either use the permissive `Lite` edition (`Kraken PP-OCRv6`) or obtain commercial licensing from `Mishkefet-v1`'s author.
5. **`לשון הספר` scholarly style rules and physical Windows printer QA:** **[Measured Fact]** `StyleModule` remains a disabled frame awaiting approved Academy rule specifications, and physical paper output from a Windows printer driver still requires human visual sign-off beyond automated PDF rendering in `--selftest`.

---

## 7. Recommended Next Steps

1. **Populate `benchmark/modern_school/` with 15–30 consented student notebook pages** (ballpoint/pencil on lined & grid paper across 5+ student hands, double-transcribed) and run `tools/benchmark_ocr.py` + `tools/benchmark_suggestions.py` in CI to establish certified modern classroom CER/WER.
2. **Fine-tune an Apache-2.0 / MIT Hebrew cursive CTC checkpoint or INT8 ONNX export:** **[Engineering Hypothesis]** Exporting `Mishkefet-v1` (for noncommercial users) to ONNX Runtime INT8/FP16 on CPU is expected to cut `beam`/`assisted` latency by ~2x (`~12s -> ~5–6s/page`) and worker bundle size by >300 MB if Kraken is made optional, while fine-tuning PP-OCRv6 or SVTRv2 on permissively licensed modern handwriting would remove the `CC-BY-NC-SA-4.0` restriction for commercial schools.
3. **Confidence-highlighted OCR tokens in the editor:** **[Engineering Hypothesis]** Surfacing per-line / per-token CTC confidence from `MishkefetEngine` as subtle background tinting in the RTL editor would focus teacher/student review directly on uncertain words without altering raw text.
4. **Curated `לשון הספר` rule implementation:** Once the school/editorial team approves specific Academy style rules with positive/negative test sentences, implement them inside `StyleModule` behind its existing independent `לשון הספר` toggle.
