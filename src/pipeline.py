"""B: 공통 분석, 원본 보존 순차/입력 스레드 실행, 사건 CSV 및 화면 표시.
입력: source/mode/config, 선택적 명시적 Mock backend. 출력: 종료 코드와 results.
의존: 수정하지 않은 A의 preprocess/detect/zones/state, recorder, benchmark.
A NotImplementedError는 전파한다. Mock은 고정 시간표이며 실제 검출이 아니다.
큐 드롭은 원본 보존 경로가 없는 현재 구현에서 명시적으로 비활성화한다.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
from queue import Queue, Empty, Full
import threading
import time
from typing import Any
import uuid

import cv2
import numpy as np

from . import detect, preprocess, state, zones as zone_module
from .benchmark import measure, save_run_metrics, write_table
from .recorder import create_recorder, buffer_frame, record_frame, close_recorder

EVENT_FIELDS = ['run_id', 'video_name', 'mock', 'event_id', 'zone_name', 'start_time',
                'alert_time', 'end_time', 'duration_seconds', 'video_path', 'pipeline_mode',
                'status', 'occurred_at', 'alert_perf_counter', 'input_perf_counter',
                'system_alert_delay_ms', 'scheduled_alert_delay_ms', 'onset_basis',
                'truncated']
CLIP_FIELDS = ['path', 'event_ids', 'zone_name', 'alert_time_s', 'occurred_at', 'start_s',
               'end_s', 'truncated', 'pre_truncated', 'post_truncated', 'frames_written',
               'held_ticks', 'resampled_inputs', 'recording_fps', 'resampling']


def validate_config(config: dict) -> dict:
    """Copy and validate B/C settings without changing shared A function signatures.
    Invalid values or unsupported drop policy fail before opening input/writers.
    """
    c = deepcopy(config)
    defaults = dict(queue_max_size=8, queue_policy='block', frame_interval=1,
                    consecutive_frames=5, clear_frames=10, min_area=200, blur_kernel=5,
                    warmup_frames=30, pre_seconds=3.0, post_seconds=5.0,
                    analysis_resolution=[640, 360], roi_enabled=False, roi_margin=32,
                    resize_enabled=True, measure_fps=True, no_display=False,
                    mock_detection=False, recording_enabled=True, recorder_max_mb=1024,
                    recording_codec='mp4v', output_dir='results', loop_video=False,
                    duration_seconds=0.0, experiment_kind='throughput',
                    camera_fps=30.0, timestamp_mode='cfr', thread_join_timeout=5.0,
                    variant='standard', repeat=1, input_resolution=None)
    for key, value in defaults.items():
        c.setdefault(key, value)
    for key in ('queue_max_size', 'frame_interval', 'consecutive_frames', 'clear_frames', 'min_area', 'blur_kernel'):
        if type(c[key]) is not int or c[key] <= 0:
            raise ValueError(f'{key} must be a positive integer')
    for key in ('warmup_frames', 'roi_margin'):
        if type(c[key]) is not int or c[key] < 0:
            raise ValueError(f'{key} must be a nonnegative integer')
    if c['blur_kernel'] % 2 != 1:
        raise ValueError('blur_kernel must be odd')
    for key in ('pre_seconds', 'post_seconds', 'duration_seconds', 'camera_fps', 'recorder_max_mb', 'thread_join_timeout'):
        if isinstance(c[key], bool) or not isinstance(c[key], (int, float)) or not math.isfinite(c[key]) or c[key] < 0:
            raise ValueError(f'{key} must be finite and nonnegative')
    if min(c['camera_fps'], c['recorder_max_mb'], c['thread_join_timeout']) <= 0:
        raise ValueError('camera_fps/recorder_max_mb/thread_join_timeout must be positive')
    for key in ('analysis_resolution', 'input_resolution'):
        value = c[key]
        if value is None and key == 'input_resolution':
            continue
        if not isinstance(value, (list, tuple)) or len(value) != 2 or any(type(x) is not int or x <= 0 for x in value):
            raise ValueError(f'{key} must be [width,height] positive integers')
    for key in ('roi_enabled', 'resize_enabled', 'measure_fps', 'no_display', 'mock_detection', 'recording_enabled', 'loop_video'):
        if type(c[key]) is not bool:
            raise ValueError(f'{key} must be bool')
    if c['queue_policy'] != 'block':
        raise ValueError('drop_oldest is disabled: a separate lossless recording path is not implemented; use block')
    if c['timestamp_mode'] not in ('cfr', 'pts'):
        raise ValueError('timestamp_mode must be cfr or pts')
    if c['experiment_kind'] not in ('throughput', 'realtime'):
        raise ValueError('experiment_kind must be throughput or realtime')
    if not isinstance(c['recording_codec'], str) or len(c['recording_codec']) != 4:
        raise ValueError('recording_codec must be four characters')
    if c['loop_video'] and c['duration_seconds'] <= 0:
        raise ValueError('loop_video requires a duration limit')
    return c


class FrameSource:
    """One capture owner, sequential iterator or bounded block Queue producer.
    File timestamps use index/FPS (CFR) or strictly increasing CAP_PROP_POS_MSEC.
    Camera timestamps use perf_counter. Exceptions are delivered after queued data.
    """

    def __init__(self, source: str, config: dict, threaded=False, *, capture_factory=None):
        """Open capture, validate metadata, initialize stop/done Events; no worker yet."""
        self.config, self.threaded = config, threaded
        self.camera = str(source).isdigit()
        if self.camera and config['loop_video']:
            raise ValueError('Camera input cannot loop')
        factory = capture_factory or cv2.VideoCapture
        self.cap = factory(int(source) if self.camera else str(source))
        try:
            if not self.cap.isOpened():
                raise OSError(f'Cannot open input: {source}')
            fps = float(self.cap.get(cv2.CAP_PROP_FPS))
            self.native_size = (int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
            if min(self.native_size) <= 0:
                raise ValueError('Input dimensions unavailable')
            if not self.camera and (not math.isfinite(fps) or fps <= 0):
                raise ValueError('File FPS unavailable: provide valid timestamped video')
            self.fps = fps if math.isfinite(fps) and fps > 0 else float(config['camera_fps'])
            self.size = tuple(config['input_resolution'] or self.native_size)
        except BaseException:
            self.cap.release()
            raise
        self.stop = threading.Event()
        self.done = threading.Event()
        self.queue = Queue(maxsize=config['queue_max_size'])
        self.error = None
        self.thread = None
        self.generator = None
        self.dropped = 0
        self.produced = 0
        self.closed = False

    def _packets(self):
        """Read/copy original frames; loop boundaries are explicit packets, never hidden."""
        index, cycle, local_index, offset = 0, 0, 0, 0.0
        epoch = time.perf_counter()
        last_media, first_pts = None, None
        try:
            while not self.stop.is_set():
                read_start = time.perf_counter()
                ok, frame = self.cap.read()
                if not ok:
                    if local_index == 0:
                        raise OSError('Input has no decodable frames')
                    if not self.config['loop_video'] or self.stop.is_set():
                        break
                    if not self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0):
                        raise OSError('Cannot rewind input')
                    offset = last_media + 1 / self.fps
                    cycle += 1
                    local_index, first_pts = 0, None
                    continue
                acquired = time.perf_counter()
                decode_ms = (acquired-read_start)*1000
                if self.camera:
                    media = acquired - epoch
                elif self.config['timestamp_mode'] == 'pts':
                    pts = float(self.cap.get(cv2.CAP_PROP_POS_MSEC)) / 1000
                    if not math.isfinite(pts) or pts < 0:
                        raise ValueError('Invalid file PTS; use explicitly verified CFR input')
                    if first_pts is None:
                        first_pts = pts
                    media = offset + pts - first_pts
                else:
                    media = offset + local_index / self.fps
                if last_media is not None and media <= last_media:
                    raise ValueError('Input timestamps are not strictly increasing')
                scheduled = epoch + media
                if not self.camera and self.config['experiment_kind'] == 'realtime':
                    if self.stop.wait(max(0, scheduled - time.perf_counter())):
                        break
                    acquired = time.perf_counter()  # time frame is admitted to the system
                original_frame = frame
                resize_start = time.perf_counter()
                if self.size != self.native_size:
                    frame = cv2.resize(frame, self.size, interpolation=cv2.INTER_AREA)
                read_ms = decode_ms + (time.perf_counter()-resize_start)*1000
                packet = dict(frame=frame, original_frame=original_frame, frame_index=index, cycle=cycle,
                              cycle_frame_index=local_index, media_time_s=media,
                              cycle_time_s=media-offset, captured_at=acquired,
                              scheduled_at=scheduled if self.config['experiment_kind'] == 'realtime' else None,
                              read_ms=read_ms, enqueued_at=time.perf_counter(),
                              read_started_at=read_start)
                self.produced += 1
                yield packet
                last_media = media
                index += 1
                local_index += 1
        finally:
            self.cap.release()

    def _produce(self):
        """Block with timeouts; publish failure out-of-band so full Queue cannot hide it."""
        try:
            for packet in self._packets():
                while not self.stop.is_set():
                    try:
                        self.queue.put(packet, timeout=.05)
                        break
                    except Full:
                        continue
                if self.stop.is_set():
                    break
        except BaseException as exc:
            self.error = exc
        finally:
            self.cap.release()
            self.done.set()

    def __iter__(self):
        """Start once; consumer remains on main thread."""
        if self.threaded:
            if self.thread is None:
                self.thread = threading.Thread(target=self._produce, name='opencv-input', daemon=True)
                self.thread.start()
        elif self.generator is None:
            self.generator = self._packets()
        return self

    def __next__(self):
        """Deliver buffered packet, then worker error/EOF; consumer never hangs on EOF."""
        if not self.threaded:
            return next(self.generator)
        while True:
            try:
                return self.queue.get(timeout=.05)
            except Empty:
                if self.done.is_set():
                    if self.error:
                        error, self.error = self.error, None
                        raise error
                    raise StopIteration

    def close(self):
        """Signal stop and join; reject blocked device shutdown instead of hiding it.
        A native camera read may ignore interruption; bounded shutdown cannot be
        guaranteed by OpenCV on every device. A daemon prevents interpreter hangs.
        """
        if self.closed:
            return
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=self.config['thread_join_timeout'])
            if self.thread.is_alive():
                raise RuntimeError('Camera/backend read did not stop within join timeout')
        if self.generator:
            self.generator.close()
        self.cap.release()
        self.closed = True


def _analysis(frame, background_subtractor, zones, config) -> tuple[dict, list, dict]:
    """Call A's shared functions and return intrusion, original boxes and stage ms."""
    timing = {}
    roi = None
    if config['roi_enabled'] and zones:
        points = np.concatenate([np.asarray(z['points']) for z in zones])
        margin = config['roi_margin']
        h, w = frame.shape[:2]
        lo = np.maximum(points.min(axis=0) - margin, [0, 0]).astype(int)
        hi = np.minimum(points.max(axis=0) + margin + 1, [w, h]).astype(int)
        roi = (int(lo[0]), int(lo[1]), int(hi[0]-lo[0]), int(hi[1]-lo[1]))
    with measure(timing, 'preprocess'):
        image, transform = preprocess.preprocess_frame(frame, config, roi)
    with measure(timing, 'detect'):
        boxes = detect.detect_motion(image, background_subtractor,
                                     config['min_area'] * transform['scale_x'] * transform['scale_y'])
    with measure(timing, 'intrusion'):
        boxes = preprocess.restore_boxes(boxes, transform)
        intrusions = detect.check_intrusion(boxes, zones)
    return intrusions, boxes, timing


