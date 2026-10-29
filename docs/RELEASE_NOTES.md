# הערות הגרסה — v0.3.0

Hebrew Notes Workbench - a program for handwritten Hebrew-script notes on
Windows, that works without an internet connection and without Python.

**מה יש בגרסה הזאת**

* זיהוי כתב יד עם kraken ומודל PP-OCRv6 (Apache-2.0).  המודל מותקן
  על ידי המשתמש, ונבדק מול הטבעה שפורסמה על יד מפרסמיו.
* מנוע שני, "Mishkefet-v1", שנכתב לכתב יד עברי מודרני: הקוד שלו
  (רישיון MIT) מצורף לתוכנה, והמשקלים שלו (רישיון CC-BY-NC-SA-4.0, שימוש
  לא מסחרי) מותקנים על ידי המשתמש ונבדקים מול טבעת SHA-256.  המנוע
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
recognition engine and its model are installed only when the user asks for
it, and the model file is checked against the digest published by its
authors.  Nothing is uploaded anywhere.  The licence texts of every bundled
component are in the folder LICENCES.

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
weights (CC-BY-NC-SA-4.0, non-commercial) are installed by the user and
checked against a SHA-256 digest.  Its default/raw benchmark profile reads with the best path alone,
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
optional non-commercial character/word models, installed separately after
licence confirmation and verified against pinned hashes. Both raw and alternative
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
