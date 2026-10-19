"""A recording's frame times are reported as measurements and never as an acceptance."""
import contextlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest

from paths import ROOT

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from scripts import order1886_perf_report as perf  # noqa: E402
import order1886_frame_trace as frame_trace  # noqa: E402
from launcher import order1886_worker as worker  # noqa: E402

FRAME_60 = 16_666_667
HEADER = 'event,timestamp_ns,render_serial,buffer_address,loading\n'
VERDICT = re.compile(r'\b(pass(ed|es|ing)?|fail(s|ed|ing)?|qualif(y|ies|ied)|approv(ed|es)'
                     r'|meets?|meeting|certif(y|ies|ied)|succeeded)\b', re.IGNORECASE)


def write_trace(directory, intervals_ns=(FRAME_60,) * 600, name='performance-fixture.csv'):
    """Write a trace whose guest flips are spaced by intervals_ns, exactly as the runtime does."""
    rows, timestamp = [HEADER], 0
    for index, interval in enumerate(intervals_ns):
        rows.append('guest_flip,%d,%d,4096,0\n' % (timestamp, index))
        timestamp += interval
    rows.append('guest_flip,%d,%d,4096,0\n' % (timestamp, len(intervals_ns)))
    path = Path(directory) / name
    path.write_text(''.join(rows), encoding='utf-8')
    return path


def only_trace(path, **options):
    return perf.summarize([path], **options)['traces'][0]


