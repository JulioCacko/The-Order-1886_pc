"""Summarize raw guest-flip/render-work timing without certifying gameplay or Gold."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


def measure(events):
    """Validate one trace and return its raw render-work measurements.

    This is the only place the trace format is interpreted: loading boundaries split the
    run into segments, a repeated render serial is not a rendered frame, and the guest
    clock must increase strictly. Anything else that reads a trace (percentiles per
    threshold, comparisons, the launcher's report method) must call this rather than
    re-read the CSV, so every number keeps one definition.
    """
    segments, current = [], []
    previous = None
    for event in events:
        if event['event'] != 'guest_flip':
            continue
        sample = {key: int(event[key]) for key in
                  ('timestamp_ns', 'render_serial', 'buffer_address', 'loading')}
        if sample['timestamp_ns'] < 0 or sample['render_serial'] < 0:
            raise ValueError('negative guest timestamp or render serial')
        if previous is not None and sample['timestamp_ns'] <= previous:
            raise ValueError('guest timestamps must increase strictly')
        previous = sample['timestamp_ns']
        if sample['loading']:
            if current:
                segments.append(current)
                current = []
        else:
            current.append(sample)
    if current:
        segments.append(current)
    elapsed_ns = guest_intervals = rendered_intervals = repeats = 0
    intervals = []
    for segment in segments:
        elapsed_ns += segment[-1]['timestamp_ns'] - segment[0]['timestamp_ns']
        guest_intervals += len(segment) - 1
        last = segment[0]
        for sample in segment[1:]:
            if sample['render_serial'] < last['render_serial']:
                raise ValueError('render serial decreased inside a segment')
            if sample['render_serial'] == last['render_serial']:
                repeats += 1
                continue
            intervals.append((sample['timestamp_ns'] - last['timestamp_ns']) / 1e6)
            rendered_intervals += 1
            last = sample
        if segment[-1]['timestamp_ns'] > last['timestamp_ns']:
            intervals.append((segment[-1]['timestamp_ns'] - last['timestamp_ns']) / 1e6)
    return {
        'segments': len(segments), 'measured_seconds': elapsed_ns / 1e9,
        'intervals_ms': intervals, 'guest_intervals': guest_intervals,
        'rendered_intervals': rendered_intervals, 'repeated_render_serials': repeats,
    }


def summarize(events):
    data = measure(events)
    seconds, intervals = data['measured_seconds'], data['intervals_ms']
    rendered_intervals = data['rendered_intervals']
    ordered = sorted(intervals)
    p99 = ordered[math.ceil(len(ordered) * .99) - 1] if ordered else None
    fps = rendered_intervals / seconds if seconds else None
    return {
        'segments': data['segments'], 'measured_seconds': seconds,
        'guest_flip_fps': data['guest_intervals'] / seconds if seconds else None,
        'render_work_fps': fps, 'p99_ms': p99, 'worst_ms': max(ordered) if ordered else None,
        'repeated_render_serials': data['repeated_render_serials'],
        'timing_gate_passed': bool(seconds >= 1800 and fps is not None and fps >= 59
                                   and p99 is not None and p99 <= 20),
        'milestone_accepted': False,
        'evidence_limits': 'Render-work serials require image/command validation to establish unique rendered frames. '
                           'This timing summary does not certify combat, output resolution, provider, input, audio or saves.',
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    with args.trace.open(newline='', encoding='utf-8') as source:
        result = summarize(csv.DictReader(source))
    result['trace'] = str(args.trace.resolve())
    text = json.dumps(result, indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    print(text, end='')
    return 0 if result['timing_gate_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
