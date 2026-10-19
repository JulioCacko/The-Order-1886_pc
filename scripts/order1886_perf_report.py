#!/usr/bin/env python3
"""Measure a recorded frame trace and say plainly what the numbers do and do not cover.

A trace is written by the native runtime when the player turns on System > Record
performance data (ORDER1886_FRAME_STATS / ORDER1886_FRAME_TRACE). This module reads one
or more of those CSVs, reuses scripts/order1886_frame_trace.py for every interpretation of
the format, and reports counts, durations, means, percentiles and slow-frame shares.

It grants nothing. Percentiles are measurements of a recording, not a verdict: a scene,
a graphics profile and an acceptance each need evidence this CSV does not carry.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import sys

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import order1886_frame_trace as frame_trace  # noqa: E402

SCHEMA_VERSION = 1
# The native writer emits exactly this header; anything else is not one of its recordings.
HEADER = ('event', 'timestamp_ns', 'render_serial', 'buffer_address', 'loading')
SLOW_MS = 33.3
FAST_MS = 16.7
# Two recordings are only compared when their measured durations are this close, relative
# to the longer one. Frame mixing and percentiles from runs of different lengths describe
# different amounts of the scene, and the CSV cannot separate that from a real difference.
TOLERANCE = 0.10
MAX_TRACES = 8
LIMITS = (
    'A trace holds guest flip and host present timestamps with render serials. It does not hold the '
    'scene, the camera, the output resolution, the graphics settings or the configured frame cap.',
    'Counts, means, percentiles and threshold shares describe the recorded frames only. They are not a '
    'frame-rate target, a rendering qualification or a gameplay acceptance.',
)


class TraceError(ValueError):
    """A recording this module cannot measure, reported as text rather than a traceback."""


def _percentile(ordered, fraction):
    """Nearest-rank percentile, the same definition scripts/order1886_frame_trace.py uses."""
    if not ordered:
        return None
    return ordered[max(math.ceil(len(ordered) * fraction) - 1, 0)]


def _read(path):
    """Read one trace's rows and its guest_flip count, refusing anything unusable."""
    events, flips = [], 0
    try:
        handle = path.open(newline='', encoding='utf-8')
    except OSError as exc:
        raise TraceError(f'{path}: cannot read this recording ({exc.strerror or exc}).') from None
    with handle:
        try:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise TraceError(
                    f'{path.name}: has no frame-trace header (expected {",".join(HEADER)}); '
                    'the file is empty or is not a performance recording.')
            if tuple(reader.fieldnames) != HEADER:
                found = ','.join(str(name) for name in reader.fieldnames)
                raise TraceError(
                    f'{path.name}: does not begin with the frame-trace header {",".join(HEADER)}; '
                    f'its first line reads "{found}", so it is not a performance recording.')
            for row in reader:
                if None not in row and all(row.get(column) is None for column in HEADER):
                    continue  # The writer emits one row per line; a blank line is not a frame.
                if None in row or any(row.get(column) is None for column in HEADER):
                    raise TraceError(
                        f'{path.name}: line {reader.line_num} is an incomplete trace row. The recording '
                        'was probably cut off while the game was still writing it; hand over the CSV '
                        'after quitting the game normally.')
                if any(character in row['event'] for character in ',\r\n'):
                    raise TraceError(f'{path.name}: line {reader.line_num} has an unusable event name.')
                try:
                    sample = {'event': row['event'],
                              **{column: int(row[column]) for column in HEADER[1:]}}
                except (TypeError, ValueError):
                    raise TraceError(
                        f'{path.name}: line {reader.line_num} is not a trace record '
                        f'(expected numbers in {", ".join(HEADER[1:])}).') from None
                events.append(sample)
                if sample['event'] == 'guest_flip':
                    flips += 1
        except TraceError:
            raise
        except UnicodeDecodeError as exc:
            raise TraceError(f'{path.name}: is not UTF-8 text ({exc.reason} at byte {exc.start}); '
                             'it is not a performance recording.') from None
    return events, flips


def measure(path, frame_cap=None):
    """Summarize one trace. The trace itself records no cap, so one is never invented."""
    source = Path(path)
    events, flips = _read(source)
    if not flips:
        raise TraceError(f'{source.name}: contains no guest_flip rows, so no frame rate, frame time '
                         'or slow-frame share can be measured from it.')
    try:
        data = frame_trace.measure(events)
    except ValueError as exc:
        raise TraceError(f'{source.name}: {exc}.') from None
    ordered = sorted(data['intervals_ms'])
    if not ordered:
        raise TraceError(
            f'{source.name}: its {flips} guest_flip rows yield no complete rendered-frame interval '
            '(every row is a loading frame or repeats one render serial), so no frame time can be '
            'measured from it.')
    seconds = data['measured_seconds']
    slow = sum(1 for value in ordered if value > SLOW_MS)
    fast = sum(1 for value in ordered if value > FAST_MS)
    return {
        'trace': str(source.resolve()),
        'frames': len(ordered),
        'guest_flips': flips,
        'repeated_render_serials': data['repeated_render_serials'],
        'segments': data['segments'],
        'duration_seconds': seconds,
        'fps': len(ordered) / seconds if seconds else None,
        'frame_time_ms': {'p50': _percentile(ordered, .50), 'p95': _percentile(ordered, .95),
                          'p99': _percentile(ordered, .99), 'worst': ordered[-1]},
        'over_33_3ms': {'threshold_ms': SLOW_MS, 'count': slow, 'share': slow / len(ordered)},
        'over_16_7ms': {'threshold_ms': FAST_MS, 'count': fast, 'share': fast / len(ordered)},
        'frame_cap': {
            'fps': frame_cap,
            'source': ('supplied by the caller, not recorded in the trace' if frame_cap is not None
                       else 'not recorded in the trace'),
        },
    }


