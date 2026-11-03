# The proposals for corrections

The program has three separate modules that propose corrections.  Every
module has its own switch, and **nothing is ever changed without the
user accepting it**.

| Module | What it proposes | State |
| --- | --- | --- |
| `spelling` (איות) | Offline Hebrew spelling proposals using the bundled CC0-1.0 lexicon (196,227 words), conservative Hebrew & rabbinic/Aramaic (`ד-`/`כד-`/`מד-`) prefix stripping, Mishnaic `-ין` plural validation, OCR visual-confusion candidate ranking (ד/ר, ה/ח/ת, ו/י/ז, ב/כ, ס/ם, ן/ו, צ/ע/מ), persistent personal dictionary, and optional custom word list override | works out-of-the-box offline |
| `grammar` (דקדוק וניסוח) | High-precision deterministic offline Hebrew grammar and punctuation rules: 1st-person singular future `א-` prefix (`אני ילך -> אני אלך`), construct definite article (`הבית ספר -> בית הספר`), 3–10 numeral gender agreement, demonstrative gender agreement (`הבעיה הזה -> הבעיה הזאת`), accidental word/article duplication (`על על -> על`, `בדף הדף -> בדף`), acronym gershayim (`ע,ש -> ע"ש`, `רש'י -> רש"י`), and comma/quote/bracket/sentence spacing | works out-of-the-box offline |
| `style` (לשון הספר) | The rules of the guide of the Israel Academy | **not implemented** - the module is a frame, and it says so |

Each of the post-OCR layers (`איות`, `דקדוק וניסוח`, `לשון הספר`) has its own independent one-click checkbox at the top of the **הצעות תיקון** pane and in the **הצעות תיקון** menu, persisted across sessions.

## How a proposal is used

1. The user chooses **הצעות תיקון > בדיקת הצעות תיקון** (or the button
   *בדיקת הצעות* in the pane).
2. The pane shows every proposal, one under the other, with the text
   that is proposed, the reason, and the other possibilities when the
   module knows more than one.
3. Every proposal is accepted (*קבל*) or refused (*דחה*) on its own.
4. The accepted changes are written into the text of the document, and
   they are kept in the file of the project, so that the user can see
   what was changed.
5. **ביטול כל שינויי התיקון** takes back every change at once.

The text that the engine recognised is never changed behind the back of
the user: every change is a proposal that is shown first, and the file
of the scan is never touched.

## Working on many proposals at once

A page of notes may have a few dozen proposals, and the teacher who
corrects it may want to go over them quickly.  The pane therefore has
buttons for the proposals as a whole, and every one of them is a
deliberate act of the user - the program never applies a correction on
its own.

| Button | What it does |
| --- | --- |
| *קבל הכל* | Accepts every proposal that is shown.  All of them are taken as one action. |
| *דחה הכל* | Refuses every proposal that is shown.  The text is not changed. |
| *קבל מסומנות* / *דחה מסומנות* | Accepts or refuses only the proposals whose box is checked. |
| *ביטול הפעולה האחרונה* | Takes back the last group of changes - the last press of any of the buttons above - as one action. |
| *ביטול כל השינויים* | Takes back every change that was accepted. |
| *חזרה לטקסט המקורי* | Goes back to the text that the recognition gave, before any correction. |

And on every proposal of a word, two more buttons:

| Button | What it does |
| --- | --- |
| *בכל המקומות* | Accepts the proposal in every place where the same word stands, and takes them all back as one action. |
| *לשמור את המילה* | Adds the word as it is written to the word list of the user, so that it is not proposed again.  When the file of the list cannot be written, the word is kept for that session only, and the program says so. |

Two rules that hold for all of the buttons:

* **Every change is one action that can be taken back.**  The changes
  that were made at once are kept as one group, and *ביטול הפעולה
  האחרונה* takes the whole group back.  A change that was made alone
  is not taken back with a group.
* **Nothing is applied without the press of the user.**  There is no
  button that decides by itself which corrections are "safe" and
  applies them, because a correction that is right for one page may be
  wrong for another.  The program proposes; the user decides.

When two proposals are about the same place in the text, only one of
them can be applied.  The other one is refused, because it does not
fit the text any more, and it is not left in the list as if it were
still waiting for an answer.

