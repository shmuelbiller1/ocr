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
  "changes": [
    {
      "module": "grammar",
      "original": " ,",
      "replacement": ",",
      "position": 4,
      "message": "אין רווח לפני הפסיק"
    }
  ]
}
```

The original text of the scan is not in the file and is not changed.