class SteadyTraceTests(unittest.TestCase):
    def test_steady_sixty_fps_trace_summarizes_counts_means_and_percentiles(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = write_trace(temporary)
            result = perf.summarize([path])
            trace = result['traces'][0]
            self.assertEqual(trace['trace'], str(path.resolve()))
            self.assertEqual(trace['frames'], 600)
            self.assertEqual(trace['guest_flips'], 601)
            self.assertEqual(trace['segments'], 1)
            self.assertAlmostEqual(trace['duration_seconds'], 600 * FRAME_60 / 1e9, places=6)
            self.assertAlmostEqual(trace['fps'], 60, places=4)
            for name in ('p50', 'p95', 'p99', 'worst'):
                with self.subTest(statistic=name):
                    self.assertAlmostEqual(trace['frame_time_ms'][name], 16.666667, places=4)
            self.assertEqual(trace['over_33_3ms']['count'], 0)
            self.assertEqual(trace['over_33_3ms']['share'], 0.0)
            self.assertEqual(trace['over_16_7ms']['count'], 0)
            self.assertEqual(trace['over_16_7ms']['share'], 0.0)

    def test_percentiles_agree_with_the_shared_parser(self):
        intervals = [FRAME_60] * 300 + [40_000_000] * 60
        with tempfile.TemporaryDirectory() as temporary:
            path = write_trace(temporary, intervals)
            trace = only_trace(path)
            import csv
            with path.open(newline='', encoding='utf-8') as source:
                shared = frame_trace.summarize(csv.DictReader(source))
            self.assertAlmostEqual(trace['frame_time_ms']['p99'], shared['p99_ms'], places=9)
            self.assertAlmostEqual(trace['frame_time_ms']['worst'], shared['worst_ms'], places=9)
            self.assertAlmostEqual(trace['fps'], shared['render_work_fps'], places=9)
            self.assertAlmostEqual(trace['duration_seconds'], shared['measured_seconds'], places=9)

    def test_summary_carries_no_verdict_and_no_invented_cap(self):
        with tempfile.TemporaryDirectory() as temporary:
            trace = only_trace(write_trace(temporary))
            self.assertNotIn('timing_gate_passed', trace)
            self.assertNotIn('milestone_accepted', trace)
            self.assertEqual(trace['frame_cap']['fps'], None)
            self.assertIn('not recorded', trace['frame_cap']['source'])
            self.assertEqual(json.dumps(trace, allow_nan=False, sort_keys=True),
                             json.dumps(trace, allow_nan=False, sort_keys=True))
            for key, value in trace.items():
                with self.subTest(key=key):
                    self.assertNotRegex(key.lower(), 'passed|accepted|qualified')
                    self.assertIsNot(value, True)


class SlowTailTests(unittest.TestCase):
    def test_a_long_slow_tail_is_reported_and_not_averaged_away(self):
        intervals = [FRAME_60] * 300 + [100_000_000] * 60
        with tempfile.TemporaryDirectory() as temporary:
            trace = only_trace(write_trace(temporary, intervals))
            self.assertEqual(trace['frames'], 360)
            self.assertAlmostEqual(trace['frame_time_ms']['p50'], 16.666667, places=4)
            self.assertAlmostEqual(trace['frame_time_ms']['p95'], 100, places=4)
            self.assertAlmostEqual(trace['frame_time_ms']['p99'], 100, places=4)
            self.assertAlmostEqual(trace['frame_time_ms']['worst'], 100, places=4)
            self.assertEqual(trace['over_33_3ms']['count'], 60)
            self.assertAlmostEqual(trace['over_33_3ms']['share'], 60 / 360, places=9)
            # A perfect 60 FPS frame is 16.667 ms, below the 16.7 ms threshold, so only the
            # slow tail crosses it: the tail is counted, not smeared into the mean.
            self.assertEqual(trace['over_16_7ms']['count'], 60)
            self.assertAlmostEqual(trace['over_16_7ms']['share'], 60 / 360, places=9)
            seconds = (300 * FRAME_60 + 60 * 100_000_000) / 1e9
            self.assertAlmostEqual(trace['duration_seconds'], seconds, places=6)
            self.assertAlmostEqual(trace['fps'], 360 / seconds, places=6)
            self.assertLess(trace['fps'], 40)

    def test_a_thirty_fps_trace_reports_every_frame_over_sixteen_point_seven(self):
        with tempfile.TemporaryDirectory() as temporary:
            trace = only_trace(write_trace(temporary, [33_333_333] * 300))
            self.assertEqual(trace['over_16_7ms']['count'], 300)
            self.assertEqual(trace['over_16_7ms']['share'], 1.0)


class RefusalTests(unittest.TestCase):
    def refused(self, path):
        with self.assertRaises(perf.TraceError) as caught:
            perf.summarize([path])
        message = str(caught.exception)
        self.assertIn(path.name, message)
        return message

    def test_an_empty_file_is_refused_with_the_expected_header(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'performance-empty.csv'
            path.write_text('', encoding='utf-8')
            self.assertIn('header', self.refused(path))

    def test_a_header_without_events_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'performance-header.csv'
            path.write_text(HEADER, encoding='utf-8')
            self.assertIn('guest_flip', self.refused(path))

    def test_a_trace_truncated_mid_row_is_refused_at_that_row(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'performance-truncated.csv'
            path.write_text(HEADER + 'guest_flip,16666667,1,40', encoding='utf-8')
            message = self.refused(path)
            self.assertIn('line 2', message)

    def test_a_trace_truncated_after_one_good_row_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'performance-one-row.csv'
            path.write_text(HEADER + 'guest_flip,0,0,4096,0\nguest_flip,16666667,1,40', encoding='utf-8')
            self.assertIn('line 3', self.refused(path))

    def test_garbage_rows_are_refused_without_leaking_a_value_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'performance-garbage.csv'
            path.write_text(HEADER + 'guest_flip,not-a-number,x,4096,0\n', encoding='utf-8')
            message = self.refused(path)
            self.assertIn('line 2', message)
            self.assertIsInstance(perf.TraceError('x'), ValueError)

    def test_a_file_that_is_not_a_trace_is_refused_by_its_header(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'performance-notes.csv'
            path.write_text('nothing to do with frame times\n', encoding='utf-8')
            self.assertIn('header', self.refused(path))

    def test_a_missing_trace_is_refused_by_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'performance-missing.csv'
            self.assertIn('performance-missing.csv', self.refused(path))

    def test_a_clock_reversal_is_refused_in_plain_language(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'performance-reversal.csv'
            path.write_text(HEADER + 'guest_flip,0,0,4096,0\nguest_flip,16666667,1,4096,0\n'
                            'guest_flip,1,2,4096,0\n', encoding='utf-8')
            self.assertIn('performance-reversal.csv', self.refused(path))


class CompareTests(unittest.TestCase):
    def test_compare_refuses_traces_of_very_different_lengths_and_states_the_tolerance(self):
        with tempfile.TemporaryDirectory() as temporary:
            short = only_trace(write_trace(temporary, (FRAME_60,) * 600, name='a.csv'))
            long = only_trace(write_trace(temporary, (FRAME_60,) * 1200, name='b.csv'))
            with self.assertRaises(ValueError) as caught:
                perf.compare(short, long)
            message = str(caught.exception)
            self.assertIn('10', message)
            self.assertIn('tolerance', message.lower())
            self.assertIn('10.000', message)
            self.assertIn('20.000', message)

    def test_compare_reports_per_statistic_deltas_for_comparable_traces(self):
        intervals = [FRAME_60] * 560 + [40_000_000] * 40
        with tempfile.TemporaryDirectory() as temporary:
            baseline = only_trace(write_trace(temporary, (FRAME_60,) * 600, name='a.csv'))
            candidate = only_trace(write_trace(temporary, intervals, name='b.csv'))
            result = perf.compare(baseline, candidate)
            self.assertEqual(result['tolerance']['max_relative_duration_difference'], 0.1)
            self.assertLess(result['tolerance']['observed_relative_duration_difference'], 0.1)
            statistics = result['statistics']
            self.assertEqual(statistics['frames']['delta'], 0)
            self.assertGreater(statistics['duration_seconds']['delta'], 0)
            self.assertLess(statistics['fps']['delta'], 0)
            self.assertAlmostEqual(statistics['p50_ms']['delta'], 0, places=4)
            self.assertAlmostEqual(statistics['p95_ms']['delta'], 40 - 16.666667, places=4)
            self.assertEqual(statistics['over_33_3ms_count']['delta'], 40)
            self.assertAlmostEqual(statistics['over_33_3ms_share']['delta'], 40 / 600, places=9)
            for name, entry in statistics.items():
                with self.subTest(statistic=name):
                    self.assertEqual(set(entry), {'baseline', 'candidate', 'delta', 'relative'})
            self.assertEqual(result['baseline'], str(baseline['trace']))
            self.assertIn('not a performance acceptance', json.dumps(result))

    def test_compare_accepts_the_summary_of_a_single_trace(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = write_trace(temporary, (FRAME_60,) * 600, name='a.csv')
            second = write_trace(temporary, (FRAME_60,) * 600, name='b.csv')
            result = perf.compare(perf.summarize([first]), perf.summarize([second]))
            self.assertEqual(result['statistics']['fps']['delta'], 0)

    def test_compare_rejects_a_summary_of_several_traces(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = write_trace(temporary, (FRAME_60,) * 600, name='a.csv')
            second = write_trace(temporary, (FRAME_60,) * 600, name='b.csv')
            with self.assertRaises(ValueError):
                perf.compare(perf.summarize([first, second]), perf.summarize([second]))


class ExplainTests(unittest.TestCase):
    def test_explain_states_what_was_measured_and_never_a_verdict(self):
        with tempfile.TemporaryDirectory() as temporary:
            summary = perf.summarize([write_trace(temporary)])
            statements = perf.explain(summary)
            self.assertGreaterEqual(len(statements), 3)
            for statement in statements:
                with self.subTest(statement=statement):
                    self.assertIsInstance(statement, str)
                    self.assertTrue(statement.strip())
                    self.assertIsNone(VERDICT.search(statement), statement)
            text = ' '.join(statements)
            self.assertIn('600 rendered frames', text)
            self.assertIn('10.000 s', text)
            self.assertIn('16.67 ms', text)

    def test_explain_says_what_a_trace_cannot_measure(self):
        with tempfile.TemporaryDirectory() as temporary:
            text = ' '.join(perf.explain(perf.summarize([write_trace(temporary)]))).lower()
            for limit in ('scene', 'frame cap', 'settings', 'resolution'):
                with self.subTest(limit=limit):
                    self.assertIn(limit, text)
            self.assertIn('not', text)
            self.assertIn('acceptance', text)

    def test_explain_reports_a_slow_tail_as_a_count_not_an_average(self):
        with tempfile.TemporaryDirectory() as temporary:
            intervals = [FRAME_60] * 300 + [100_000_000] * 60
            text = ' '.join(perf.explain(perf.summarize([write_trace(temporary, intervals)])))
            self.assertIn('60 frames', text)
            self.assertIn('33.3 ms', text)


class MainTests(unittest.TestCase):
    def test_main_writes_json_and_text_next_to_the_trace(self):
        intervals = [FRAME_60] * 300 + [100_000_000] * 60
        with tempfile.TemporaryDirectory() as temporary:
            path = write_trace(temporary, intervals)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(perf.main([str(path)]), 0)
            summary = Path(temporary) / 'frame-summary.json'
            text = Path(temporary) / 'frame-summary.txt'
            self.assertTrue(summary.is_file())
            self.assertTrue(text.is_file())
            document = json.loads(summary.read_text(encoding='utf-8'))
            self.assertEqual(document['traces'][0]['frames'], 360)
            self.assertIn('60 frames', text.read_text(encoding='utf-8'))
            printed = json.loads(output.getvalue())
            self.assertEqual(printed['traces'][0]['trace'], str(path.resolve()))

    def test_main_reports_a_bad_trace_without_a_traceback(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'performance-empty.csv'
            path.write_text('', encoding='utf-8')
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                self.assertEqual(perf.main([str(path)]), 2)
            self.assertIn('performance-empty.csv', error.getvalue())

    def test_main_compares_two_traces_side_by_side(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = write_trace(temporary, (FRAME_60,) * 600, name='a.csv')
            second = write_trace(temporary, [FRAME_60] * 560 + [40_000_000] * 40, name='b.csv')
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(perf.main([str(first), str(second), '--compare']), 0)
            document = json.loads((Path(temporary) / 'frame-summary.json').read_text(encoding='utf-8'))
            self.assertEqual(document['comparison']['statistics']['over_33_3ms_count']['delta'], 40)


class PackagingTests(unittest.TestCase):
    def test_the_packaged_worker_ships_the_report_helper_and_its_parser(self):
        """performance.report imports both lazily, so both must be data files in the package."""
        build = (ROOT / 'packaging/windows/order1886-go-build.ps1').read_text(encoding='utf-8')
        for name in ('order1886_frame_trace.py', 'order1886_perf_report.py'):
            with self.subTest(script=name):
                self.assertIn("'%s'" % name, build)


class WorkerReportTests(unittest.TestCase):
    def worker(self, directory):
        state = Path(directory) / 'user'
        state.mkdir(parents=True, exist_ok=True)
        return worker.Worker(state, ROOT), state

    def test_report_without_a_recording_names_the_folder_it_looked_in(self):
        self.assertIn('performance.report', worker.METHODS)
        with tempfile.TemporaryDirectory() as temporary:
            app, state = self.worker(temporary)
            with self.assertRaises(ValueError) as caught:
                app.dispatch('performance.report', {})
            message = str(caught.exception)
            self.assertIn('no performance recording', message.lower())
            self.assertIn(str(state / 'logs'), message)

    def test_report_summarizes_the_most_recent_trace_in_the_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            app, state = self.worker(temporary)
            logs = state / 'logs'
            logs.mkdir()
            older = write_trace(logs, (FRAME_60,) * 600, name='performance-aaaa.csv')
            newer = write_trace(logs, [FRAME_60] * 300 + [100_000_000] * 60, name='performance-bbbb.csv')
            os.utime(older, (1_000_000, 1_000_000))
            os.utime(newer, (2_000_000, 2_000_000))
            result = app.dispatch('performance.report', {})
            self.assertEqual([row['trace'] for row in result['traces']], [str(newer.resolve())])
            self.assertEqual(result['traces'][0]['over_33_3ms']['count'], 60)
            self.assertNotIn('timing_gate_passed', result['traces'][0])

    def test_report_can_return_two_recent_traces_and_rejects_a_bad_count(self):
        with tempfile.TemporaryDirectory() as temporary:
            app, state = self.worker(temporary)
            logs = state / 'logs'
            logs.mkdir()
            older = write_trace(logs, (FRAME_60,) * 600, name='performance-aaaa.csv')
            newer = write_trace(logs, (FRAME_60,) * 600, name='performance-bbbb.csv')
            os.utime(older, (1_000_000, 1_000_000))
            os.utime(newer, (2_000_000, 2_000_000))
            result = app.dispatch('performance.report', {'count': 2})
            self.assertEqual([row['trace'] for row in result['traces']],
                             [str(newer.resolve()), str(older.resolve())])
            for invalid in (0, 9, '2', True, None):
                with self.subTest(count=invalid), self.assertRaises(ValueError):
                    app.dispatch('performance.report', {'count': invalid})


if __name__ == '__main__':
    unittest.main()
