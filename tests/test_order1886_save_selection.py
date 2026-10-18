"""Selected backup routing uses temporary state, never player saves or a game process."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from launcher import order1886_launcher as launcher
import order1886


class SaveSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.state = self.base / 'state'
        self.game = self.base / 'game'
        self.game.mkdir()
        self.original = self.game / 'eboot.bin'
        self.original.write_bytes(b'original game')
        self.save = self.state / 'savedata/1/CUSA00035/Playthrough00/SYSTEM.DAT'
        self.save.parent.mkdir(parents=True)
        self.save.write_bytes(b'selected checkpoint')
        self.name = order1886.save_backup.backup(self.state).name
        self.save.write_bytes(b'current checkpoint')
        self.app = launcher.DesktopLauncher.__new__(launcher.DesktopLauncher)
        self.app.state, self.app.root = self.state, Mock()
        self.app.values = {'game_dir': str(self.game)}
        self.app.language, self.app.busy, self.app.current_page = 'en', False, 'game'
        self.app.backup_list = Mock()
        self.app.backup_list.curselection.return_value = (0,)
        self.app.backup_list.get.return_value = self.name
        self.app.refresh_backups = Mock()
        self.app.save_page_settings = Mock(return_value=True)

    def test_selected_backup_is_restored_before_play_and_current_save_is_retained(self):
        def start(mode):
            self.assertEqual(mode, 'play')
            self.assertEqual(self.save.read_bytes(), b'selected checkpoint')
        with patch('tkinter.messagebox.askyesno', return_value=True), \
             patch.object(launcher.Launcher, 'run', side_effect=start) as run:
            self.app.run('play')
        run.assert_called_once_with('play')
        self.assertIn(b'current checkpoint', [p.read_bytes() for p in
            (self.state / 'savedata_backups').glob('*/1/CUSA00035/Playthrough00/SYSTEM.DAT')])
        self.assertEqual(self.original.read_bytes(), b'original game')

    def test_cancelled_restore_does_not_launch_or_change_saves(self):
        with patch('tkinter.messagebox.askyesno', return_value=False), \
             patch.object(launcher.Launcher, 'run') as run:
            self.app.run('play')
        run.assert_not_called()
        self.assertEqual(self.save.read_bytes(), b'current checkpoint')

    def test_verify_never_restores_selected_backup(self):
        with patch('tkinter.messagebox.askyesno') as ask, patch.object(launcher.Launcher, 'run') as run:
            self.app.run('verify')
        ask.assert_not_called()
        run.assert_called_once_with('verify')
        self.assertEqual(self.save.read_bytes(), b'current checkpoint')

    def test_other_pages_do_not_restore_a_hidden_selection(self):
        self.app.current_page = 'home'
        with patch('tkinter.messagebox.askyesno') as ask, patch.object(launcher.Launcher, 'run') as run:
            self.app.run('play')
        ask.assert_not_called()
        run.assert_called_once_with('play')
        self.assertEqual(self.save.read_bytes(), b'current checkpoint')

    def test_stopping_an_owned_session_does_not_restore(self):
        self.app.busy = True
        with patch('tkinter.messagebox.askyesno') as ask, patch.object(launcher.Launcher, 'run') as run:
            self.app.run('play')
        ask.assert_not_called()
        run.assert_called_once_with('play')
        self.assertEqual(self.save.read_bytes(), b'current checkpoint')

    def test_external_session_blocks_restore_and_launch(self):
        with order1886.session_lock(self.state), \
             patch('tkinter.messagebox.askyesno', return_value=True), \
             patch('tkinter.messagebox.showerror') as error, \
             patch.object(launcher.Launcher, 'run') as run:
            self.app.run('play')
        run.assert_not_called()
        error.assert_called_once()
        self.assertEqual(self.save.read_bytes(), b'current checkpoint')

    def test_failed_restore_does_not_launch_with_the_wrong_save(self):
        with patch('tkinter.messagebox.askyesno', return_value=True), \
             patch.object(order1886.save_backup, 'restore', side_effect=OSError('restore failed')), \
             patch('tkinter.messagebox.showerror') as error, \
             patch.object(launcher.Launcher, 'run') as run:
            self.app.run('play')
        run.assert_not_called()
        error.assert_called_once()
        self.assertEqual(self.save.read_bytes(), b'current checkpoint')

    def test_restore_without_selection_explains_the_required_action(self):
        self.app.backup_list.curselection.return_value = ()
        with patch('tkinter.messagebox.showinfo') as notice:
            self.app.restore_saves()
        notice.assert_called_once()
        self.assertEqual(self.save.read_bytes(), b'current checkpoint')


if __name__ == '__main__':
    unittest.main()
