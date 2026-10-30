"""Build the optional AGPL Hebrew spelling distribution from pinned source.

Network is build-time only. There are no downloaded executables. Generated
artifacts stay under build/; neither core edition gains dictionary assets.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'optional_plugins/hunspell_hebrew'


def fetch(name, pin, cache):
    path = cache / name
    if not path.exists():
        headers = {'User-Agent': 'HebrewNotesWorkbench-builder'}
        if pin.get('encoding') == 'raw-github-blob':
            headers['Accept'] = 'application/vnd.github.raw+json'
        request = urllib.request.Request(pin['url'], headers=headers)
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(16 * 1024 * 1024 + 1)
        if len(data) > 16 * 1024 * 1024:
            raise ValueError('Upstream response exceeds build limit')
        if pin.get('encoding') == 'github-blob':
            data = base64.b64decode(json.loads(data)['content'], validate=False)
        if len(data) != pin['size'] or hashlib.sha256(data).hexdigest() != pin['sha256']:
            raise ValueError(f'Upstream verification failed: {name}')
        path.write_bytes(data)
    if path.stat().st_size != pin['size'] or hashlib.sha256(path.read_bytes()).hexdigest() != pin['sha256']:
        raise ValueError(f'Cached upstream verification failed: {name}')
    return path


def extract(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as source:
        members = source.getmembers()
        for member in members:
            target = (destination / member.name).resolve()
            if destination.resolve() not in target.parents or not (member.isfile() or member.isdir()):
                raise ValueError('Unsafe source archive member')
        source.extractall(destination, members=members)
    folders = [p for p in destination.iterdir() if p.is_dir()]
    if len(folders) != 1:
        raise ValueError('Expected one source root')
    return folders[0]


def source_files(root):
    """Use Git's tracked list, or the captured list from an unpacked source ZIP.

    Never recursively collect an arbitrary checkout (personal data/secrets).
    """
    manifest = root / 'SOURCE-FILES.json'
    if manifest.is_file():
        names = json.loads(manifest.read_text(encoding='utf-8'))
    else:
        names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    result = []
    for name in names:
        if not name or name == 'SOURCE-FILES.json':
            continue
        path = (root / name).resolve()
        if root.resolve() not in path.parents or not path.is_file():
            raise ValueError('Missing or unsafe corresponding source: ' + name)
        result.append(name)
    return result


def build(output, cmake='cmake'):
    output = Path(output).resolve()
    # Avoid deleting any user-selected directory: builds stage in a fresh subfolder.
    output.mkdir(parents=True, exist_ok=True)
    cache = output / 'downloads'; cache.mkdir(exist_ok=True)
    pins = json.loads((TEMPLATE / 'upstream-pins.json').read_text())
    files = {name: fetch(name, pin, cache) for name, pin in pins.items()}
    hunspell = extract(files['hunspell-source.tar.gz'], output / 'upstream-hunspell')
    hspell = extract(files['hspell-source.tar.gz'], output / 'upstream-hspell')
    compile_dir = output / ('native-vs2022-x64' if os.name == 'nt' else 'native')
    configure = [cmake, '-S', str(TEMPLATE), '-B', str(compile_dir),
                 '-DHUNSPELL_SOURCE=' + str(hunspell), '-DCMAKE_BUILD_TYPE=Release']
    if os.name == 'nt':
        # Hosted runners can export CMAKE_GENERATOR=NMake without a developer
        # shell. The VS generator locates MSVC without relying on PATH/nmake.
        configure += ['-G', 'Visual Studio 17 2022', '-A', 'x64']
    subprocess.run(configure, check=True)
    subprocess.run([cmake, '--build', str(compile_dir), '--config', 'Release', '--parallel', '2'], check=True)
    binary_name = 'hebrew-spelling-worker.exe' if os.name == 'nt' else 'hebrew-spelling-worker'
    candidates = list(compile_dir.rglob(binary_name))
    if len(candidates) != 1:
        raise ValueError('Expected exactly one native spelling worker')
    stage = Path(tempfile.mkdtemp(prefix='plugin-stage-', dir=output))
    bundle = stage / 'hunspell-hebrew'
    bundle.mkdir()
    for name in ('plugin.json', 'spelling.py', 'README.md', 'upstream-pins.json', 'worker.cpp', 'CMakeLists.txt'):
        shutil.copy2(TEMPLATE / name, bundle / name)
    shutil.copy2(candidates[0], bundle / binary_name)
    data = bundle / 'data'; data.mkdir(exist_ok=True)
    for name in ('he_IL.aff', 'he_IL.dic', 'README_he_IL.txt'):
        shutil.copy2(files[name], data / name)
    sources = bundle / 'SOURCE'; sources.mkdir(exist_ok=True)
    for name in ('hunspell-source.tar.gz', 'hspell-source.tar.gz'):
        shutil.copy2(files[name], sources / name)
    # Include exact tracked application sources as well as upstream generators.
    tracked = source_files(ROOT)
    with zipfile.ZipFile(sources / 'workbench-source.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('SOURCE-FILES.json', json.dumps(tracked, indent=2))
        for name in tracked:
            archive.write(ROOT / name, name)
    shutil.copy2(Path(__file__), sources / 'build_spelling_plugin.py')
    licenses = bundle / 'LICENCES'; licenses.mkdir(exist_ok=True)
    shutil.copy2(hspell / 'COPYING', licenses / 'AGPL-3.0.txt')
    shutil.copy2(hspell / 'LICENSE', licenses / 'HSPELL-NOTICE.txt')
    for name in ('COPYING', 'COPYING.LESSER', 'COPYING.MPL', 'license.hunspell'):
        shutil.copy2(hunspell / name, licenses / ('HUNSPELL-' + name))
    shutil.copy2(ROOT / 'LICENSE', licenses / 'WORKBENCH-MIT.txt')
    (bundle / 'NOTICE.txt').write_text(
        'Hebrew spelling plugin distribution: AGPL-3.0-only.\n'
        'Dictionary: Hspell 1.4, copyright 2000-2017 Nadav Har\'El and Dan Kenigsberg.\n'
        'Uses PRE-JUNE-2017 spelling rules; not validated for modern school notes.\n'
        'Dictionary files are unmodified from the pinned LibreOffice blobs.\n'
        'Hunspell 1.7.6 engine: LGPL/GPL/MPL tri-license, see LICENCES.\n'
        'Project-authored adapter/bridge/build sources retain MIT notices;\n'
        'this AGPL distribution does not relabel the dictionary as MIT.\n'
        'Complete application sources and upstream source/generators are in SOURCE.\n'
        'No noncommercial OCR weights are included in this separate package.\n'
        'Separate-process packaging is NOT a promise of exemption from copyleft.\n', encoding='utf-8')
    manifest = {'protocol': 1, 'dictionary_version': 'Hspell 1.4 (pre-2017)',
                'sha256': {name: hashlib.sha256((bundle / name).read_bytes()).hexdigest()
                           for name in (binary_name, 'data/he_IL.aff', 'data/he_IL.dic')}}
    (bundle / 'BUNDLE.json').write_text(json.dumps(manifest, indent=2)+'\n')
    zip_path = output / ('hunspell-hebrew-win64.zip' if binary_name.endswith('.exe') else 'hunspell-hebrew-linux.zip')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(bundle.rglob('*')):
            if path.is_file():
                archive.write(path, 'hunspell-hebrew/' + path.relative_to(bundle).as_posix())
    runtime_bytes = sum((bundle / n).stat().st_size for n in manifest['sha256'])
    shutil.rmtree(stage)
    print(json.dumps({'plugin_zip': str(zip_path), 'zip_bytes': zip_path.stat().st_size,
                      'runtime_bytes': runtime_bytes,
                      'sha256': hashlib.sha256(zip_path.read_bytes()).hexdigest()}, indent=2))
    return zip_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/hebrew-spelling')
    parser.add_argument('--cmake', default='cmake')
    args = parser.parse_args()
    build(args.output, args.cmake)
