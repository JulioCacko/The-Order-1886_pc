"""Button prompts option: shipped plan and art, composition rules, overlay priority, packaging."""
from pathlib import Path
import json
import tempfile
import unittest

import order1886
import order1886_mods as mods
import order1886_prompts as prompts
import order1886_input as inputs

ROOT = Path(__file__).resolve().parents[1]


def disc_with_cross(size=64):
    """A light engraved-style disc with a dark X, like the game's static face icons."""
    from PIL import Image, ImageDraw
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 4, size - 5, size - 5), fill=(236, 236, 236, 255), outline=(30, 30, 30, 255), width=3)
    draw.line((20, 20, size - 21, size - 21), fill=(15, 15, 15, 255), width=5)
    draw.line((20, size - 21, size - 21, 20), fill=(15, 15, 15, 255), width=5)
    return image


def entry(**values):
    base = dict(key='InteractApp-34c664-1', id=1, glyph='cross', role='face', static=True,
                box=[4, 4, 60, 60], fill=.8, soft=False, width=64, height=64)
    base.update(values)
    return base


class PromptPlanTests(unittest.TestCase):
    def test_plan_has_roles_for_both_sets_and_shipped_art_covers_them(self):
        for prompt_set in ('xbox', 'keyboard'):
            planned = prompts.plan(prompt_set)
            self.assertEqual(len(planned), 290)
            active = [e for e in planned.values() if e['role'] != 'keep']
            self.assertTrue(active)
            for e in active:
                self.assertIn(e['role'], ('face', 'label'))
        marks = {p.stem for p in (prompts.ASSETS / 'marks').glob('*.png')}
        self.assertTrue(set(prompts.XBOX.values()) <= marks)
        needed = {label for label in prompts.KEYS.values() if label not in prompts.DRAWN_KEYS}
        self.assertTrue(needed <= marks)
        drawings = {p.stem for p in (prompts.ASSETS / 'keyboard').glob('*.png')}
        self.assertTrue(set(prompts.DRAWN_KEYS.values()) | {'key-square', 'key-wide', 'mouse-left',
                        'mouse-right', 'mouse-move', 'wasd'} <= drawings)

    def test_keyboard_preset_is_a_valid_binding_map_matching_the_keycaps(self):
        preset = prompts.keyboard_bindings()
        inputs.validate(preset, 'keyboard')
        self.assertEqual(preset['cross'], 'Space')
        self.assertEqual(preset['options'], 'Escape')
        self.assertEqual((preset['right'], preset['left'], preset['down'], preset['up']), ('1', '2', '5', '6'))
        self.assertEqual(prompts.KEYS['dpad_right'], '1')

    def test_playstation_builds_nothing_and_unknown_sets_are_refused(self):
        with tempfile.TemporaryDirectory() as state:
            self.assertEqual(prompts.prepare('game', state, 'playstation'), [])
            with self.assertRaises(ValueError):
                prompts.prepare('game', state, 'switch')


class CompositionTests(unittest.TestCase):
    def test_xbox_replaces_only_the_marking_inside_the_edit_region(self):
        import numpy as np
        source = disc_with_cross()
        result = prompts.composite(entry(), source, 'A')
        self.assertEqual(result.size, source.size)
        before, after = np.asarray(source), np.asarray(result)
        changed = np.any(before != after, axis=2)
        self.assertTrue(changed.any(), 'the marking must change')
        # The ring and everything outside the concentric edit disc stay the source's own pixels.
        yy, xx = np.indices(changed.shape)
        outside = ((xx - 31.5) ** 2 + (yy - 31.5) ** 2) > (56 * .41) ** 2
        self.assertFalse(changed[outside].any())
        # The old X arms reach into the corners of the disc and are gone there.
        self.assertGreater(int(after[24, 24, 0]), 120)

    def test_xbox_keeps_sticks_and_dpad_as_the_game_draws_them(self):
        source = disc_with_cross()
        self.assertIsNone(prompts.xbox(entry(glyph='dpad_up'), source))
        self.assertIsNone(prompts.xbox(entry(glyph='left_stick'), source))

    def test_keyboard_draws_keys_at_the_original_size_and_clears_menu_discs(self):
        source = disc_with_cross()
        drawn = prompts.keyboard(entry(), source)
        self.assertEqual(drawn.size, source.size)
        self.assertIsNotNone(drawn.getchannel('A').getbbox())
        backing = prompts.keyboard(entry(key='MenuApp-4-288', id=288), source)
        self.assertIsNone(backing.getchannel('A').getbbox())
        # Menus select with a left click and go back with Esc (the runtime's menu routing).
        menu_cross = entry(key='MenuApp-4-104', id=104)
        self.assertEqual(prompts.keyboard(menu_cross, source).tobytes(),
                         prompts.placed(menu_cross, prompts.master('mouse-left'), 'mouse-left').tobytes())
        self.assertNotEqual(prompts.keyboard(menu_cross, source).tobytes(), drawn.tobytes())
        menu_circle = entry(key='MenuApp-4-107', id=107, glyph='circle')
        self.assertEqual(prompts.keyboard(menu_circle, source).tobytes(),
                         prompts.placed(menu_circle, prompts.keycap('ESC'), 'keycap').tobytes())
        for glyph in ('r2', 'l2', 'left_stick', 'right_stick', 'dpad_up_down', 'options'):
            with self.subTest(glyph=glyph):
                self.assertEqual(prompts.keyboard(entry(glyph=glyph, static=False), source).size, source.size)


