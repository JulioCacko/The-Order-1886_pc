"""Compile CPU-only save/dialog tracing contracts; never start the runtime or GPU."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SaveTraceTests(unittest.TestCase):
    def test_opt_in_status_sampling_bounds_and_unchanged_dialog_contracts(self):
        compiler = shutil.which(os.environ.get('CC', 'clang'))
        environment = os.environ.copy()
        if os.name == 'nt' and compiler is None:
            candidate = Path(environment.get('MSYS2_ROOT', r'C:\msys64')) / 'clang64/bin/clang.exe'
            if candidate.is_file():
                compiler = str(candidate)
        self.assertIsNotNone(compiler, 'clang is required for the save trace CPU regression')
        environment['PATH'] = str(Path(compiler).parent) + os.pathsep + environment.get('PATH', '')
        with tempfile.TemporaryDirectory(prefix='order-save-trace-') as directory:
            for source in ('test_save_trace.c', 'test_services.c', 'test_savedata_trace.c'):
                binary = Path(directory) / (source + ('.exe' if os.name == 'nt' else '.bin'))
                command = [compiler, '-std=c11', '-O2', '-UNDEBUG', '-Wall', '-Wextra', '-Werror',
                           '-pthread', '-I' + str(ROOT), '-I' + str(ROOT / 'src'),
                           str(ROOT / 'tests' / source), '-o', str(binary)]
                if os.name == 'nt':
                    command += ['-lws2_32']
                compiled = subprocess.run(command, env=environment, capture_output=True, text=True)
                self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
                if source == 'test_savedata_trace.c':
                    for enabled in ('0', '1'):
                        for api in ('mount', 'mount2'):
                            with self.subTest(source=source, enabled=enabled, api=api):
                                result = subprocess.run([str(binary), api],
                                    env={**environment, 'ORDER1886_DIAG_SAVE': enabled},
                                    capture_output=True, text=True, timeout=30)
                                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                                self.assertEqual('SaveTrace:' in result.stdout, enabled == '1')
                                if enabled == '1':
                                    self.assertIn('result=0x809f0001 status=0', result.stdout)
                                    self.assertIn('result=0x809f0011 status=1', result.stdout)
                    continue
                for enabled in ('0', '1'):
                    with self.subTest(source=source, enabled=enabled):
                        result = subprocess.run([str(binary)], env={**environment, 'ORDER1886_DIAG_SAVE': enabled},
                                                capture_output=True, text=True, timeout=30)
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        lines = [line for line in result.stdout.splitlines() if line.startswith('SaveTrace:')]
                        if enabled == '0':
                            self.assertEqual(lines, [])
                            continue
                        self.assertTrue(lines)
                        for field in ('phase=enter', 'phase=return', 'thread=', 'monotonic_ns=',
                                      'duration_ns=', 'result=0x', 'status='):
                            self.assertIn(field, result.stdout)
                        if source == 'test_save_trace.c':
                            self.assertIn('result=0x809f0008 status=7', result.stdout)
                            status = [line for line in lines if 'api=fixture.status ' in line]
                            self.assertLessEqual(len(status), 128)
                            self.assertIn('sample=change', result.stdout)
                        else:
                            self.assertIn('api=sceSaveDataDialogOpen ', result.stdout)
                            self.assertIn('mode=5', result.stdout)
                            self.assertIn('result=0x80b80005 status=2', result.stdout)
                            status = [line for line in lines if 'api=sceSaveDataDialogGet/UpdateStatus ' in line]
                            self.assertLessEqual(len(status), 128)
                            self.assertIn('result=0x00000003 status=3', result.stdout)


if __name__ == '__main__':
    unittest.main()
