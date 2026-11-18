"""Mixed-case dumps: enumeration, replacement case and resolve() (fixtures only)."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import order1886_mods as mods
import order1886_ui_extract as ui


def _case_sensitive():
    """True when ps4/ and PS4/ can coexist here (posix dumps); NTFS folds them into one folder."""
    with tempfile.TemporaryDirectory() as folder:
        (Path(folder) / 'ps4').mkdir()
        return not (Path(folder) / 'PS4').exists()


needs_case_sensitive_fs = unittest.skipUnless(
    _case_sensitive(), 'ps4/ and PS4/ siblings need a case-sensitive file system (posix dumps)')


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


class ResolveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.game = Path(temporary.name)
        self.ns = self.game / ui.NAMESPACE

    def test_exact_case_wins(self):
        put(self.ns / 'primary/p1/v1/res', b'exact')
        self.assertEqual(ui.resolve(self.game, 'primary/p1/v1/res').read_bytes(), b'exact')

    def test_folds_a_single_unique_variant(self):
        game = self.game / 'upper'                      # only PS4/ exists
        put(game / '_data/1408209885/PS4/primary/p2/v1/res', b'upper')
        self.assertEqual(ui.resolve(game, 'primary/p2/v1/res').read_bytes(), b'upper')

    @needs_case_sensitive_fs
    def test_ambiguous_siblings_prefer_the_written_case(self):
        put(self.ns / 'primary/p1/v1/res', b'a')
        put(self.game / '_data/1408209885/PS4/primary/p1/v1/res', b'b')
        # An exact lowercase path is what the guest asks for; fold never jumps branches.
        self.assertEqual(ui.resolve(self.game, 'primary/p1/v1/res').read_bytes(), b'a')

    def test_missing_is_none(self):
        put(self.ns / 'primary/p1/v1', b'directory')
        self.assertIsNone(ui.resolve(self.game, 'primary/p1/v1/res'))

    def test_resource_only_in_the_update_tree_folds_to_sibling(self):
        # Mixed-case dump: the walked lowercase branch lacks the resource entirely
        # (update extraction put it only in PS4/); the guest would fold to the sibling.
        put(self.ns / 'primary/p1/v1/res', b'other')
        put(self.game / '_data/1408209885/PS4/primary/p2/v1/res', b'upper only')
        self.assertEqual(ui.resolve(self.game, 'primary/p2/v1/res').read_bytes(), b'upper only')


class StaleBaseTests(unittest.TestCase):
    """A ps4/ copy that differs from the PS4/ update makes the guest show old art;
    prepare() must refuse to paint prompts on it until the dump is merged."""

    def setUp(self):
        import order1886_prompts as prompts
        self.prompts = prompts
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.game = Path(temporary.name)

    @needs_case_sensitive_fs
    def test_diverged_duplicate_is_stale(self):
        put(self.game / '_data/1408209885/ps4/primary/p1/v1/res', b'base 1.00')
        put(self.game / '_data/1408209885/PS4/primary/p1/v1/res', b'update 1.02')
        self.assertTrue(self.prompts._base_is_stale(self.game, 'primary/p1/v1/res'))

    def test_merged_duplicate_is_not_stale(self):
        put(self.game / '_data/1408209885/ps4/primary/p1/v1/res', b'update 1.02')
        put(self.game / '_data/1408209885/PS4/primary/p1/v1/res', b'update 1.02')
        self.assertFalse(self.prompts._base_is_stale(self.game, 'primary/p1/v1/res'))

    def test_single_tree_is_not_stale(self):
        put(self.game / '_data/1408209885/ps4/primary/p1/v1/res', b'base')
        self.assertFalse(self.prompts._base_is_stale(self.game, 'primary/p1/v1/res'))
        put(self.game / '_data/1408209885/PS4/primary/p2/v1/res', b'update only')
        self.assertFalse(self.prompts._base_is_stale(self.game, 'primary/p2/v1/res'))


class MergeUpdateTests(unittest.TestCase):
    @needs_case_sensitive_fs
    def test_plan_lists_replacements_and_additions(self):
        import order1886_merge_update as merge
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / '_data/1408209885'
        base, update = root / 'ps4', root / 'PS4'
        put(base / 'primary/p1/v1/same', b'same')
        put(update / 'primary/p1/v1/same', b'same')
        put(base / 'primary/p1/v1/old', b'1.00')
        put(update / 'primary/p1/v1/old', b'1.02')
        put(update / 'primary/p2/v1/new', b'only in update')
        actions = dict(merge.plan(base, update))
        self.assertEqual(actions, {Path('primary/p1/v1/old'): 'replace',
                                   Path('primary/p2/v1/new'): 'add'})


class OverlayMixedCaseTests(unittest.TestCase):
    """The mirror may hold ps4/ and PS4/ siblings; a replacement must land on the exact
    case the guest opens, and enumeration must not refuse the dump (case-sensitive FS)."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.game, self.state, self.mods = [self.base / name for name in ('game', 'state', 'mods')]
        self.state.mkdir()
        put(self.game / '_data/1408209885/ps4/primary/p1/v1/res', b'lower original')
        put(self.game / '_data/1408209885/PS4/primary/p2/v1/res', b'upper original')
        put(self.game / '_data/keep', b'untouched')
        put(self.game / 'eboot.bin', b'eboot')
        put(self.game / 'archivemap.bin', b'index')

    def test_mirror_and_replace(self):
        if os.name == 'nt':
            self.skipTest('case-sensitive enumeration only applies to posix dumps')
        put(self.mods / 'Set/_data/1408209885/ps4/primary/p1/v1/res', b'replacement')
        put(self.mods / 'Set/readme.txt', b'ok')
        overlay = mods.build_overlay(self.game, self.state, self.mods, True, ['Set'])
        self.assertNotEqual(overlay, self.game)
        self.assertEqual((overlay / '_data/1408209885/ps4/primary/p1/v1/res').read_bytes(),
                         b'replacement')
        self.assertEqual((overlay / '_data/1408209885/PS4/primary/p2/v1/res').read_bytes(),
                         b'upper original')                       # sibling tree preserved
        self.assertEqual((overlay / '_data/keep').read_bytes(), b'untouched')

    def test_disabling_restores_original_mount(self):
        overlay = mods.build_overlay(self.game, self.state, self.mods, False, [])
        self.assertEqual(overlay, self.game)

    @needs_case_sensitive_fs
    def test_mod_folder_case_conflict_stays_rejected(self):
        put(self.mods / 'Both/_data/1408209885/ps4/primary/p1/v1/res', b'one')
        put(self.mods / 'Both/_data/1408209885/PS4/primary/p1/v1/other', b'two')
        with self.assertRaises(ValueError):
            mods.plan(self.game, self.mods, True, ['Both'])

    def test_exact_case_preferred_over_folded_canonical(self):
        if os.name == 'nt':
            self.skipTest('case-sensitive enumeration only applies to posix dumps')
        # A mod path that matches only the uppercase tree folds to it, not to ps4/.
        put(self.mods / 'Up/_data/1408209885/ps4/primary/p2/v1/res', b'folded')
        replacements, _ = mods.plan(self.game, self.mods, True, ['Up'])
        self.assertEqual([str(rel) for rel, _src in replacements],
                         [str(Path('_data/1408209885/ps4/primary/p2/v1/res'))])


if __name__ == '__main__':
    unittest.main()
