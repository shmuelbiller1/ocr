"""Bundled CC0-1.0 Hebrew lexicon, morphological prefix validator, and
handwritten-OCR-aware candidate ranker.

Uses ``data/hebrew_words_cc0.txt.gz`` (``roni5604/hebrew-words-db``, CC0-1.0,
pinned by uncompressed SHA-256) plus a small public-domain supplement of
rabbinic/Aramaic study terms, ketiv-chaser variants, and common Hebrew names.
"""

from __future__ import annotations

import gzip
import hashlib
import os
import re
from pathlib import Path

__all__ = [
    "BUNDLED_RAW_SIZE",
    "BUNDLED_RAW_SHA256",
    "BUNDLED_WORD_COUNT",
    "HebrewLexicon",
    "bundled_lexicon",
    "personal_dictionary_path",
    "strip_nikud",
]

BUNDLED_RAW_SIZE = 2_670_751
BUNDLED_RAW_SHA256 = (
    "30a01c45da1381637da708d74af81c0f1b4ad225d9a3a85252683217fe107be3"
)
BUNDLED_WORD_COUNT = 196_227

# Strip only cantillation and vowel points; preserve maqaf (\u05be), paseq (\u05c0),
# sof pasuq (\u05c3), and nun hafukha (\u05c6) so hyphenated words never fuse.
NIKUD_RE = re.compile(r"[\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7]")

# Contiguous Hebrew tokens including internal/trailing geresh/gershayim/quotes.
HEBREW_TOKEN_RE = re.compile(
    r"[א-ת][\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7א-ת'׳\"״]*"
)

HEBREW_ALPHABET = "אבגדהוזחטיכךלמםנןסעפףצץקרשת"

FINAL_OF_MEDIAL = {"כ": "ך", "מ": "ם", "נ": "ן", "פ": "ף", "צ": "ץ"}
MEDIAL_OF_FINAL = {v: k for k, v in FINAL_OF_MEDIAL.items()}

# Productive modern Hebrew proclitic prefix combinations (BKL"M + Vav + Shin/Kaf).
VALID_PREFIXES: tuple[str, ...] = (
    "ב",
    "ה",
    "ו",
    "כ",
    "ל",
    "מ",
    "ש",
    "וב",
    "וה",
    "וכ",
    "ול",
    "ומ",
    "וש",
    "שב",
    "שה",
    "שכ",
    "של",
    "שמ",
    "כש",
    "בה",
    "כה",
    "לה",
    "מה",
    "ובה",
    "וכה",
    "ולה",
    "ומה",
    "ושה",
    "וכש",
    "שבה",
    "שכה",
    "שלה",
    "שמה",
    "כשה",
    "וכשה",
    "מב",
    "מל",
    "מש",
)

# Handwritten & optical Hebrew character confusions, weighted by empirical frequency.
PRIMARY_OCR_CONFUSIONS: dict[str, tuple[tuple[str, float], ...]] = {
    "ד": (("ר", 0.32), ("ך", 0.36), ("ב", 0.40), ("ז", 0.45)),
    "ר": (("ד", 0.32), ("ך", 0.36), ("ו", 0.44)),
    "ו": (("י", 0.30), ("ז", 0.36), ("ן", 0.36), ("ר", 0.44), ("נ", 0.46)),
    "י": (("ו", 0.30), ("ז", 0.38), ("ן", 0.40), ("נ", 0.48)),
    "ז": (("ו", 0.36), ("י", 0.38), ("צ", 0.42), ("ד", 0.45), ("ג", 0.48)),
    "ב": (("כ", 0.32), ("ד", 0.40), ("ג", 0.40), ("פ", 0.46), ("נ", 0.48)),
    "כ": (("ב", 0.32), ("ל", 0.44), ("פ", 0.46), ("ק", 0.48)),
    "ה": (("ח", 0.34), ("ת", 0.36), ("ק", 0.48)),
    "ח": (("ה", 0.34), ("ת", 0.34), ("מ", 0.46)),
    "ת": (("ח", 0.34), ("ה", 0.36), ("מ", 0.45)),
    "ס": (("ם", 0.28), ("מ", 0.42), ("ט", 0.44), ("ע", 0.48)),
    "ם": (("ס", 0.22), ("מ", 0.24), ("ט", 0.46)),
    "מ": (("ם", 0.24), ("ס", 0.42), ("ט", 0.42), ("ת", 0.45), ("ח", 0.46)),
    "ט": (("מ", 0.42), ("ס", 0.44), ("ש", 0.48)),
    "נ": (("ג", 0.38), ("ו", 0.44), ("י", 0.46), ("ן", 0.24), ("ב", 0.48)),
    "ג": (("נ", 0.38), ("ב", 0.40), ("ק", 0.42), ("ז", 0.46)),
    "ן": (("ו", 0.28), ("י", 0.32), ("נ", 0.24), ("ך", 0.42)),
    "ך": (("ד", 0.32), ("ר", 0.32), ("כ", 0.24), ("ן", 0.42)),
    "ף": (("פ", 0.24), ("ך", 0.45)),
    "פ": (("ף", 0.24), ("ב", 0.46), ("כ", 0.46)),
    "ץ": (("צ", 0.24), ("ע", 0.46)),
    "צ": (("ע", 0.38), ("ץ", 0.24), ("ז", 0.42)),
    "ע": (("צ", 0.38), ("ש", 0.48), ("א", 0.48)),
    "ל": (("כ", 0.44), ("ק", 0.48)),
    "ק": (("ג", 0.42), ("ה", 0.46), ("כ", 0.48), ("ר", 0.48)),
    "ש": (("ט", 0.48), ("ע", 0.48)),
    "א": (("ע", 0.48), ("צ", 0.50)),
}

