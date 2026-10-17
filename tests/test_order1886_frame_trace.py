import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'scripts/order1886_frame_trace.py'
spec = importlib.util.spec_from_file_location('order1886_frame_trace', MODULE)
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)


def frames(count, step=16_666_667, duplicate_every=0):
    return [dict(event='guest_flip', timestamp_ns=i * step,
                 render_serial=i // duplicate_every if duplicate_every else i,
                 buffer_address=4096, loading=0) for i in range(count)]


class FrameTraceTests(unittest.TestCase):
    def test_repeated_flips_and_host_presents_do_not_inflate_rendered_rate(self):
        events = frames(121, duplicate_every=2)
        events += [dict(event='host_present', timestamp_ns=i * 8_333_333,
                        render_serial=0, buffer_address=0, loading=0) for i in range(241)]
        result = trace.summarize(events)
        self.assertAlmostEqual(result['guest_flip_fps'], 60, places=4)
        self.assertAlmostEqual(result['render_work_fps'], 30, places=4)
        self.assertEqual(result['repeated_render_serials'], 60)
        self.assertFalse(result['timing_gate_passed'])
        self.assertFalse(result['milestone_accepted'])

    def test_long_frames_are_retained_in_p99(self):
        events = frames(101)
        for event in events[50:]:
            event['timestamp_ns'] += 500_000_000
        for event in events[75:]:
            event['timestamp_ns'] += 500_000_000
        result = trace.summarize(events)
        self.assertGreater(result['p99_ms'], 500)
        self.assertFalse(result['timing_gate_passed'])

    def test_loading_boundary_does_not_create_an_interval(self):
        events = frames(31)
        events.append(dict(event='guest_flip', timestamp_ns=1_000_000_000,
                           render_serial=31, buffer_address=0, loading=1))
        events += [dict(e, timestamp_ns=e['timestamp_ns'] + 2_000_000_000,
                        render_serial=e['render_serial'] + 32) for e in frames(31)]
        result = trace.summarize(events)
        self.assertAlmostEqual(result['measured_seconds'], 1, places=4)
        self.assertLess(result['p99_ms'], 17)
        self.assertEqual(result['segments'], 2)

    def test_clock_reversal_is_rejected(self):
        events = frames(3)
        events[-1]['timestamp_ns'] = 1
        with self.assertRaises(ValueError):
            trace.summarize(events)

    def test_short_sixty_fps_run_cannot_pass_thirty_minutes(self):
        result = trace.summarize(frames(601))
        self.assertAlmostEqual(result['render_work_fps'], 60, places=4)
        self.assertFalse(result['timing_gate_passed'])

    def test_thirty_minutes_does_not_certify_gameplay_or_resolution(self):
        result = trace.summarize(frames(108_002))
        self.assertTrue(result['timing_gate_passed'])
        self.assertFalse(result['milestone_accepted'])
        self.assertIn('unique rendered frames', result['evidence_limits'])

    def test_stalled_tail_is_included_in_rate(self):
        events = frames(61)
        events.append(dict(events[-1], timestamp_ns=10_000_000_000))
        result = trace.summarize(events)
        self.assertAlmostEqual(result['render_work_fps'], 6)
        self.assertGreater(result['p99_ms'], 8000)


if __name__ == '__main__':
    unittest.main()
