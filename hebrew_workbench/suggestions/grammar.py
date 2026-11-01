"""Offline Hebrew grammar and punctuation module (high-precision, deterministic).

Checks both Hebrew punctuation/spacing conventions and high-precision modern
Israeli Hebrew morphosyntactic rules:
1. Punctuation, quotation, and bracket spacing (merged cleanly without span
   collisions when space-before and missing-space-after co-occur),
2. First-person singular future prefix (`אני ילך -> אני אלך`), excluding
   `י-` initial present-tense participles (`אני יכול`, `אני יודע`, ...),
3. Definite-article placement in fixed construct compounds (`הבית ספר -> בית הספר`),
4. Cardinal numeral (3-10) gender polarity on unambiguous plural nouns
   (`שלוש ימים -> שלושה ימים`, `שלושה פעמים -> שלוש פעמים`, excluding ambiguous
   unpointed `שמונה`),
5. Demonstrative gender agreement on unambiguous definite nouns
   (`הבעיה הזה -> הבעיה הזאת`, `הספר הזאת -> הספר הזה`), and
6. Accidental word/phrase duplication (`על על -> על`, `בדף הדף -> בדף`),
   excluding idiomatic Hebrew distributive reduplications (`לאט לאט`, `יום יום`).

Every proposal is optional, reviewable, and reversible; text is never modified
automatically.
"""

from __future__ import annotations

import re

from .base import KIND_GRAMMAR, Suggestion, SuggestionModule
from .hebrew_lexicon import strip_nikud

__all__ = ["GrammarModule"]


def _proposal(
    text: str,
    start: int,
    end: int,
    replacement: str,
    message: str,
    kind: str = "punctuation",
    alternatives: tuple[str, ...] = (),
) -> Suggestion:
    return Suggestion(
        module=KIND_GRAMMAR,
        original=text[start:end],
        replacement=replacement,
        message=message,
        start=start,
        end=end,
        kind=kind,
        alternatives=alternatives,
    )


# ---------------------------------------------------------------------------
# 1. Punctuation, quotation, and bracket spacing
# ---------------------------------------------------------------------------


def space_before_comma(text: str) -> list[Suggestion]:
    """A comma or semicolon is written without a space before it."""
    proposals: list[Suggestion] = []
    for match in re.finditer(r" +([,;])", text):
        proposals.append(
            _proposal(
                text,
                match.start(),
                match.end(),
                match.group(1),
                "אין רווח לפני הפסיק",
            )
        )
    return proposals


def space_after_comma(text: str) -> list[Suggestion]:
    """A comma or semicolon is written with a space after it."""
    proposals: list[Suggestion] = []
    for match in re.finditer(r"([,;])(?=[^\s\d\"״'׳)\]])", text):
        proposals.append(
            _proposal(
                text,
                match.start(),
                match.end(),
                match.group(1) + " ",
                "חסר רווח אחרי הפסיק",
            )
        )
    return proposals


def space_before_end_punctuation(text: str) -> list[Suggestion]:
    """Sentence-ending punctuation (. ? ! :) has no space before it."""
    proposals: list[Suggestion] = []
    for match in re.finditer(r' +([?!:]|\.(?!\.))(?=\s|$|[)\]"״])', text):
        proposals.append(
            _proposal(
                text,
                match.start(),
                match.end(),
                match.group(1),
                "אין רווח לפני סימן הפיסוק",
            )
        )
    return proposals


def double_space(text: str) -> list[Suggestion]:
    """Two spaces in a row are written as one."""
    proposals: list[Suggestion] = []
    for match in re.finditer(r" {2,}", text):
        proposals.append(
            _proposal(text, match.start(), match.end(), " ", "יותר מרווח אחד")
        )
    return proposals


