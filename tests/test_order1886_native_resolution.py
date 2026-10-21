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

    def test_the_launcher_does_not_configure_a_four_k_internal_render(self):
        # A selectable 4K choice must say it is an upscaled output, and a description may only
        # mention 4K to deny it, so a "native 4K" claim cannot be smuggled in as a toggle.
        for item in options.FIELDS:
            for choice in item.get('choices', []):
                text = choice['label'].lower()
                if ('3840' in text or '4k' in text) and choice['available']:
                    self.assertIn('not native 4k', text, f"{item['key']}: {choice['label']}")
            if item['available']:
                text = (item['label'] + ' ' + item['description']).lower()
                if '3840' in text or '4k' in text:
                    self.assertTrue('not native 4k' in text or 'not ' in text, item['key'])
        values = runtime_settings({'presentation_filter': 'linear'})
        self.assertNotIn('internal_width', values)
        self.assertNotIn('output_resolution', values)


if __name__ == '__main__':
    unittest.main()
