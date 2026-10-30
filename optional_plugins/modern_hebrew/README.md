# Experimental modern Hebrew spelling supplement

This separate plugin combines Hspell 1.4 + Hunspell with an **acceptance-only**
supplement of 196,227 exact forms from the pinned `hebrew-words-db` list. It is
not a full new spelling engine or a guarantee of 2017-rule coverage. The
unmodified original `hunspell-hebrew` plugin remains separately installable.

## What changes, and what does not

For an exact, unvocalized Hebrew word present in the supplement, this plugin
suppresses Hspell's spelling flag. It does not generate suggestions from the
supplement. Other words, including prefixed forms absent from the list, are
checked and suggested by the original Hspell engine. Prefixes are **not**
guessed or stripped from the supplement. Personal words are stored separately
in the same per-user list as the baseline plugin. No text is changed unless
explicitly accepted; raw OCR is preserved. Spelling is not grammar.

The supplement includes spelling variants and is **AI-assisted**, not a
vetted Academy dictionary. Its upstream states CC0 and provides methodology;
provenance and accuracy have not been independently audited. It may accept
incorrect words, old variants, or ambiguous real words, reducing false alarms
at the cost of missed errors. No complete modern Hebrew standard compliance or
school-note accuracy is claimed. Names, abbreviations, niqqud and prefixes remain
limitations. Do not use this as an authoritative correction service.

The Academy's 2017 examples form a **small public smoke fixture**, not a
representative independent benchmark. Our tests compare the old and new plugin
on the same fixture, real-word prefixes and selected obvious typos. Human-
verified school pages, false positives/negatives, correction ranking, speed and
memory on Windows must be measured before claiming a better general checker.

## Installation

From the built Windows artifact `Modern-Hebrew-spelling-Windows`, install
`modern-hebrew-spelling-win64.zip` using Settings → Plugins and engines → Install
ZIP, then select `modern-hebrew-spelling` for spelling. It works offline after
installation, without Python or downloads. Remove it through Settings; your
personal words survive removal. Both plugins may be installed, but only the
selected spelling plugin checks a document. Changing to a custom Hunspell
`.dic/.aff` pair keeps this supplement active: select the original plugin if
that is not wanted. Existing v0.4.0 release files do not contain this plugin.

## Reproduce

On Windows with VS2022 x64 (or Linux with a C++ compiler), install CMake 3.31.6
and run `python tools/build_modern_spelling_plugin.py`. Verify with
`python tools/verify_spelling_plugin.py --modern --zip build/hebrew-spelling/modern-hebrew-spelling-win64.zip --report build/modern-report.json`.
Use `modern-hebrew-spelling-linux.zip` on Linux. Packaged Windows testing adds
`--packaged-app dist/HebrewNotesWorkbench/HebrewNotesWorkbench.exe`.

The plugin contains the upstream list (2,670,751 bytes), its CC0 notice,
methodology, pinned commit and SHA-256. Hspell data remains **AGPL-3.0-only**;
the Hunspell engine retains LGPL/GPL/MPL terms. The complete Hspell, Hunspell
and application corresponding sources and notices remain in SOURCE/LICENCES.
Adding CC0 data does not relicense Hspell or exempt the distribution from
copyleft. No external executables, AI models or online runtime are needed.

### Earlier example correction

An earlier message implied that Hspell's suggestion of **אימא** for the common
spelling **אמא** resulted from the 2017 change. That was not established:
Hspell's older guide already preferred אימא. The 2017 examples compared in this
plugin are instead based on the Academy's published update:
https://hebrew-academy.org.il/%d7%9b%d7%9c%d7%9c%d7%99-%d7%94%d7%9b%d7%aa%d7%99%d7%91-%d7%94%d7%9e%d7%9c%d7%90-%d7%94%d7%9b%d7%9c%d7%9c%d7%99%d7%9d-%d7%94%d7%97%d7%93%d7%a9%d7%99%d7%9d-%d7%a1%d7%99%d7%95%d7%95%d7%9f/
