# Final-readiness audit — 2026-10-29

## Verdict

**A usable OCR release is not the same as the whole original project being
finished.** The All Models download contains all supported recognition models
and decoding priors. It does not supply a complete spelling dictionary, a
Hebrew grammar engine or implemented לשון הספר rules.

This audit identified a real v0.4.0 defect: the printer factory called Qt 5
page-size/margin APIs on Qt 6. Printing, print preview and PDF saving share
that factory. The source patch uses QPageSize, QMarginsF and QPageLayout and
explicit PDF output mode. **Existing v0.4.0 downloads do not contain this
patch.** Do not mark the released printing workflow fixed until a later
version containing the patch has been built, launched, tested and published.

## What must be present

The eight built-in plugin IDs and their roles are listed in [PLUGINS.md](PLUGINS.md).
In-process adapters are useful in a source environment; the Windows bundles use
the separate worker, which carries the ML dependencies. An unavailable
in-process adapter is not evidence that the worker/model is missing.

| Item | Lite EXE | All Models EXE | Portable ZIP |
| --- | --- | --- | --- |
| Desktop app, Qt, image/PDF preview, DOCX support, worker and notices | Included | Included | Included |
| Kraken small recognition weights | Included | Included | Install explicitly |
| Kraken medium recognition weights | Install explicitly | Included | Install explicitly |
| Mishkefet recognition weights | Install explicitly; noncommercial | Included; noncommercial | Install explicitly; noncommercial |
| Mishkefet character and word decoding priors | Install explicitly; noncommercial | Both included; noncommercial | Install explicitly; noncommercial |
| Hebrew spelling dictionary | Not bundled | Not bundled | Not bundled |
| Full Hebrew grammar / scholarly-style model | Not implemented | Not implemented | Not implemented |

There are **five model files**, not five independent recognition engines:
`small.safetensors`, `medium.safetensors`, `mishkefet-v1.pt`, `hebrew_char6.pkl`,
`hebrew_words.pkl`. The last two assist decoding only. Raw output remains
available and is not silently replaced. NC assets use CC-BY-NC-SA-4.0; the
Kraken recognition weights use Apache-2.0. Model size/digest pins, attribution
and notices remain required. No new model, word list or external service is
added by this audit.

## Workflow and evidence

| Area | Evidence / remaining qualification |
| --- | --- |
| Windows build and launch | v0.4.0 release run [40927514989](https://github.com/shmuelbiller1/ocr/actions/runs/40927514989) passed all five jobs, including both one-click launches; main run [40930484056](https://github.com/shmuelbiller1/ocr/actions/runs/40930484056) passed. These earlier checks did **not** catch the printer-factory defect. |
| Offline recognition | Windows worker checks run small, medium, Mishkefet raw, beam and assisted cases and compare baseline/candidate results. This is inference evidence, not a handwriting-accuracy score. |
| Image/PDF input, preview, document deletion, cancellation, per-document edits | Covered by preview, window, task and worker tests; deleting a workspace entry must not delete its source scan. |
| Save/reopen; original vs edited text | Project tests cover persistence, original transcription, alternatives and accepted changes. The expanded packaged self-test also round-trips synthetic original/edited text. |
| TXT / DOCX output | Real files are generated and read back; DOCX right-to-left paragraph markers are checked. The packaged self-test now performs these checks too. |
| PDF / shared printing setup | New tests call the actual GUI PDF-save action, check A4/15 mm layout and read a generated PDF. The packaged self-test now creates and renders a real PDF through the app's printer factory. |
| Physical printer and visual layout | Not certified by a virtual PDF or a launch test. A real Windows printer and representative mixed Hebrew/English documents still need human checking. |
| Plugins | Installer/registry/UI tests cover folder/ZIP installation, removal, enable/disable, selection, persisted settings and invalid-plugin handling. Packaged self-test now checks **all declared built-in imports**, not just the presence of `kraken`. |
| Removal granularity | User-installed plugins are removable. Built-ins can be disabled, not individually uninstalled. Bundled decoding priors are protected from deletion because deleting them invalidates the one-click cache. This does **not** fully meet a strict independently-removable-components requirement. |
| Offline scope | Included models work offline. Optional installation/download actions remain explicit; Lite/ZIP do not magically contain All Models assets. |

The new self-test's document text is a **synthetic fixture**, never a fabricated
OCR result. It does not substitute for actual worker inference tests, a
GUI-to-worker recognition acceptance run, or a physical printer test. A source
fix is not a verified Windows fix until the updated packaged checks pass.

## Remaining gates before calling the entire original scope final

1. **Spelling:** supply a reviewed, redistribution-compatible Hebrew word list
   and test its handling of school vocabulary, names and abbreviations. The
   current adapter works with a user's list; it is not a supplied full lexicon.
2. **Grammar:** implement and validate the desired language-level rules or an
   approved offline model. The existing four rules cover punctuation/spacing.
3. **לשון הספר:** obtain the user's approved guide and examples; implement
   independently tested accept/reject proposals. Do not turn on the current
   placeholder or treat its unverified planned examples as authoritative rules.
4. **Search:** in-document text search is still unimplemented.
5. **Component removal:** decide whether disabling built-ins is acceptable or
   implement genuinely independent removal/reinstallation without breaking the
   shared worker or one-click integrity checks.
6. **Modern handwriting quality:** add independently verified transcripts and
   measure raw CER/WER, line completeness and human correction time. The supplied
   scan has no checked transcript; accuracy remains unverified. Do not select a
   default by an accuracy ranking that has not been established.
7. **Windows acceptance:** run the complete scan/PDF → real GUI recognition →
   optional review/edit → save/reopen → TXT/DOCX/PDF → real printer workflow on
   the candidate download under a standard account without Python. Check RTL
   visual output, cancellation and recovery from missing/broken plugins.
8. **Ship the fix:** publish a new version only after its own packaged checks
   pass; leave v0.4.0 and v0.3.0 artifacts unchanged and identify which version
   contains the printer fix. Unsigned executables may trigger Windows warnings.

No training, cloud processing, automatic rewriting or invented grammar/style
rules are needed or justified to complete this audit.


## Follow-up: optional spelling candidate

A separately built `hunspell-hebrew` plugin now provides genuine word checking,
three native candidates at most, and persistent personal vocabulary. Its
AGPL-licensed dictionary is **not included in the existing core releases**.
This closes the adapter/dictionary-format prototype gap only, not the validated
modern-school spelling gate: upstream Hspell 1.4 uses pre-June-2017 rules, and
school/Aramaic/Yiddish vocabulary still needs checking. Frozen Windows plugin
installation and native smoke checks are required in CI. The curated smoke
fixtures are not an independent accuracy benchmark. See the plugin guide.

## Follow-up: modern Hebrew spell-check candidate

A second separately installed candidate supplements Hspell 1.4 with exact
forms from a pinned AI-assisted CC0 word list. On 16 Academy 2017 examples,
7 Hspell-only flags became 0; on seven selected obvious typo examples both
flagged all seven. This narrow smoke test is not independent school-corpus
validation. The list may accept incorrect forms, and no modern correction
ranking or full Academy compliance is claimed. Baseline Hspell remains
selectable, suggestions require acceptance, and released v0.4.0 is unchanged.
See `optional_plugins/modern_hebrew/README.md`.
