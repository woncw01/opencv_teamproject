"""원본 시간 버퍼 및 독립 사건 영상 저장 (담당 B).
입력: 원본 BGR 프레임, 영상 초, 외부 alert/cleared 전이. 출력: 클립 메타데이터.
의존: collections.deque, OpenCV. 감지/상태 판정 및 사건 CSV는 수행하지 않는다.
불규칙 시각은 직전 프레임 유지 방식으로 고정 FPS에 재표본화한다.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import math
from pathlib import Path
import re
from typing import Any
import uuid

import cv2
import numpy as np


def create_recorder(config: dict[str, Any], source_fps: float, frame_size: tuple[int, int]) -> dict[str, Any]:
    """Create a recording session; reject invalid FPS/size and excessive buffer budget.
    Input FPS is output CFR cadence, size is original (width,height). Each event has
    its own writer; callers must close the session in finally. No I/O until alert.
    """
    if not math.isfinite(source_fps) or source_fps <= 0:
        raise ValueError('Recording requires positive finite source/recording FPS')
    if len(frame_size) != 2 or any(x <= 0 for x in frame_size):
        raise ValueError('Invalid frame size')
    pre, post = float(config.get('pre_seconds', 3)), float(config.get('post_seconds', 5))
    if not all(math.isfinite(x) and x >= 0 for x in (pre, post)):
        raise ValueError('Recording durations must be finite and nonnegative')
    budget = int(config.get('recorder_max_mb', 1024) * 1024**2)
    if (math.ceil(pre * source_fps) + 1) * frame_size[0] * frame_size[1] * 3 > budget:
        raise ValueError('Pre-buffer exceeds recorder_max_mb; increase budget explicitly')
    return dict(buffer=deque(), active={}, seen=set(), clips=[], fps=float(source_fps),
                size=tuple(frame_size), pre=pre, post=post, last_time=None,
                first_time=None, budget=budget, buffer_bytes=0,
                output=Path(config.get('recording_dir', 'results/clips')),
                codec=config.get('recording_codec', 'mp4v'), closed=False)


def buffer_frame(session: dict, frame: np.ndarray, media_time_s: float) -> None:
    """Copy an original frame into the time-window deque before analysis.
    Repeated identical timestamp is idempotent for record_frame's second phase;
    timestamps otherwise must increase, frames must match the original size.
    """
    if session['closed']:
        raise RuntimeError('Recorder is closed')
    t = float(media_time_s)
    if not math.isfinite(t) or t < 0:
        raise ValueError('Invalid media timestamp')
    if frame.dtype != np.uint8 or frame.shape != (session['size'][1], session['size'][0], 3):
        raise ValueError('Recorder requires original uint8 BGR size')
    last = session['last_time']
    if last is not None and t < last:
        raise ValueError('Recording timestamps must increase')
    if last == t:
        return
    if session['first_time'] is None:
        session['first_time'] = t
    session['last_time'] = t
    buf = session['buffer']
    # First remove expired frames so peak use does not include an extra full frame.
    while buf and buf[0][0] < t - session['pre'] - 1e-9:
        _, old = buf.popleft()
        session['buffer_bytes'] -= old.nbytes
    if session['buffer_bytes'] + frame.nbytes > session['budget']:
        raise MemoryError('Actual pre-buffer exceeds recorder_max_mb')
    copy = frame.copy()
    buf.append((t, copy))
    session['buffer_bytes'] += copy.nbytes


def _write_sample(session: dict, clip: dict, frame: np.ndarray, timestamp: float) -> None:
    """Zero-order-hold resampling: fill missing CFR ticks using previous frame.
    Exact tick uses current frame. All source frames are observed; multiple inputs
    in one output tick cannot all be represented by a CFR file (counted separately).
    """
    if clip['last_input'] == timestamp:
        return
    limit = min(timestamp, clip['deadline']) if not clip['alert_active'] else timestamp
    step = 1 / session['fps']
    if clip['previous'] is None:
        clip['previous'] = frame
    wrote_current = False
    while clip['next_tick'] <= limit + 1e-8:
        exact = abs(clip['next_tick'] - timestamp) <= 1e-8
        clip['writer'].write(frame if exact else clip['previous'])
        clip['frames_written'] += 1
        if not exact:
            clip['held_ticks'] += 1
        else:
            wrote_current = True
        clip['last_written_s'] = clip['next_tick']
        clip['next_tick'] += step
    if not wrote_current:
        clip['resampled_inputs'] += 1
    clip['previous'] = frame.copy()
    clip['last_input'] = timestamp


def _finish(session: dict, event_id: str, truncated: bool) -> dict:
    """Release exactly one writer and return serializable metadata; caller owns CSV."""
    clip = session['active'].pop(event_id)
    clip['writer'].release()
    info = {k: clip[k] for k in ('path', 'event_ids', 'zone_name', 'alert_time_s',
                                'occurred_at', 'start_s', 'frames_written',
                                'held_ticks', 'resampled_inputs')}
    info.update(end_s=clip['last_written_s'], truncated=bool(truncated or clip['pre_truncated']),
                pre_truncated=clip['pre_truncated'], post_truncated=bool(truncated),
                recording_fps=session['fps'], resampling='previous_frame_hold')
    session['clips'].append(info)
    return info


def record_frame(session: dict[str, Any], frame: np.ndarray, media_time_s: float,
                 events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Buffer frame, open independent event writers, consume transitions, then write.
    Duplicate alert/clear transitions are idempotent. Alert stays open until clear;
    close time is max(alert+post, clear+post). Incomplete EOF clips are truncated.
    Existing positional interface preserved; input events use A's original fields.
    """
    buffer_frame(session, frame, media_time_s)
    t = float(media_time_s)
    finished = []
    for event in events:
        key = str(event['event_id'])
        if event['type'] == 'alert' and key not in session['seen']:
            alert = float(event['media_time_s'])
            if abs(alert - t) > 1e-6:
                raise ValueError('Alert must be delivered with its original frame')
            session['output'].mkdir(parents=True, exist_ok=True)
            safe_id = re.sub(r'[^\w.-]', '_', key)
            stamp = datetime.now(timezone.utc)
            path = session['output'] / f'{stamp:%Y%m%dT%H%M%S}_{safe_id}_{uuid.uuid4().hex[:8]}.mp4'
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*session['codec']), session['fps'], session['size'])
            if not writer.isOpened():
                writer.release()
                raise OSError(f'Cannot open video writer: {path}')
            first = session['buffer'][0][0]
            clip = dict(writer=writer, path=str(path), event_ids=[key], zone_name=event['zone_name'],
                        alert_time_s=alert, occurred_at=stamp.isoformat(), start_s=first,
                        pre_truncated=first > alert - session['pre'] + 1e-8,
                        alert_active=True, deadline=alert + session['post'], next_tick=first,
                        previous=None, last_input=None, last_written_s=None,
                        frames_written=0, held_ticks=0, resampled_inputs=0)
            session['active'][key] = clip
            session['seen'].add(key)
            for old_t, old_frame in session['buffer']:
                _write_sample(session, clip, old_frame, old_t)
        elif event['type'] == 'cleared' and key in session['active']:
            clip = session['active'][key]
            if clip['alert_active']:
                clip['alert_active'] = False
                clip['deadline'] = max(clip['deadline'], float(event['media_time_s']) + session['post'])
    for key, clip in list(session['active'].items()):
        _write_sample(session, clip, frame, t)
        if not clip['alert_active'] and t >= clip['deadline'] - 1e-8:
            finished.append(_finish(session, key, False))
    return finished


def close_recorder(session: dict[str, Any]) -> list[dict[str, Any]]:
    """Finalize all active clips at EOF/error; repeated close is safe, returns []."""
    if session['closed']:
        return []
    result = []
    first_error = None
    try:
        for key in list(session['active']):
            try:
                result.append(_finish(session, key, True))
            except Exception as exc:
                first_error = first_error or exc
    finally:
        session['buffer'].clear()
        session['buffer_bytes'] = 0
        session['closed'] = True
    if first_error:
        raise first_error
    return result