class OverlayTests(unittest.TestCase):
    def test_generated_prompt_files_override_mods_without_touching_the_game(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            game, state, mod_root = base / 'game', base / 'state', base / 'mods'
            for path, data in ((game / '_data/ui', b'original'), (game / '_data/other', b'other'),
                               (mod_root / 'Mod/_data/ui', b'mod'), (base / 'prompts/ui', b'prompts')):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            extra = [(Path('_data/ui'), base / 'prompts/ui')]
            state.mkdir()
            with order1886.session_lock(state):
                alone = mods.build_overlay(game, state, '', False, [], extra=extra)
                self.assertEqual((alone / '_data/ui').read_bytes(), b'prompts')
                both = mods.build_overlay(game, state, mod_root, True, ['Mod'], extra=extra)
                self.assertEqual((both / '_data/ui').read_bytes(), b'prompts')
                self.assertEqual((both / '_data/other').read_bytes(), b'other')
                self.assertEqual(mods.build_overlay(game, state, '', False, []), game)
            self.assertEqual((game / '_data/ui').read_bytes(), b'original')


class WiringTests(unittest.TestCase):
    def test_option_reaches_the_backend_and_keyboard_applies_its_layout(self):
        from launcher import order1886_common as launcher
        from launcher.order1886_options import FIELDS
        field = next(f for f in FIELDS if f['key'] == 'button_prompts')
        self.assertEqual([c['value'] for c in field['choices']], list(prompts.SETS))
        settings = vars(order1886.argument_parser().parse_args(['--button-prompts', 'keyboard']))
        self.assertEqual(settings['button_prompts'], 'keyboard')
        command = launcher.backend_command({'game_dir': 'g', 'display_mode': 'windowed', 'vsync': True,
                                            'show_fps': False, 'button_prompts': 'xbox'})
        self.assertEqual(command[command.index('--button-prompts') + 1], 'xbox')
        source = (ROOT / 'order1886.py').read_text(encoding='utf-8')
        self.assertIn("args.keyboard_bindings = prompts.keyboard_bindings()", source)

    def test_packaging_ships_the_generator_its_art_and_dependencies(self):
        build = (ROOT / 'packaging/windows/order1886-go-build.ps1').read_text(encoding='utf-8')
        linux = (ROOT / 'packaging/linux/order1886-go-package.py').read_text(encoding='utf-8')
        workflow = (ROOT / '.github/workflows/order1886-go-linux-package.yml').read_text(encoding='utf-8')
        for name in ('order1886_prompts.py', 'order1886_glyph_mod.py', 'order1886_ui_extract.py'):
            self.assertIn(f"'{name}'", build)
            self.assertIn(f"'{name}'", linux)
        self.assertIn('scripts/button_prompts', build)
        self.assertIn("scripts/button_prompts", linux)
        for text in (build, workflow):
            self.assertIn("'unicorn==2.1.4'", text)
            self.assertIn('--collect-all unicorn', text)
            self.assertIn('--hidden-import numpy', text)


if __name__ == '__main__':
    unittest.main()
