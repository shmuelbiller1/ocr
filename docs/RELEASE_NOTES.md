# הערות הגרסה — v0.4.0

## Download / הורדה

For Windows x64, choose **one** of these downloads:

| Download | What is included | Use |
| --- | --- | --- |
| `HebrewNotesWorkbench-0.4.0-one-click.exe` (**Lite**) | App, OCR worker and Kraken PP-OCRv6 small (Apache-2.0) | Recommended starting point; no Python, installer or separate model download. |
| `HebrewNotesWorkbench-0.4.0-all-models-noncommercial-one-click.exe` | App, worker, Kraken small + medium, Mishkefet-v1, character LM and word LM | **Noncommercial use only** for the bundled Mishkefet assets (CC-BY-NC-SA-4.0). Includes assisted decoding offline. |
| `HebrewNotesWorkbench-0.4.0-win64.zip` | App and worker, without recognition weights | Manual/portable folder option; install the required models before going offline. |

Download the matching `.sha256` file to verify a binary's SHA-256 checksum.
Double-click an EXE; it unpacks automatically into a per-user cache. First
launch can take time and requires free disk space for extraction. The onefile
payload is temporarily extracted on each launch. Additional models selected
later require a download, but the models listed for each EXE work locally.
Nothing is uploaded. These EXEs are not claimed to be digitally signed.

The noncommercial model licence does not replace the surrounding application
and dependency licences. Application/dependency licence texts are included in
`LICENCES`. The Mishkefet notice includes attribution, original model sources
and an online link to the CC-BY-NC-SA-4.0 terms; its full legal text is not
bundled. Reading that link is not required to run OCR. See `docs/THIRD_PARTY.md`
and use Lite if the noncommercial restrictions do not suit your intended use.

## Changes in v0.4.0

- Two one-click offline Windows editions, with pinned model-integrity checks.
- Optional Raw / Beam + three scales / Assisted comparison. Raw remains the
  default; alternatives are separate, labelled and never silently adopted.
- Conservative worker cleanup: about 31.6 MB less unpacked and 13.5 MB less
  compressed in the same-run worker-only comparison. No models or image codecs
  removed, and no accuracy, speed or RAM improvement claimed.
- Packaged Windows launch, local image/PDF recognition, all three recognition
  checkpoints and assisted decoding checked in CI. School-note accuracy is
  **still unverified** without independently checked transcripts.

## Existing features and limitations

Hebrew Notes Workbench - a program for handwritten Hebrew-script notes on
Windows, that works without an internet connection and without Python.

**מה יש בגרסה הזאת**

* זיהוי כתב יד עם kraken ומודל PP-OCRv6 (Apache-2.0). המודל הקטן כלול
  בגרסאות Lite ו-All Models. בגרסת ZIP יש להתקין אותו בנפרד לפני עבודה
  ללא אינטרנט. המודלים נבדקים מול הטבעות SHA-256 קבועות.
* מנוע שני, "Mishkefet-v1", שנכתב לכתב יד עברי מודרני: הקוד שלו
  (רישיון MIT) מצורף לתוכנה, והמשקלים שלו (רישיון CC-BY-NC-SA-4.0, שימוש
  לא מסחרי) כלולים בגרסת All Models בלבד. ב-Lite וב-ZIP אפשר להתקינם
  בנפרד, בהסכמה לרישיון, לפני עבודה ללא אינטרנט; הם נבדקים מול SHA-256. המנוע
  קורא בלי מילון ובלי מודל שפה, כדי שהמדידה תהיה מדידה של המנוע עצמו.
* מנוע הזיהוי ומודלי השפה הם תוספים: אפשר להתקין, להסיר ולבחור אותם
  במסך "הגדרות".
* תצוגה מקדימה של תמונות ושל דפי PDF, שמירת העבודה בקובץ .hwproj,
  ייצוא ל-TXT ול-DOCX, הדפסה ותצוגה מקדימה לפני ההדפסה.
* הצעות תיקון של איות ושל ניסוח, כל הצעה מתקבלת או נדחית בנפרד,
  ואפשר לבטל את כל השינויים.
* התוכנה שואלת לפני שהיא סוגרת חלון שיש בו עבודה שלא נשמרה, ולפני
  שהיא מחליפה קובץ שכבר קיים.
* עבודה על ההצעות של דף ביחד: "קבל הכל", "דחה הכל", קבל או דחה רק
  את ההצעות שסומנו, שינוי מילה בכל המקומות שבהם היא מופיעה, שמירת
  מילה במילון של המשתמש, ביטול הפעולה האחרונה כמעשה אחד, וחזרה לטקסט
  שהזיהוי נתן.  שום הצעה אינה מוחלת בלי לחיצה של המשתמש.
* רק המסמך המזוהה נעול בזמן הזיהוי, כדי שמה שהמשתמש כותב בינתיים לא ייעלם
  כשתוצאת הזיהוי מחליפה את הטקסט.
