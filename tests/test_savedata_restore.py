"""Backup/restore reaches the production savedata search and mount exports."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import paths
import save_backup


class SavedataRestoreTest(unittest.TestCase):
    def test_restored_slots_and_metadata_are_visible_to_game_apis(self):
        environment = paths.native_environment()
        compiler = shutil.which(os.environ.get('CC', 'clang'), path=environment['PATH'])
        self.assertIsNotNone(compiler, 'clang is required for the savedata restore regression')
        with tempfile.TemporaryDirectory(prefix='order-save-restore-') as directory:
            root = Path(directory)
            binary = root / ('savedata.exe' if os.name == 'nt' else 'savedata')
            command = [compiler, '-std=c11', '-O2', '-UNDEBUG', '-Wall', '-Wextra', '-Werror',
                       '-pthread', '-I' + str(paths.ROOT), '-I' + str(paths.ROOT / 'src'),
                       str(paths.ROOT / 'tests/test_savedata_restore.c'), '-o', str(binary)]
            if os.name == 'nt':
                command += ['-lws2_32']
            compiled = subprocess.run(command, env=environment, capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            state = root / 'user'

            def fixture(action, marker):
                result = subprocess.run([str(binary), str(state), action, str(marker)],
                                        env=environment, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            fixture('write', 111)
            selected = save_backup.backup(state)
            fixture('write', 222)
            safety = save_backup.restore(state, selected.name)
            self.assertTrue(safety.is_dir())
            fixture('check', 111)
            save_backup.restore(state, safety.name)
            fixture('check', 222)


if __name__ == '__main__':
    unittest.main()
