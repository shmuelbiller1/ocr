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


def verify(archive, report, packaged_app=None, modern=False):
    with tempfile.TemporaryDirectory(prefix='hebrew-spell-') as folder:
        home = Path(folder) / 'עברית space'
        previous = os.environ.get('HEBREW_WORKBENCH_HOME')
        try:
            os.environ['HEBREW_WORKBENCH_HOME'] = str(home)
            _verify_at_home(archive, report, packaged_app, home, modern)
        finally:
            if previous is None:
                os.environ.pop('HEBREW_WORKBENCH_HOME', None)
            else:
                os.environ['HEBREW_WORKBENCH_HOME'] = previous


def _verify_at_home(archive, report, packaged_app, home, modern):
    root = home / 'plugins'
    installer = PluginInstaller(root)
    installer.install_zip(archive)
    settings = root / 'settings.json'
    registry = PluginRegistry(root=root, settings_path=settings)
    plugin_id = 'modern-hebrew-spelling' if modern else 'hunspell-hebrew'
    plugin = registry.get(plugin_id)
    assert plugin and plugin.object and plugin.available(), plugin.error if plugin else 'missing'
    registry.set_active('spelling', plugin.id)
    module = plugin.object
    result = exercise(module)
    if modern:
        baseline_path = archive.with_name('hunspell-hebrew-win64.zip' if sys.platform == 'win32'
                                          else 'hunspell-hebrew-linux.zip')
        installer.install_zip(baseline_path)
        registry.load()
        baseline = registry.get('hunspell-hebrew').object
        # Public Hebrew Academy 2017 examples; selected small smoke fixture,
        # not an independent representative benchmark.
        examples = 'אונייה אמיתי לעיתים פירות שמיים תוכנית תוכנה יוזמה צוהריים אומן אומנם קורבן שיער ברירה עבירה ריאלי'
        old_proposals = baseline.check(examples)
        modern_proposals = module.check(examples)
        assert modern_proposals == [], 'Modern orthography examples were flagged'
        assert len(old_proposals) > len(modern_proposals), 'No observed improvement on the examples'
        typos = 'שלומ תלמיידים אניטרנט תילמידים מוררה כתתב חדדשמ'
        old_typos = {p.original for p in baseline.check(typos)}
        modern_typos = {p.original for p in module.check(typos)}
        assert old_typos == modern_typos == set(typos.split()), 'Obvious typo regression'
        prefixes = 'בבית והילדים בשיעור למורה במחשב'
        assert baseline.check(prefixes) == module.check(prefixes) == []
        result['comparison'] = {
            'scope': 'small curated example smoke; not representative or independently benchmarked',
            'academy_example_count': len(examples.split()),
            'baseline_flags': len(old_proposals), 'modern_flags': len(modern_proposals),
            'baseline_flagged_words': [p.original for p in old_proposals],
            'selected_typos_flagged_by_both': len(modern_typos),
            'prefix_examples': len(prefixes.split()),
        }

    before = hashlib.sha256(module.dictionary_path.read_bytes()).hexdigest()
    assert module.keep_word('מונחבדיקהייחודי')
    assert module.check('מונחבדיקהייחודי') == []
    registry.load()
    assert registry.get(plugin.id).object.check('מונחבדיקהייחודי') == []
    assert hashlib.sha256(module.dictionary_path.read_bytes()).hexdigest() == before
    if packaged_app:
        output = home / 'packaged-selftest.json'
        env = dict(os.environ, HEBREW_WORKBENCH_HOME=str(home),
                   HEBREW_WORKBENCH_TEST_SPELLING_PLUGIN=('modern' if modern else '1'))
        payload = check_packaged_app(packaged_app, output, home, env)
        result['packaged_app'] = payload
    installer.remove(plugin_id)
    assert (home / 'spelling/hunspell-hebrew-personal.txt').exists()
    installer.install_zip(archive)
    registry.load()
    assert registry.get(plugin_id).object.check('מונחבדיקהייחודי') == []
    result.update(zip_bytes=archive.stat().st_size,
                  zip_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                  runtime_bytes=sum(p.stat().st_size for p in
                                    (module.dictionary_path, module.dictionary_path.with_suffix('.aff'),
                                     module._worker)) + (2670751 if modern else 0),
                  ok=True, unicode_install_path=True, personal_persistence=True,
                  uninstall_reinstall=True, dictionary_unchanged=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True, indent=2))


def check_packaged_app(packaged_app, output, home, env):
    def show(stdout, stderr):
        # bytes repr is console-codepage safe, including partial UTF-8 output.
        if stdout:
            print('Packaged stdout:', repr(stdout))
        if stderr:
            print('Packaged stderr:', repr(stderr))
    try:
        run = subprocess.run([str(packaged_app.resolve()), '--selftest', '--selftest-report', str(output)],
                             env=env, cwd=home, capture_output=True, timeout=90)
    except subprocess.TimeoutExpired as exc:
        show(exc.stdout, exc.stderr)
        raise
    show(run.stdout, run.stderr)
    payload = json.loads(output.read_text(encoding='utf-8'))
    assert run.returncode == 0 and payload['ok'], payload
    assert any(c['name']=='optional-hebrew-spelling' and c['ok'] for c in payload['results'])
    return payload


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--zip', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--packaged-app', type=Path)
    p.add_argument('--modern', action='store_true')
    a = p.parse_args()
    verify(a.zip, a.report, a.packaged_app, a.modern)
