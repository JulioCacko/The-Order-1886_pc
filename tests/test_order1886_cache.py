import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import order1886
from scripts import order1886_cache


class ShaderCacheTests(unittest.TestCase):
    def setUp(self):
        self.cache_module = order1886_cache
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / 'state'
        self.cache = self.state / 'gpu' / order1886.SHADER_CACHE_ABI / 'cache' / order1886.TITLE_ID
        self.cache.mkdir(parents=True)
        self.shader = self.cache / 'shader.bin'
        self.shader.write_bytes(b'cached shader')

    def clear(self, state=None):
        return self.cache_module.clear_shader_cache(state or self.state)

    def link_directory(self, link, destination):
        try:
            link.symlink_to(destination, target_is_directory=True)
        except OSError:
            if os.name != 'nt':
                raise
            import _winapi
            _winapi.CreateJunction(str(destination), str(link))

    def test_removes_only_selected_title_shader_cache(self):
        preserved = [
            self.cache.parent / 'CUSA99999' / 'shader.bin',
            self.state / 'gpu' / 'previous-abi' / 'cache' / order1886.TITLE_ID / 'shader.bin',
            self.state / 'gpu' / order1886.SHADER_CACHE_ABI / 'config.toml',
            self.state / 'settings.json', self.state / 'runtime.ini',
            self.state / 'saves' / 'save.dat', self.state / 'mods' / 'mod.bin',
            self.state / 'backups' / 'save.dat', self.state / 'prepared' / 'eboot.bin',
            self.root / 'game' / 'eboot.bin',
        ]
        for path in preserved:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'preserve me')
        nested = self.cache / 'nested' / 'pipeline.bin'
        nested.parent.mkdir()
        nested.write_bytes(b'pipeline')

        self.assertTrue(self.clear())
        self.assertFalse(self.cache.exists())
        for path in preserved:
            self.assertEqual(path.read_bytes(), b'preserve me', str(path))

    def test_missing_cache_is_idempotent(self):
        self.assertTrue(self.clear())
        self.assertFalse(self.clear())

    def test_missing_state_is_idempotent_without_creating_it(self):
        missing = self.root / 'missing-state'
        self.assertFalse(self.clear(missing))
        self.assertFalse(missing.exists())

    def test_active_session_refuses_and_preserves_cache(self):
        with order1886.session_lock(self.state):
            with self.assertRaisesRegex(RuntimeError, 'already running|in use'):
                self.clear()
        self.assertEqual(self.shader.read_bytes(), b'cached shader')

    def test_holds_session_lock_through_deletion(self):
        import shutil
        original = shutil.rmtree

        def checked_remove(path, *args, **kwargs):
            with self.assertRaisesRegex(RuntimeError, 'already running|in use'):
                with order1886.session_lock(self.state):
                    self.fail('Clearing released the session lock before deletion')
            return original(path, *args, **kwargs)

        with patch.object(self.cache_module.shutil, 'rmtree', side_effect=checked_remove):
            self.assertTrue(self.clear())

    def test_redirected_state_refuses_and_preserves_cache(self):
        alias = self.root / 'state-link'
        self.link_directory(alias, self.state)
        with self.assertRaisesRegex(ValueError, 'link|reparse|redirect'):
            self.clear(alias)
        self.assertEqual(self.shader.read_bytes(), b'cached shader')

    def test_redirected_state_ancestor_refuses_and_preserves_cache(self):
        alias = self.root / 'root-link'
        self.link_directory(alias, self.root)
        with self.assertRaisesRegex(ValueError, 'link|reparse|redirect'):
            self.clear(alias / 'state')
        self.assertEqual(self.shader.read_bytes(), b'cached shader')

    def test_redirected_cache_ancestors_refuse_without_deleting(self):
        for relative in ('gpu', 'gpu/' + order1886.SHADER_CACHE_ABI,
                         'gpu/' + order1886.SHADER_CACHE_ABI + '/cache'):
            with self.subTest(relative=relative):
                target = self.state / relative
                outside = self.root / ('outside-' + relative.replace('/', '-'))
                target.rename(outside)
                self.link_directory(target, outside)
                try:
                    with self.assertRaisesRegex(ValueError, 'link|reparse|redirect'):
                        self.clear()
                    self.assertEqual(self.shader.read_bytes(), b'cached shader')
                finally:
                    if target.is_symlink():
                        target.unlink()
                    else:
                        target.rmdir()
                    outside.rename(target)

    def test_redirected_title_refuses_without_deleting_external_data(self):
        outside = self.root / 'outside-cache'
        self.cache.rename(outside)
        self.link_directory(self.cache, outside)
        with self.assertRaisesRegex(ValueError, 'link|reparse|redirect'):
            self.clear()
        self.assertEqual((outside / 'shader.bin').read_bytes(), b'cached shader')

    def test_redirected_cache_entry_refuses_before_partial_deletion(self):
        outside = self.root / 'save-data'
        outside.mkdir()
        (outside / 'save.dat').write_bytes(b'precious save')
        self.link_directory(self.cache / 'redirect', outside)
        with self.assertRaisesRegex(ValueError, 'link|reparse|redirect'):
            self.clear()
        self.assertEqual(self.shader.read_bytes(), b'cached shader')
        self.assertEqual((outside / 'save.dat').read_bytes(), b'precious save')

    @unittest.skipUnless(os.name == 'nt', 'Windows junction behavior')
    def test_junction_target_refuses_without_deleting_external_data(self):
        import _winapi
        outside = self.root / 'junction-cache'
        self.cache.rename(outside)
        _winapi.CreateJunction(str(outside), str(self.cache))
        with self.assertRaisesRegex(ValueError, 'link|reparse|redirect'):
            self.clear()
        self.assertEqual((outside / 'shader.bin').read_bytes(), b'cached shader')

    def test_io_failure_is_reported_and_lock_released(self):
        with patch.object(self.cache_module.shutil, 'rmtree', side_effect=OSError('device unavailable')):
            with self.assertRaisesRegex(OSError, 'device unavailable'):
                self.clear()
        self.assertEqual(self.shader.read_bytes(), b'cached shader')
        with order1886.session_lock(self.state):
            pass

    @unittest.skipUnless(os.name == 'nt', 'Windows read-only file behavior')
    def test_read_only_shader_failure_is_reported(self):
        self.shader.chmod(stat.S_IREAD)
        try:
            with self.assertRaises(PermissionError):
                self.clear()
            self.assertEqual(self.shader.read_bytes(), b'cached shader')
        finally:
            self.shader.chmod(stat.S_IWRITE | stat.S_IREAD)


if __name__ == '__main__':
    unittest.main()
