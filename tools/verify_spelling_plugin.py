"""Exercise the real installed native plugin, optionally inside the frozen app.

Curated smoke fixtures, NOT independently verified school accuracy benchmarks.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hebrew_workbench.plugins import PluginInstaller, PluginRegistry


def exercise(module):
    start = time.perf_counter()
    valid = 'שלום בית בבית והילדים תלמידים ספרים שפה עברית'
    assert module.check(valid) == [], 'A common-word/morphology smoke fixture was flagged'
    text = 'English 123 שלום שָׁלוֹם שלומ תלמיידים רש״י וכו׳'
    proposals = module.check(text)
    assert {p.original for p in proposals} == {'שלומ', 'תלמיידים'}, proposals
    assert any(p.original == 'שלומ' and 'שלום' in (p.replacement, *p.alternatives) for p in proposals)
    assert any(p.original == 'תלמיידים' and 'תלמידים' in (p.replacement, *p.alternatives) for p in proposals)
    for p in proposals:
        assert text[p.start:p.end] == p.original
        assert len(p.alternatives) <= 2
    # No fake OCR/grammar/quality score. Record real word-check wall time only.
    return {'fixtures': 'developer-curated spelling smoke, not school accuracy',
            'seconds': round(time.perf_counter()-start, 4),
            'proposals': [{'original': p.original, 'replacement': p.replacement,
                           'alternatives': p.alternatives} for p in proposals]}


def verify(archive, report, packaged_app=None):
    with tempfile.TemporaryDirectory(prefix='hebrew-spell-') as folder:
        home = Path(folder) / 'עברית space'
        root = home / 'plugins'
        installer = PluginInstaller(root)
        installer.install_zip(archive)
        settings = root / 'settings.json'
        registry = PluginRegistry(root=root, settings_path=settings)
        plugin = registry.get('hunspell-hebrew')
        assert plugin and plugin.object and plugin.available(), plugin.error if plugin else 'missing'
        registry.set_active('spelling', plugin.id)
        registry.set_option(plugin.id, 'personal_dictionary', str(home / 'spelling/personal.txt'))
        plugin = registry.get('hunspell-hebrew')
        module = plugin.object
        result = exercise(module)
        before = hashlib.sha256(module.dictionary_path.read_bytes()).hexdigest()
        assert module.keep_word('מונחבדיקהייחודי')
        assert module.check('מונחבדיקהייחודי') == []
        registry.load()
        assert registry.get(plugin.id).object.check('מונחבדיקהייחודי') == []
        assert hashlib.sha256(module.dictionary_path.read_bytes()).hexdigest() == before
        if packaged_app:
            output = home / 'packaged-selftest.json'
            env = dict(os.environ, HEBREW_WORKBENCH_HOME=str(home),
                       HEBREW_WORKBENCH_TEST_SPELLING_PLUGIN='1')
            run = subprocess.run([str(packaged_app.resolve()), '--selftest', '--selftest-report', str(output)],
                                 env=env, cwd=home, capture_output=True, timeout=90)
            payload = json.loads(output.read_text(encoding='utf-8'))
            assert run.returncode == 0 and payload['ok'], payload
            assert any(c['name']=='optional-hebrew-spelling' and c['ok'] for c in payload['results'])
            result['packaged_app'] = payload
        installer.remove('hunspell-hebrew')
        assert (home / 'spelling/personal.txt').exists()
        installer.install_zip(archive)
        registry.load()
        assert registry.get('hunspell-hebrew').object.check('מונחבדיקהייחודי') == []
        result.update(ok=True, unicode_install_path=True, personal_persistence=True,
                      uninstall_reinstall=True, dictionary_unchanged=True)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--zip', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--packaged-app', type=Path)
    a = p.parse_args()
    verify(a.zip, a.report, a.packaged_app)
