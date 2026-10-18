import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('runtime_build_identity',
    Path(__file__).resolve().parents[1] / 'scripts/runtime_build_identity.py')
identity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(identity)


class BuildIdentityTests(unittest.TestCase):
    def check_receipt(self, platform, compiler, build_command):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / 'order1886-runtime'
            runtime.write_bytes(b'tested runtime')
            (root / 'source.c').write_text('source', encoding='utf-8')

            def command(*args):
                if args[:2] == ('git', 'ls-files'):
                    return 'source.c'
                if args[:2] == ('git', 'rev-parse'):
                    return 'verified-revision'
                if args[:2] in (('git', 'status'), ('git', 'submodule')):
                    return ''
                if args == (compiler, '--version'):
                    return 'verified compiler\nextra'
                raise AssertionError(args)

            with mock.patch.object(identity, 'ROOT', root), \
                 mock.patch.object(identity, 'command', side_effect=command), \
                 mock.patch.object(identity.sys, 'argv', ['identity', str(runtime)]), \
                 mock.patch.object(identity.sys, 'platform', platform), \
                 mock.patch.dict('os.environ', {'CC': 'clang'}, clear=False), \
                 contextlib.redirect_stdout(io.StringIO()):
                identity.main()
            receipt = json.loads(runtime.with_name('runtime-build.json').read_text())
            self.assertEqual(receipt['runtime_sha256'], hashlib.sha256(runtime.read_bytes()).hexdigest())
            self.assertEqual(receipt['source_revision'], 'verified-revision')
            self.assertFalse(receipt['source_dirty'])
            self.assertEqual(receipt['compiler'], 'verified compiler')
            self.assertEqual(receipt['build_command'], build_command)

    def test_windows_receipt_preserves_msys_build_command(self):
        self.check_receipt('win32', 'clang', ['C:/msys64/usr/bin/bash.exe', 'build.sh'])

    def test_linux_receipt_records_native_build_command(self):
        self.check_receipt('linux', 'clang', ['bash', 'build.sh'])


if __name__ == '__main__':
    unittest.main()
