import datetime
import struct
import tempfile
import unittest
from pathlib import Path

import paths  # noqa: F401  (puts scripts/ on sys.path)
import save_backup


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


class SaveBackupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.user = Path(self.temp.name)
        self.save = self.user / 'savedata' / '1' / 'CUSA01623' / 'AUTOSAVE' / 'data.bin'
        self.clock = datetime.datetime(2026, 10, 9, 18, 0, 0)

    def tearDown(self):
        self.temp.cleanup()

    def tick(self):
        self.clock += datetime.timedelta(minutes=1)
        return self.clock

    def test_copies_savedata(self):
        write(self.save, 'v1')
        made = save_backup.backup(self.user, now=self.tick())
        self.assertEqual(made.name, '20261009-180100')
        self.assertEqual((made / self.save.relative_to(self.user / 'savedata')).read_text(), 'v1')

    def test_no_backup_without_saves(self):
        self.assertIsNone(save_backup.backup(self.user, now=self.tick()))
        (self.user / 'savedata').mkdir()
        self.assertIsNone(save_backup.backup(self.user, now=self.tick()))
        self.assertEqual(save_backup.list_backups(self.user), [])

    def test_same_second_gets_unique_name(self):
        write(self.save, 'v1')
        first = save_backup.backup(self.user, now=self.clock)
        second = save_backup.backup(self.user, now=self.clock)
        self.assertNotEqual(first, second)
        self.assertEqual(len(save_backup.list_backups(self.user)), 2)

    def test_same_second_backups_sort_by_creation_sequence(self):
        write(self.save, 'v1')
        made = [save_backup.backup(self.user, now=self.clock, keep=20) for _ in range(12)]
        self.assertEqual(save_backup.list_backups(self.user), [p.name for p in reversed(made)])

    def test_same_second_retention_keeps_latest_contents_and_unique_names(self):
        made = []
        for index in range(14):
            write(self.save, f'version {index}')
            made.append(save_backup.backup(self.user, now=self.clock))
            self.assertTrue(made[-1].is_dir(), 'the backup just created must survive pruning')
        self.assertEqual(len(set(made)), len(made))
        expected = list(reversed(made[-save_backup.KEEP:]))
        self.assertEqual(save_backup.list_backups(self.user), [p.name for p in expected])
        relative = self.save.relative_to(self.user / 'savedata')
        self.assertEqual([(p / relative).read_text() for p in expected],
                         [f'version {i}' for i in range(13, 3, -1)])

    def test_keeps_newest_ten(self):
        write(self.save, 'v')
        made = [save_backup.backup(self.user, now=self.tick()) for _ in range(12)]
        kept = save_backup.list_backups(self.user)
        self.assertEqual(len(kept), save_backup.KEEP)
        self.assertEqual(kept[0], made[-1].name)  # newest first
        self.assertFalse(made[0].exists())
        self.assertFalse(made[1].exists())

    def test_same_second_restore_keeps_the_safety_backup(self):
        for index in range(12):
            write(self.save, f'version {index}')
            save_backup.backup(self.user, now=self.clock)
        oldest = save_backup.list_backups(self.user)[-1]
        write(self.save, 'current progress')
        safety = save_backup.restore(self.user, oldest, now=self.clock)
        relative = self.save.relative_to(self.user / 'savedata')
        self.assertEqual(self.save.read_text(), 'version 2')
        self.assertEqual((safety / relative).read_text(), 'current progress')
        self.assertEqual(save_backup.list_backups(self.user)[0], safety.name)
        self.assertEqual(len(save_backup.list_backups(self.user)), save_backup.KEEP)

    def test_restore_backs_up_current_first(self):
        write(self.save, 'old')
        old = save_backup.backup(self.user, now=self.tick())
        write(self.save, 'new')
        write(self.save.parent / 'extra.bin', 'x')
        safety = save_backup.restore(self.user, old.name, now=self.tick())
        self.assertEqual(self.save.read_text(), 'old')
        self.assertFalse((self.save.parent / 'extra.bin').exists())
        self.assertEqual((safety / self.save.relative_to(self.user / 'savedata')).read_text(), 'new')

    def test_restore_oldest_when_full(self):
        write(self.save, 'oldest')
        oldest = save_backup.backup(self.user, now=self.tick())
        write(self.save, 'later')
        for _ in range(save_backup.KEEP - 1):
            save_backup.backup(self.user, now=self.tick())
        save_backup.restore(self.user, oldest.name, now=self.tick())
        self.assertEqual(self.save.read_text(), 'oldest')
        self.assertEqual(len(save_backup.list_backups(self.user)), save_backup.KEEP)

    def test_restore_rejects_unknown_or_unsafe_names(self):
        write(self.save, 'v')
        for name in ('missing', '..', '../savedata', ''):
            with self.assertRaises(ValueError):
                save_backup.restore(self.user, name, now=self.tick())
        self.assertEqual(self.save.read_text(), 'v')


class SaveImportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.user, self.other = root / 'user', root / 'other'
        self.title = self.user / 'savedata' / '1' / 'CUSA00035'
        self.clock = datetime.datetime(2026, 10, 24, 12, 0, 0)

    def tearDown(self):
        self.temp.cleanup()

    def save(self, title_dir, name, text):
        write(title_dir / name / 'SYSTEM.DAT', text)
        write(title_dir / (name + '.sce_sys') / 'param.bin', 'meta-' + text)

    def test_imports_from_savedata_root_and_backs_up_first(self):
        self.save(self.title, 'Playthrough00', 'mine')
        self.save(self.title, 'Profile', 'my-profile')
        self.save(self.other / 'savedata' / '1' / 'CUSA00035', 'Playthrough00', 'theirs')
        names, safety = save_backup.import_saves(self.user, self.other / 'savedata', now=self.clock)
        self.assertEqual(names, ['Playthrough00'])
        self.assertEqual((self.title / 'Playthrough00' / 'SYSTEM.DAT').read_text(), 'theirs')
        self.assertEqual((self.title / 'Playthrough00.sce_sys' / 'param.bin').read_text(), 'meta-theirs')
        self.assertEqual((self.title / 'Profile' / 'SYSTEM.DAT').read_text(), 'my-profile')
        self.assertEqual((safety / '1' / 'CUSA00035' / 'Playthrough00' / 'SYSTEM.DAT').read_text(), 'mine')

    def test_imports_a_single_save_into_an_empty_installation(self):
        source = self.other / 'CUSA00035'
        self.save(source, 'Playthrough00', 'theirs')
        self.save(source, 'Profile', 'profile')
        names, safety = save_backup.import_saves(self.user, source / 'Playthrough00', now=self.clock)
        self.assertEqual(names, ['Playthrough00'])
        self.assertIsNone(safety)
        self.assertEqual((self.title / 'Playthrough00' / 'SYSTEM.DAT').read_text(), 'theirs')
        self.assertFalse((self.title / 'Profile').exists())

    def sfo(self, path, entries):
        """A param.sfo with text (str) and integer (int) entries, as a PS4 export holds it."""
        keys, values, index = b'', b'', b''
        for key, value in entries.items():
            data = value.to_bytes(4, 'little') if isinstance(value, int) else value.encode() + b'\0'
            index += struct.pack('<HHIII', len(keys), 0x0404 if isinstance(value, int) else 0x0204,
                                 len(data), len(data), len(values))
            keys += key.encode() + b'\0'
            values += data
        header = struct.pack('<4sIIII', b'\0PSF', 0x101, 20 + len(index), 20 + len(index) + len(keys),
                             len(entries))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(header + index + keys + values)

    def test_converts_a_decrypted_ps4_export(self):
        export = self.other / 'CUSA00035' / '10000001_CUSA00035_Playthrough00'
        write(export / 'SYSTEM.DAT', 'chapter 11')
        write(export / 'sce_sys' / 'icon0.png', 'icon')
        write(export / 'sce_sys' / 'keystone', 'key')
        self.sfo(export / 'sce_sys' / 'param.sfo', {
            'MAINTITLE': 'CHAPTER XI - The United India House', 'SUBTITLE': 'The Order: 1886',
            'DETAIL': 'Save Data', 'SAVEDATA_DIRECTORY': 'Playthrough00', 'SAVEDATA_LIST_PARAM': 7,
            'TITLE_ID': 'CUSA00035'})
        names, _ = save_backup.import_saves(self.user, self.other / 'CUSA00035', now=self.clock)
        self.assertEqual(names, ['Playthrough00'])
        self.assertEqual((self.title / 'Playthrough00' / 'SYSTEM.DAT').read_text(), 'chapter 11')
        self.assertFalse((self.title / 'Playthrough00' / 'sce_sys').exists())
        meta = self.title / 'Playthrough00.sce_sys'
        self.assertEqual((meta / 'icon0.png').read_text(), 'icon')
        title, subtitle, detail, user_param, _, _, _ = save_backup.PARAM_BIN.unpack(
            (meta / 'param.bin').read_bytes())
        self.assertEqual(title.rstrip(b'\0'), b'CHAPTER XI - The United India House')
        self.assertEqual((subtitle.rstrip(b'\0'), detail.rstrip(b'\0'), user_param),
                         (b'The Order: 1886', b'Save Data', 7))

    def test_rejects_an_export_of_another_game(self):
        export = self.other / 'CUSA01623_SAVE'
        write(export / 'data.bin', 'x')
        self.sfo(export / 'sce_sys' / 'param.sfo', {'TITLE_ID': 'CUSA01623', 'SAVEDATA_DIRECTORY': 'SAVE'})
        with self.assertRaisesRegex(ValueError, 'not The Order'):
            save_backup.import_saves(self.user, export, now=self.clock)

    def test_rejects_an_export_without_a_title_id(self):
        export = self.other / 'UNNAMED_SAVE'
        write(export / 'data.bin', 'x')
        self.sfo(export / 'sce_sys' / 'param.sfo', {'SAVEDATA_DIRECTORY': 'Playthrough00'})
        with self.assertRaisesRegex(ValueError, 'an unnamed title, not The Order'):
            save_backup.import_saves(self.user, export, now=self.clock)
        self.assertFalse((self.title / 'Playthrough00').exists())

    def test_imports_runtime_saves_and_exports_from_one_folder(self):
        source = self.other / 'CUSA00035'
        self.save(source, 'Playthrough00', 'runtime')
        export = source / '10000001_CUSA00035_Playthrough01'
        write(export / 'SYSTEM.DAT', 'exported')
        self.sfo(export / 'sce_sys' / 'param.sfo', {'SAVEDATA_DIRECTORY': 'Playthrough01', 'TITLE_ID': 'CUSA00035'})
        names, _ = save_backup.import_saves(self.user, source, now=self.clock)
        self.assertEqual(sorted(names), ['Playthrough00', 'Playthrough01'])
        self.assertEqual((self.title / 'Playthrough00' / 'SYSTEM.DAT').read_text(), 'runtime')
        self.assertEqual((self.title / 'Playthrough01' / 'SYSTEM.DAT').read_text(), 'exported')

    def test_rejects_encrypted_ps4_saves(self):
        source = self.other / 'CUSA00035'
        write(source / 'Playthrough00', 'pfs image')
        (source / 'Playthrough00.bin').write_bytes(b'pfsSKKey\x05\x00' + bytes(86))
        with self.assertRaisesRegex(ValueError, 'encrypted PS4 saves'):
            save_backup.import_saves(self.user, self.other, now=self.clock)

    def test_rejects_folders_without_saves_and_its_own_savedata(self):
        self.other.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'No saves found'):
            save_backup.import_saves(self.user, self.other, now=self.clock)
        self.save(self.title, 'Playthrough00', 'mine')
        with self.assertRaisesRegex(ValueError, 'already'):
            save_backup.import_saves(self.user, self.title, now=self.clock)
        self.assertEqual((self.title / 'Playthrough00' / 'SYSTEM.DAT').read_text(), 'mine')


if __name__ == '__main__':
    unittest.main()
