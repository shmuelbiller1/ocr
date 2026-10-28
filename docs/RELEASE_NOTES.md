# הערות הגרסה

Hebrew Notes Workbench - a program for handwritten Hebrew-script notes on
Windows, that works without an internet connection and without Python.

**מה יש בגרסה הזאת**

* זיהוי כתב יד עם kraken ומודל PP-OCRv6 (Apache-2.0).  המודל מותקן
  על ידי המשתמש, ונבדק מול הטבעה שפורסמה על יד מפרסמיו.
* מנוע הזיהוי ומודלי השפה הם תוספים: אפשר להתקין, להסיר ולבחור אותם
  במסך "הגדרות".
* תצוגה מקדימה של תמונות ושל דפי PDF, שמירת העבודה בקובץ .hwproj,
  ייצוא ל-TXT ול-DOCX, הדפסה ותצוגה מקדימה לפני ההדפסה.
* הצעות תיקון של איות ושל ניסוח, כל הצעה מתקבלת או נדחית בנפרד,
  ואפשר לבטל את כל השינויים.
* עבודה על ההצעות של דף ביחד: "קבל הכל", "דחה הכל", קבל או דחה רק
  את ההצעות שסומנו, שינוי מילה בכל המקומות שבהם היא מופיעה, שמירת
  מילה במילון של המשתמש, ביטול הפעולה האחרונה כמעשה אחד, וחזרה לטקסט
  שהזיהוי נתן.  שום הצעה אינה מוחלת בלי לחיצה של המשתמש.

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

The proposals of a page can be worked on together: accept all of them,
refuse all of them, accept or refuse only the ones that were checked,
change one word in every place it appears, keep a word in the word list
of the user, take the last group of changes back as one action, and go
back to the text that the recognition gave.  Nothing is applied without
the press of the user.

The accuracy of the recognition on modern school handwriting is **not
verified** yet: there is no page with a transcript that was checked by
somebody else.  The tools that build the corpus and that measure the
engines on it are in the repository, and `docs/MODERN_SCHOOL_BENCHMARK.md`
says what the school has to add.
