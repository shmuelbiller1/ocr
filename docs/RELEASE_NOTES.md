# הערות הגרסה — v0.5.0

## Download / הורדה

For Windows x64, choose **one** of these downloads:

| Download | What is included | Use |
| --- | --- | --- |
| `HebrewNotesWorkbench-0.5.0-one-click.exe` (**Lite**) | App, OCR worker, bundled CC0-1.0 Hebrew lexicon, and Kraken PP-OCRv6 small (Apache-2.0) | Recommended Apache-2.0 starting point; no Python, installer or separate model download. |
| `HebrewNotesWorkbench-0.5.0-all-models-noncommercial-one-click.exe` | App, worker, bundled CC0-1.0 Hebrew lexicon, Kraken small + medium, Mishkefet-v1, character LM and word LM | **Noncommercial use only** for the bundled Mishkefet assets (CC-BY-NC-SA-4.0). Defaults to Mishkefet-v1 for modern cursive and includes assisted decoding + per-student offline adaptation. |
| `HebrewNotesWorkbench-0.5.0-win64.zip` | App, worker, and bundled CC0-1.0 Hebrew lexicon, without recognition weights | Manual/portable folder option; install the required models before going offline. |

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

## Changes in v0.5.0

- **Offline 50-student school learning & side-by-side RTL verification** (`docs/SCHOOL_LEARNING.md`):
  - Strict two-stage separation between **Stage A** (exact as-written diplomatic transcription before spelling/grammar/style edits) and **Stage B** (per-item accept/reject language suggestions that never overwrite Stage A training labels).
  - Side-by-side scan & line-crop verification with bounding-box highlighting, keyboard navigation, and explicit `Verified` / `Uncertain` / `Not reviewed` review states (editing or saving a draft never marks a line `Verified` without confirmation, and only `Verified` lines of the selected student are used for adaptation).
  - Local SQLite provenance store (`learning.sqlite3`) with full correction audit history, SHA-256 integrity-checked backup/restore ZIP, profile deletion, online-training ZIP export (`train_mishkefet_head_online.py`), and leak-free held-out-validated `.npz` adapter re-import (`allow_pickle=False`). The export anonymizes writer metadata by default, but not images or transcriptions; review both before uploading.
  - Per-student lightweight frozen-backbone CTC head adaptation (`~405 KB` per student; `General / Unknown` always uses the unmodified base model) with held-out validation gate, honest `"insufficient_evidence"` reporting on tiny sets, adapter version history, one-click rollback, opt-in administrator-approved shared vocabulary, and 2-page LRU bounded memory suitable for 8 GB RAM Windows PCs.
- **Measured default engine selection**: When `Mishkefet-v1` is installed and the user has not chosen another engine, the app selects `Mishkefet-v1` automatically (`61.78%` character accuracy on the verified public-domain modern cursive benchmark vs. `19.51%` for `Kraken` small), while never overriding an explicit user choice.
- **PhotoCraft page enhancement & stroke-width audit**: Automatic shadow/exposure correction (`Automatic page enhancement: On / Off`) with `Original / Processed / Side-by-side` preview comparison, keeping original antialiased grayscale stroke width as default.
- **Bundled offline Hebrew & rabbinic suggestions**: Ships a bundled CC0-1.0 Hebrew lexicon (`196,227` words plus Mishnaic/rabbinic morphology and abbreviations/rashei-teivot), OCR-confusion candidate ranker, and deterministic Hebrew grammar/punctuation rules (`100%` top-1 on the 27-case benchmark with `0` false flags).
- **Qt 6 printing & PDF fix**: Fixes in-app Print, Print Preview, and Save-as-PDF (`QPageSize` / `QPageLayout` Qt 6 APIs) that were broken in `v0.4.0`.
- Classroom school-note accuracy (`benchmark/modern_school`) is **still unverified** without consented, independently checked school transcripts.

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
  נבחר כברירת מחדל כאשר הוא מותקן והמשתמש טרם בחר מנוע אחר, וקורא בפרופיל
  הבסיס בלי מילון ובלי מודל שפה כדי שהמדידה תהיה מדידה של המנוע עצמו.
* אימות שורות צד-לצד מול הסריקה המקורית (שלב א׳: טקסט מדויק כפי שנכתב בדיו
  לפני תיקוני איות ודקדוק) והתאמת ראש זיהוי אישי קל-משקל לכל תלמיד (עד ~50
  תלמידים) עם בדיקת שיפור על קבוצת בקרה עצמאית, היסטוריית גרסאות, חזרה בלחיצה
  אחת, אוצר מילים משותף באישור מנהל בלבד, גיבוי/שחזור וייצוא לאימון מקוון חיצוני.
