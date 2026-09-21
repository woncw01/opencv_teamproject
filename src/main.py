"""목적: CLI 설정, 폴더 준비, 기존 미리보기와 향후 감시 모드 진입.
담당 팀원: B. 입력 데이터: CLI 인수, config.json, 원본 영상.
출력 데이터: 종료 코드, 미리보기 화면, 설계 점검 JSON.
의존 관계: utils; 감시 실행 시 pipeline. 구현 TODO: 감시 모드 연결 검증.
"""
import argparse
import json
from pathlib import Path

import cv2

if __package__:
    from .utils import FPSMeter, open_source, load_config
else:
    from utils import FPSMeter, open_source, load_config


def process(frame):
    """[담당: B] 목적: 기존 그레이스케일 미리보기 보존.
    입력: frame: np.ndarray BGR uint8. 반환: np.ndarray BGR uint8.
    구현 순서: BGR→GRAY→BGR (기존 구현). TODO: 미리보기 수동 확인.
    예외/경계: 빈 영상은 cv2.error. 연결: preview 전용, 감지에 사용하지 않음.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def main():
    """[담당: B] 목적: CLI 진입 및 실행 상태를 정직하게 안내.
    입력: sys.argv 문자열 목록. 반환: int 종료 코드 (0 성공, 2 미구현/설정 오류).
    구현 순서: 인수 파싱 → 설정 검증 → 폴더 생성 → 점검/미리보기/감시 분기.
    예외/경계: 잘못된 설정은 argparse 오류; 영상 열기 실패는 기존 SystemExit.
    연결: utils.load_config/open_source, pipeline.run_pipeline.
    TODO: 감시 완성 후 통합 검증 및 미리보기 finally 정리 보강.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="0=웹캠, 또는 동영상 파일 경로")
    ap.add_argument("--config", default=str(Path(__file__).resolve().parent.parent / "config.json"))
    ap.add_argument("--mode", choices=("baseline", "threaded", "optimized"), default="baseline")
    ap.add_argument("--dry-run", action="store_true", help="설정 및 폴더 연결만 점검")
    ap.add_argument("--preview", action="store_true", help="기존 그레이스케일 미리보기")
    args = ap.parse_args()

    try:
        config = load_config(args.config)
        for key in ("min_area", "consecutive_frames", "clear_frames", "queue_max_size", "frame_interval"):
            if not isinstance(config[key], int) or isinstance(config[key], bool) or config[key] <= 0:
                raise ValueError(f"{key}는 양의 정수여야 합니다")
        if config["blur_kernel"] <= 0 or config["blur_kernel"] % 2 == 0:
            raise ValueError("blur_kernel은 양의 홀수여야 합니다")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        ap.error(str(exc))
    for folder in ("data/samples", "results"):
        Path(folder).mkdir(parents=True, exist_ok=True)
    source = args.source if args.source is not None else config["source"]
    if args.dry_run:
        print(json.dumps({"source": source, "mode": args.mode, "status": "scaffold_only",
                          "note": "설정 기본 검사 완료; 영상/구역/전체 스키마 검증 및 감시는 미구현"}, ensure_ascii=False, indent=2))
        return 0
    if not args.preview:
        if __package__:
            from .pipeline import run_pipeline
        else:
            from pipeline import run_pipeline
        try:
            return run_pipeline(source, args.mode, config)
        except NotImplementedError as exc:
            print(f"[미구현] {exc}. --dry-run 또는 --preview를 사용하세요.")
            return 2
    cap = open_source(source)
    fps = FPSMeter()

    while True:
        ok, frame = cap.read()
        if not ok:
            print("[INFO] 영상이 끝났거나 프레임을 읽지 못했습니다.")
            break

        out = process(frame)
        cv2.putText(out, f"FPS {fps.tick():.1f}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.imshow("result", out)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