def quote_and_bracket_spacing(text: str) -> list[Suggestion]:
    """Check spaces inside paired quotes and parentheses/brackets."""
    proposals: list[Suggestion] = []

    # Space before closing quote
    for match in re.finditer(r" +([\"״»])", text):
        quote = match.group(1)
        if quote != "»" and text.count(quote, 0, match.start(1)) % 2 == 0:
            continue
        proposals.append(
            _proposal(
                text,
                match.start(),
                match.end(),
                quote,
                "אין רווח לפני הגרשיים",
            )
        )

    # Space after opening quote (only when the quote has a matching closer)
    for match in re.finditer(r"(?:^|(?<=\s))([\"״«]) +(?=\S)", text):
        quote = match.group(1)
        q_pos = match.start(1)
        if quote != "«":
            if text.count(quote, 0, q_pos) % 2 != 0:
                continue
            if text.count(quote, q_pos + 1) < 1:
                continue
        proposals.append(
            _proposal(
                text,
                q_pos,
                match.end(),
                quote,
                "אין רווח אחרי פתיחת מרכאות",
            )
        )

    # Space immediately after opening parenthesis / bracket
    for match in re.finditer(r"([(\[]) +(?=\S)", text):
        proposals.append(
            _proposal(
                text,
                match.start(),
                match.end(),
                match.group(1),
                "אין רווח אחרי סוגריים פותחים",
            )
        )

    # Space immediately before closing parenthesis / bracket
    for match in re.finditer(r"(?<=\S) +([)\]])", text):
        proposals.append(
            _proposal(
                text,
                match.start(),
                match.end(),
                match.group(1),
                "אין רווח לפני סוגריים סוגרים",
            )
        )

    return proposals


# ---------------------------------------------------------------------------
# 2. First-person singular future verb prefix (אותיות אית"ן: אני ילך -> אני אלך)
# ---------------------------------------------------------------------------

YOD_VALID_PARTICIPLES_AND_ADJ: frozenset[str] = frozenset(
    {
        "יכול",
        "יכולה",
        "יודע",
        "יודעת",
        "יוצא",
        "יוצאת",
        "יושב",
        "יושבת",
        "יורד",
        "יורדת",
        "ישן",
        "ישנה",
        "יוזם",
        "יוזמת",
        "יועץ",
        "יועצת",
        "יורש",
        "יורשת",
        "יוצר",
        "יוצרת",
        "יורה",
        "יודגש",
        "יחיד",
        "יחידה",
        "ישר",
        "ישרה",
        "יקר",
        "יקרה",
        "יפה",
        "יציב",
        "יציבה",
        "יעיל",
        "יעילה",
        "ידיד",
        "ילד",
        "ילדה",
        "יהודי",
        "יהודייה",
        "ישראלי",
        "ישראלית",
        "ימיני",
        "יבש",
        "יבשה",
        "ירא",
        "יתום",
        "יגע",
        "יזם",
        "יותר",
        "יחד",
        "יחסית",
        "יום",
    }
)

# High-frequency verified 3ms -> 1sg future pairs in everyday modern Hebrew
FUTURE_3MS_TO_1SG: dict[str, str] = {
    "ילך": "אלך",
    "יכתוב": "אכתוב",
    "יכתב": "אכתוב",
    "יגיד": "אגיד",
    "יאמר": "אומר",
    "יעשה": "אעשה",
    "יראה": "אראה",
    "יבוא": "אבוא",
    "יקח": "אקח",
    "ייקח": "אקח",
    "יתן": "אתן",
    "ייתן": "אתן",
    "יביא": "אביא",
    "יגיע": "אגיע",
    "יחזור": "אחזור",
    "ילמד": "אלמד",
    "יבדוק": "אבדוק",
    "ינסה": "אנסה",
    "ידבר": "אדבר",
    "ישאל": "אשאל",
    "יענה": "אענה",
    "יקרא": "אקרא",
    "ישמע": "אשמע",
    "יחשוב": "אחשוב",
    "יבין": "אבין",
    "יזכור": "אזכור",
    "ישכח": "אשכח",
    "יפתח": "אפתח",
    "יסגור": "אסגור",
    "ימצא": "אמצא",
    "יתחיל": "אתחיל",
    "יסיים": "אסיים",
    "ימשיך": "אמשיך",
    "יסביר": "אסביר",
    "ישלח": "אשלח",
    "יקבל": "אקבל",
    "ישלם": "אשלם",
    "יקנה": "אקנה",
    "ימכור": "אמכור",
    "יעזור": "אעזור",
    "יפגוש": "אפגוש",
    "יבקש": "אבקש",
    "יכין": "אכין",
    "ישתמש": "אשתמש",
    "יתקשר": "אתקשר",
    "יבדק": "אבדוק",
    "יוכל": "אוכל",
    "יוסיף": "אוסיף",
    "יוציא": "אוציא",
    "יוריד": "אוריד",
    "יוביל": "אוביל",
    "יוכיח": "אוכיח",
    "יהיה": "אהיה",
}

_ANI_FUTURE_RE = re.compile(
    r"(?<![א-ת])(?:ו|ש|כש|אם)?אני(?:\s+(?:לא|גם|כבר|עוד|ממש|רק))?\s+(י[א-ת]{2,8})(?![א-ת])"
)