def summarize(paths, frame_cap=None):
    """Measure every trace given, newest first or not, in the order the caller listed them."""
    if isinstance(paths, (str, Path)):
        paths = [paths]
    listed = list(paths)
    if not listed:
        raise ValueError('Give at least one recorded trace to summarize.')
    return {'schema_version': SCHEMA_VERSION,
            'traces': [measure(path, frame_cap=frame_cap) for path in listed],
            'limits': list(LIMITS)}


STATISTICS = (
    ('frames', ('frames',)),
    ('duration_seconds', ('duration_seconds',)),
    ('fps', ('fps',)),
    ('p50_ms', ('frame_time_ms', 'p50')),
    ('p95_ms', ('frame_time_ms', 'p95')),
    ('p99_ms', ('frame_time_ms', 'p99')),
    ('worst_ms', ('frame_time_ms', 'worst')),
    ('over_33_3ms_count', ('over_33_3ms', 'count')),
    ('over_33_3ms_share', ('over_33_3ms', 'share')),
    ('over_16_7ms_count', ('over_16_7ms', 'count')),
    ('over_16_7ms_share', ('over_16_7ms', 'share')),
)


def _one(summary):
    """Accept one trace summary, or the single-trace result of summarize()."""
    if isinstance(summary, dict) and 'traces' in summary:
        traces = summary['traces']
        if len(traces) != 1:
            raise ValueError('Compare exactly one recording against one other; the summary given '
                             f'holds {len(traces)}.')
        return traces[0]
    if not isinstance(summary, dict) or 'duration_seconds' not in summary:
        raise ValueError('A comparison needs a trace summary, for example summarize([path])["traces"][0].')
    return summary


def _value(trace, keys):
    value = trace
    for key in keys:
        value = value[key]
    return value


def compare(baseline, candidate):
    """Delta every statistic between two recordings of about the same length."""
    first, second = _one(baseline), _one(candidate)
    first_seconds, second_seconds = first['duration_seconds'], second['duration_seconds']
    longer = max(first_seconds, second_seconds)
    difference = abs(first_seconds - second_seconds) / longer if longer else 0.0
    if difference > TOLERANCE:
        raise ValueError(
            'These recordings are not comparable: the baseline measured %.3f s and the candidate '
            '%.3f s, a %.1f%% difference against a tolerance of %.0f%% of the longer recording. '
            'Means and percentiles from runs of different lengths cover different amounts of the '
            'scene, so record both runs for about the same time before comparing.'
            % (first_seconds, second_seconds, difference * 100, TOLERANCE * 100))
    statistics = {}
    for name, keys in STATISTICS:
        left, right = _value(first, keys), _value(second, keys)
        statistics[name] = {'baseline': left, 'candidate': right, 'delta': right - left,
                            'relative': (right - left) / left if left else None}
    limitations = ['A comparison of two recordings is not a performance acceptance: the deltas say the '
                   'two runs differed, not why.',
                   'Neither recording identifies its scene, resolution, graphics settings or frame cap, '
                   'so a delta here cannot be attributed to the change between the two runs.']
    for trace in (first, second):
        if trace['frame_cap']['fps'] is None:
            limitations.append(f'{Path(trace["trace"]).name}: the trace does not record the configured '
                               'frame cap, so pacing cannot be separated from a cap.')
    return {'schema_version': SCHEMA_VERSION,
            'baseline': first['trace'], 'candidate': second['trace'],
            'tolerance': {'max_relative_duration_difference': TOLERANCE,
                          'observed_relative_duration_difference': difference,
                          'rule': 'Compare only recordings whose measured durations differ by at most '
                                  '%.0f%% of the longer one.' % (TOLERANCE * 100)},
            'statistics': statistics, 'limitations': limitations}


def _traces(summary):
    if isinstance(summary, dict) and 'traces' in summary:
        return list(summary['traces'])
    return [_one(summary)]


