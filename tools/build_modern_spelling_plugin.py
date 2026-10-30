"""Build a second, optional modern-supplemented plugin from the baseline ZIP.

Only pinned source/data is downloaded by the parent builder and this tool.
No externally built executable is downloaded. The baseline remains unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_spelling_plugin import build, fetch

TEMPLATE = ROOT / 'optional_plugins/modern_hebrew'


def build_modern(output, cmake='cmake'):
    output = Path(output).resolve()
    baseline_zip = build(output, cmake)
    cache = output / 'downloads'
    pin = json.loads((TEMPLATE / 'upstream.json').read_text(encoding='utf-8'))
    wordlist = fetch('modern-words.txt', pin, cache)
    with tempfile.TemporaryDirectory(prefix='modern-plugin-', dir=output) as temp:
        folder = Path(temp)
        with zipfile.ZipFile(baseline_zip) as source:
            # Generated in this process by our trusted builder; check that
            # paths remain under the fresh temp folder anyway.
            for member in source.infolist():
                destination = (folder / member.filename).resolve()
                if folder.resolve() not in destination.parents:
                    raise ValueError('Unsafe baseline ZIP path')
            source.extractall(folder)
        bundle = folder / 'hunspell-hebrew'
        if sys.platform != 'win32':
            # ZipFile.extractall does not restore POSIX executable bits.
            (bundle / 'hebrew-spelling-worker').chmod(0o755)
        shutil.move(bundle / 'spelling.py', bundle / 'hspell_base.py')
        for name in ('plugin.json', 'modern_spelling.py', 'README.md', 'upstream.json'):
            shutil.copy2(TEMPLATE / name, bundle / name)
        shutil.copy2(wordlist, bundle / 'data/modern-words.txt')
        shutil.copy2(TEMPLATE / 'UPSTREAM-CC0.txt', bundle / 'LICENCES/CC0-1.0.txt')
        shutil.copy2(TEMPLATE / 'UPSTREAM-SOURCES.md', bundle / 'LICENCES/MODERN-SOURCES.md')
        with (bundle / 'NOTICE.txt').open('a', encoding='utf-8') as notice:
            notice.write('\nModern supplement: CC0-1.0 as declared by upstream; see LICENCES.\n'
                         'The supplement is AI-assisted and has not been independently audited.\n'
                         'It only suppresses flags for exact matches; it is not a verified dictionary.\n')
        target = output / ('modern-hebrew-spelling-win64.zip' if sys.platform == 'win32'
                           else 'modern-hebrew-spelling-linux.zip')
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(bundle.rglob('*')):
                if path.is_file():
                    archive.write(path, 'modern-hebrew-spelling/' + path.relative_to(bundle).as_posix())
    print(json.dumps({'modern_plugin_zip': str(target), 'zip_bytes': target.stat().st_size,
                      'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}, indent=2))
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/hebrew-spelling')
    parser.add_argument('--cmake', default='cmake')
    options = parser.parse_args()
    build_modern(options.output, options.cmake)