def first_person_future_prefix(text: str) -> list[Suggestion]:
    """Propose `א-` instead of `י-` on 1st-person singular future verbs after `אני`."""
    proposals: list[Suggestion] = []
    for match in _ANI_FUTURE_RE.finditer(text):
        verb_raw = match.group(1)
        verb = strip_nikud(verb_raw)
        if verb in YOD_VALID_PARTICIPLES_AND_ADJ:
            continue
        target = FUTURE_3MS_TO_1SG.get(verb)
        if target is None:
            continue
        proposals.append(
            _proposal(
                text,
                match.start(1),
                match.end(1),
                target,
                "בגוף ראשון יחיד בעתיד נוהגת תחילית א׳ (אית״ן)",
                kind="grammar",
            )
        )
    return proposals


# ---------------------------------------------------------------------------
# 3. Definite article in construct compounds (יידוע הסמיכות)
# ---------------------------------------------------------------------------

CONSTRUCT_COMPOUNDS: dict[tuple[str, str], str] = {
    ("הבית", "ספר"): "בית הספר",
    ("מהבית", "ספר"): "מבית הספר",
    ("הבית", "חולים"): "בית החולים",
    ("מהבית", "חולים"): "מבית החולים",
    ("הבית", "משפט"): "בית המשפט",
    ("הבית", "כנסת"): "בית הכנסת",
    ("הבית", "מדרש"): "בית המדרש",
    ("הבית", "קפה"): "בית הקפה",
    ("הבית", "מלון"): "בית המלון",
    ("העורך", "דין"): "עורך הדין",
    ("העורכת", "דין"): "עורכת הדין",
    ("העורכי", "דין"): "עורכי הדין",
    ("הראש", "ממשלה"): "ראש הממשלה",
    ("הראש", "עיר"): "ראש העיר",
    ("הבעל", "בית"): "בעל הבית",
    ("הבעלת", "בית"): "בעלת הבית",
    ("החדר", "אוכל"): "חדר האוכל",
    ("החדר", "שינה"): "חדר השינה",
    ("החדר", "כושר"): "חדר הכושר",
    ("הלוח", "שנה"): "לוח השנה",
    ("הסדר", "יום"): "סדר היום",
    ("השדה", "תעופה"): "שדה התעופה",
    ("התחנת", "רכבת"): "תחנת הרכבת",
    ("התחנת", "אוטובוס"): "תחנת האוטובוס",
    ("המזג", "אוויר"): "מזג האוויר",
    ("הכוח", "אדם"): "כוח האדם",
    ("השכר", "דירה"): "שכר הדירה",
    ("השכר", "לימוד"): "שכר הלימוד",
    ("הנקודת", "מבט"): "נקודת המבט",
    ("התעודת", "זהות"): "תעודת הזהות",
    ("הרישיון", "נהיגה"): "רישיון הנהיגה",
}

_TWO_WORD_HEB_RE = re.compile(r"(?<![א-ת])([א-ת]{3,10}) +([א-ת]{2,10})(?![א-ת])")


def construct_definite_article(text: str) -> list[Suggestion]:
    """Move definite `ה-` from construct head (`נסמך`) to modifier (`סומך`)."""
    proposals: list[Suggestion] = []
    idx = 0
    while idx < len(text):
        match = _TWO_WORD_HEB_RE.search(text, idx)
        if match is None:
            break
        w1 = strip_nikud(match.group(1))
        w2 = strip_nikud(match.group(2))
        replacement = CONSTRUCT_COMPOUNDS.get((w1, w2))
        if replacement is not None:
            proposals.append(
                _proposal(
                    text,
                    match.start(),
                    match.end(),
                    replacement,
                    "בצירוף סמיכות ה׳ הידיעה באה בסומך (המילה השנייה)",
                    kind="grammar",
                )
            )
            idx = match.end()
        else:
            idx = match.start(2)
    return proposals


# ---------------------------------------------------------------------------
# 4. Cardinal numeral (3-10) gender polarity agreement (שם המספר)
#    Note: unpointed `שמונה` is intentionally excluded because masculine
#    `שמונָה` and feminine `שמונֶה` are homographs without nikud.
# ---------------------------------------------------------------------------

FEM_NUM_TO_MASC: dict[str, str] = {
    "שלוש": "שלושה",
    "ארבע": "ארבעה",
    "חמש": "חמישה",
    "שש": "שישה",
    "שבע": "שבעה",
    "תשע": "תשעה",
    "עשר": "עשרה",
}
MASC_NUM_TO_FEM: dict[str, str] = {v: k for k, v in FEM_NUM_TO_MASC.items()}
MASC_NUM_TO_FEM["חמשה"] = "חמש"
MASC_NUM_TO_FEM["ששה"] = "שש"

