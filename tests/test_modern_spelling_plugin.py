"""Unit tests for the modern supplement; no large upstream files in source."""
from __future__ import annotations
import hashlib
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class ModernSupplementTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'data').mkdir()
        shutil.copy2(ROOT / 'optional_plugins/modern_hebrew/modern_spelling.py', self.root / 'modern_spelling.py')
        self.data = 'צוהריים\nאונייה\nאמיתי\n'.encode('utf-8')
        (self.root / 'data/modern-words.txt').write_bytes(self.data)
        self.calls = []
        calls = self.calls

        class Base:
            def __init__(self, options=None):
                self.options = options
            def _lookup(self, words):
                calls.append(words)
                return {w: (False, ('שלום',)) for w in words}

        package = types.ModuleType('_modern_test')
        package.__path__ = [str(self.root)]
        base = types.ModuleType('_modern_test.hspell_base')
        base.HunspellSpelling = Base
        self.patcher = patch.dict(sys.modules, {'_modern_test': package, '_modern_test.hspell_base': base})
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        spec = importlib.util.spec_from_file_location('_modern_test.modern_spelling', self.root / 'modern_spelling.py')
        self.code = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.code)
        self.code.MODERN_SIZE = len(self.data)
        self.code.MODERN_SHA256 = hashlib.sha256(self.data).hexdigest()
        self.code.MODERN_COUNT = 3

    def test_exact_modern_forms_suppress_false_flags_and_never_invent_candidates(self):
        module = self.code.ModernHebrewSpelling()
        result = module._lookup(['צוהריים', 'שלומ', 'אונייה'])
        self.assertEqual(result['צוהריים'], (True, ()))
        self.assertEqual(result['אונייה'], (True, ()))
        self.assertEqual(result['שלומ'], (False, ('שלום',)))
        self.assertEqual(self.calls, [['שלומ']])

    def test_no_arbitrary_prefix_stripping(self):
        module = self.code.ModernHebrewSpelling()
        self.assertEqual(module._lookup(['באונייה'])['באונייה'], (False, ('שלום',)))
        self.assertEqual(self.calls, [['באונייה']])

    def test_base_failure_propagates_without_partial_success(self):
        module = self.code.ModernHebrewSpelling()
        with patch.object(self.code.HunspellSpelling, '_lookup', side_effect=RuntimeError('timeout')):
            with self.assertRaisesRegex(RuntimeError, 'timeout'):
                module._lookup(['אונייה', 'שלומ'])

    def test_corruption_and_missing_data_fail_closed(self):
        for contents in (b'changed', b''):
            (self.root / 'data/modern-words.txt').write_bytes(contents)
            with self.assertRaisesRegex(OSError, 'integrity'):
                self.code.ModernHebrewSpelling()
        (self.root / 'data/modern-words.txt').unlink()
        with self.assertRaises(OSError):
            self.code.ModernHebrewSpelling()

    def test_invalid_data_rejected_even_with_matching_digest(self):
        for contents in ('שלום\nhello\n', 'שלום\nשלום\n'):
            raw = contents.encode('utf-8')
            (self.root / 'data/modern-words.txt').write_bytes(raw)
            self.code.MODERN_SIZE = len(raw)
            self.code.MODERN_SHA256 = hashlib.sha256(raw).hexdigest()
            self.code.MODERN_COUNT = 2
            with self.assertRaises(OSError):
                self.code.ModernHebrewSpelling()

    def test_options_still_pass_to_baseline(self):
        module = self.code.ModernHebrewSpelling({'dictionary': 'user-selected.dic'})
        self.assertEqual(module.options['dictionary'], 'user-selected.dic')

    def test_windows_ci_checks_real_frozen_modern_plugin_and_keeps_baseline(self):
        workflow = (ROOT / '.github/workflows/windows.yml').read_text()
        self.assertIn('--modern --zip build/hebrew-spelling/modern-hebrew-spelling-win64.zip --packaged-app', workflow)
        self.assertIn('Hebrew-spelling-plugin-Windows', workflow)
        self.assertIn('Modern-Hebrew-spelling-Windows', workflow)


if __name__ == '__main__':
    unittest.main()
