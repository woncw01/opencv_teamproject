from __future__ import annotations

from typing import Any

import cv2
import numpy as np


def preprocess_frame(
    frame: np.ndarray,
    config: dict[str, Any],
    roi: tuple[int, int, int, int] | None,
) -> tuple[np.ndarray, dict[str, float]]:
    """[담당: 팀원 A]
    목적: 공통 전처리 수행
    입력: frame(BGR uint8 원본 프레임), config(설정), roi(원본 x,y,w,h 또는 None)
    반환: (분석 BGR 영상, {offset_x, offset_y, scale_x, scale_y})
      - offset_*: ROI crop으로 인한 원본 기준 이동량
      - scale_*: crop 이후 분석 해상도로 축소한 배율 (분석좌표 * scale = crop좌표)
    구현 순서:
      1. 프레임 및 ROI 검증
      2. ROI crop 후 종횡비 유지하며 분석 해상도 이내로 축소
      3. 동일 blur_kernel로 블러
      4. 실제 축소 비율과 원본 오프셋 반환
    """
    if frame is None or frame.size == 0:
        raise ValueError("빈 프레임입니다")

    h, w = frame.shape[:2]

    if roi is not None:
        rx, ry, rw, rh = roi
        if rw <= 0 or rh <= 0 or rx < 0 or ry < 0 or rx + rw > w or ry + rh > h:
            raise ValueError(f"ROI가 프레임 범위를 벗어났습니다: {roi}, frame=({w}x{h})")
        cropped = frame[ry:ry + rh, rx:rx + rw]
        offset_x, offset_y = rx, ry
    else:
        cropped = frame
        offset_x, offset_y = 0, 0

    crop_h, crop_w = cropped.shape[:2]

    target_w, target_h = config.get("analysis_resolution", [640, 360])
    if target_w <= 0 or target_h <= 0:
        raise ValueError("analysis_resolution은 양수여야 합니다")

    # 종횡비를 유지하면서 분석 해상도 "이내"로 들어오도록 축소 (더 크게 키우지는 않음)
    scale = min(target_w / crop_w, target_h / crop_h, 1.0)
    new_w = max(1, int(round(crop_w * scale)))
    new_h = max(1, int(round(crop_h * scale)))
    resized = cv2.resize(cropped, (new_w, new_h), interpolation=cv2.INTER_AREA)

    blur_kernel = config.get("blur_kernel", 5)
    if not isinstance(blur_kernel, int) or blur_kernel <= 0 or blur_kernel % 2 != 1:
        raise ValueError("blur_kernel은 양의 홀수여야 합니다")
    blurred = cv2.GaussianBlur(resized, (blur_kernel, blur_kernel), 0)

    transform = {
        "offset_x": float(offset_x),
        "offset_y": float(offset_y),
        # crop_w/new_w == 실제 축소 비율의 역수. restore 시 analysis좌표 / scale = crop좌표.
        "scale_x": new_w / crop_w,
        "scale_y": new_h / crop_h,
    }
    return blurred, transform


def restore_boxes(
    boxes: list[tuple[int, int, int, int]],
    transform: dict[str, float],
) -> list[tuple[int, int, int, int]]:
    """[담당: 팀원 A]
    목적: 분석 좌표를 원본 좌표로 복원
    입력: boxes(분석 x,y,w,h 목록), transform(preprocess_frame이 반환한 변환 정보)
    반환: 원본 기준 x,y,w,h 목록
    구현 순서:
      1. x/scale_x + offset_x 등 역변환
      2. 정수 반올림 규칙 통일 (반올림 후 int 변환)
    """
    if not boxes:
        return []

    scale_x = transform["scale_x"]
    scale_y = transform["scale_y"]
    if scale_x <= 0 or scale_y <= 0:
        raise ValueError("scale은 양수여야 합니다")

    offset_x = transform["offset_x"]
    offset_y = transform["offset_y"]

    restored: list[tuple[int, int, int, int]] = []
    for x, y, w, h in boxes:
        ox = round(x / scale_x) + offset_x
        oy = round(y / scale_y) + offset_y
        ow = round(w / scale_x)
        oh = round(h / scale_y)
        restored.append((int(ox), int(oy), int(ow), int(oh)))

    return restored


