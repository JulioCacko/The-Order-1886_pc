import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('linux_package',
    Path(__file__).resolve().parents[1] / 'packaging/linux/order1886-package.py')
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)
SMOKE_SPEC = importlib.util.spec_from_file_location('linux_smoke',
    Path(__file__).resolve().parents[1] / 'packaging/linux/order1886-smoke.py')
smoke = importlib.util.module_from_spec(SMOKE_SPEC)
SMOKE_SPEC.loader.exec_module(smoke)


class LinuxPackageTests(unittest.TestCase):
    def test_collects_transitive_libraries_without_host_glibc_or_wsl_driver(self):
        result = package.dependencies('''
linux-vdso.so.1 (0x0000)
libps4gpu.so => /build/out/gpu/libps4gpu.so (0x0000)
libSDL3.so.0 => /lib/x86_64-linux-gnu/libSDL3.so.0 (0x0000)
libstdc++.so.6 => /lib/x86_64-linux-gnu/libstdc++.so.6 (0x0000)
libc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x0000)
libm.so.6 => /lib/x86_64-linux-gnu/libm.so.6 (0x0000)
libdxcore.so => /usr/lib/wsl/lib/libdxcore.so (0x0000)
/lib64/ld-linux-x86-64.so.2 (0x0000)
''')
        self.assertEqual(set(result), {'libps4gpu.so', 'libSDL3.so.0', 'libstdc++.so.6'})

    def test_missing_dependency_prevents_publication(self):
        with self.assertRaisesRegex(ValueError, 'Unresolved native dependency'):
            package.dependencies('libSDL3.so.0 => not found')

    def test_hash_mismatch_prevents_any_package_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            source.mkdir()
            (source / 'binary').write_bytes(b'changed')
            (source / 'package-manifest.json').write_text(json.dumps({'files': {'binary': 'wrong'}}))
            with mock.patch.object(smoke.sys, 'platform', 'linux'), \
                 mock.patch.object(smoke.sys, 'argv', ['smoke', str(source), '--output', str(root / 'result')]), \
                 mock.patch.object(smoke.subprocess, 'run') as execute:
                with self.assertRaisesRegex(ValueError, 'Package hash mismatch'):
                    smoke.main()
                execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
