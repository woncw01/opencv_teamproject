"""B·C 성능 계측과 실험 자동화 (담당 C).
입력: perf_counter 기반 프레임 표본/실제 영상 경로. 출력: CSV, 통계, 그래프.
의존: numpy, pandas, matplotlib; 실행 시 pipeline을 지연 import한다.
Mock 표본은 실제 결과와 분리하며 정답 평가는 Mock을 거부한다.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
from pathlib import Path
import time
import uuid
from typing import Any

import numpy as np

STAGES = ('read', 'queue_wait', 'preprocess', 'detect', 'intrusion', 'state',
          'record', 'display', 'total')
RAW_FIELDS = ['run_id', 'source', 'pipeline_mode', 'resolution', 'variant', 'repeat',
              'experiment_kind', 'mock', 'frame_index', 'cycle', 'media_time_s',
              'source_fps', 'captured_at', 'scheduled_at', 'processing_started_at',
              'completed_at', 'measurement_start_at', 'measurement_end_at',
              'analyzed', 'dropped', 'warmup', 'observed_duration_s',
              'alert_delay_s', 'system_alert_delay_ms', 'scheduled_alert_delay_ms'] + [s + '_ms' for s in STAGES]


@contextmanager
def measure(row: dict, stage: str):
    """Measure a block into row[stage+'_ms']; record even when the block raises."""
    start = time.perf_counter()
    try:
        yield
    finally:
        row[stage + '_ms'] = (time.perf_counter() - start) * 1000


def _stats(values) -> dict[str, float]:
    """Return finite-value mean/median/population std/p95; empty values yield NaN."""
    a = np.asarray([float(x) for x in values if x is not None and x != ''], dtype=float)
    a = a[np.isfinite(a)]
    if not len(a):
        return dict.fromkeys(('mean', 'median', 'std', 'p95'), float('nan'))
    return dict(mean=float(a.mean()), median=float(np.median(a)),
                std=float(a.std(ddof=0)), p95=float(np.percentile(a, 95)))


def summarize_metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Exclude warm-up, validate monotonic completion, then aggregate actual samples.
    Input rows use Python bool flags and perf_counter seconds. Throughput uses the
    complete measured interval including read/queue/display/record costs; FPS
    samples use successive analyzed completion intervals. Empty stats are NaN.
    """
    measured = [r for r in rows if not r.get('warmup', False)]
    analyzed = [r for r in measured if r.get('analyzed', True) and not r.get('dropped', False)]
    ends = np.asarray([r['completed_at'] for r in analyzed], dtype=float)
    diffs = np.diff(ends)
    if np.any(diffs <= 0):
        raise ValueError('Completion times must strictly increase')
    fps = _stats(1 / diffs)
    elapsed = 0.0
    if measured:
        elapsed = max(r['measurement_end_at'] for r in measured) - min(r['measurement_start_at'] for r in measured)
        if elapsed <= 0:
            raise ValueError('Measurement interval must be positive')
    result = {'throughput_fps': len(analyzed) / elapsed if elapsed else float('nan'),
              'mean_fps': fps['mean'], 'median_fps': fps['median'],
              'std_fps': fps['std'], 'p95_fps': fps['p95'],
              'elapsed_seconds': elapsed, 'input_frames': len(measured),
              'analyzed_frames': len(analyzed),
              'drop_rate': sum(bool(r.get('dropped')) for r in measured) / len(measured) if measured else float('nan'),
              'skip_rate': sum(not r.get('analyzed', True) and not r.get('dropped', False) for r in measured) / len(measured) if measured else float('nan')}
    for key in [s + '_ms' for s in STAGES] + ['alert_delay_s', 'system_alert_delay_ms', 'scheduled_alert_delay_ms']:
        for stat, value in _stats(r.get(key) for r in measured).items():
            result[f'{key}_{stat}'] = value
    return result


