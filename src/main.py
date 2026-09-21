"""B: CLI, configuration, preserved grayscale preview and pipeline entry point.
Input: command-line options/JSON/video. Output: exit status and real/mock artifacts.
Dependencies: unchanged utils and B pipeline. A's unfinished functions fail visibly.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import cv2

if not __package__:
    # Preserve `python src/main.py` without modifying shared utils or A imports.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.utils import FPSMeter, load_config
from src.pipeline import run_pipeline, validate_config


def process(frame):
    """Preserved preview: input BGR uint8 -> grayscale BGR, invalid frame raises cv2.error."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def preview(source: str, no_display: bool = False) -> int:
    """Play original grayscale preview; headless mode consumes frames without GUI.
    Use platform-default capture backend in B code, leaving utils unchanged.
    """
    cap = cv2.VideoCapture(int(source) if str(source).isdigit() else source)
    try:
        if not cap.isOpened():
            raise OSError(f'Cannot open input: {source}')
        fps = FPSMeter()
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            out = process(frame)
            cv2.putText(out, f'FPS {fps.tick():.1f}', (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, .8, (0, 255, 0), 2)
            if not no_display:
                cv2.imshow('result', out)
                if cv2.waitKey(1) & 0xff == ord('q'):
                    break
    finally:
        cap.release()
        if not no_display:
            cv2.destroyAllWindows()
    return 0


def main(argv=None) -> int:
    """Parse CLI, validate config and dispatch; errors return 2, Ctrl-C returns 130."""
    ap = argparse.ArgumentParser(description='OpenCV safety monitor: B/C pipeline with explicit A/mock backend')
    ap.add_argument('--source', help='camera number or video file')
    ap.add_argument('--config', default=str(Path(__file__).resolve().parent.parent / 'config.json'))
    ap.add_argument('--mode', choices=('baseline', 'threaded', 'optimized'), default='baseline')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--preview', action='store_true')
    ap.add_argument('--no-display', action='store_true', default=None)
    ap.add_argument('--mock-detection', action='store_true', default=None)
    ap.add_argument('--output-dir')
    ap.add_argument('--duration', type=float, help='measured wall-time limit in seconds; 0=EOF')
    ap.add_argument('--loop-video', action='store_true', default=None)
    ap.add_argument('--experiment-kind', choices=('throughput', 'realtime'))
    ap.add_argument('--queue-policy', choices=('block', 'drop_oldest'))
    args = ap.parse_args(argv)
    try:
        config = load_config(args.config)
        for name in ('no_display', 'mock_detection', 'output_dir', 'loop_video', 'experiment_kind', 'queue_policy'):
            value = getattr(args, name)
            if value is not None:
                config[name] = value
        if args.duration is not None:
            config['duration_seconds'] = args.duration
        config = validate_config(config)
        source = args.source if args.source is not None else config['source']
        for folder in ('data/samples', config['output_dir']):
            Path(folder).mkdir(parents=True, exist_ok=True)
        if args.dry_run:
            print(json.dumps(dict(source=source, mode=args.mode, config_valid=True,
                                  mock=config['mock_detection'], note='Input/A implementation not exercised'), ensure_ascii=False))
            return 0
        if args.preview:
            return preview(source, config['no_display'])
        return run_pipeline(source, args.mode, config)
    except NotImplementedError as exc:
        print(f'[A 미구현] {exc}. B/C 검증에는 명시적으로 --mock-detection을 사용하세요.', file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, cv2.error) as exc:
        print(f'[ERROR] {exc}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
