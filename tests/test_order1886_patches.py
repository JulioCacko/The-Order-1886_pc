"""Version-checked patch recipes refuse every image they were not verified against.

Only recipes bound to a real executable are catalogued, so every test here works on
synthetic guest images in a temporary directory and never on the game folder.
"""
from contextlib import contextmanager
import hashlib
import os
import struct
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from launcher import order1886_worker as worker
from paths import ROOT

sys.path.insert(0, str(ROOT / 'scripts'))
import order1886_display as display
import order1886_frame_rate as timing
from scripts import order1886_patches as patches

METADATA = {'TITLE_ID': 'CUSA00076', 'APP_VER': '01.00', 'VERSION': '01.03'}


def elf_image(size, sites=()):
    """A minimal plain ELF the SELF parser returns unchanged, with optional edit sites."""
    image = bytearray(size)
    image[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HHIQQQIHHHHHH', image, 16, 2, 62, 1, 0x1000, 64, 0, 0, 64, 56, 1, 0, 0, 0)
    struct.pack_into('<IIQQQQQQ', image, 64, 1, 5, 0, 0x1000, 0x1000, size, size, 0x1000)
    for offset, data in sites:
        image[offset:offset + len(data)] = data
    return bytes(image)


def matching_image(recipe):
    """A guest image carrying exactly the bytes this recipe expects where it edits."""
    size = max(edit['offset'] + len(edit['expected']) for edit in recipe['edits']) + 512
    return elf_image(size, [(edit['offset'], edit['expected']) for edit in recipe['edits']])


def bound_to(recipe, image):
    """The recipe re-verified against a synthetic image, so only the tested guard can fail."""
    return dict(recipe, image_sha256=hashlib.sha256(image).hexdigest(),
                guest_sha256=hashlib.sha256(image).hexdigest(),
                edits=tuple(dict(edit) for edit in recipe['edits']))


class RecipeCatalogueTests(unittest.TestCase):
    def test_catalogue_starts_with_the_two_recipes_the_project_already_verifies(self):
        self.assertEqual([item['id'] for item in patches.RECIPES],
                         ['order1886-a8ce-engine-60-v1', 'order1886-a8ce-16x9-v1'])

    def test_recipes_reuse_the_existing_modules_constants_and_verified_identity(self):
        sixty, wide = patches.RECIPES
        self.assertEqual(sixty['edits'][0]['offset'], timing.INSTRUCTION_RVA)
        self.assertEqual(sixty['edits'][0]['expected'], timing.EXPECTED_INSTRUCTION)
        self.assertEqual(sixty['edits'][0]['replacement'][:6], timing.EXPECTED_INSTRUCTION[:6])
        self.assertEqual(sixty['edits'][0]['replacement'],
                         bytes.fromhex(timing.recipe(60)['replacement_instruction']))
        self.assertEqual(sixty['edits'][0]['replacement'][6], 1)
        self.assertEqual(len(sixty['edits'][0]['replacement']), len(timing.EXPECTED_INSTRUCTION))
        self.assertEqual(wide['edits'][0]['offset'], display.INSTRUCTION_RVA)
        self.assertEqual(wide['edits'][0]['expected'], display.EXPECTED_INSTRUCTION)
        self.assertEqual(wide['edits'][0]['replacement'], display.REPLACEMENT_INSTRUCTION)
        for recipe in patches.RECIPES:
            with self.subTest(recipe=recipe['id']):
                self.assertTrue(recipe['title'])
                self.assertTrue(recipe['description'])
                self.assertEqual(recipe['guest_executable'], 'eboot.bin')
                self.assertEqual(recipe['guest_sha256'], timing.EXPECTED_SELF_SHA256)
                self.assertEqual(recipe['image_sha256'], timing.EXPECTED_ELF_SHA256)
                self.assertEqual(patches.target(recipe), timing.EXPECTED_METADATA)
                for edit in recipe['edits']:
                    self.assertEqual(len(edit['expected']), len(edit['replacement']))
                    self.assertLessEqual(edit['offset'] + len(edit['expected']),
                                         timing.EXPECTED_IMAGE_SIZE)

    def test_identities_are_unique_and_do_not_depend_on_dict_order(self):
        self.assertEqual(len({item['id'] for item in patches.RECIPES}), len(patches.RECIPES))
        for recipe in patches.RECIPES:
            with self.subTest(recipe=recipe['id']):
                self.assertRegex(patches.recipe_sha256(recipe), '^[0-9a-f]{64}$')
                reordered = dict(reversed(list(recipe.items())))
                self.assertEqual(patches.recipe_sha256(reordered), patches.recipe_sha256(recipe))
                self.assertEqual(patches.recipe(recipe['id']), recipe)
        with self.assertRaisesRegex(ValueError, 'Unknown patch recipe'):
            patches.recipe('order1886-invented-cheat-v1')
        with self.assertRaisesRegex(ValueError, 'Unknown patch recipe'):
            patches.recipe(7)


class RecipeRejectionTests(unittest.TestCase):
    def test_every_recipe_rejects_a_wrong_title_id_app_ver_and_version(self):
        for recipe in patches.RECIPES:
            image = matching_image(recipe)
            bound = bound_to(recipe, image)
            with self.subTest(recipe=recipe['id'], field='match'):
                self.assertIsNone(patches.validate_recipe(bound, image, dict(METADATA)))
            for name, wrong in (('TITLE_ID', 'CUSA99999'), ('APP_VER', '01.02'), ('VERSION', '01.00')):
                with self.subTest(recipe=recipe['id'], field=name):
                    error = patches.validate_recipe(bound, image, {**METADATA, name: wrong})
                    self.assertIn(name, error)
                    self.assertIn(wrong, error)

    def test_every_recipe_rejects_a_hash_mismatch_without_reading_the_edits(self):
        for recipe in patches.RECIPES:
            image = matching_image(recipe)
            bound = bound_to(recipe, image)
            other = elf_image(len(image))
            with self.subTest(recipe=recipe['id']):
                error = patches.validate_recipe(bound, other, dict(METADATA))
                self.assertIn('SHA256', error)
                self.assertIn(bound['image_sha256'], error)

    def test_every_recipe_rejects_an_edit_past_the_end_of_the_image(self):
        for recipe in patches.RECIPES:
            tiny = elf_image(1024)
            bound = bound_to(recipe, tiny)
            with self.subTest(recipe=recipe['id']):
                error = patches.validate_recipe(bound, tiny, dict(METADATA))
                self.assertIn(f"{recipe['edits'][0]['offset']:#x}", error)
                self.assertIn('byte guest image', error)

    def test_every_recipe_rejects_expected_bytes_that_do_not_match_the_image(self):
        for recipe in patches.RECIPES:
            image = bytearray(matching_image(recipe))
            edit = recipe['edits'][0]
            image[edit['offset']] ^= 0xFF
            corrupted = bytes(image)
            bound = bound_to(recipe, corrupted)
            with self.subTest(recipe=recipe['id']):
                error = patches.validate_recipe(bound, corrupted, dict(METADATA))
                self.assertIn(f"{edit['offset']:#x}", error)
                self.assertIn(edit['expected'].hex(), error)

    def test_validation_reports_an_empty_or_unreadable_guest_image(self):
        recipe = bound_to(patches.RECIPES[0], elf_image(4096))
        self.assertIn('empty', patches.validate_recipe(recipe, b'', dict(METADATA)))
        self.assertIn('bytes', patches.validate_recipe(recipe, 'not bytes', dict(METADATA)))


class RecipeApplicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.catalogue_recipe = patches.RECIPES[0]
        self.image = matching_image(self.catalogue_recipe)
        self.recipe = bound_to(self.catalogue_recipe, self.image)
        self.source = self.base / 'derived guest image.bin'
        self.source.write_bytes(self.image)
        self.source_sha256 = hashlib.sha256(self.image).hexdigest()
        self.destination = self.base / 'patched image.bin'

    def test_a_matching_image_is_patched_into_a_new_file_and_the_source_is_untouched(self):
        result = patches.apply_recipe(self.recipe, self.source, self.destination, dict(METADATA))
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_sha256)
        self.assertEqual(self.source.read_bytes(), self.image)
        patched = self.destination.read_bytes()
        self.assertEqual(len(patched), len(self.image))
        self.assertEqual(result['source'], str(self.source))
        self.assertEqual(result['source_sha256'], self.source_sha256)
        self.assertEqual(result['image_sha256'], hashlib.sha256(patched).hexdigest())
        self.assertEqual(result['recipe_id'], self.recipe['id'])
        self.assertEqual(result['recipe_sha256'], patches.recipe_sha256(self.recipe))
        self.assertTrue(result['applied'])
        self.assertFalse(result['gameplay_verified'])
        for edit, change in zip(self.recipe['edits'], result['edits']):
            with self.subTest(offset=change['offset']):
                start, end = edit['offset'], edit['offset'] + len(edit['replacement'])
                self.assertEqual(patched[start:end], edit['replacement'])
                self.assertEqual(change['before'], edit['expected'].hex())
                self.assertEqual(self.image[:start], patched[:start])
                self.assertEqual(self.image[end:], patched[end:])

    def test_in_place_patching_is_refused_and_nothing_is_written(self):
        same = self.base / '.' / 'derived guest image.bin'
        for destination in (self.source, same):
            with self.subTest(destination=destination), self.assertRaisesRegex(ValueError, 'in place'):
                patches.apply_recipe(self.recipe, self.source, destination, dict(METADATA))
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_sha256)

    def test_a_refused_image_writes_no_destination_and_no_leftover(self):
        other = elf_image(len(self.image))
        self.source.write_bytes(other)
        before = hashlib.sha256(other).hexdigest()
        for metadata, pattern in ((dict(METADATA), 'SHA256'),
                                  ({**METADATA, 'APP_VER': '01.02'}, 'APP_VER')):
            with self.subTest(pattern=pattern), self.assertRaisesRegex(ValueError, pattern):
                patches.apply_recipe(self.recipe, self.source, self.destination, metadata)
            self.assertFalse(self.destination.exists())
            self.assertFalse(self.destination.with_name(self.destination.name + '.tmp').exists())
            self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), before)

    def test_a_missing_source_is_named_and_created_nowhere(self):
        with self.assertRaisesRegex(ValueError, 'source image is missing'):
            patches.apply_recipe(self.recipe, self.base / 'absent.bin', self.destination, dict(METADATA))
        self.assertFalse(self.destination.exists())

    def test_a_caller_without_metadata_still_requires_the_verified_image(self):
        patched = bytearray(self.image)
        for edit in self.recipe['edits']:
            start = edit['offset']
            patched[start:start + len(edit['replacement'])] = edit['replacement']
        second = self.base / 'second copy.bin'
        result = patches.apply_recipe(self.recipe, self.source, second)
        self.assertEqual(second.read_bytes(), bytes(patched))
        self.assertEqual(result['target'], dict(METADATA))
        with self.assertRaisesRegex(ValueError, 'VERSION'):
            patches.apply_recipe(self.recipe, self.source, second, {**METADATA, 'VERSION': '01.02'})
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_sha256)

    def test_a_malformed_edit_is_refused_instead_of_raising(self):
        offset = self.recipe['edits'][0]['offset']
        for edits in (({'offset': 'first', 'expected': b'AB', 'replacement': b'ABC'},),
                      ({'offset': offset, 'expected': b'AB', 'replacement': b'ABC'},),
                      ({'offset': -1, 'expected': b'AB', 'replacement': b'CD'},)):
            with self.subTest(edits=edits):
                error = patches.validate_recipe(dict(self.recipe, edits=edits), self.image,
                                                dict(METADATA))
                self.assertIn('malformed edit', error)