def explain(summary):
    """Statements a human can paste into an issue: what was measured, and what was not."""
    statements = []
    for trace in _traces(summary):
        name = Path(trace['trace']).name
        statistics = trace['frame_time_ms']
        statements.append(
            f'{name}: {trace["frames"]} rendered frames over {trace["duration_seconds"]:.3f} s of '
            f'recording, mean {trace["fps"]:.2f} rendered frames/s.')
        statements.append(
            f'{name}: frame time p50 {statistics["p50"]:.2f} ms, p95 {statistics["p95"]:.2f} ms, '
            f'p99 {statistics["p99"]:.2f} ms, worst {statistics["worst"]:.2f} ms.')
        statements.append(
            f'{name}: {trace["over_33_3ms"]["count"]} frames '
            f'({trace["over_33_3ms"]["share"]:.1%}) took longer than {SLOW_MS} ms and '
            f'{trace["over_16_7ms"]["count"]} frames ({trace["over_16_7ms"]["share"]:.1%}) took longer '
            f'than {FAST_MS} ms.')
        if trace['repeated_render_serials']:
            statements.append(
                f'{name}: {trace["repeated_render_serials"]} guest flips repeated the previous render '
                'serial and were not counted as rendered frames.')
        if trace['segments'] != 1:
            statements.append(
                f'{name}: the recording is {trace["segments"]} separate pieces split by loading '
                'transitions; the duration, rate and shares above cover only the measured pieces.')
    statements.append(
        'Not measured by a trace: the scene, the camera, the output resolution, the graphics settings '
        'and the configured frame cap. The CSV holds flip and present timestamps with render serials '
        'only, so these numbers cannot be attributed to a scene or to a settings profile.')
    statements.append(
        'This is a summary of a recording, not an acceptance. It does not evaluate the 30-minute timing '
        'gate in scripts/order1886_frame_trace.py, issue #3 (sustained 4K/60) or issue #37 (the 8-14 FPS '
        'report from Chapter 2); each of those needs its own decision on a scene-identified capture.')
    statements.append(
        'The configured frame cap is not part of a trace, so no cap is reported here unless a caller '
        'supplies one; a supplied cap is labelled as caller-supplied and may not be the cap that was in '
        'effect during the recording.')
    return statements


def render_text(summary):
    lines = ['Frame trace summary', '']
    for statement in explain(summary):
        lines.append('- ' + statement)
    lines += ['', 'Measured', '  %-40s %6s %9s %7s %7s %7s %7s %9s'
              % ('trace', 'frames', 'duration', 'fps', 'p50', 'p95', 'p99', 'worst')]
    for trace in _traces(summary):
        statistics = trace['frame_time_ms']
        lines.append('  %-40s %6d %8.3fs %7.2f %7.2f %7.2f %7.2f %7.2f'
                     % (Path(trace['trace']).name, trace['frames'], trace['duration_seconds'],
                        trace['fps'], statistics['p50'], statistics['p95'], statistics['p99'],
                        statistics['worst']))
    comparison = summary.get('comparison') if isinstance(summary, dict) else None
    if comparison:
        tolerance = comparison['tolerance']
        lines += ['', 'Comparison', '  %-20s %10s %10s %10s'
                  % ('statistic', 'baseline', 'candidate', 'delta')]
        for name, entry in comparison['statistics'].items():
            number = '%10d' if isinstance(entry['baseline'], int) else '%10.4f'
            lines.append(('  %-20s ' + number + ' ' + number + ' ' + number)
                         % (name, entry['baseline'], entry['candidate'], entry['delta']))
        lines += ['',
                  '  Tolerance: %s' % tolerance['rule'],
                  '  Observed duration difference: %.1f%%'
                  % (100 * tolerance['observed_relative_duration_difference'])]
        for limitation in comparison['limitations']:
            lines.append('  - ' + limitation)
    lines += ['', 'Written by scripts/order1886_perf_report.py from the recorded CSV. '
                  'These are measurements of a recording, not a performance acceptance.']
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('traces', type=Path, nargs='+', metavar='trace',
                        help='performance-*.csv files written by ORDER1886_FRAME_TRACE')
    parser.add_argument('--compare', action='store_true',
                        help='also compare the first two traces and report every delta')
    parser.add_argument('--frame-cap', type=int, default=None,
                        help='configured presentation cap in FPS, when the operator knows it; a '
                             'trace does not record it')
    parser.add_argument('--output-dir', type=Path, default=None,
                        help='where frame-summary.json and frame-summary.txt go (default: next to '
                             'the first trace)')
    args = parser.parse_args(argv)
    try:
        summary = summarize(args.traces, frame_cap=args.frame_cap)
        if args.compare:
            if len(args.traces) != 2:
                raise ValueError('--compare needs exactly two traces, one baseline and one candidate.')
            summary['comparison'] = compare(summary['traces'][0], summary['traces'][1])
    except (TraceError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    directory = args.output_dir or Path(args.traces[0]).resolve().parent
    directory.mkdir(parents=True, exist_ok=True)
    document = json.dumps(summary, indent=2, allow_nan=False) + '\n'
    (directory / 'frame-summary.json').write_text(document, encoding='utf-8')
    (directory / 'frame-summary.txt').write_text(render_text(summary), encoding='utf-8')
    # The exit code reports whether a summary could be produced, never how the run measured.
    print(document, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