def analyze_frame(frame: np.ndarray, background_subtractor: Any,
                  zones: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, bool]:
    """Preserved public A-composition interface: original frame/settings -> zone bools."""
    return _analysis(frame, background_subtractor, zones, validate_config(config))[0]


class RealBackend:
    """Thin adapter to unchanged A interfaces; never falls back to mock silently."""

    def __init__(self, config, native_size, size):
        """Load native zones through A and scale only for explicit input experiments."""
        self.config = config
        self.zones = zone_module.load_zones(config['zones_path'], native_size)
        if native_size != size:
            self.zones = deepcopy(self.zones)
            for zone in self.zones:
                zone['points'] = [[round(x*size[0]/native_size[0]), round(y*size[1]/native_size[1])]
                                  for x, y in zone['points']]
        self.reset()

    def reset(self):
        """Fresh background model and state at each replay boundary."""
        self.background = detect.create_background_subtractor(self.config)
        self.states = {}

    def analyze(self, frame, packet):
        """Original frame/packet -> zone booleans, boxes, timing through common A path."""
        return _analysis(frame, self.background, self.zones, self.config)

    def update(self, intrusions, packet):
        """Call A state even for skipped(None) frames; original index/time preserved."""
        self.states, events = state.update_state(self.states, intrusions, packet['frame_index'],
                                                 packet['media_time_s'], self.config)
        return self.states, events


