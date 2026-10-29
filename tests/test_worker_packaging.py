"""Safe exclusions, explicit offline resources and fail-closed validation."""
import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.build_worker import build_arguments, remove_video_plugin, MODEL_MODULES
from tools.verify_worker_bundle import inventory, validate_payload, CASES


class WorkerPackagingTests(unittest.TestCase):
    def test_inference_keeps_segmentation_data_and_dynamic_model_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for resource in ('blla.mlmodel', 'iso15924.json', 'lib/dataset/scripts.json'):
                path = root / resource
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            args = build_arguments('inference', root / 'dist', root / 'build', root)
            self.assertEqual(args.count('--collect-all'), 1)
            self.assertEqual(args[args.index('--collect-all') + 1], 'torchvision')
            self.assertIn('--copy-metadata', args)
            for module in MODEL_MODULES:
                self.assertIn(module, args)
            self.assertIn(f'{root / "blla.mlmodel"}:kraken', args)
            for required in ('torch', 'torchvision', 'pyarrow', 'scipy', 'sklearn', 'kraken.lib.dataset'):
                self.assertNotIn(required, [args[i+1] for i, arg in enumerate(args[:-1]) if arg == '--exclude-module'])

    def test_missing_offline_segmentation_model_prevents_build(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FileNotFoundError):
                build_arguments('inference', Path(temp), Path(temp), Path(temp))

    def test_baseline_reproduces_original_collection_recipe(self):
        args = build_arguments('baseline', Path('dist'), Path('build'), Path('unused'))
        self.assertEqual(args.count('--collect-all'), 2)
        self.assertNotIn('--exclude-module', args)

    def test_build_timeout_fails_without_starting_a_real_packager(self):
        import contextlib
        import io
        from unittest.mock import Mock, patch
        from tools import build_worker
        distribution = Mock(version='7.1.1')
        with tempfile.TemporaryDirectory() as temp:
            distribution.locate_file.return_value = Path(temp)
            with patch.object(build_worker.importlib.metadata, 'distribution', return_value=distribution), \
                 patch.object(build_worker.subprocess, 'run', side_effect=subprocess.TimeoutExpired('build', 1800)) as run, \
                 contextlib.redirect_stderr(io.StringIO()):
                status = build_worker.main(['--profile', 'baseline', '--distpath', temp,
                                            '--workpath', temp, '--report', str(Path(temp) / 'report.json')])
            self.assertEqual(status, 1)
            self.assertEqual(run.call_args.kwargs['timeout'], 1800)

    def test_only_separate_video_plugin_is_deleted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cv2 = root / '_internal' / 'cv2'
            cv2.mkdir(parents=True)
            for name in ('opencv_videoio_ffmpeg4120_64.dll', 'cv2.pyd', 'opencv_imgcodecs.dll', 'other.dll'):
                (cv2 / name).write_bytes(b'x' * 10)
            other = root / 'opencv_videoio_ffmpeg4120_64.dll'
            other.write_bytes(b'not in cv2 directory')
            deleted = remove_video_plugin(root)
            self.assertEqual(len(deleted), 1)
            self.assertEqual(deleted[0]['bytes'], 10)
            self.assertTrue((cv2 / 'cv2.pyd').is_file())
            self.assertTrue((cv2 / 'opencv_imgcodecs.dll').is_file())
            self.assertTrue(other.is_file())
            self.assertEqual(remove_video_plugin(root), [])

    def test_inventory_counts_actual_bundle_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'worker.exe').write_bytes(b'123')
            (root / '_internal' / 'torch').mkdir(parents=True)
            (root / '_internal' / 'torch' / 'x.dll').write_bytes(b'12345')
            self.assertEqual(inventory(root)['bytes'], 8)
            self.assertEqual(inventory(root)['components']['torch'], 5)

    def test_empty_output_fallback_or_network_attempts_fail_checks(self):
        payload = {'text': 'raw', 'assisted_text': 'alternative', 'decoding_mode': 'assisted',
                   'offline_check': {'enabled': True, 'blocked_attempts': []}}
        validate_payload(payload, 'assisted')
        for change in ({'text': ''}, {'assisted_text': ''}, {'decoding_mode': 'raw'},
                       {'offline_check': {'enabled': True, 'blocked_attempts': ['network']}},
                       {'offline_check': {}}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                validate_payload({**payload, **change}, 'assisted')

    def test_matrix_covers_all_models_profiles_and_both_input_types(self):
        self.assertEqual({row[1] for row in CASES}, {'small.safetensors', 'medium.safetensors', 'mishkefet-v1.pt'})
        self.assertEqual({row[3] for row in CASES}, {'raw', 'beam', 'assisted'})
        self.assertEqual({row[4] for row in CASES}, {'pdf', 'image'})

    def test_release_waits_for_all_validation_jobs(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/windows.yml').read_text()
        self.assertIn('needs: [test-and-package, unit-tests, ocr-engine, ocr-worker-windows]', workflow)

    def test_offline_guard_blocks_outbound_lookup_and_connect_without_reaching_network(self):
        # Audit hooks cannot be removed, so keep this check in a fresh process.
        code = '''
import json, socket
from ocr_worker.main import _install_offline_guard
attempts=[]
_install_offline_guard(attempts)
for operation in (lambda:socket.getaddrinfo('example.invalid',443),
                  lambda:socket.gethostbyname('example.invalid'),
                  lambda:socket.gethostbyname_ex('example.invalid'),
                  lambda:socket.gethostbyaddr('192.0.2.1'),
                  lambda:socket.getnameinfo(('192.0.2.1',443),0),
                  lambda:socket.socket().connect(('192.0.2.1',443))):
    try: operation()
    except OSError: pass
    else: raise AssertionError('outbound access allowed')
assert len(attempts)==6, attempts
socket.getaddrinfo('127.0.0.1',443)
assert len(attempts)==6
print(json.dumps(attempts))
'''
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)), 6)


if __name__ == '__main__':
    unittest.main()