MASC_PLURAL_NOUNS: frozenset[str] = frozenset(
    {
        "ימים",
        "חודשים",
        "שבועות",
        "אנשים",
        "תלמידים",
        "ילדים",
        "בנים",
        "ספרים",
        "עמודים",
        "דפים",
        "פרקים",
        "שיעורים",
        "מורים",
        "חברים",
        "מקומות",
        "דברים",
        "חלקים",
        "שקלים",
        "אחוזים",
        "סעיפים",
        "שלבים",
        "משפטים",
        "נושאים",
        "תרגילים",
        "מבחנים",
        "קורסים",
        "מסמכים",
    }
)

FEM_PLURAL_NOUNS: frozenset[str] = frozenset(
    {
        "פעמים",
        "שנים",
        "שעות",
        "דקות",
        "שניות",
        "מילים",
        "שאלות",
        "תשובות",
        "שורות",
        "כיתות",
        "מחברות",
        "נקודות",
        "בעיות",
        "דוגמאות",
        "אפשרויות",
        "טעויות",
        "בנות",
        "נשים",
        "מדינות",
        "ערים",
        "קבוצות",
        "יחידות",
        "פסקאות",
        "משימות",
        "עבודות",
        "הצעות",
    }
)


def numeral_gender_agreement(text: str) -> list[Suggestion]:
    """Check 3-10 numeral gender agreement before unambiguous plural nouns."""
    proposals: list[Suggestion] = []
    idx = 0
    while idx < len(text):
        match = _TWO_WORD_HEB_RE.search(text, idx)
        if match is None:
            break
        raw_num = strip_nikud(match.group(1))
        prefix = "ו" if raw_num.startswith("ו") and raw_num[1:] in (*FEM_NUM_TO_MASC, *MASC_NUM_TO_FEM) else ""
        num = raw_num[len(prefix):]
        noun = strip_nikud(match.group(2))
        if num in FEM_NUM_TO_MASC and noun in MASC_PLURAL_NOUNS:
            proposals.append(
                _proposal(
                    text,
                    match.start(1),
                    match.end(1),
                    prefix + FEM_NUM_TO_MASC[num],
                    f"התאמת שם המספר: '{noun}' הוא ממין זכר",
                    kind="grammar",
                )
            )
        elif num in MASC_NUM_TO_FEM and noun in FEM_PLURAL_NOUNS:
            proposals.append(
                _proposal(
                    text,
                    match.start(1),
                    match.end(1),
                    prefix + MASC_NUM_TO_FEM[num],
                    f"התאמת שם המספר: '{noun}' הוא ממין נקבה",
                    kind="grammar",
                )
            )
        idx = match.start(2)
    return proposals


# ---------------------------------------------------------------------------
# 5. Demonstrative gender agreement (הבעיה הזה -> הבעיה הזאת)
# ---------------------------------------------------------------------------

DEF_FEM_SINGULAR_NOUNS: frozenset[str] = frozenset(
    {
        "הבעיה",
        "השאלה",
        "התשובה",
        "המילה",
        "השורה",
        "הכיתה",
        "המחברת",
        "העבודה",
        "המשימה",
        "הטעות",
        "הנקודה",
        "הדוגמה",
        "התוכנית",
        "התכנית",
        "המערכת",
        "המדינה",
        "השפה",
        "התקופה",
        "התופעה",
        "השיטה",
        "הגישה",
        "הבדיקה",
        "התוצאה",
        "ההצעה",
        "ההחלטה",
        "הפסקה",
        "היחידה",
    }
)

DEF_MASC_SINGULAR_NOUNS: frozenset[str] = frozenset(
    {
        "הספר",
        "הפרק",
        "העמוד",
        "הדף",
        "השיעור",
        "המסמך",
        "הטקסט",
        "המשפט",
        "הנושא",
        "המאמר",
        "המחקר",
        "המקרה",
        "המצב",
        "התהליך",
        "הפתרון",
        "החלק",
        "השלב",
        "הסעיף",
        "המקום",
        "הדבר",
        "הזמן",
        "היום",
        "החודש",
        "השבוע",
    }
)