# Curated public-domain supplement: common rabbinic/Aramaic study vocabulary,
# ketiv-chaser roots left when nikud is stripped, and standard Israeli names.
SUPPLEMENT_WORDS: frozenset[str] = frozenset(
    {
        # Aramaic / Beit Midrash / classroom terms
        "סברא",
        "סברה",
        "דאורייתא",
        "דרבנן",
        "גמרא",
        "משנה",
        "משניות",
        "תוספות",
        "ראשונים",
        "אחרונים",
        "סוגיא",
        "סוגיה",
        "סוגיות",
        "נפקא",
        "מינה",
        "קושיא",
        "קושיה",
        "קושיות",
        "תירוץ",
        "תירוצים",
        "פשיטא",
        "מאי",
        "תנא",
        "תנאים",
        "אמורא",
        "אמוראים",
        "ברייתא",
        "מדרש",
        "הלכה",
        "הלכות",
        "אגדה",
        "פסק",
        "פוסקים",
        "שולחן",
        "ערוך",
        "רמבם",
        "רמבן",
        "רשבם",
        "רשבא",
        "ריטבא",
        "מאירי",
        "מהרל",
        "חזון",
        "חפץ",
        "לקוטי",
        "ליקוטי",
        "אדמור",
        "אלקים",
        "הקבה",
        "כתיב",
        "קאמר",
        "מתני",
        "נפקמ",
        "לכאורה",
        "דלמא",
        "אלמא",
        "איפכא",
        "מסתברא",
        "שפיר",
        "הלכתא",
        "בעלמא",
        # Ketiv chaser / unpointed vocalized forms
        "לעתים",
        "אמתי",
        "תכנית",
        "תכניות",
        "תכנה",
        "יזמה",
        "צהריים",
        "צהרים",
        "אמנם",
        "קרבן",
        "קרבנות",
        "שמים",
        "מים",
        "חיים",
        "עינים",
        "עיניים",
        "ידים",
        "ידיים",
        "רגלים",
        "רגליים",
        "שנים",
        "שניים",
        "שתיים",
        "אניה",
        "אניות",
        "בררה",
        "עברה",
        "פרות",
        # Common names & places
        "ישראל",
        "ירושלים",
        "תל",
        "אביב",
        "חיפה",
        "אברהם",
        "יצחק",
        "יעקב",
        "משה",
        "אהרן",
        "יוסף",
        "דוד",
        "שלמה",
        "שמואל",
        "דניאל",
        "מיכאל",
        "גבריאל",
        "רפאל",
        "אורי",
        "איתי",
        "יואב",
        "נועם",
        "עידו",
        "עומר",
        "אלון",
        "שרה",
        "רבקה",
        "רחל",
        "לאה",
        "מרים",
        "חנה",
        "אסתר",
        "רות",
        "נעמי",
        "תמר",
        "נועה",
        "מאיה",
        "שירה",
        "יעל",
        "מיכל",
        "דנה",
        "טליה",
        "אביגיל",
    }
)

