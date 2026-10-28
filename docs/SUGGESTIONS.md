# The proposals for corrections

The program has three separate modules that propose corrections.  Every
module has its own switch, and **nothing is ever changed without the
user accepting it**.

| Module | What it proposes | State |
| --- | --- | --- |
| `spelling` (איות) | The words that are not in the word list of the user | works, with a word list that the user brings |
| `grammar` (ניסוח) | Punctuation and spacing: a space before a comma, a missing space after a comma, two spaces in a row, a space before a closing quote | works, a few rules only |
| `style` (לשון הספר) | The rules of the guide of the Israel Academy | **not implemented** - the module is a frame, and it says so |

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

The program does **not** ship a Hebrew dictionary.  The Hebrew Hunspell
dictionary of LibreOffice (`he_IL`) is under the AGPL, and it may not be
given away inside this program.  The module therefore works with a word
list that the user has:

* **הצעות תיקון > בחירת מילון לאיות** points at the file.
* The file is a text file with one word in every line.  A line may hold
  the word and its alternatives, separated by a slash, the way a
  Hunspell dictionary does:

  ```
  שלום/תחתונות
  בית
  ```

* A word that is shorter than four letters is not proposed, because a
  short word is often an abbreviation or a name.
* If a file with the name `LICENSE`, `LICENCE` or `COPYING` is next to
  the word list, its text is read, so that the licence of the list is
  known.
* *לשמור את המילה* adds the word to the end of that file, with the
  same format.

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
