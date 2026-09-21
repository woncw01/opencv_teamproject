"""목적: 공통 영상 전처리와 원본 좌표 복원
담당 팀원: A
입력 데이터: BGR uint8 원본 프레임, 설정, ROI
출력 데이터: 분석 영상, 좌표 변환 정보
의존 관계: NumPy, 구현 시 OpenCV; pipeline에서 호출
구현 TODO: ROI 자르기, 축소, 블러, 좌표 복원
상태: 인터페이스 설계만 완료. 함수 본문은 미구현.
"""
from __future__ import annotations

from typing import Any
import numpy as np
import cv2


def preprocess_frame(frame: np.ndarray, config: dict[str, Any], roi: tuple[int, int, int, int] | None = None) -> tuple[np.ndarray, dict[str, float]]:
    """[담당: 팀원 A]
    목적: 공통 전처리 수행
    매개변수 / 입력 타입: frame: HxWx3 uint8; config: 설정; roi: 튜플 x,y,w,h 또는 None
    반환 / 출력 타입: (분석 BGR 영상, {offset_x, offset_y, scale_x, scale_y}); scale은 분석/원본 비율
    구현 순서 TODO:
        1. 프레임 및 ROI 검증
        2. ROI crop 후 종횡비를 유지하여 분석 해상도로 축소
        3. 동일 blur_kernel로 블러
        4. 실제 축소 비율과 원본 오프셋 반환
    예외 및 경계 조건: 빈 프레임·범위 밖 ROI는 ValueError; 커널은 양의 홀수
    모듈 연결: 모든 버전 pipeline → preprocess → detect
    """
    if frame is None or frame.size == 0:
        raise ValueError("빈 프레임입니다.")

    h, w = frame.shape[:2]

    # 1. 프레임 및 ROI 검증, crop
    if roi is not None:
        x, y, rw, rh = roi
        if x < 0 or y < 0 or rw <= 0 or rh <= 0 or x + rw > w or y + rh > h:
            raise ValueError(f"ROI가 프레임 범위를 벗어났습니다: {roi}, frame={w}x{h}")
        cropped = frame[y:y + rh, x:x + rw]
        offset_x, offset_y = x, y
    else:
        cropped = frame
        offset_x, offset_y = 0, 0

    ch, cw = cropped.shape[:2]

    # 2. 종횡비를 유지하여 분석 해상도로 축소
    target_w = int(config.get("target_width", cw))
    scale = target_w / cw if cw > 0 else 1.0
    target_h = max(1, int(round(ch * scale)))
    resized = cv2.resize(cropped, (target_w, target_h), interpolation=cv2.INTER_AREA)

    # 3. 동일 blur_kernel로 블러 (양의 홀수 보정)
    blur_kernel = int(config.get("blur_kernel", 5))
    if blur_kernel < 1:
        raise ValueError("blur_kernel은 1 이상의 홀수여야 합니다.")
    if blur_kernel % 2 == 0:
        blur_kernel += 1
    blurred = cv2.GaussianBlur(resized, (blur_kernel, blur_kernel), 0)

    # 4. 실제 축소 비율과 원본 오프셋 반환
    transform = {
        "offset_x": float(offset_x),
        "offset_y": float(offset_y),
        "scale_x": float(scale),
        "scale_y": float(scale),
    }
    return blurred, transform


def restore_boxes(boxes: list[tuple[int, int, int, int]], transform: dict[str, float]) -> list[tuple[int, int, int, int]]:
    """[담당: 팀원 A]
    목적: 분석 좌표를 원본 좌표로 복원
    매개변수 / 입력 타입: boxes: 분석 x,y,w,h들; transform: 전처리 변환 정보
    반환 / 출력 타입: 원본 x,y,w,h 목록
    구현 순서 TODO:
        1. x/scale_x+offset_x 등 역변환
        2. 정수 반올림 규칙 통일
    예외 및 경계 조건: 빈 박스는 []; scale은 양수
    모듈 연결: detect의 결과를 pipeline이 복원 후 침입 판정
    """
    if not boxes:
        return []

    scale_x = transform.get("scale_x", 1.0)
    scale_y = transform.get("scale_y", 1.0)
    offset_x = transform.get("offset_x", 0.0)
    offset_y = transform.get("offset_y", 0.0)

    if scale_x <= 0 or scale_y <= 0:
        raise ValueError("scale 값은 양수여야 합니다.")

    restored = []
    for (x, y, w, h) in boxes:
        # 1. x/scale_x+offset_x 등 역변환
        orig_x = x / scale_x + offset_x
        orig_y = y / scale_y + offset_y
        orig_w = w / scale_x
        orig_h = h / scale_y
        # 2. 정수 반올림 규칙 통일 (반올림 후 int)
        restored.append((int(round(orig_x)), int(round(orig_y)), int(round(orig_w)), int(round(orig_h))))

    return restored


if __name__ == "__main__":
    print("preprocess.py 모듈이 정상적으로 로드됩니다.")