# High-frequency short words allowed on one side of a run-on word split.
COMMON_SHORT_SPLIT_WORDS: frozenset[str] = frozenset(
    {
        "את",
        "של",
        "על",
        "אל",
        "עם",
        "גם",
        "לא",
        "כל",
        "זה",
        "זו",
        "כי",
        "אם",
        "או",
        "עד",
        "רק",
        "יש",
        "אין",
        "בית",
        "יום",
        "עוד",
        "כמו",
        "לפי",
        "אבל",
        "הוא",
        "היא",
        "הם",
        "אני",
        "אנו",
    }
)


def strip_nikud(text: str) -> str:
    return NIKUD_RE.sub("", text)


def personal_dictionary_path() -> Path:
    """User-writable personal dictionary path, isolated from read-only app files."""
    home = os.environ.get("HEBREW_WORKBENCH_HOME")
    if home:
        return Path(home) / "spelling" / "personal_dictionary.txt"
    if os.name == "nt":
        base = Path(
            os.environ.get("LOCALAPPDATA")
            or (Path.home() / "AppData" / "Local")
        )
        return base / "HebrewNotesWorkbench" / "spelling" / "personal_dictionary.txt"
    base = Path(
        os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    )
    return base / "hebrew-notes-workbench" / "spelling" / "personal_dictionary.txt"


def _bundled_gz_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "hebrew_words_cc0.txt.gz"