def fixture_recipe(image, offset=0x1C0, expected=b'ORIGINAL', replacement=b'PATCHED!'):
    """A catalogue-shaped recipe whose edit lands inside a small synthetic image."""
    return dict(patches.RECIPES[0], id='order1886-fixture-v1', title='Fixture patch',
                description='Test-only recipe shape.',
                image_sha256=hashlib.sha256(image).hexdigest(),
                guest_sha256=hashlib.sha256(image).hexdigest(),
                edits=({'offset': offset, 'expected': expected, 'replacement': replacement},))


class GuestImageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.guest = elf_image(4096, [(0x1C0, b'ORIGINAL')])
        self.recipe = fixture_recipe(self.guest)

    def test_a_plain_elf_guest_is_addressed_unchanged(self):
        self.assertEqual(patches.decode(self.recipe, self.guest), self.guest)
        with self.assertRaisesRegex(ValueError, 'cannot address this executable'):
            patches.decode(self.recipe, b'not an executable')

    def test_the_catalogue_explains_why_a_selected_executable_cannot_take_a_recipe(self):
        with patch.object(patches, 'RECIPES', (self.recipe,)):
            listed = patches.catalogue(self.guest, dict(METADATA))
            self.assertEqual(len(listed), 1)
            self.assertTrue(listed[0]['applicable'])
            self.assertEqual(listed[0]['reason'], '')
            self.assertEqual(listed[0]['id'], self.recipe['id'])
            self.assertTrue(listed[0]['title'] and listed[0]['description'])
            self.assertEqual(listed[0]['recipe_sha256'], patches.recipe_sha256(self.recipe))
            wrong_executable = patches.catalogue(elf_image(4096), dict(METADATA))
            self.assertFalse(wrong_executable[0]['applicable'])
            self.assertIn('SHA256', wrong_executable[0]['reason'])
            wrong_build = patches.catalogue(self.guest, {**METADATA, 'TITLE_ID': 'CUSA99999'})
            self.assertFalse(wrong_build[0]['applicable'])
            self.assertIn('TITLE_ID', wrong_build[0]['reason'])
            unreadable = patches.catalogue(b'', dict(METADATA))
            self.assertFalse(unreadable[0]['applicable'])
            self.assertIn('empty', unreadable[0]['reason'])

    def test_applicability_writes_nothing_wherever_it_runs(self):
        previous = Path.cwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(self.base)
        self.assertIsNone(patches.applicability(self.recipe, self.guest, dict(METADATA)))
        self.assertIn('TITLE_ID', patches.applicability(self.recipe, self.guest,
                                                        {**METADATA, 'TITLE_ID': 'CUSA99999'}))
        self.assertEqual(sorted(path.name for path in self.base.iterdir()), [])


class WorkerPatchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state = self.root / 'user'
        self.game = self.root / 'game'
        self.game.mkdir(parents=True)
        self.image = matching_image(patches.RECIPES[0])
        self.recipe = bound_to(patches.RECIPES[0], self.image)
        (self.game / 'eboot.bin').write_bytes(self.image)
        (self.game / 'archivemap.bin').write_bytes(b'original game content')
        self.app = worker.Worker(self.state, worker.PROJECT_ROOT)

    @contextmanager
    def selected_game(self):
        with patch.object(self.app, 'settings', return_value={'game_dir': str(self.game)}), \
                patch.object(worker.order1886, 'inspect_game', return_value=dict(METADATA)), \
                patch.object(patches, 'RECIPES', (self.recipe,)):
            yield

    def game_folder(self):
        return {str(path.relative_to(self.game)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(self.game.rglob('*')) if path.is_file()}

    def test_the_patch_methods_are_allowlisted(self):
        for method in ('patches.list', 'patches.apply'):
            with self.subTest(method=method):
                self.assertIn(method, worker.METHODS)

    def test_listing_reports_every_recipe_with_its_applicability(self):
        with self.selected_game():
            listing = self.app.dispatch('patches.list', {})
        entry = listing['recipes'][0]
        self.assertEqual(entry['id'], self.recipe['id'])
        self.assertTrue(entry['title'] and entry['description'])
        self.assertTrue(entry['applicable'])
        self.assertEqual(entry['reason'], '')
        self.assertTrue(listing['game']['ready'])
        self.assertEqual(listing['game']['metadata']['TITLE_ID'], 'CUSA00076')

    def test_apply_requires_confirmation_and_leaves_the_game_folder_byte_identical(self):
        before = self.game_folder()
        with self.selected_game():
            for params in ({'id': self.recipe['id']},
                           {'id': self.recipe['id'], 'confirmed': False},
                           {'id': self.recipe['id'], 'confirmed': 'yes'},
                           {}):
                with self.subTest(params=params), \
                        self.assertRaisesRegex(ValueError, 'explicit confirmation'):
                    self.app.dispatch('patches.apply', params)
        self.assertEqual(self.game_folder(), before)
        self.assertFalse((self.state / 'patched').exists())

    def test_apply_refuses_a_busy_session_and_an_unknown_recipe(self):
        before = self.game_folder()
        with self.selected_game():
            self.app.busy = True
            try:
                with self.assertRaisesRegex(ValueError, 'Stop the current session'):
                    self.app.dispatch('patches.apply', {'id': self.recipe['id'], 'confirmed': True})
            finally:
                self.app.busy = False
            for params in ({'id': 'order1886-invented-cheat-v1', 'confirmed': True},
                           {'id': 7, 'confirmed': True}):
                with self.subTest(params=params), self.assertRaisesRegex(ValueError, 'patch recipe|Unknown'):
                    self.app.dispatch('patches.apply', params)
        self.assertEqual(self.game_folder(), before)
        self.assertFalse((self.state / 'patched').exists())

    def test_apply_refuses_an_inapplicable_recipe_and_names_the_mismatch(self):
        (self.game / 'eboot.bin').write_bytes(elf_image(len(self.image)))
        before = self.game_folder()
        with self.selected_game():
            listing = self.app.dispatch('patches.list', {})
            self.assertFalse(listing['recipes'][0]['applicable'])
            self.assertIn('SHA256', listing['recipes'][0]['reason'])
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                self.app.dispatch('patches.apply', {'id': self.recipe['id'], 'confirmed': True})
        self.assertEqual(self.game_folder(), before)
        self.assertFalse((self.state / 'patched').exists())

    def test_apply_writes_a_derived_image_outside_the_selected_game_folder(self):
        before = self.game_folder()
        with self.selected_game():
            result = self.app.dispatch('patches.apply', {'id': self.recipe['id'], 'confirmed': True})
        self.assertEqual(self.game_folder(), before)
        destination = Path(result['destination']).resolve()
        self.assertFalse(destination == self.game or self.game in destination.parents)
        patched = destination.read_bytes()
        self.assertEqual(len(patched), len(self.image))
        for edit in self.recipe['edits']:
            start, end = edit['offset'], edit['offset'] + len(edit['replacement'])
            self.assertEqual(patched[start:end], edit['replacement'])
        self.assertFalse(result['gameplay_verified'])
        self.assertIn(self.recipe['id'], destination.name)


if __name__ == '__main__':
    unittest.main()
