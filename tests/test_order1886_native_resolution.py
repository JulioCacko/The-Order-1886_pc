"""The original-resolution, non-FSR path is selectable and identifiable, and nothing else
claims to be native 4K."""
from pathlib import Path
import tempfile
import unittest

import order1886
from launcher import order1886_options as options

ROOT = Path(__file__).resolve().parents[1]


def runtime_settings(settings):
    """Write and read back the runtime.ini the launcher hands to the game."""
    with tempfile.TemporaryDirectory() as temporary:
        user = Path(temporary)
        order1886.write_runtime_config(user, settings)
        text = (user / 'runtime.ini').read_text(encoding='utf-8')
    return dict(line.split('=', 1) for line in text.splitlines() if '=' in line and not line.startswith('#'))


def field(key):
    return next(item for item in options.FIELDS if item['key'] == key)


class OriginalResolutionPathTests(unittest.TestCase):
    def test_the_no_fsr_path_is_selectable_and_says_so(self):
        select = field('presentation_filter')
        linear = next(choice for choice in select['choices'] if choice['value'] == 'linear')
        self.assertTrue(linear['available'])
        self.assertIn('no fsr', linear['label'].lower())
        # The description must not imply that linear means a native 4K internal render.
        self.assertIn('does not establish native internal resolution',
                      field('presentation_filter')['description'].lower())

    def test_linear_reaches_the_runtime_without_an_upscaler(self):
        values = runtime_settings({'presentation_filter': 'linear', 'display_mode': 'borderless'})
        self.assertEqual(values['presentation_filter'], 'linear')
        # Internal render resolution is the guest's own; the launcher never claims otherwise.
        self.assertEqual(values['render_resolution'], 'native')

    def test_fsr1_is_recorded_as_the_presentation_filter_only(self):
        values = runtime_settings({'presentation_filter': 'fsr1'})
        self.assertEqual(values['presentation_filter'], 'fsr1')
        self.assertEqual(values['render_resolution'], 'native')

    def test_output_resolution_is_an_output_size_not_an_internal_render(self):
        select = field('output_resolution')
        self.assertTrue(select['available'])
        self.assertIn('separately', select['description'].lower())
        self.assertIn('not native 4k', select['description'].lower())
        for choice in select['choices']:
            if choice['value'] != 'automatic':
                self.assertIn('output', choice['label'].lower())
        values = runtime_settings({'output_resolution': '2560x1440'})
        self.assertEqual(values['output_res'], '2560x1440')
        self.assertEqual(values['render_resolution'], 'native')

    def test_only_render_resolution_offers_a_native_four_k(self):
        # Render resolution is the one setting that changes what the game draws; any other 4K
        # choice must say it is an upscaled output, so it cannot pass for native 4K.
        for item in options.FIELDS:
            if item['key'] in ('render_width', 'custom_render_width'):
                continue
            for choice in item.get('choices', []):
                text = choice['label'].lower()
                if ('3840' in text or '4k' in text) and choice['available']:
                    self.assertIn('not native 4k', text, f"{item['key']}: {choice['label']}")
            if item['available']:
                text = (item['label'] + ' ' + item['description']).lower()
                if '3840' in text or '4k' in text:
                    self.assertTrue('not native 4k' in text or 'not ' in text, item['key'])
        native = next(c for c in field('render_width')['choices'] if c['value'] == 3840)
        self.assertIn('native 4k', native['label'].lower())
        values = runtime_settings({'presentation_filter': 'linear'})
        self.assertNotIn('internal_width', values)
        self.assertNotIn('output_resolution', values)

    def test_native_four_k_is_drawn_by_the_game_and_presented_one_to_one(self):
        values = runtime_settings({'presentation_filter': 'dlss', 'render_width': 3840})
        self.assertEqual(values['render_resolution'], '3840x1600')
        self.assertEqual(values['presentation_filter'], 'linear')
        self.assertNotIn('upscaler', values)
        values = runtime_settings({'render_width': 3840, 'aspect_ratio': '16:9'})
        self.assertEqual(values['render_resolution'], '3840x2160')


if __name__ == '__main__':
    unittest.main()
