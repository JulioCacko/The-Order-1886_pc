import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'order1886_release_receipt', ROOT / 'packaging' / 'order1886_release_receipt.py')
receipt_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receipt_module)

REVISION = 'a' * 40


def make_packages(folder, dirty=False, linux_revision=REVISION):
    windows = folder / 'order1886-go-windows.zip'
    with zipfile.ZipFile(windows, 'w') as z:
        z.writestr('The Order 1886/bin/runtime-build.json', json.dumps(
            {'source_revision': REVISION, 'source_dirty': dirty, 'runtime_sha256': 'b' * 64}))
    linux = folder / 'order1886-linux-x86_64.tar.gz'
    with tarfile.open(linux, 'w:gz') as t:
        data = json.dumps({'source_revision': linux_revision, 'runtime_sha256': 'c' * 64}).encode()
        info = tarfile.TarInfo('The Order 1886/package-manifest.json')
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
    return windows, linux


class ReleaseReceiptTests(unittest.TestCase):
    def test_receipt_matches_the_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            windows, linux = make_packages(Path(tmp))
            data = receipt_module.receipt('v0.2.0', windows, linux, '42', {'native_tests': '56'})
        self.assertEqual(data['archive'], 'order1886-go-windows.zip')
        self.assertEqual(data['archive_bytes'], data['windows']['bytes'])
        self.assertEqual(len(data['archive_sha256']), 64)
        self.assertEqual(data['source_revision'], REVISION)
        self.assertEqual(data['linux']['runtime_sha256'], 'c' * 64)
        self.assertEqual(data['update_abi'], 'order1886-update-2')

    def test_refuses_what_the_updater_would_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            windows, linux = make_packages(Path(tmp), dirty=True)
            with self.assertRaises(SystemExit):
                receipt_module.receipt('v0.2.0', windows, linux, '42', {})
        with tempfile.TemporaryDirectory() as tmp:
            windows, linux = make_packages(Path(tmp), linux_revision='d' * 40)
            with self.assertRaises(SystemExit):
                receipt_module.receipt('v0.2.0', windows, linux, '42', {})
            with self.assertRaises(SystemExit):
                receipt_module.receipt('v1.0', windows, linux, '42', {})


if __name__ == '__main__':
    unittest.main()
