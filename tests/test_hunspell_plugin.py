"""Adapter failure/offset tests; real native/frozen checks run separately in CI."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class HunspellPluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'plugin'
        self.root.mkdir()
        shutil.copy2(ROOT / 'optional_plugins/hunspell_hebrew/spelling.py', self.root / 'spelling.py')
        (self.root / 'data').mkdir()
        (self.root / 'data/he_IL.aff').write_text('SET UTF-8\n', encoding='utf-8')
        (self.root / 'data/he_IL.dic').write_text('2\nשלום\nתלמידים\n', encoding='utf-8')
        self.worker = 'hebrew-spelling-worker.exe' if os.name == 'nt' else 'hebrew-spelling-worker'
        (self.root / self.worker).write_bytes(b'fixture; never executed by unit tests')
        pins = {n: hashlib.sha256((self.root / n).read_bytes()).hexdigest()
                for n in (self.worker, 'data/he_IL.aff', 'data/he_IL.dic')}
        self.manifest = {'protocol': 1, 'sha256': pins}
        (self.root / 'BUNDLE.json').write_text(json.dumps(self.manifest))
        spec = importlib.util.spec_from_file_location('spelling_test_fixture', self.root / 'spelling.py')
        self.code = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.code)
        self.personal = Path(self.temp.name) / 'user/personal.txt'
        self.plugin = self.code.HunspellSpelling({'personal_dictionary': str(self.personal)})

    def response(self, lines, code=0):
        return subprocess.CompletedProcess([], code, 'HUNSPELL-HEBREW/1\n'+lines, '')

    def test_source_only_folder_is_unavailable_with_actionable_error(self):
        (self.root / 'BUNDLE.json').unlink()
        with self.assertRaises(OSError):
            self.code.HunspellSpelling()

    def test_real_hunspell_format_count_is_not_a_custom_slash_word_list(self):
        self.assertEqual(self.plugin.word_count, 2)
        self.assertTrue(self.plugin.available())

    def test_hebrew_offsets_niqqud_mixed_scripts_and_acronyms(self):
        text = 'English 123abc אבגEnglish רש״י וכו׳ שָׁלוֹם שלומ'
        with patch.object(self.code.subprocess, 'run', return_value=self.response('1\n0\tשלום\n')) as run:
            proposals = self.plugin.check(text)
        self.assertEqual(len(proposals), 1)
        p = proposals[0]
        self.assertEqual(text[p.start:p.end], 'שלומ')
        self.assertEqual(p.replacement, 'שלום')
        request = run.call_args.kwargs['input'].splitlines()
        self.assertEqual(request[2:], ['שלום', 'שלומ'])
        self.assertFalse(run.call_args.kwargs['shell'])
        self.assertEqual(run.call_args.kwargs['timeout'], 8)

    def test_hebrew_punctuation_splits_words_without_losing_offsets(self):
        text = 'שלומ־עולם שלומ׃ שלומ׀'
        with patch.object(self.code.subprocess, 'run',
                          return_value=self.response('0\tשלום\n1\n')):
            proposals = self.plugin.check(text)
        self.assertEqual(len(proposals), 3)
        self.assertTrue(all(text[p.start:p.end] == 'שלומ' for p in proposals))

    def test_unknown_without_candidate_does_not_invent_replacement(self):
        with patch.object(self.code.subprocess, 'run', return_value=self.response('0\n')):
            p = self.plugin.check('אבגד')[0]
        self.assertEqual(p.replacement, p.original)

    def test_at_most_three_native_candidates(self):
        with patch.object(self.code.subprocess, 'run', return_value=self.response('0\tשלום\tשלמו\tלשמו\n')):
            p = self.plugin.check('שלומ')[0]
        self.assertEqual((p.replacement, *p.alternatives), ('שלום', 'שלמו', 'לשמו'))

    def test_timeout_is_reported_not_swallowed_or_turned_into_correct_words(self):
        with patch.object(self.code.subprocess, 'run', side_effect=subprocess.TimeoutExpired('worker', 8)):
            with self.assertRaisesRegex(RuntimeError, '8 seconds'):
                self.plugin.check('אבגד')

    def test_missing_worker_process_error_is_not_fake_output(self):
        with patch.object(self.code.subprocess, 'run', side_effect=OSError('missing worker')):
            with self.assertRaises(OSError):
                self.plugin.check('אבגד')

    def test_malformed_partial_or_failed_worker_is_rejected(self):
        for result in [self.response(''), self.response('2\n'), self.response('1\textra\n'),
                       self.response('0\t\n'), self.response('0\n', code=2)]:
            with self.subTest(result=result), patch.object(self.code.subprocess, 'run', return_value=result):
                with self.assertRaises(RuntimeError):
                    self.plugin.check('אבגד')

    def test_tampered_worker_or_dictionary_fails_closed(self):
        for name in (self.worker, 'data/he_IL.dic'):
            path = self.root / name
            before = path.read_bytes()
            path.write_bytes(b'tampered')
            with self.assertRaises(OSError):
                self.code.HunspellSpelling()
            path.write_bytes(before)

    def test_manifest_cannot_omit_a_required_hash(self):
        del self.manifest['sha256'][self.worker]
        (self.root / 'BUNDLE.json').write_text(json.dumps(self.manifest))
        with self.assertRaises(OSError):
            self.code.HunspellSpelling()

    def test_personal_file_cannot_be_the_dictionary_or_inside_plugin(self):
        for path in (self.plugin.dictionary_path, self.root / 'personal.txt'):
            with self.subTest(path=path), self.assertRaises(OSError):
                self.plugin.configure({'personal_dictionary': str(path)})

    def test_bad_dictionary_setting_preserves_previous_configuration(self):
        old = self.plugin.dictionary_path
        with self.assertRaises(OSError):
            self.plugin.set_dictionary(self.root / 'missing.dic')
        self.assertEqual(self.plugin.dictionary_path, old)
        self.assertTrue(self.plugin.available())

    def test_keep_word_persists_outside_plugin_without_modifying_dictionary(self):
        before = self.plugin.dictionary_path.read_bytes()
        self.assertTrue(self.plugin.keep_word('מונחייחודי'))
        self.assertTrue(self.plugin.keep_word('מונחייחודי'))
        self.assertEqual(self.personal.read_text(encoding='utf-8').splitlines(), ['מונחייחודי'])
        loaded = self.code.HunspellSpelling({'personal_dictionary': str(self.personal)})
        with patch.object(self.code.subprocess, 'run') as run:
            self.assertEqual(loaded.check('מונחייחודי'), [])
            run.assert_not_called()
        self.assertEqual(self.plugin.dictionary_path.read_bytes(), before)

    def test_keep_word_write_failure_is_session_only_and_retryable(self):
        with patch.object(Path, 'open', side_effect=PermissionError('readonly')):
            self.assertFalse(self.plugin.keep_word('מונחייחודי'))
        self.assertEqual(self.plugin.check('מונחייחודי'), [])
        self.assertTrue(self.plugin.keep_word('מונחייחודי'))

    def test_personal_list_without_final_newline_is_not_corrupted(self):
        self.personal.parent.mkdir()
        self.personal.write_text('שלום', encoding='utf-8')
        self.assertTrue(self.plugin.keep_word('מונחייחודי'))
        self.assertEqual(self.personal.read_text(encoding='utf-8'), 'שלום\nמונחייחודי\n')

    def test_repeated_words_are_checked_once_and_cached(self):
        with patch.object(self.code.subprocess, 'run', return_value=self.response('0\n')) as run:
            self.assertEqual(len(self.plugin.check('אבגד אבגד')), 2)
            self.plugin.check('אבגד')
            self.assertEqual(run.call_count, 1)

    def test_distinct_word_limit_is_explicit_not_silent_partial_checking(self):
        words = ['אב'+chr(0x05d0+i//484)+chr(0x05d0+(i//22)%22)+chr(0x05d0+i%22)
                 for i in range(2049)]
        with patch.object(self.code.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'shorter'):
                self.plugin.check(' '.join(words))
            run.assert_not_called()

    def test_eviction_keeps_current_document_cached_words(self):
        self.plugin._cache = {str(i): (True, ()) for i in range(4095)}
        self.plugin._cache['שלום'] = (True, ())
        with patch.object(self.code.subprocess, 'run', return_value=self.response('0\n')):
            self.assertEqual(len(self.plugin.check('שלום אבגד')), 1)
        self.assertLessEqual(len(self.plugin._cache), 4096)

    def test_archive_sources_and_hashes_are_required_not_optional_downloads(self):
        from tools.build_spelling_plugin import fetch
        with self.assertRaisesRegex(ValueError, 'verification'):
            fetch('spelling.py', {'size': 1, 'sha256': '0'*64}, self.root)

    def test_optional_frozen_check_is_a_mandatory_windows_step(self):
        workflow = (ROOT / '.github/workflows/windows.yml').read_text()
        self.assertIn('--hidden-import unicodedata', workflow)
        self.assertIn('--packaged-app dist/HebrewNotesWorkbench/HebrewNotesWorkbench.exe', workflow)
        self.assertIn('Hebrew-spelling-plugin-Windows', workflow)

class AdditionalSpellingGuards(unittest.TestCase):
    def test_source_extraction_rejects_traversal_and_links(self):
        import io
        import tarfile
        from tools.build_spelling_plugin import extract
        for name, is_link in [('../outside', False), ('root/link', True)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                archive = Path(temp) / 'source.tar'
                with tarfile.open(archive, 'w') as tar:
                    item = tarfile.TarInfo(name)
                    if is_link:
                        item.type = tarfile.SYMTYPE
                        item.linkname = '/outside'
                        tar.addfile(item)
                    else:
                        item.size = 1
                        tar.addfile(item, io.BytesIO(b'x'))
                with self.assertRaises(ValueError):
                    extract(archive, Path(temp) / 'out')

    @unittest.skipIf(os.name == 'nt', 'Windows does not use executable permission bits')
    def test_zip_installer_restores_native_execute_bit_but_not_setuid(self):
        import zipfile
        from hebrew_workbench.plugins import PluginInstaller
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'plugin.zip'
            with zipfile.ZipFile(archive, 'w') as zip_file:
                zip_file.writestr('plugin.json', json.dumps({
                    'id': 'example-native', 'name': 'Native fixture', 'version': '1',
                    'kind': 'spelling', 'entry': 'spelling:Fixture'}))
                native = zipfile.ZipInfo('worker')
                native.external_attr = (0o104755 << 16)
                zip_file.writestr(native, b'not executed')
            root = Path(temp) / 'plugins'
            PluginInstaller(root).install_zip(archive)
            self.assertEqual((root / 'example-native/worker').stat().st_mode & 0o7777, 0o755)


    def test_unpacked_corresponding_source_build_does_not_need_git_metadata(self):
        from tools.build_spelling_plugin import source_files
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'app.py').write_text('pass')
            (root / 'private.txt').write_text('not tracked; must never be captured')
            (root / 'SOURCE-FILES.json').write_text('["app.py"]')
            self.assertEqual(source_files(root), ['app.py'])
            (root / 'SOURCE-FILES.json').write_text('["../outside"]')
            with self.assertRaises(ValueError):
                source_files(root)


if __name__ == '__main__':
    unittest.main()