* אפשר לבטל את הורדת המודל, והורדה שבוטלה אינה משאירה קובץ מאחור.
* דף אמיתי אחד של כתב יד עברי מודרני נמצא במאגר, וכל בנייה קוראת
  אותו בכל המנועים ומפרסמת את מה שכל מנוע קרא.  הדיוק על חומר בית
  הספר עדיין **לא מאומת**, כי לאף דף אין עדיין תמליל שנבדק על ידי
  מישהו אחר.

**מה עדיין לא עובד**

* הדיוק של הזיהוי על כתב יד של בית ספר מודרני **לא מאומת עדיין**: אין
  עדיין דפים עם תמליל שנבדק על ידי מישהו אחר.  ראו
  `docs/MODERN_SCHOOL_BENCHMARK.md`.
* מודול "לשון הספר" הוא מסגרת בלבד: הכללים עדיין לא כתובים, והמודול
  כבוי ואינו מציע דבר.
* אין מילון מצורף לתוכנה: המילון של המשתמש נטען לבד.
* בחירת מנוע ברירת המחדל לפי המדידה היא **התוכנית**, ולא מה שהתוכנה
  עושה היום: התוכנה משחזרת את המנוע שהמשתמש בחר, ואם אין כזה בחירה
  היא לוקחת את המנוע הראשון שהיא מוצאת.  בחירה של המשתמש לעולם
  אינה מוחלפת.

**English**

This is an offline Windows program for Hebrew handwriting: import a scan,
recognise the text, correct it, and print it.  Python is not needed.  The
regular ZIP requires recognition weights to be installed when the user asks;
the one-click editions already include the models listed above, and
the model file is checked against the digest published by its authors.  Nothing is uploaded anywhere.  Application/dependency licence texts are in `LICENCES`. Bundled model source
and attribution details are in `models/MODEL-SOURCE.txt` and
`models/OFFLINE-MODELS.json`. In the all-models edition,
`LICENCES/MISHKEFET-MODEL-NOTICE.txt` links to the full Mishkefet licence online.

The program asks before it closes a window with work that was not saved,
and before it replaces a file that is already there.

The proposals of a page can be worked on together: accept all of them,
refuse all of them, accept or refuse only the ones that were checked,
change one word in every place it appears, keep a word in the word list
of the user, take the last group of changes back as one action, and go
back to the text that the recognition gave.  Nothing is applied without
the press of the user.

There is a second engine, *Mishkefet-v1*, which was written for modern
Hebrew cursive: its code (MIT) is shipped with the program, and its
weights (CC-BY-NC-SA-4.0, non-commercial) are included in All Models only.
Lite and ZIP users can install them separately after licence confirmation,
before going offline. The weights are checked against a SHA-256 digest.  Its default/raw benchmark profile reads with the best path alone,
without a dictionary and without a language model, so that a measurement
measures the engine and not the word list.  The search that led to it and
the models that were not used are in `docs/ENGINES.md`.

The accuracy of the recognition on modern school handwriting is **not
verified** yet: there is no page with a transcript that was checked by
somebody else.  The tools that build the corpus and that measure the
engines on it are in the repository, and `docs/MODERN_SCHOOL_BENCHMARK.md`
says what the school has to add.

One real page of contemporary handwritten Hebrew is in the repository,
and every build reads it with every engine and publishes what each of
them read.  No rate is calculated from it: without a transcript that
somebody else checked, the number would be the number of the mistakes
of the transcript and not of the engine.

The editor is closed while the recognition runs, so that what the user
writes in the meantime is not lost when the result replaces the text.
The download of a model can be stopped, and a download that was stopped
leaves nothing behind.

## Experimental decoding comparison

Settings now exposes Raw (default), Beam + three scales, and Assisted with
optional non-commercial character/word models, included in All Models and
available separately for Lite/ZIP after licence confirmation. They are
verified against pinned hashes. Both raw and alternative
readings are retained and shown side by side; applying the alternative requires
confirmation and can be undone. These profiles do not change the raw benchmark
or establish an accuracy improvement on school notes. See `docs/ASSISTED_DECODING.md`.

## One-click offline release options

Two single-download, double-click Windows EXE editions are published alongside
the existing ZIP, with no installer, extraction wizard, Python setup, or
separate model download.

- **One-click Lite** bundles the Kraken PP-OCRv6 small model (Apache-2.0).
- **One-click All Models — Noncommercial** bundles Kraken small, Kraken medium,
  Mishkefet-v1 and both of Mishkefet's optional language models. The Mishkefet
  model files are CC-BY-NC-SA-4.0, attributed and supplied unmodified for
  noncommercial use. See the included notice and license link.

All bundled model files are validated against pinned SHA-256 digests. Windows
automatically unpacks the program into a per-user cache; the PyInstaller
onefile payload is temporarily extracted on every launch, so it may open
more slowly than the regular ZIP. Switching OCR engines is done in Settings.
