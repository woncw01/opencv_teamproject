"""B recorder tests with tiny synthetic frames, not real experimental video."""
import cv2
import numpy as np
import pytest
from src.recorder import create_recorder, buffer_frame, record_frame, close_recorder


def session(tmp_path, **extra):
    return create_recorder({'recording_dir': str(tmp_path), **extra}, 10, (32, 24))


def frame():
    return np.full((24, 32, 3), 80, dtype=np.uint8)


def event(kind, t, key='one', zone='z'):
    return dict(type=kind, event_id=key, zone_name=zone, media_time_s=t)


def test_three_second_buffer(tmp_path):
    s = session(tmp_path)
    f = frame()
    for n in range(101):
        buffer_frame(s, f, n/10)
    assert s['buffer'][0][0] == 7
    assert s['buffer'][-1][0] == 10
    assert len(s['buffer']) == 31
    f[:] = 0
    assert s['buffer'][0][1].mean() == 80
    close_recorder(s)


def test_event_file_and_long_extension(tmp_path):
    s = session(tmp_path)
    for n in range(181):
        t = n/10
        ev = [event('alert', t)] if n == 40 else [event('cleared', t)] if n == 120 else []
        record_frame(s, frame(), t, ev)
        if n == 100:
            assert 'one' in s['active']  # alert+5 elapsed but still active
    assert not s['active']
    clip = s['clips'][0]
    assert clip['start_s'] == 1
    assert clip['end_s'] == pytest.approx(17)
    assert not clip['truncated']
    cap = cv2.VideoCapture(clip['path'])
    assert cap.isOpened()
    assert cap.get(cv2.CAP_PROP_FRAME_COUNT) == 161
    assert cap.get(cv2.CAP_PROP_FRAME_WIDTH) == 32
    cap.release()
    close_recorder(s)


def test_independent_duplicate_events_and_close(tmp_path):
    s = session(tmp_path)
    ev = [event('alert', 0), event('alert', 0), event('alert', 0, 'two', 'z2')]
    record_frame(s, frame(), 0, ev)
    assert len(s['active']) == 2
    writers = [c['writer'] for c in s['active'].values()]
    clips = close_recorder(s)
    assert len(clips) == 2 and len({c['path'] for c in clips}) == 2
    assert all(not w.isOpened() for w in writers)
    assert close_recorder(s) == []
    assert all(c['truncated'] for c in clips)


def test_irregular_hold_and_invalid_time(tmp_path):
    s = session(tmp_path)
    record_frame(s, frame(), 0, [event('alert', 0)])
    record_frame(s, frame(), .5, [])
    assert s['active']['one']['frames_written'] == 6
    assert s['active']['one']['held_ticks'] == 4
    with pytest.raises(ValueError):
        record_frame(s, frame(), .2, [])
    close_recorder(s)


def test_writer_open_failure_releases(tmp_path, monkeypatch):
    from src import recorder
    class BadWriter:
        def __init__(self):
            self.released=False
        def isOpened(self):
            return False
        def release(self):
            self.released=True
    writer=BadWriter()
    monkeypatch.setattr(recorder.cv2,'VideoWriter',lambda *args:writer)
    s=session(tmp_path)
    with pytest.raises(OSError,match='writer'):
        record_frame(s,frame(),0,[event('alert',0)])
    assert writer.released
    close_recorder(s)


def test_prebuffer_memory_limit(tmp_path):
    with pytest.raises(ValueError,match='recorder_max_mb'):
        session(tmp_path,recorder_max_mb=.0001)


def test_all_writers_release_even_if_one_release_fails(tmp_path):
    s=session(tmp_path)
    class ReleaseWriter:
        def __init__(self, fail):
            self.fail=fail
            self.released=False
        def release(self):
            self.released=True
            if self.fail:
                raise RuntimeError('release test failure')
    writers=[ReleaseWriter(True),ReleaseWriter(False)]
    common=dict(path='TEST',event_ids=[],zone_name='z',alert_time_s=0,occurred_at='',start_s=0,
                frames_written=1,held_ticks=0,resampled_inputs=0,last_written_s=0,pre_truncated=False)
    s['active']={str(i):dict(common,writer=w) for i,w in enumerate(writers)}
    with pytest.raises(RuntimeError,match='release test failure'):
        close_recorder(s)
    assert all(w.released for w in writers)
    assert s['closed'] and not s['active']
