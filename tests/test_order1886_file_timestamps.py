"""Build the real file backend in an isolated CPU fixture and inspect its file effects."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FileTimestampTests(unittest.TestCase):
    def test_guest_futimes_updates_real_files_and_preserves_errors_and_game(self):
        compiler = shutil.which(os.environ.get('CC', 'clang'))
        env = os.environ.copy()
        if os.name == 'nt' and compiler is None:
            candidate = Path(env.get('MSYS2_ROOT', r'C:\msys64')) / 'clang64/bin/clang.exe'
            if candidate.is_file():
                compiler = str(candidate)
        self.assertIsNotNone(compiler, 'clang is required for the native timestamp contract')
        env['PATH'] = str(Path(compiler).parent) + os.pathsep + env.get('PATH', '')
        with tempfile.TemporaryDirectory(prefix='Order timestamp files ') as name:
            work = Path(name)
            game, state = work / 'Game Original', work / 'User State'
            game.mkdir()
            state.mkdir()
            original = game / 'original.bin'
            original.write_bytes(b'preserved original fixture')
            before = original.stat()
            # The host filesystem must support the subsecond values being asserted.
            probe = work / 'timestamp-precision'
            probe.touch()
            os.utime(probe, ns=(1600000000123456000, 1600000100654321000))
            precision = probe.stat()
            if (precision.st_atime_ns, precision.st_mtime_ns) != (1600000000123456000, 1600000100654321000):
                self.skipTest('Host filesystem does not preserve the required microsecond timestamps')
            binary = work / ('file-timestamps.exe' if os.name == 'nt' else 'file-timestamps')
            command = [compiler, '-std=c11', '-O2', '-UNDEBUG', '-Wall', '-Wextra', '-Werror',
                       '-pthread', '-I' + str(ROOT), '-I' + str(ROOT / 'src'),
                       str(ROOT / 'tests/test_file_timestamps.c'), str(ROOT / 'src/runtime.c')]
            if os.name == 'nt':
                command += [str(ROOT / 'src/compat_win.c'), '-lbcrypt']
            command += ['-o', str(binary)]
            compiled = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([str(binary), str(game), str(state)], env=env,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            target = state / 'data/timestamp-save.bin'
            actual = target.stat()
            self.assertEqual((actual.st_atime_ns, actual.st_mtime_ns),
                             (1600000200234567000, 1600000300765432000))
            preserved = original.stat()
            self.assertEqual((preserved.st_atime_ns, preserved.st_mtime_ns),
                             (before.st_atime_ns, before.st_mtime_ns))
            self.assertEqual(target.read_bytes(), b'owned-save')
            self.assertEqual(original.read_bytes(), b'preserved original fixture')


if __name__ == '__main__':
    unittest.main()
