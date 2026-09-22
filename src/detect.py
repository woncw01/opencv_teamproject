from __future__ import annotations

from typing import Any

import cv2
import numpy as np


def create_background_subtractor(config: dict[str, Any]) -> Any:
    """[담당: 팀원 A]
    목적: 실행별 MOG2 인스턴스 생성
    입력: config(전체 설정 dict, mog2 하위 키 사용)
    반환: OpenCV BackgroundSubtractorMOG2
    """
    mog2_cfg = config.get("mog2", {})
    history = mog2_cfg.get("history", 500)
    var_threshold = mog2_cfg.get("var_threshold", 16.0)
    detect_shadows = mog2_cfg.get("detect_shadows", True)

    if not isinstance(history, int) or history <= 0:
        raise ValueError("mog2.history는 양의 정수여야 합니다")
    if not isinstance(var_threshold, (int, float)) or var_threshold <= 0:
        raise ValueError("mog2.var_threshold는 양수여야 합니다")
    if not isinstance(detect_shadows, bool):
        raise ValueError("mog2.detect_shadows는 bool이어야 합니다")

    return cv2.createBackgroundSubtractorMOG2(
        history=history,
        varThreshold=var_threshold,
        detectShadows=detect_shadows,
    )


def detect_motion(
    frame: np.ndarray,
    background_subtractor: Any,
    min_area: float,
) -> list[tuple[int, int, int, int]]:
    """[담당: 팀원 A]
    목적: 움직이는 객체 영역 검출
    입력: frame(분석 BGR uint8), background_subtractor(MOG2), min_area(분석 해상도 기준 최소 면적)
    반환: (x, y, w, h) 바운딩 박스 목록
    """
    fg_mask = background_subtractor.apply(frame)

    # 그림자(127)는 배경으로 취급하고 순수 전경(255)만 사용
    _, binary = cv2.threshold(fg_mask, 200, 255, cv2.THRESH_BINARY)

    # 노이즈 제거: opening(침식->팽창)으로 작은 점 노이즈 제거,
    # closing(팽창->침식)으로 객체 내부 구멍 메우기
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes: list[tuple[int, int, int, int]] = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area:
            continue
        x, y, w, h = cv2.boundingRect(cnt)
        boxes.append((x, y, w, h))

    return boxes


def check_intrusion(
    boxes: list[tuple[int, int, int, int]],
    zones: list[dict[str, Any]],
) -> dict[str, bool]:
    """[담당: 팀원 A]
    목적: 위험 구역별 침입 여부 판정
    입력: boxes((x,y,w,h) 목록), zones([{name, points}] 목록)
    반환: {구역 이름: 침입 여부(bool)} - 모든 구역이 키로 포함됨 (침입 없으면 False)

    판정 기준: 각 박스의 바닥 중심점(x + w/2, y + h)을
    cv2.pointPolygonTest로 각 구역 폴리곤과 비교.
    """
    result: dict[str, bool] = {zone["name"]: False for zone in zones}

    if not boxes or not zones:
        return result

    zone_polys = [
        (zone["name"], np.array(zone["points"], dtype=np.float32))
        for zone in zones
    ]

    for (x, y, w, h) in boxes:
        # 바닥 중심점을 사용 (사람/물체가 바닥에 닿는 지점 기준 판정이 더 정확)
        point = (float(x + w / 2), float(y + h))
        for name, poly in zone_polys:
            if result[name]:
                continue  # 이미 침입으로 확정된 구역은 재검사 불필요
            inside = cv2.pointPolygonTest(poly, point, False)
            if inside >= 0:  # 0: 경계선 위, 1: 내부 -> 둘 다 침입으로 간주
                result[name] = True

    return result