Going back to the text of the recognition takes away what the user
wrote after it, and the program asks before it does that.

## The word list of the spelling module

The built-in `spelling-hebrew` plugin ships out-of-the-box with a compressed
CC0-1.0 Hebrew word list (`hebrew_workbench/suggestions/data/hebrew_words_cc0.txt.gz`,
196,227 words from `roni5604/hebrew-words-db` commit `879f0f46`), combined with:

* Conservative Hebrew proclitic/conjunction prefix recognition (`ו`, `ה`, `ב`,
  `כ`, `ל`, `מ`, `ש` and standard two-letter combinations) gated against minimum
  stem length and valid final-letter rules.
* False-positive guards for Hebrew abbreviations and numerals (`״` / `׳`),
  standard Aramaic/rabbinic study terms in Hebrew script, and short tokens.
* OCR-specific weighted edit-distance ranking that prioritises common handwritten
  Hebrew letter confusions (`ד↔ר`, `ה↔ח↔ת`, `ו↔י↔ז↔ן`, `ב↔כ`, `ס↔ם`, `ע↔צ`, `ג↔נ`)
  and safe run-on word splits (`ביתהספר -> בית הספר`).
* A persistent personal dictionary (`personal_dictionary.txt` inside the user's
  application data folder) updated whenever the user clicks *לשמור את המילה*.

Users who prefer their own custom word list (or the optional AGPL Hunspell/Hspell
plugin) can still point **הצעות תיקון > בחירת מילון לאיות** at any `.txt`/`.dic`
file (`שלום/תחתונות` slash-variant format remains supported).

## The rules of the style module

The style module is switched off when the program starts, and it
proposes nothing.  The rules that will be in it are written down in
`hebrew_workbench/suggestions/style.py`, each one with the place in the
guide it comes from and with the state of the work.  A rule of לשון
הספר that is wrong is worse than no rule at all, because the user would
have to check every proposal.

## In the file of the project

Every document in the file of the project (`.hwproj`) keeps the changes
that were accepted:

```json
{
  "path": "C:\\scans\\page1.png",
  "transcription": "שלום, עולם",
  "original_transcription": "שלום ,עולם",
  "changes": [
    {
      "module": "grammar",
      "original": " ,",
      "replacement": ",",
      "position": 4,
      "message": "אין רווח לפני הפסיק",
      "batch": 1
    }
  ]
}
```

`original_transcription` is the text that the recognition gave, and it
is what *חזרה לטקסט המקורי* goes back to.  The `batch` number is the
group of the change: the changes that were made at once have the same
number, and they are taken back together.

The file of the scan itself is never changed.


## Optional native Hunspell/Hspell plugin

The separate `hunspell-hebrew` plugin uses actual UTF-8 .dic/.aff files, a
source-built native subprocess with an 8-second timeout, and its own personal
vocabulary file. It does not reuse the custom slash-list parser. Install its
built ZIP and select it as the active spelling plugin in Settings. It is not
in current release downloads. Hspell 1.4 follows pre-June-2017 orthography;
modern-school quality remains unverified. See
[the plugin guide](../optional_plugins/hunspell_hebrew/README.md) for the AGPL
source offer, install/remove steps, limits and build recipe.

## Experimental modern-spelling supplement

A second **optional** plugin, `modern-hebrew-spelling`, keeps the original
Hspell/Hunspell engine and adds a pinned AI-assisted CC0 word list for exact
acceptance only. It does not replace the unmodified `hunspell-hebrew` plugin,
and neither plugin is included in the published v0.4.0 downloads. The modern
list suppresses flags, so it can also suppress real errors if the list contains
incorrect words. Suggestions still come from Hspell's old dictionary. Review
and accept each one explicitly; the raw OCR baseline never changes.

In one small developer smoke comparison of 16 examples from the Hebrew
Academy's 2017 spelling update, original Hspell flagged seven and the modern
supplement flagged none. Seven deliberately misspelled examples were flagged
by both; five prefixed examples were accepted by both. This is **not** an
independent or representative accuracy benchmark and does not establish
modern-school performance. See the [plugin guide](../optional_plugins/modern_hebrew/README.md)
for provenance, size, risks, installation and native Windows verification.
