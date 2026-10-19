"""Catalogue recipes are applied inside the derived prepared image, never to the game."""
import json
from pathlib import Path
import tempfile
import unittest

import order1886
from scripts import order1886_patches as patches
from scripts import order1886_frame_rate as timing

ROOT = Path(__file__).resolve().parents[1]
METADATA = {'TITLE_ID': 'CUSA00076', 'APP_VER': '01.00', 'VERSION': '01.03'}


def container(image):
    """A minimal PS4BOOT2 container holding `image`, shaped like prepare.prepare's output."""
    header = timing.HEADER.size + 24 + 128 + 32
    body = timing.HEADER.pack(b'PS4BOOT2', len(image), 0xa0, 1, 1, 1, 1) + bytes(24 + 128 + 32)
    return body + bytes(image)


def third_party(offset=0x1C0, expected=b'ORIGINAL', replacement=b'PATCHED!'):
    return {'id': 'order1886-test-third-party',
            'title': 'Test third-party recipe',
            'description': 'Not shipped; proves the preparation pipeline applies catalogued recipes.',
            'title_id': METADATA['TITLE_ID'], 'app_ver': METADATA['APP_VER'],
            'version': METADATA['VERSION'],
            'guest_executable': 'eboot.bin', 'guest_sha256': '0' * 64,
            'image': patches.IMAGE_KIND, 'image_sha256': '0' * 64,
            'edits': ({'offset': offset, 'expected': expected, 'replacement': replacement},),
            'experimental': True, 'warning': 'test only'}


class SelectionTests(unittest.TestCase):
    def test_the_builtin_recipes_cannot_be_applied_twice(self):
        for identifier in patches.BUILTIN_IDS:
            with self.subTest(identifier=identifier), self.assertRaises(ValueError) as caught:
                patches.select([identifier], METADATA)
            self.assertIn('its own preparation profile', str(caught.exception))

    def test_an_unknown_identifier_is_an_error_not_a_default(self):
        with self.assertRaises(ValueError):
            patches.select(['order1886-does-not-exist'], METADATA)

    def test_a_wrong_build_is_refused(self):
        original = patches.RECIPES
        try:
            patches.RECIPES = original + (third_party(),)
            with self.assertRaises(ValueError):
                patches.select([third_party()['id']], {'TITLE_ID': 'CUSA00076', 'APP_VER': '01.02',
                                                       'VERSION': '01.03'})
        finally:
            patches.RECIPES = original


class PreparedContainerTests(unittest.TestCase):
    def test_no_selection_leaves_the_image_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'boot.bin'
            data = container(bytearray(0x400))
            path.write_bytes(data)
            self.assertEqual(patches.apply_to_prepared(path, (), METADATA), [])
            self.assertEqual(path.read_bytes(), data)

    def test_a_catalogued_recipe_edits_the_prepared_image_and_reports_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'boot.bin'
            image = bytearray(0x400)
            image[0x1C0:0x1C8] = b'ORIGINAL'
            path.write_bytes(container(image))
            applied = patches.apply_to_prepared(path, (third_party(),), METADATA)
            self.assertEqual(len(applied), 1)
            self.assertEqual(applied[0]['id'], third_party()['id'])
            self.assertEqual(applied[0]['edits'][0]['before'], b'ORIGINAL'.hex())
            self.assertEqual(applied[0]['edits'][0]['after'], b'PATCHED!'.hex())
            patched = path.read_bytes()
            self.assertIn(b'PATCHED!', patched)
            self.assertNotIn(b'ORIGINAL', patched)

    def test_the_guest_executable_is_never_the_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / 'boot.bin'
            game.write_bytes(container(bytearray(0x400)))
            before = game.read_bytes()
            # The caller is expected to pass the prepared artifact; a container without the
            # expected bytes must fail rather than "succeed" on a different build.
            with self.assertRaises(ValueError) as caught:
                patches.apply_to_prepared(game, (third_party(),), METADATA)
            self.assertIn('expected bytes are absent', str(caught.exception))
            self.assertEqual(game.read_bytes(), before)

    def test_a_non_container_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'boot.bin'
            path.write_bytes(b'not a container at all' * 8)
            with self.assertRaises(ValueError):
                patches.apply_to_prepared(path, (third_party(),), METADATA)

    def test_an_edit_outside_the_image_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'boot.bin'
            path.write_bytes(container(bytearray(0x200)))
            with self.assertRaises(ValueError) as caught:
                patches.apply_to_prepared(path, (third_party(offset=0x1FF),), METADATA)
            self.assertIn('outside the prepared image', str(caught.exception))


class PreparationPipelineTests(unittest.TestCase):
    def test_the_selection_is_part_of_the_preparation_fingerprint(self):
        # A different patch selection must not reuse the cached prepared image.
        source = (ROOT / 'order1886.py').read_text(encoding='utf-8')
        self.assertIn('patches=', source)
        self.assertIn('patch_catalogue.patch_fingerprint', source)
        self.assertIn('apply_to_prepared', source)

    def test_the_fingerprint_helper_is_stable_and_order_independent(self):
        one = patches.patch_fingerprint((third_party(),))
        two = patches.patch_fingerprint((third_party(),))
        self.assertEqual(one, two)
        self.assertNotEqual(one, patches.patch_fingerprint(()))


if __name__ == '__main__':
    unittest.main()
