"""B integration tests: temporary synthetic videos and explicit mock only."""
import csv
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import cv2
import numpy as np
import pytest
from src.pipeline import run_pipeline, validate_config, FrameSource, EventLedger


@pytest.fixture
def video(tmp_path):
    path = tmp_path/'TEST_ONLY.avi'
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 10, (64,48))
    assert writer.isOpened()
    for i in range(40):
        writer.write(np.full((48,64,3), i*5, dtype=np.uint8))
    writer.release()
    return str(path)


@pytest.fixture
def config(tmp_path):
    return validate_config(dict(output_dir=str(tmp_path/'results'), no_display=True,
                                mock_detection=True, warmup_frames=0,
                                pre_seconds=.5, post_seconds=.5))


def read_rows(path):
    with open(path, newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def test_baseline_mock(video, config):
    assert run_pipeline(video, 'baseline', config) == 0
    root = Path(config['output_dir'])/'mock'
    rows = read_rows(root/'events.csv')
    assert len(rows) == 1
    event = rows[0]
    assert float(event['start_time']) == 1
    assert float(event['alert_time']) == 1.5
    assert float(event['end_time']) == 2.5
    assert float(event['duration_seconds']) == 1.5
    assert event['mock'] == 'True'
    assert Path(event['video_path']).is_file()
    assert not (root.parent/'events.csv').exists()
    raw = read_rows(root/'benchmark_raw.csv')
    assert len(raw) == 40
    assert all(float(r['read_ms']) >= 0 and float(r['state_ms']) >= 0 for r in raw)
    assert all(float(r['total_ms']) >= 0 for r in raw)


@pytest.mark.parametrize('mode', ['baseline', 'threaded', 'optimized'])
def test_modes_cli(video, config, tmp_path, mode):
    path = tmp_path/'config.json'
    path.write_text(json.dumps(config))
    r = subprocess.run([sys.executable, '-m', 'src.main', '--config', str(path),
                        '--source', video, '--mode', mode, '--no-display', '--mock-detection'],
                       capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    assert '[MOCK]' in r.stdout


def test_real_a_error_not_hidden(video, config):
    config.update(mock_detection=False, zones_path='missing.json')
    with pytest.raises(NotImplementedError):
        run_pipeline(video, 'baseline', config)
    assert not (Path(config['output_dir'])/'events.csv').exists()


def test_optimized_skip_preserves_recording(video, config):
    config.update(frame_interval=2, post_seconds=.5)
    run_pipeline(video, 'optimized', config)
    root = Path(config['output_dir'])/'mock'
    raw = read_rows(root/'benchmark_raw.csv')
    assert len(raw) == 40 and sum(r['analyzed']=='True' for r in raw)==20
    clips = read_rows(next(root.glob('runs/*/clips.csv')))
    cap = cv2.VideoCapture(clips[0]['path'])
    # 1.1s pre-buffer start through 3.1s end includes every original 0.1s tick.
    assert cap.get(cv2.CAP_PROP_FRAME_COUNT) == 21
    cap.release()


class FakeCapture:
    """Finite/erroring capture fixture; no external video or device access."""
    def __init__(self, source, fail=False):
        self.released = False
        self.count = 0
        self.fail = fail
    def isOpened(self):
        return True
    def get(self, prop):
        return {cv2.CAP_PROP_FPS:10, cv2.CAP_PROP_FRAME_WIDTH:64, cv2.CAP_PROP_FRAME_HEIGHT:48}.get(prop, 0)
    def read(self):
        self.count += 1
        if self.fail and self.count == 2:
            raise RuntimeError('worker failed')
        if self.count > 10:
            return False, None
        return True, np.zeros((48,64,3), dtype=np.uint8)
    def release(self):
        self.released = True


def test_full_queue_block_and_shutdown(config):
    config['queue_max_size'] = 1
    reader = FrameSource('fake', config, True, capture_factory=FakeCapture)
    iter(reader)
    deadline = time.monotonic()+2
    while reader.queue.qsize()!=1 and time.monotonic()<deadline:
        time.sleep(.005)
    time.sleep(.1)
    assert reader.queue.qsize() == 1
    assert reader.produced <= 2
    assert reader.dropped == 0
    reader.close()
    assert not reader.thread.is_alive()
    assert reader.cap.released


def test_worker_error_delivered(config):
    reader = FrameSource('fake', config, True, capture_factory=lambda s: FakeCapture(s, True))
    try:
        it = iter(reader)
        assert next(it)['frame_index'] == 0
        with pytest.raises(RuntimeError, match='worker failed'):
            next(it)
    finally:
        reader.close()
    assert reader.cap.released and not reader.thread.is_alive()


def test_drop_policy_rejected(config):
    config['queue_policy'] = 'drop_oldest'
    with pytest.raises(ValueError, match='lossless'):
        validate_config(config)


def test_ledger_concurrent_dedup():
    ledger = EventLedger('run', 'v', 'baseline', True)
    ledger.observe({'a': True, 'b': True}, 1)
    packet = dict(captured_at=time.perf_counter(), media_time_s=2)
    events = [dict(type='alert', event_id=z, zone_name=z, media_time_s=2) for z in ('a','b')]
    assert len(ledger.transitions(events+events, packet, 0)) == 2
    assert len(ledger.rows) == 2
    ledger.observe({'a':False,'b':False}, 3)
    cleared = [{**e, 'type':'cleared', 'media_time_s':4} for e in events]
    ledger.transitions(cleared, packet, 0)
    assert all(e['duration_seconds']==2 for e in ledger.rows.values())


def test_input_resize_keeps_native_recording(video, config):
    config['input_resolution'] = [32,24]
    run_pipeline(video, 'optimized', config)
    root = Path(config['output_dir'])/'mock'
    ev = read_rows(root/'events.csv')[0]
    cap = cv2.VideoCapture(ev['video_path'])
    assert cap.get(cv2.CAP_PROP_FRAME_WIDTH) == 64
    assert cap.get(cv2.CAP_PROP_FRAME_HEIGHT) == 48
    cap.release()
    assert read_rows(root/'benchmark_summary.csv')[0]['resolution'] == '32x24'


def test_replay_boundary_resets_and_monotonic(video, config):
    config.update(loop_video=True, duration_seconds=.15, recording_enabled=False)
    run_pipeline(video, 'threaded', config)
    root = Path(config['output_dir'])/'mock'
    raw = read_rows(root/'benchmark_raw.csv')
    assert max(int(r['cycle']) for r in raw) > 0
    times = [float(r['media_time_s']) for r in raw]
    assert all(b>a for a,b in zip(times,times[1:]))
    events = read_rows(root/'events.csv')
    assert len(events) == len({e['event_id'] for e in events})
    assert not any(t.name=='opencv-input' for t in threading.enumerate())


def test_common_a_adapter_roi_coordinates(monkeypatch):
    from src import pipeline
    called = {}
    def prep(frame, config, roi):
        called['roi'] = roi
        return frame[:10,:10], dict(scale_x=.5, scale_y=.5, offset_x=0, offset_y=0)
    def motion(frame, background, min_area):
        called['min_area'] = min_area
        return [(1,2,3,4)]
    def restore(boxes, transform):
        called['boxes'] = boxes
        return [(2,4,6,8)]
    def intrusion(boxes, zones):
        assert boxes == [(2,4,6,8)]
        return {'z':True}
    monkeypatch.setattr(pipeline.preprocess, 'preprocess_frame', prep)
    monkeypatch.setattr(pipeline.detect, 'detect_motion', motion)
    monkeypatch.setattr(pipeline.preprocess, 'restore_boxes', restore)
    monkeypatch.setattr(pipeline.detect, 'check_intrusion', intrusion)
    c = validate_config(dict(roi_enabled=True, roi_margin=5, min_area=200))
    zones = [dict(name='z', points=[[10,10],[20,10],[20,20]])]
    assert pipeline.analyze_frame(np.zeros((48,64,3),dtype=np.uint8), object(), zones, c)=={'z':True}
    assert called['roi'] == (5,5,21,21)
    assert called['min_area'] == 50


def test_skips_do_not_extend_observed_positive_span():
    ledger = EventLedger('r','v','optimized',True)
    ledger.observe({'z':True}, 1)
    ledger.observe(None, 2)
    assert ledger.sampled_spans['z'] == (1,1)
    assert 'z' not in ledger.starts
    ledger.observe({'z':True}, 3)
    assert ledger.sampled_spans['z'] == (1,3)


def test_failure_finalizes_open_writer(video, config, monkeypatch):
    from src import pipeline
    sessions=[]
    original_create=pipeline.create_recorder
    def create(*args):
        s=original_create(*args)
        sessions.append(s)
        return s
    class FailingMock(pipeline.MockBackend):
        def analyze(self, frame, packet):
            if packet['frame_index']==2:
                raise RuntimeError('analysis test failure')
            return super().analyze(frame, packet)
    config['mock_events']=[dict(zone_name='z',start=0,alert=0,end=100)]
    backend=FailingMock(config,(64,48))
    monkeypatch.setattr(pipeline,'create_recorder',create)
    with pytest.raises(RuntimeError,match='analysis test failure'):
        run_pipeline(video,'threaded',config,backend=backend)
    assert sessions[0]['closed'] and not sessions[0]['active']
    assert not any(t.name=='opencv-input' for t in threading.enumerate())
    root=Path(config['output_dir'])/'mock'
    ev=read_rows(root/'events.csv')[0]
    assert ev['status']=='failed' and ev['end_time']==''
    assert Path(ev['video_path']).is_file()
    assert json.loads(next(root.glob('runs/*/status.json')).read_text())['status']=='failed'


def test_realtime_schedule(video,config):
    config.update(experiment_kind='realtime',duration_seconds=.15,recording_enabled=False)
    run_pipeline(video,'baseline',config)
    raw=read_rows(Path(config['output_dir'])/'mock'/'benchmark_raw.csv')
    assert len(raw)>=2
    planned=[float(r['scheduled_at']) for r in raw]
    assert planned[1]-planned[0]==pytest.approx(.1)
    assert all(float(r['captured_at'])>=float(r['scheduled_at']) for r in raw)


def test_headless_preview(video):
    from src.main import main
    assert main(['--source',video,'--preview','--no-display'])==0


def test_pts_failure_releases_capture(config):
    config['timestamp_mode']='pts'
    reader=FrameSource('fake',config,True,capture_factory=FakeCapture)
    try:
        it=iter(reader)
        next(it)
        with pytest.raises(ValueError,match='timestamps'):
            next(it)
    finally:
        reader.close()
    assert reader.cap.released