class HebrewLexicon:
    """Fast in-memory Hebrew lexicon with prefix morphology and OCR-aware ranking."""

    def __init__(self, words: frozenset[str]) -> None:
        self.words: frozenset[str] = words | SUPPLEMENT_WORDS

    @classmethod
    def load_bundled(cls, gz_path: Path | None = None) -> "HebrewLexicon":
        path = gz_path or _bundled_gz_path()
        raw = gzip.decompress(path.read_bytes())
        if (
            len(raw) != BUNDLED_RAW_SIZE
            or hashlib.sha256(raw).hexdigest() != BUNDLED_RAW_SHA256
        ):
            raise ValueError(
                "Bundled Hebrew lexicon failed SHA-256 integrity check"
            )
        lines = raw.decode("utf-8").splitlines()
        if len(lines) != BUNDLED_WORD_COUNT:
            raise ValueError("Bundled Hebrew lexicon has unexpected word count")
        return cls(frozenset(lines))

    def is_known(
        self,
        raw_token: str,
        extra_words: set[str] | frozenset[str] = frozenset(),
    ) -> bool:
        cleaned = strip_nikud(raw_token)
        if not cleaned:
            return True

        # Acronyms (" / ״ inside) and geresh abbreviations (' / ׳ at end)
        if '"' in cleaned or "״" in cleaned:
            parts = re.split(r'["״]', cleaned)
            if len(parts) >= 2 and all(p and all("א" <= c <= "ת" for c in p) for p in parts):
                return True
        if cleaned.endswith(("'", "׳")) and len(cleaned) >= 2:
            stem = cleaned.rstrip("'׳")
            if stem and all("א" <= c <= "ת" for c in stem):
                return True
        # Loanwords with consonant geresh (ג'ירפה, צ'יפס, ז'אנר)
        if "'" in cleaned or "׳" in cleaned:
            degeresh = cleaned.replace("'", "").replace("׳", "")
            if degeresh and self._is_known_pure(degeresh, extra_words):
                return True
            if len(cleaned) >= 3 and cleaned[0] in "גזצדתח" and cleaned[1] in ("'", "׳"):
                return True

        core = cleaned.rstrip('"״')
        if not core or not all("א" <= c <= "ת" for c in core):
            return True
        cleaned = core

        # Words with misplaced medial/final letter forms are NEVER valid Hebrew
        if self._has_final_form_violation(cleaned):
            return cleaned in extra_words

        if len(cleaned) < 4:
            return True

        return self._is_known_pure(cleaned, extra_words)

    def _has_final_form_violation(self, word: str) -> bool:
        if len(word) < 3:
            return False
        if any(ch in MEDIAL_OF_FINAL for ch in word[:-1]):
            return True
        if word[-1] in FINAL_OF_MEDIAL:
            # Academy-standard hard-/p/ loanwords end in medial פ (טלסקופ, מיקרוסקופ, סירופ)
            if word[-1] == "פ" and (
                word in self.words
                or any(
                    word.startswith(p)
                    and len(word) - len(p) >= 3
                    and word[len(p) :] in self.words
                    for p in VALID_PREFIXES
                )
            ):
                return False
            return True
        return False

    _PLURAL_POSSESSIVE_SUFFIXES = (
        "ותיך",
        "ותיו",
        "ותיה",
        "ותינו",
        "ותיכם",
        "ותיכן",
        "ותיהם",
        "ותיהן",
    )

    def _is_stem_known(
        self,
        stem: str,
        extra_words: set[str] | frozenset[str] = frozenset(),
    ) -> bool:
        if stem in self.words or stem in extra_words:
            return True
        for suf in self._PLURAL_POSSESSIVE_SUFFIXES:
            if stem.endswith(suf) and len(stem) >= len(suf) + 3:
                plural_base = stem[: -len(suf)] + "ות"
                if plural_base in self.words:
                    return True
        return False

    def _is_known_pure(
        self,
        word: str,
        extra_words: set[str] | frozenset[str] = frozenset(),
    ) -> bool:
        if self._is_stem_known(word, extra_words):
            return True
        for prefix in VALID_PREFIXES:
            if not word.startswith(prefix):
                continue
            stem = word[len(prefix) :]
            if len(stem) < 3:
                continue
            if self._is_stem_known(stem, extra_words):
                return True
            # Consonantal vav/yod doubling after prefix (וועד -> ועד, יישוב -> ישוב)
            if stem.startswith("וו") and len(stem) >= 4 and self._is_stem_known(stem[1:], extra_words):
                return True
            if stem.startswith("יי") and len(stem) >= 4 and self._is_stem_known(stem[1:], extra_words):
                return True
        return False

    def suggest(
        self,
        raw_token: str,
        extra_words: set[str] | frozenset[str] = frozenset(),
        document_words: set[str] | frozenset[str] = frozenset(),
        limit: int = 4,
    ) -> list[str]:
        word = strip_nikud(raw_token)
        if not word or len(word) > 32 or not all("א" <= c <= "ת" for c in word):
            return []

        scored: dict[str, float] = {}

        def _add(cand: str, cost: float) -> None:
            if not cand or cand == word:
                return
            # Validate candidate (either single word or two-word run-on split)
            if " " in cand:
                left, right = cand.split(" ", 1)
                left_ok = left in COMMON_SHORT_SPLIT_WORDS or (
                    len(left) >= 3 and left in self.words
                )
                right_ok = right in COMMON_SHORT_SPLIT_WORDS or (
                    len(right) >= 3
                    and (
                        right in self.words
                        or (right.startswith("ה") and right[1:] in self.words)
                    )
                )
                if not (left_ok and right_ok):
                    return
                if not (
                    left in COMMON_SHORT_SPLIT_WORDS
                    or right in COMMON_SHORT_SPLIT_WORDS
                    or right.startswith("ה")
                ):
                    cost += 0.22
            else:
                if self._has_final_form_violation(cand):
                    return
                if not self._is_known_pure(cand, extra_words):
                    return
                # Prefer direct dictionary words slightly over stripped-prefix forms
                if cand not in self.words and cand not in extra_words:
                    cost += 0.14
            if cand in document_words:
                cost -= 0.18
            prev = scored.get(cand)
            if prev is None or cost < prev:
                scored[cand] = cost

        # 1. Final/medial letter form normalization (e.g. שלומ -> שלום, מםפר -> מספר)
        fixed_chars = list(word)
        changed_form = False
        for i in range(len(fixed_chars) - 1):
            ch = fixed_chars[i]
            if ch in MEDIAL_OF_FINAL:
                # Try both corresponding medial AND optical lookalike (e.g. ם -> ס)
                for repl, step_cost in (
                    (MEDIAL_OF_FINAL[ch], 0.18),
                    *(PRIMARY_OCR_CONFUSIONS.get(ch, ())),
                ):
                    trial = word[:i] + repl + word[i + 1 :]
                    if trial[-1] in FINAL_OF_MEDIAL:
                        trial = trial[:-1] + FINAL_OF_MEDIAL[trial[-1]]
                    _add(trial, step_cost)
                fixed_chars[i] = MEDIAL_OF_FINAL[ch]
                changed_form = True
        if fixed_chars[-1] in FINAL_OF_MEDIAL:
            fixed_chars[-1] = FINAL_OF_MEDIAL[fixed_chars[-1]]
            changed_form = True
        if changed_form:
            _add("".join(fixed_chars), 0.14)

        # 2. Missing space run-on split (e.g. ביתהספר -> בית הספר)
        if len(word) >= 5:
            for split_at in range(2, len(word) - 1):
                left, right = word[:split_at], word[split_at:]
                if left[-1] in FINAL_OF_MEDIAL:
                    left_fixed = left[:-1] + FINAL_OF_MEDIAL[left[-1]]
                    _add(f"{left_fixed} {right}", 0.48)
                _add(f"{left} {right}", 0.42)

        # 3. Doubled/dropped vav & yod (e.g. תלמיידים -> תלמידים)
        for pair, single in (("יי", "י"), ("וו", "ו")):
            start = 0
            while True:
                idx = word.find(pair, start)
                if idx < 0:
                    break
                _add(word[:idx] + single + word[idx + 2 :], 0.28)
                start = idx + 1
        for i, ch in enumerate(word):
            if ch in ("י", "ו"):
                _add(word[:i] + ch + ch + word[i + 1 :], 0.45)

        # 4. 1-edit and 2-edit handwritten OCR confusion substitutions
        confusion_1: list[tuple[str, float, int]] = []
        keep_two_edit = len(word) <= 14
        for i, ch in enumerate(word):
            for repl, c_cost in PRIMARY_OCR_CONFUSIONS.get(ch, ()):
                cand = word[:i] + repl + word[i + 1 :]
                if len(cand) >= 2 and cand[-1] in FINAL_OF_MEDIAL:
                    cand = cand[:-1] + FINAL_OF_MEDIAL[cand[-1]]
                _add(cand, c_cost)
                if keep_two_edit:
                    confusion_1.append((cand, c_cost, i))

        # Two optical confusions in the same word (e.g. בירישלים -> בירושלים,
        # שיעיר -> שיעור, התלמירים -> התלמידים, הכתיכה -> הכתיבה)
        if len(word) <= 14:
            for cand1, cost1, pos1 in confusion_1:
                for j in range(pos1 + 1, len(cand1)):
                    ch2 = cand1[j]
                    for repl2, cost2 in PRIMARY_OCR_CONFUSIONS.get(ch2, ()):
                        cand2 = cand1[:j] + repl2 + cand1[j + 1 :]
                        if len(cand2) >= 2 and cand2[-1] in FINAL_OF_MEDIAL:
                            cand2 = cand2[:-1] + FINAL_OF_MEDIAL[cand2[-1]]
                        _add(cand2, cost1 + cost2 + 0.04)

        # 5. Standard 1-edit Damerau-Levenshtein (deletions, transpositions,
        # substitutions, insertions) when high-confidence optical matches are sparse
        if len(scored) < limit and len(word) <= 15:
            # Deletions
            for i in range(len(word)):
                cand = word[:i] + word[i + 1 :]
                if len(cand) >= 3:
                    _add(cand, 0.82)
            # Adjacent transpositions
            for i in range(len(word) - 1):
                cand = word[:i] + word[i + 1] + word[i] + word[i + 2 :]
                _add(cand, 0.76)
            # Substitutions
            for i in range(len(word)):
                for letter in HEBREW_ALPHABET:
                    if letter != word[i]:
                        _add(word[:i] + letter + word[i + 1 :], 0.88)
            # Insertions (only if still fewer than limit)
            if len(scored) < limit and len(word) <= 11:
                for i in range(len(word) + 1):
                    for letter in "יוהאמנתלרבדכסעפצקשזגחטםןףץך":
                        _add(word[:i] + letter + word[i:], 0.92)

        ranked = sorted(
            scored.items(),
            key=lambda kv: (round(kv[1], 4), abs(len(kv[0]) - len(word)), kv[0]),
        )
        return [cand for cand, _score in ranked[:limit]]


_BUNDLED_CACHE: HebrewLexicon | None = None


def bundled_lexicon() -> HebrewLexicon:
    global _BUNDLED_CACHE
    if _BUNDLED_CACHE is None:
        _BUNDLED_CACHE = HebrewLexicon.load_bundled()
    return _BUNDLED_CACHE