def write_table(path: str | Path, rows: list[dict], fields: list[str], *, append=False) -> None:
    """Write fixed-schema UTF-8 CSV, ignoring extra keys; caller serializes writers.
    Append validates existing schema; no synchronous per-frame writes are used.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    if append and exists:
        with path.open(encoding='utf-8', newline='') as f:
            if next(csv.reader(f)) != fields:
                raise ValueError(f'CSV schema mismatch: {path}')
    with path.open('a' if append else 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        if not append or not exists:
            writer.writeheader()
        writer.writerows(rows)


def write_metrics(path: str, rows: list[dict[str, Any]]) -> None:
    """Write buffered frame rows with stable headers; empty input writes a header."""
    write_table(path, rows, RAW_FIELDS)


def save_run_metrics(root: Path, run_dir: Path, rows: list[dict], metadata: dict) -> dict:
    """Save immutable per-run samples and append root aggregates after execution."""
    summary = {**metadata, **summarize_metrics(rows)}
    write_metrics(str(run_dir / 'benchmark_raw.csv'), rows)
    write_table(root / 'benchmark_raw.csv', rows, RAW_FIELDS, append=True)
    fields = list(summary)
    write_table(run_dir / 'benchmark_summary.csv', [summary], fields)
    write_table(root / 'benchmark_summary.csv', [summary], fields, append=True)
    return summary


def generate_plots(summary_path: str | Path, output_dir: str | Path) -> list[Path]:
    """Plot only existing measured rows; empty or invalid data returns [] with notice.
    Each experiment kind is kept separate. Mock plots carry a MOCK watermark.
    """
    import pandas as pd
    path = Path(summary_path)
    if not path.exists() or path.stat().st_size == 0:
        print('[benchmark] 데이터 없음: 그래프를 생성하지 않습니다.')
        return []
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        print('[benchmark] 데이터 없음: 그래프를 생성하지 않습니다.')
        return []
    if 'run_status' in df:
        df = df[df.run_status.eq('completed')]
    if df.empty or 'throughput_fps' not in df or not np.isfinite(df['throughput_fps']).any():
        print('[benchmark] 유효한 측정 데이터 없음.')
        return []
    if df['source'].nunique() > 1:
        raise ValueError('Select one source video before plotting')
    if df['experiment_kind'].nunique() > 1 or df['mock'].nunique() > 1:
        raise ValueError('Separate experiment kinds and mock/real before plotting')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    mock = str(df['mock'].iloc[0]).lower() in ('true', '1')
    label = ('MOCK - NOT DETECTION PERFORMANCE | ' if mock else '') + str(df['experiment_kind'].iloc[0])
    specs = [
        ('fps_comparison.png', df[df.variant.eq('standard')].pivot_table(index='resolution', columns='pipeline_mode', values='throughput_fps', aggfunc='mean'), 'Throughput FPS'),
        ('stage_latency.png', df[df.variant.eq('standard')].groupby(['resolution', 'pipeline_mode'])[[s + '_ms_mean' for s in STAGES if s != 'total']].mean(), 'Mean stage latency (ms)'),
        ('optimization_comparison.png', df[df.pipeline_mode.eq('optimized')].pivot_table(index='resolution', columns='variant', values='throughput_fps', aggfunc='mean'), 'Throughput FPS'),
    ]
    files = []
    for name, table, ylabel in specs:
        if table.empty:
            print(f'[benchmark] {name}: 해당 조건 데이터 없음')
            continue
        ax = table.plot.bar(figsize=(11, 5))
        ax.set_ylabel(ylabel)
        ax.set_title(label)
        ax.figure.tight_layout()
        target = out / name
        ax.figure.savefig(target, dpi=140)
        plt.close(ax.figure)
        files.append(target)
    return files


def evaluate_events(truth: list[dict], events: list[dict], *, video_name: str,
                    tolerance_s: float = 0.0, mock: bool = False) -> dict:
    """One-to-one maximum bipartite matching by video, zone and interval overlap.
    Truth types: intrusion/normal. Events must come from ONE run. False alarm rate
    = unmatched alarms / all alarms, miss rate = unmatched truth / intrusion truth.
    Normal windows are annotations, not an invented count of true negatives.
    Open events and mock outputs are rejected. Empty denominators return NaN.
    """
    if mock or any(str(e.get('mock', '')).lower() in ('true', '1') for e in events):
        raise ValueError('Mock cannot be used for detection accuracy')
    if not np.isfinite(tolerance_s) or tolerance_s < 0:
        raise ValueError('Tolerance must be nonnegative')
    if len({e.get('run_id') for e in events}) > 1:
        raise ValueError('Evaluate one run at a time')
    if any(t['event_type'] not in ('intrusion', 'normal') for t in truth):
        raise ValueError('Truth event_type must be intrusion or normal')
    gt = [t for t in truth if t['video_name'] == video_name and t['event_type'] == 'intrusion']
    ev = [e for e in events if e.get('video_name', video_name) == video_name]
    if any(e.get('end_time') in (None, '') or e.get('status', 'closed') != 'closed' for e in ev):
        raise ValueError('Open/incomplete events require review before evaluation')
    for item in gt + ev:
        if not all(np.isfinite(float(item[k])) for k in ('start_time', 'end_time')) or float(item['end_time']) < float(item['start_time']):
            raise ValueError('Invalid interval')
    candidates = {i: [j for j, t in enumerate(gt)
                      if e['zone_name'] == t['zone_name']
                      and float(e['start_time']) <= float(t['end_time']) + tolerance_s
                      and float(e['end_time']) >= float(t['start_time']) - tolerance_s]
                  for i, e in enumerate(ev)}
    assigned = {}

    def match(i, visited):
        """Augment one matching path; visited truth indices prevent recursion cycles."""
        for j in candidates[i]:
            if j in visited:
                continue
            visited.add(j)
            if j not in assigned or match(assigned[j], visited):
                assigned[j] = i
                return True
        return False

    for i in range(len(ev)):
        match(i, set())
    tp = len(assigned)
    delays = [float(ev[i]['alert_time']) - float(gt[j]['start_time']) for j, i in assigned.items()]
    return {'actual_events': len(gt), 'detected_events': tp,
            'false_alarms': len(ev) - tp, 'missed_events': len(gt) - tp,
            'false_alarm_rate': (len(ev) - tp) / len(ev) if ev else float('nan'),
            'miss_rate': (len(gt) - tp) / len(gt) if gt else float('nan'),
            'mean_alert_delay_s': _stats(delays)['mean']}


def run_suite(source: str, config: dict, *, seconds=60.0, repeats=3,
              experiment_kind='throughput', mock=False, no_display=False,
              resolutions=((640, 480), (1280, 720), (1920, 1080)), ablations=False) -> None:
    """Run >=60 measured wall seconds/condition, >=3 repeats; replay short files.
    Resize the SAME real source at input and transform zones from native geometry.
    Each EOF resets A's model/state; recorder finalizes truncated boundary clips.
    No synthetic source is created. Optional ablations are single-change variants.
    """
    from .pipeline import run_pipeline
    if seconds < 60 or repeats < 3:
        raise ValueError('Formal benchmark requires >=60 seconds and >=3 repeats')
    if str(source).isdigit() or not Path(source).is_file():
        raise ValueError('Benchmark requires an existing video file')
    suite_id = 'suite-' + uuid.uuid4().hex[:10]
    variants = [('baseline', 'standard', {}), ('threaded', 'standard', {}), ('optimized', 'standard', {})]
    if ablations:
        base = dict(roi_enabled=False, resize_enabled=False, frame_interval=1)
        variants += [('optimized', name, {**base, **changes}) for name, changes in (
            ('none', {}), ('roi_only', {'roi_enabled': True}), ('resize_only', {'resize_enabled': True}),
            ('interval_only', {'frame_interval': 2}), ('queue_only', {'queue_max_size': 2}))]
    for resolution in resolutions:
        for repeat in range(1, repeats + 1):
            order = variants[repeat % len(variants):] + variants[:repeat % len(variants)]
            for mode, variant, changes in order:
                current = {**config, **changes, 'input_resolution': list(resolution),
                           'duration_seconds': seconds, 'loop_video': True, 'suite_run': True, 'suite_id': suite_id,
                           'experiment_kind': experiment_kind, 'mock_detection': mock,
                           'no_display': no_display, 'measure_fps': True,
                           'repeat': repeat, 'variant': variant}
                run_pipeline(source, mode, current)
    root = Path(config.get('output_dir', 'results'))
    if mock:
        root /= 'mock'
    root /= experiment_kind
    root /= suite_id
    generate_plots(root / 'benchmark_summary.csv', root)


def main(argv=None) -> int:
    """Parse benchmark suite/plots CLI; invalid input returns an argparse error."""
    from .utils import load_config
    ap = argparse.ArgumentParser(description='Real video benchmark; mock results are isolated')
    ap.add_argument('--source')
    ap.add_argument('--config', default='config.json')
    ap.add_argument('--seconds', type=float, default=60)
    ap.add_argument('--repeats', type=int, default=3)
    ap.add_argument('--experiment-kind', choices=('throughput', 'realtime'), default='throughput')
    ap.add_argument('--mock-detection', action='store_true')
    ap.add_argument('--no-display', action='store_true')
    ap.add_argument('--ablations', action='store_true')
    ap.add_argument('--plot-only', metavar='SUMMARY_CSV')
    ap.add_argument('--output-dir')
    args = ap.parse_args(argv)
    try:
        if args.plot_only:
            generate_plots(args.plot_only, args.output_dir or str(Path(args.plot_only).parent))
        else:
            config = load_config(args.config)
            if args.output_dir:
                config['output_dir'] = args.output_dir
            run_suite(args.source or config['source'], config, seconds=args.seconds,
                      repeats=args.repeats, experiment_kind=args.experiment_kind,
                      mock=args.mock_detection, no_display=args.no_display, ablations=args.ablations)
    except (ValueError, OSError, NotImplementedError, RuntimeError) as exc:
        ap.error(str(exc))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