class MockBackend:
    """Explicit test fixture with scripted times; does NOT implement A algorithms/N.
    Default schedule: observed 1s, alert 1.5s, clear 2.5s. No accuracy inference.
    """
    is_mock = True

    def __init__(self, config, size):
        """Validate scripted schedules and create visible full-frame mock zones."""
        self.schedule = deepcopy(config.get('mock_events', [dict(zone_name='MOCK_ZONE', start=1.0, alert=1.5, end=2.5)]))
        for e in self.schedule:
            if not (0 <= e['start'] <= e['alert'] < e['end']):
                raise ValueError('Invalid mock schedule')
        w, h = size
        self.zones = [dict(name=name, points=[[0, 0], [w-1, 0], [w-1, h-1], [0, h-1]])
                      for name in sorted({e['zone_name'] for e in self.schedule})]
        self.reset()

    def reset(self):
        """Clear fixture emission flags at replay boundary."""
        self.alerted, self.cleared = set(), set()
        self.states = {z['name']: {'status': 'IDLE'} for z in self.zones}

    def analyze(self, frame, packet):
        """Return scheduled booleans and a clearly mock box, without inspecting pixels."""
        start = time.perf_counter()
        t = packet['cycle_time_s']
        values = {z['name']: any(e['zone_name'] == z['name'] and e['start'] <= t < e['end'] for e in self.schedule) for z in self.zones}
        h, w = frame.shape[:2]
        return values, ([(w//4, h//4, w//2, h//2)] if any(values.values()) else []), {'detect_ms': (time.perf_counter()-start)*1000}

    def update(self, intrusions, packet):
        """Emit fixture transitions only on analyzed frames; no stale-success counting."""
        if intrusions is None:
            return self.states, []
        t = packet['cycle_time_s']
        events = []
        for i, e in enumerate(self.schedule):
            name = e['zone_name']
            if e['start'] <= t < e['alert']:
                self.states[name] = {'status': 'DETECTING'}
            if e['alert'] <= t < e['end'] and i not in self.alerted:
                self.alerted.add(i)
                self.states[name] = {'status': 'ALERT'}
                events.append(dict(type='alert', event_id=f'mock-{i}', zone_name=name, media_time_s=packet['media_time_s']))
            if t >= e['end'] and i in self.alerted and i not in self.cleared:
                self.cleared.add(i)
                self.states[name] = {'status': 'CLEARED'}
                events.append(dict(type='cleared', event_id=f'mock-{i}', zone_name=name, media_time_s=packet['media_time_s']))
        return self.states, events


class EventLedger:
    """B metadata adapter: observations enrich A transitions, never decide alerts.
    Starts/ends are first observed true/first false in the confirmed clear streak.
    Unknown skipped observations invalidate pending streaks, not confirmed events.
    """

    def __init__(self, run_id, source, mode, mock):
        """Initialize per-run metadata and per-zone onset/clear observation maps."""
        self.run_id, self.source, self.mode, self.mock = run_id, Path(str(source)).name, mode, mock
        self.rows, self.active, self.starts, self.false_starts = {}, {}, {}, {}
        self.ids = {}
        self.sampled_spans = {}

    def observe(self, intrusions, t):
        """Track observed candidate onset/end only; None never counts as detection."""
        if intrusions is None:
            self.starts = {z: start for z, start in self.starts.items() if z in self.active}
            self.false_starts.clear()
            return
        for zone, present in intrusions.items():
            if present:
                first, _ = self.sampled_spans.get(zone, (t, t))
                self.sampled_spans[zone] = (first, t)
                self.starts.setdefault(zone, t)
                self.false_starts.pop(zone, None)
            elif zone in self.active:
                self.sampled_spans.pop(zone, None)
                self.false_starts.setdefault(zone, t)
            else:
                self.sampled_spans.pop(zone, None)
                self.starts.pop(zone, None)

    def transitions(self, events, packet, cycle):
        """Normalize IDs and enrich CSV rows without changing A event dictionaries."""
        normalized = []
        now = time.perf_counter()
        for original in events:
            event = dict(original)
            zone = event['zone_name']
            local_id = (cycle, zone, str(event['event_id']))
            key = self.ids.setdefault(local_id, f'{self.run_id}-{len(self.ids)+1:04d}')
            event['event_id'] = key
            t = float(event['media_time_s'])
            if event['type'] == 'alert' and key not in self.rows:
                start = float(event.get('start_time_s', self.starts.get(zone, t)))
                if start > t:
                    raise ValueError('Event onset is after alert')
                scheduled = packet.get('scheduled_at')
                self.rows[key] = dict(run_id=self.run_id, video_name=self.source, mock=self.mock,
                                     event_id=key, zone_name=zone, start_time=start, alert_time=t,
                                     end_time=None, duration_seconds=None, video_path='', pipeline_mode=self.mode,
                                     status='open', occurred_at=datetime.now(timezone.utc).isoformat(),
                                     alert_perf_counter=now, input_perf_counter=packet['captured_at'],
                                     system_alert_delay_ms=(now-packet['captured_at'])*1000,
                                     scheduled_alert_delay_ms=(now-scheduled)*1000 if scheduled is not None else None,
                                     onset_basis='backend' if 'start_time_s' in event else 'first_observed_frame', truncated=False)
                self.active[zone] = key
                normalized.append(event)
            elif event['type'] == 'cleared' and key in self.rows and self.rows[key]['status'] == 'open':
                end = float(event.get('end_time_s', self.false_starts.get(zone, t)))
                row = self.rows[key]
                if end < row['start_time']:
                    raise ValueError('Event ends before onset')
                row.update(end_time=end, duration_seconds=end-row['start_time'], status='closed')
                self.active.pop(zone, None)
                self.starts.pop(zone, None)
                self.false_starts.pop(zone, None)
                normalized.append(event)
        return normalized

    def attach_clips(self, clips):
        """Attach finished video paths once; preserve independent event IDs."""
        for clip in clips:
            for key in clip['event_ids']:
                if key in self.rows:
                    self.rows[key].update(video_path=clip['path'], truncated=clip['truncated'])

    def finish(self, reason):
        """Mark unresolved events censored at EOF/error; do not invent an end time."""
        for key in self.active.values():
            self.rows[key]['status'] = reason
        self.active.clear()
        self.starts.clear()
        self.false_starts.clear()
        self.sampled_spans.clear()


def _draw(frame, mode, fps, zones, boxes, states, recording, mock):
    """Draw original-coordinate overlays on a copy; caller is always the main thread."""
    out = frame.copy()
    for index, zone in enumerate(zones):
        points = np.asarray(zone['points'], dtype=np.int32)
        cv2.polylines(out, [points], True, (0, 220, 220), 2)
        cv2.putText(out, f'Zone {index+1}', tuple(points[0]),
                    cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 220, 220), 1)
        # OpenCV Hershey fonts do not render Korean; labels are indexed in metadata.
    for x, y, w, h in boxes:
        cv2.rectangle(out, (x, y), (x+w, y+h), (0, 255, 0), 2)
    alert = any(s.get('status') == 'ALERT' for s in states.values())
    if alert:
        cv2.rectangle(out, (1, 1), (out.shape[1]-2, out.shape[0]-2), (0, 0, 255), 6)
    lines = [f'{mode} FPS {fps:.1f} REC {recording}', 'MOCK - NOT REAL DETECTION' if mock else 'REAL DETECTION']
    lines += [f'Zone {i+1}: {states.get(z["name"], {}).get("status", "IDLE")}' for i, z in enumerate(zones)]
    if alert:
        lines.append('WARNING: INTRUSION')
    for i, text in enumerate(lines):
        cv2.putText(out, text, (10, 25+i*23), cv2.FONT_HERSHEY_SIMPLEX, .55, (0, 0, 255) if alert else (255, 255, 255), 1)
    return out


def _file_hash(source):
    """Stream SHA-256 without loading video into RAM; camera has no file hash."""
    if str(source).isdigit():
        return None
    digest = hashlib.sha256()
    with open(source, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def run_pipeline(source: str, mode: str, config: dict[str, Any], *, backend=None) -> int:
    """Run baseline/threaded/optimized; existing three positional args are preserved.
    Optional backend must explicitly declare is_mock=True and implements reset,
    analyze/update/zones. A errors propagate. All original frames reach recorder,
    including frame_interval skips; output is finalized on EOF, q, error, Ctrl-C.
    """
    c = validate_config(config)
    if mode not in ('baseline', 'threaded', 'optimized'):
        raise ValueError('Unknown mode')
    mock = c['mock_detection'] or backend is not None
    if backend is not None and not getattr(backend, 'is_mock', False):
        raise ValueError('Injected test backend must declare is_mock=True')
    if not c['no_display'] and threading.current_thread() is not threading.main_thread():
        raise RuntimeError('GUI must run on main thread')
    reader = FrameSource(source, c, threaded=mode != 'baseline')
    rec, ledger, output, run_dir = None, None, None, None
    rows, all_clips = [], []
    status, current_cycle = 'failed', None
    started_measurement, ended_measurement = None, None
    metadata = None
    error = None
    processed_frames = 0
    try:
        if mode != 'optimized':
            c.update(roi_enabled=False, resize_enabled=False, frame_interval=1)
        if not c['resize_enabled']:
            c['analysis_resolution'] = list(reader.size)
        backend = backend or (MockBackend(c, reader.size) if mock else RealBackend(c, reader.native_size, reader.size))
        if mock:
            print('[MOCK] Scripted test detector/state; NOT real detection or accuracy data.', flush=True)
        output = Path(c['output_dir'])
        if mock:
            output /= 'mock'
        if c.get('suite_run', False):
            output /= c['experiment_kind']
            output /= c['suite_id']
        run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:10]
        run_dir = output / 'runs' / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        c['recording_dir'] = str(run_dir / 'clips')
        ledger = EventLedger(run_id, source, mode, mock)
        metadata = dict(run_id=run_id, source=str(source), pipeline_mode=mode,
                        resolution=f'{reader.size[0]}x{reader.size[1]}', variant=c['variant'],
                        repeat=c['repeat'], experiment_kind=c['experiment_kind'], mock=mock,
                        source_fps=reader.fps, run_status='running')
        environment = dict(config=c, zones=backend.zones, native_size=reader.native_size,
                           source_sha256=_file_hash(source), python=platform.python_version(),
                           platform=platform.platform(), processor=platform.processor(),
                           opencv=cv2.__version__, numpy=np.__version__,
                           timestamp_basis='monotonic' if reader.camera else c['timestamp_mode'],
                           repeat_boundary='reset_model_and_state_finalize_truncated_clips')
        (run_dir / 'effective_config.json').write_text(json.dumps(environment, ensure_ascii=False, indent=2), encoding='utf-8')
        previous_completed = None
        display_fps = 0.0
        boxes = []
        for packet in reader:
            work_start = time.perf_counter()
            if current_cycle != packet['cycle']:
                if current_cycle is not None:
                    if rec:
                        clips = close_recorder(rec)
                        ledger.attach_clips(clips)
                        all_clips.extend(clips)
                    ledger.finish('open_at_loop_boundary')
                    backend.reset()
                current_cycle = packet['cycle']
                if c['recording_enabled']:
                    rec = create_recorder(c, reader.fps, reader.native_size)
            warmup = packet['frame_index'] < c['warmup_frames']
            if not warmup and started_measurement is None:
                started_measurement = max(packet['read_started_at'], previous_completed or packet['read_started_at'])
            row = {key: metadata[key] for key in ('run_id', 'source', 'pipeline_mode', 'resolution', 'variant', 'repeat', 'experiment_kind', 'mock', 'source_fps')}
            row.update({key: packet[key] for key in ('frame_index', 'cycle', 'media_time_s', 'captured_at', 'scheduled_at', 'read_ms')})
            row.update(processing_started_at=work_start, queue_wait_ms=(work_start-packet['enqueued_at'])*1000,
                       dropped=False, warmup=warmup)
            frame, t = packet['frame'], packet['media_time_s']
            record_ms = 0.0
            if rec:
                begin = time.perf_counter()
                buffer_frame(rec, packet['original_frame'], t)
                record_ms += (time.perf_counter()-begin)*1000
            analyzed = packet['cycle_frame_index'] % c['frame_interval'] == 0
            row['analyzed'] = analyzed
            if analyzed:
                intrusions, boxes, timing = backend.analyze(frame, packet)
                row.update(timing)
            else:
                intrusions, boxes = None, []
            with measure(row, 'state'):
                ledger.observe(intrusions, t)
                states, transitions = backend.update(intrusions, packet)
                events = ledger.transitions(transitions, packet, current_cycle)
            if ledger.sampled_spans:
                row['observed_duration_s'] = max(last-first for first, last in ledger.sampled_spans.values())
            alert_rows = [ledger.rows[e['event_id']] for e in events if e['type'] == 'alert']
            if alert_rows:
                row['alert_delay_s'] = sum(e['alert_time']-e['start_time'] for e in alert_rows)/len(alert_rows)
                row['system_alert_delay_ms'] = sum(e['system_alert_delay_ms'] for e in alert_rows)/len(alert_rows)
                scheduled_delays = [e['scheduled_alert_delay_ms'] for e in alert_rows if e['scheduled_alert_delay_ms'] is not None]
                if scheduled_delays:
                    row['scheduled_alert_delay_ms'] = sum(scheduled_delays)/len(scheduled_delays)
            quit_requested = False
            if not c['no_display']:
                with measure(row, 'display'):
                    display = _draw(frame, mode, display_fps, backend.zones, boxes, states,
                                    bool(rec and (rec['active'] or any(e['type']=='alert' for e in events))), mock)
                    cv2.imshow('OpenCV safety monitor', display)
                    quit_requested = cv2.waitKey(1) & 0xff == ord('q')
            if rec:
                begin = time.perf_counter()
                clips = record_frame(rec, packet['original_frame'], t, events)
                record_ms += (time.perf_counter()-begin)*1000
                ledger.attach_clips(clips)
                all_clips.extend(clips)
            row['record_ms'] = record_ms if rec else None
            processed_frames += 1
            completed = time.perf_counter()
            row['total_ms'] = (completed-work_start)*1000 + row['queue_wait_ms'] + packet['read_ms']
            row['completed_at'] = completed
            if previous_completed is not None and completed > previous_completed:
                display_fps = 1/(completed-previous_completed)
            previous_completed = completed
            if c['measure_fps']:
                rows.append(row)
            ended_measurement = completed
            if quit_requested:
                status = 'interrupted'
                break
            if started_measurement is not None and c['duration_seconds'] and completed-started_measurement >= c['duration_seconds']:
                status = 'completed'
                break
        else:
            status = 'completed'
    except BaseException as exc:
        error = exc
        status = 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed'
    finally:
        try:
            reader.close()
        except BaseException as exc:
            error = error or exc
            status = 'failed'
        if rec:
            try:
                clips = close_recorder(rec)
                if ledger:
                    ledger.attach_clips(clips)
                all_clips.extend(clips)
            except BaseException as exc:
                error = error or exc
                status = 'failed'
        if not c['no_display']:
            cv2.destroyAllWindows()
        if ledger and run_dir:
            ledger.finish('open_at_eof' if status == 'completed' else status)
            event_rows = list(ledger.rows.values())
            write_table(run_dir / 'events.csv', event_rows, EVENT_FIELDS)
            write_table(output / 'events.csv', event_rows, EVENT_FIELDS, append=True)
            write_table(run_dir / 'clips.csv', all_clips, CLIP_FIELDS)
            metadata['run_status'] = status
            if c['measure_fps']:
                for row in rows:
                    row['measurement_start_at'] = started_measurement if started_measurement is not None else row['processing_started_at']
                    row['measurement_end_at'] = ended_measurement or time.perf_counter()
                save_run_metrics(output, run_dir, rows, metadata)
            (run_dir / 'status.json').write_text(json.dumps(dict(status=status, error=str(error) if error else None,
                                                                produced_frames=reader.produced, processed_frames=processed_frames,
                                                                pending_at_stop=reader.produced-processed_frames,
                                                                analyzed_queue_drops=reader.dropped), indent=2), encoding='utf-8')
    if error:
        raise error
    print(f'[pipeline] {mode}: {status}; results: {run_dir}', flush=True)
    return 0
