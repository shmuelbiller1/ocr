"""Optional offline adapter; no network, automatic rewriting or native DLL loading.

The worker runs in a killable subprocess. A generated bundle manifest pins the
locally built executable and the unmodified dictionary pair. The source-only
folder is intentionally unavailable until the reproducible builder is run.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import unicodedata

from hebrew_workbench.plugins.paths import application_directory
from hebrew_workbench.suggestions.base import Suggestion, SuggestionModule

TOKENS = re.compile(r"[\w\u0591-\u05c7]+(?:['\"׳״][\w\u0591-\u05c7]+)*", re.UNICODE)
MAX_WORDS = 2048
TIMEOUT = 8


def normalized(word: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', word)
                   if unicodedata.category(c) != 'Mn')


def hebrew(word: str) -> bool:
    return bool(word) and all('א' <= c <= 'ת' for c in word)


def native_path(path: Path) -> str:
    value = str(path.resolve())
    if os.name == 'nt':
        return '\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value
    return value


class HunspellSpelling(SuggestionModule):
    """Suggest only; Hspell 1.4 is not a complete modern-school vocabulary."""
    id = 'spelling'
    kind = 'spelling'
    name = 'Hunspell / Hspell 1.4 — איות'

    def __init__(self, options=None):
        self.root = Path(__file__).resolve().parent
        self._personal = set()
        self._cache = {}
        self._reason = ''
        self.configure(options or {})

    def configure(self, options):
        # Validate everything before committing: rejected changes preserve state.
        dictionary = Path(options.get('dictionary') or self.root / 'data/he_IL.dic').resolve()
        personal = Path(options.get('personal_dictionary') or
                        application_directory() / 'spelling/hunspell-hebrew-personal.txt').resolve()
        worker = self.root / ('hebrew-spelling-worker.exe' if os.name == 'nt'
                              else 'hebrew-spelling-worker')
        try:
            manifest = json.loads((self.root / 'BUNDLE.json').read_text(encoding='utf-8'))
            if manifest.get('protocol') != 1:
                raise ValueError('Unsupported spelling protocol')
            pins = manifest['sha256']
            if not isinstance(pins, dict) or set(pins) != {worker.name, 'data/he_IL.aff', 'data/he_IL.dic'}:
                raise ValueError('Invalid spelling bundle manifest')
            for name, digest in pins.items():
                if not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest):
                    raise ValueError('Invalid spelling digest')
                if hashlib.sha256((self.root / name).read_bytes()).hexdigest() != digest:
                    raise ValueError(f'Bundled spelling file failed verification: {name}')
            aff = dictionary.with_suffix('.aff')
            if any(c in str(dictionary) + str(personal) for c in '\t\r\n'):
                raise ValueError('Dictionary/personal paths cannot contain control characters')
            if not dictionary.is_file() or not aff.is_file() or not worker.is_file():
                raise ValueError('The worker and matching .dic/.aff files are required.')
            if dictionary.stat().st_size > 32 * 1024 * 1024 or aff.stat().st_size > 1024 * 1024:
                raise ValueError('Dictionary pair exceeds size limits')
            if not re.search(r'^SET\s+UTF-8\s*$', aff.read_text(encoding='utf-8'), re.M):
                raise ValueError('Only UTF-8 Hunspell .dic/.aff pairs are supported.')
            with dictionary.open(encoding='utf-8') as handle:
                count = int(handle.readline(32).strip())
                if not 1 <= count <= 2000000:
                    raise ValueError('Invalid Hunspell word count')
            if personal.exists() and personal.stat().st_size > 1024 * 1024:
                raise ValueError('Personal word list exceeds 1 MiB')
            kept = ({normalized(w.strip()) for w in personal.read_text(encoding='utf-8').splitlines()
                     if w.strip()} if personal.exists() else set())
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise OSError(str(exc)) from exc
        self._cache = {}
        self._reason = ''
        self._dictionary, self._aff, self._worker = dictionary, aff, worker
        self._personal_path, self._personal = personal, kept
        self._persisted = set(kept)
        self._count = count

    def set_dictionary(self, path):
        self.configure({'dictionary': str(path), 'personal_dictionary': str(self._personal_path)})

    @property
    def dictionary_path(self):
        return self._dictionary

    @property
    def word_count(self):
        if not self.available():
            return 0
        return self._count

    def available(self):
        return not self._reason

    def unavailable_reason(self):
        return self._reason

    def keep_word(self, word):
        key = normalized(word)
        if not hebrew(key) or len(key) > 64:
            return False
        self._personal.add(key)
        if key in self._persisted:
            return True
        try:
            self._personal_path.parent.mkdir(parents=True, exist_ok=True)
            with self._personal_path.open('a+b') as handle:
                handle.seek(0, 2)
                if handle.tell():
                    handle.seek(-1, 2)
                    newline = handle.read(1) not in (b'\n', b'\r')
                    handle.seek(0, 2)
                    if newline:
                        handle.write(b'\n')
                handle.write((key + '\n').encode('utf-8'))
        except OSError:
            return False
        self._persisted.add(key)
        return True

    def _lookup(self, words):
        request = '\n'.join([native_path(self._aff), native_path(self._dictionary), *words]) + '\n'
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        try:
            result = subprocess.run([str(self._worker)], input=request, capture_output=True,
                                    text=True, encoding='utf-8', timeout=TIMEOUT,
                                    creationflags=flags, cwd=self.root, shell=False)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('Spelling exceeded 8 seconds; check a shorter document.') from exc
        lines = result.stdout.splitlines()
        if (result.returncode or not lines or lines[0] != 'HUNSPELL-HEBREW/1' or
                len(lines) != len(words) + 1):
            raise RuntimeError('Spelling worker failed or returned incomplete output.')
        parsed = {}
        for word, line in zip(words, lines[1:]):
            fields = line.split('\t')
            if (fields[0] not in ('0', '1') or len(fields) > 4 or
                    any(not x for x in fields[1:]) or (fields[0] == '1' and len(fields) != 1)):
                raise RuntimeError('Invalid spelling worker response.')
            parsed[word] = (fields[0] == '1', tuple(fields[1:]))
        return parsed

    def check(self, text):
        if not self.available():
            return []
        tokens = []
        for match in TOKENS.finditer(text):
            raw = match.group()
            key = normalized(raw)
            # Conservatively ignore acronyms, mixed scripts, digits and very
            # short words. Niqqud normalization never changes source offsets.
            if not hebrew(key) or not 3 <= len(key) <= 64 or key in self._personal:
                continue
            if text[match.end():match.end()+1] in ("'", '׳') and len(key) <= 4:
                continue
            tokens.append((match, key))
        distinct = set(key for _, key in tokens)
        words = list(dict.fromkeys(key for _, key in tokens if key not in self._cache))
        if len(distinct) > MAX_WORDS:
            raise RuntimeError('Too many distinct words; check a shorter document.')
        if words:
            values = self._lookup(words)
            if len(self._cache) + len(values) > 4096:
                self._cache = {key: value for key, value in self._cache.items() if key in distinct}
            self._cache.update(values)
        proposals = []
        for match, key in tokens:
            valid, choices = self._cache[key]
            if valid:
                continue
            proposals.append(Suggestion(
                module=self.id, original=match.group(),
                replacement=choices[0] if choices else match.group(),
                alternatives=choices[1:], start=match.start(), end=match.end(), kind='word',
                message='הצעת Hspell 1.4 (כללי כתיב ישנים); יש לבדוק לפני קבלה'))
        return proposals
