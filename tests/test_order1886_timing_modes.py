"""Engine timing, presentation cadence, VSync and the host frame cap stay separate."""
from pathlib import Path
import unittest

import order1886

ROOT = Path(__file__).resolve().parents[1]


def environment(settings):
    return order1886.runtime_environment(ROOT / 'out' / 'runtime.exe', ROOT / 'out' / 'state', settings, {})


class TimingModeTests(unittest.TestCase):
    def test_default_keeps_the_existing_engine_rate_cap(self):
        # The default cap of 120 must never raise the presented rate: the engine rate
        # still wins, so an update cannot silently change how the game paces.
        for rate in (30, 60):
            with self.subTest(rate=rate):
                env = environment({'frame_rate': rate})
                self.assertEqual(env['ORDER1886_FPS_LIMIT'], str(rate))
                self.assertEqual(env['ORDER1886_VBLANK_HZ'], '60')

    def test_a_lower_host_cap_throttles_presentation_only(self):
        env = environment({'frame_rate': 60, 'fps_cap': 30})
        self.assertEqual(env['ORDER1886_FPS_LIMIT'], '30')
        self.assertEqual(env['ORDER1886_VBLANK_HZ'], '60')

    def test_the_host_cap_can_exceed_the_engine_rate_without_changing_it(self):
        env = environment({'frame_rate': 30, 'fps_cap': 120})
        self.assertEqual(env['ORDER1886_FPS_LIMIT'], '30')
        env = environment({'frame_rate': 60, 'fps_cap': 240})
        self.assertEqual(env['ORDER1886_FPS_LIMIT'], '60')

    def test_the_cap_is_validated_as_a_number_in_range(self):
        for invalid in (29, 241, 'fast', 60.5, True, None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError) as raised:
                environment({'frame_rate': 60, 'fps_cap': invalid})
            self.assertIn('frame cap', str(raised.exception).lower())

    def test_diagnostics_report_the_resolved_timing(self):
        timing = order1886.timing_profile({'frame_rate': 60, 'fps_cap': 90, 'vsync': True})
        self.assertEqual(timing['engine_fps'], 60)
        self.assertEqual(timing['fps_cap'], 90)
        self.assertEqual(timing['fps_limit'], 60)
        self.assertEqual(timing['vblank_hz'], 60)
        self.assertTrue(timing['vsync'])
        # A cap below the engine rate is the only way it changes the presented rate.
        self.assertEqual(order1886.timing_profile({'frame_rate': 60, 'fps_cap': 30})['fps_limit'], 30)

    def test_ninety_keeps_the_cap_rule_and_unlocked_takes_the_cap(self):
        self.assertEqual(environment({'frame_rate': 90})['ORDER1886_FPS_LIMIT'], '90')
        self.assertEqual(environment({'frame_rate': 90, 'fps_cap': 60})['ORDER1886_FPS_LIMIT'], '60')
        for cap in (30, 120, 240):
            with self.subTest(cap=cap):
                env = environment({'frame_rate': 0, 'fps_cap': cap})
                self.assertEqual(env['ORDER1886_FPS_LIMIT'], str(cap))
                self.assertEqual(env['ORDER1886_VBLANK_HZ'], '60')

    def test_vsync_stays_a_presentation_switch(self):
        self.assertFalse(order1886.timing_profile({'frame_rate': 60, 'vsync': False})['vsync'])
        self.assertTrue(order1886.timing_profile({'frame_rate': 60})['vsync'])


if __name__ == '__main__':
    unittest.main()