def demonstrative_agreement(text: str) -> list[Suggestion]:
    """Check gender agreement between definite singular nouns and `הזה`/`הזאת`."""
    proposals: list[Suggestion] = []
    idx = 0
    while idx < len(text):
        match = _TWO_WORD_HEB_RE.search(text, idx)
        if match is None:
            break
        raw_noun = strip_nikud(match.group(1))
        # Allow a single proclitic ב/ל/מ/כ/ו before the definite noun (בבעיה הזאת -> already without ה, skip; והבעיה הזה -> הבעיה)
        def_noun = raw_noun[1:] if raw_noun.startswith("ו") else raw_noun
        dem = strip_nikud(match.group(2))
        if def_noun in DEF_FEM_SINGULAR_NOUNS and dem == "הזה":
            proposals.append(
                _proposal(
                    text,
                    match.start(2),
                    match.end(2),
                    "הזאת",
                    f"התאמת מין: '{def_noun}' ממין נקבה",
                    kind="grammar",
                    alternatives=("הזו",),
                )
            )
        elif def_noun in DEF_MASC_SINGULAR_NOUNS and dem in ("הזאת", "הזו"):
            proposals.append(
                _proposal(
                    text,
                    match.start(2),
                    match.end(2),
                    "הזה",
                    f"התאמת מין: '{def_noun}' ממין זכר",
                    kind="grammar",
                )
            )
        idx = match.start(2)
    return proposals


# ---------------------------------------------------------------------------
# 6. Accidental word / article-echo duplication (כפילות מילים בשוגג)
# ---------------------------------------------------------------------------

IDIOMATIC_REDUPLICATIONS: frozenset[str] = frozenset(
    {
        "לאט",
        "יום",
        "שנה",
        "אחד",
        "אחת",
        "פעם",
        "מעט",
        "רגע",
        "שלב",
        "צעד",
        "דור",
        "איש",
        "מילה",
        "בוקר",
        "ערב",
        "לילה",
        "שעה",
        "דבר",
        "פרט",
        "סוף",
        "כלל",
        "ממש",
        "ככה",
        "די",
        "טוב",
        "יפה",
        "מהר",
        "גבוה",
        "נמוך",
        "רחוק",
        "קרוב",
        "לא",
        "כן",
        "קצת",
        "הרבה",
        "שוב",
        "מאוד",
    }
)

_DUP_WORD_RE = re.compile(r"(?<![א-ת])([א-ת]{2,12}) +\1(?![א-ת])")
_ECHO_ARTICLE_RE = re.compile(r"(?<![א-ת])([בלמכ])([א-ת]{2,10}) +ה\2(?![א-ת])")


def accidental_duplication(text: str) -> list[Suggestion]:
    """Flag accidental adjacent repeated words (`על על`) and article echoes (`בדף הדף`)."""
    proposals: list[Suggestion] = []
    for match in _DUP_WORD_RE.finditer(text):
        word = strip_nikud(match.group(1))
        if word in IDIOMATIC_REDUPLICATIONS:
            continue
        proposals.append(
            _proposal(
                text,
                match.start(),
                match.end(),
                match.group(1),
                "כפילות מילה ברצף",
                kind="grammar",
            )
        )

    for match in _ECHO_ARTICLE_RE.finditer(text):
        stem = strip_nikud(match.group(2))
        if stem in IDIOMATIC_REDUPLICATIONS or stem in ("בית", "יום", "שנת", "כל"):
            continue
        first_word = match.group(1) + match.group(2)
        proposals.append(
            _proposal(
                text,
                match.start(),
                match.end(),
                first_word,
                "כפילות מילה ברצף",
                kind="grammar",
            )
        )
    return proposals


RULES = (
    space_before_comma,
    space_after_comma,
    space_before_end_punctuation,
    double_space,
    quote_and_bracket_spacing,
    first_person_future_prefix,
    construct_definite_article,
    numeral_gender_agreement,
    demonstrative_agreement,
    accidental_duplication,
)


class GrammarModule(SuggestionModule):
    """High-precision offline Hebrew punctuation and morphosyntactic checker."""

    id = KIND_GRAMMAR
    name = "דקדוק וניסוח"
    kind = KIND_GRAMMAR
    description = (
        "בדיקת דקדוק ופיסוק עברית לא-מקוונת (אותיות אית״ן, סמיכות, שם המספר, "
        "כינויי רמז, כפילויות ורווחי פיסוק)"
    )

    def check(self, text: str) -> list[Suggestion]:
        proposals: list[Suggestion] = []
        for rule in RULES:
            proposals.extend(rule(text))
        proposals.sort(key=lambda item: (item.start, item.end))
        return proposals
