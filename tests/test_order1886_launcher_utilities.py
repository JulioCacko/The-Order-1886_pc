"""Launcher utility routing without touching Steam or real shader caches."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tests.test_order1886_launcher import launcher
import order1886
import order1886_cache
import order1886_steam


class LauncherUtilityTests(unittest.TestCase):
    def setUp(self):
        self.app = SimpleNamespace(root=Mock(), state=Path('owned-state'), busy=False, language='en')
        self.app.tr = launcher.Launcher.tr.__get__(self.app)

    def test_cache_clear_requires_confirmation_and_routes_selected_state(self):
        with patch('tkinter.messagebox.askyesno', return_value=True), \
             patch('tkinter.messagebox.showinfo') as info, \
             patch.object(order1886_cache, 'clear_shader_cache', return_value=True) as clear:
            launcher.DesktopLauncher.clear_cache(self.app)
        clear.assert_called_once_with(self.app.state)
        info.assert_called_once()

    def test_cancelled_or_busy_cache_clear_does_not_delete(self):
        for busy in (False, True):
            self.app.busy = busy
            with patch('tkinter.messagebox.askyesno', return_value=False), \
                 patch('tkinter.messagebox.showerror'), \
                 patch.object(order1886_cache, 'clear_shader_cache') as clear:
                launcher.DesktopLauncher.clear_cache(self.app)
            clear.assert_not_called()

    def test_cache_failures_are_reported(self):
        with patch('tkinter.messagebox.askyesno', return_value=True), \
             patch('tkinter.messagebox.showerror') as error, \
             patch.object(order1886_cache, 'clear_shader_cache', side_effect=RuntimeError('Game is running')):
            launcher.DesktopLauncher.clear_cache(self.app)
        self.assertIn('Game is running', error.call_args.args[1])

    def test_steam_action_routes_installation_and_explains_restart(self):
        with patch.object(order1886_steam, 'add_to_steam', return_value=Path('shortcuts.vdf')) as add, \
             patch('tkinter.messagebox.showinfo') as info:
            launcher.DesktopLauncher.add_steam(self.app)
        add.assert_called_once_with(launcher.ROOT, state=self.app.state)
        self.assertIn('Steam', info.call_args.args[1])

    def test_steam_failure_is_actionable(self):
        with patch.object(order1886_steam, 'add_to_steam', side_effect=order1886_steam.SteamIntegrationError('Close Steam first')), \
             patch('tkinter.messagebox.showerror') as error:
            launcher.DesktopLauncher.add_steam(self.app)
        self.assertIn('Close Steam first', error.call_args.args[1])


if __name__ == '__main__':
    unittest.main()
