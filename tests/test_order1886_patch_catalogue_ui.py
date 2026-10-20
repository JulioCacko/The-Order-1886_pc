"""The catalogue reaches the launcher: selection, snapshot rows and the backend command."""
from pathlib import Path
import tempfile
import unittest

from launcher import order1886_common as launcher
from launcher import order1886_worker as worker
from scripts import order1886_patches as patches

ROOT = Path(__file__).resolve().parents[1]
BUILTIN = patches.BUILTIN_IDS[0]


def values(**overrides):
    base = {'game_dir': str(ROOT / 'game'), 'display_mode': 'windowed', 'vsync': True,
            'show_fps': False, 'mouse_look': True, 'mouse_sensitivity': 100,
            'mouse_invert_y': False, 'readbacks': 'relaxed', 'performance_capture': False,
            'frame_rate': 30, 'aspect_ratio': 'original'}
    base.update(overrides)
    return base


class SelectionSettingTests(unittest.TestCase):
    def test_an_empty_selection_is_the_default_and_adds_no_argument(self):
        command = launcher.backend_command(values(), 'play')
        self.assertNotIn('--patches', command)
        self.assertEqual(launcher.load_launch_settings(ROOT / 'out/none', {})['selected_patches'], [])

    def test_a_selection_reaches_the_backend_command(self):
        command = launcher.backend_command(values(selected_patches=['a', 'b']), 'play')
        self.assertIn('--patches', command)
        self.assertEqual(command[command.index('--patches') + 1], 'a,b')

    def test_selection_validation_refuses_unknown_and_builtin_ids(self):
        self.assertEqual(patches.validate_selection([]), [])
        with self.assertRaises(ValueError) as caught:
            patches.validate_selection(['order1886-not-a-recipe'])
        self.assertIn('Unknown patch id', str(caught.exception))
        with self.assertRaises(ValueError) as caught:
            patches.validate_selection([BUILTIN])
        self.assertIn('configured by the game frame rate', str(caught.exception))
        for invalid in ('id', None, [1], [None]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                patches.validate_selection(invalid)

    def test_a_duplicate_selection_is_reduced_to_one_entry(self):
        # Only built-in recipes exist today, so the duplicate rule is proven through the
        # validator's dedupe on a catalogued id it does not refuse for another reason.
        known = [item['id'] for item in patches.RECIPES if item['id'] not in patches.BUILTIN_IDS]
        if not known:
            self.skipTest('no non-built-in recipe is catalogued yet, so nothing is selectable')
        self.assertEqual(patches.validate_selection([known[0], known[0]]), [known[0]])

    def test_the_worker_refuses_the_same_ids_through_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = worker.Worker(Path(temporary), ROOT)
            self.assertEqual(app.dispatch('settings.set', {'values': {'selected_patches': []}})['settings']['selected_patches'], [])
            with self.assertRaises(ValueError):
                app.dispatch('settings.set', {'values': {'selected_patches': [BUILTIN]}})
            with self.assertRaises(ValueError):
                app.dispatch('settings.set', {'values': {'selected_patches': ['nope']}})


class SnapshotCatalogueTests(unittest.TestCase):
    def test_the_snapshot_lists_every_recipe_with_its_reason(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = worker.Worker(Path(temporary), ROOT)
            rows = app.snapshot()['patches']
            self.assertEqual(len(rows), len(patches.RECIPES))
            for row in rows:
                self.assertTrue(row['id'] and row['title'] and row['description'])
                if row['builtin']:
                    self.assertFalse(row['available'])
                    self.assertIn('Configured by the game frame rate', row['reason'])
                else:
                    self.assertTrue(row['reason'] or row['available'])

    def test_an_unusable_game_folder_marks_rows_unavailable_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = worker.Worker(Path(temporary), ROOT)
            rows = app.snapshot()['patches']
            for row in rows:
                self.assertFalse(row['available'])
                self.assertTrue(row['reason'])


if __name__ == '__main__':
    unittest.main()