* מילון איות עברי ותורני לא-מקוון מצורף לתוכנה (CC0-1.0) יחד עם הצעות דקדוק
  ופיסוק הניתנות להפעלה או לכיבוי; כל הצעה מתקבלת או נדחית בנפרד בשלב ב׳ מבלי
  לשנות את נתוני האימון של שלב א׳.
* שיפור אוטומטי של צילומי דפים (צללים ותאורה) עם תצוגת השוואה: מקור / מעובד /
  זה לצד זה.
* מנוע הזיהוי ומודלי השפה הם תוספים: אפשר להתקין, להסיר ולבחור אותם
  במסך "הגדרות".
* תצוגה מקדימה של תמונות ושל דפי PDF, שמירת העבודה בקובץ .hwproj,
  ייצוא ל-TXT ול-DOCX, הדפסה תקינה ב-Qt 6 ותצוגה מקדימה לפני ההדפסה.
* התוכנה שואלת לפני שהיא סוגרת חלון שיש בו עבודה שלא נשמרה, ולפני
  שהיא מחליפה קובץ שכבר קיים.
* עבודה על ההצעות של דף ביחד: "קבל הכל", "דחה הכל", קבל או דחה רק
  את ההצעות שסומנו, שינוי מילה בכל המקומות שבהם היא מופיעה, שמירת
  מילה במילון של המשתמש, ביטול הפעולה האחרונה כמעשה אחד, וחזרה לטקסט
  שהזיהוי נתן.  שום הצעה אינה מוחלת בלי לחיצה של המשתמש.
* רק המסמך המזוהה נעול בזמן הזיהוי, כדי שמה שהמשתמש כותב בינתיים לא ייעלם
  כשתוצאת הזיהוי מחליפה את הטקסט.
* אפשר לבטל את הורדת המודל, והורדה שבוטלה אינה משאירה קובץ מאחור.

**מה עדיין לא עובד**

* הדיוק של הזיהוי על מחברות כיתה של בית הספר (`benchmark/modern_school`) **לא
  מאומת עדיין**: בעוד שהדיוק על כתב-יד עברי מודרני ציבורי נמדד ואומת
  (`benchmark/modern_cursive`, ‏`61.78%` דיוק תווים ב-Mishkefet-v1), עדיין אין
  במאגר דפי תלמידים עם תמליל מוסכם שנבדק על ידי גורם עצמאי. ראו
  `docs/MODERN_SCHOOL_BENCHMARK.md`.
* מודול "לשון הספר" הוא מסגרת בלבד: הכללים הסגנוניים עדיין לא כתובים, והמודול
  כבוי ואינו מציע דבר.

**English**

This is an offline Windows program for Hebrew handwriting: import a scan,
recognise the text, verify lines side by side for optional per-student
adaptation, review spelling/grammar suggestions, and export or print it.  Python is not needed.  The
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

While public-domain modern cursive accuracy is measured in `docs/OCR_ACCURACY.md`
and per-writer held-out behavior is measured in `docs/SCHOOL_LEARNING.md`, the
accuracy of the recognition on classroom school handwriting (`benchmark/modern_school`) is **not
verified** yet: there is no classroom page with a consented transcript checked
by an independent reviewer.  `docs/MODERN_SCHOOL_BENCHMARK.md` says what the
school has to add.

The editor is closed while the recognition runs, so that what the user
writes in the meantime is not lost when the result replaces the text.
The download of a model can be stopped, and a download that was stopped
leaves nothing behind.

## Experimental decoding comparison

Settings exposes Raw (default), Beam + three scales, and Assisted with
optional non-commercial character/word models (plus administrator-approved
shared school vocabulary when opted in), included in All Models and
available separately for Lite/ZIP after licence confirmation. They are
verified against pinned hashes. Both raw and alternative
readings are retained and shown side by side; applying the alternative requires
confirmation and can be undone. These profiles do not change the raw benchmark.
See `docs/ASSISTED_DECODING.md` and `docs/SCHOOL_LEARNING.md`.

## One-click offline release options

Two single-download, double-click Windows EXE editions are published alongside
the existing ZIP, with no installer, extraction wizard, Python setup, or
separate model download.

- **One-click Lite** bundles the Kraken PP-OCRv6 small model (Apache-2.0) and
  the CC0-1.0 offline Hebrew spelling lexicon.
- **One-click All Models — Noncommercial** bundles Kraken small, Kraken medium,
  Mishkefet-v1, both of Mishkefet's optional language models, and the CC0-1.0
  offline Hebrew spelling lexicon. The Mishkefet model files are
  CC-BY-NC-SA-4.0, attributed and supplied unmodified for noncommercial use.
  See the included notice and license link.

All bundled model files are validated against pinned SHA-256 digests. Windows
automatically unpacks the program into a per-user cache; the PyInstaller
onefile payload is temporarily extracted on every launch, so it may open
more slowly than the regular ZIP. Switching OCR engines is done in Settings.
