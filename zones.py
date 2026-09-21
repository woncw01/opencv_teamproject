"""목적: 마우스 다각형 획득 구역 편집 및 JSON 입출력
담당 팀원: A
입력 데이터: 첫봇 표류일 또는 JSON 경로
출력 데이터: 이름과 폭소점 목록
의존 관계: 구현 시 OpenCV, json; detect에서 구역 사용
구현 TODO: 좌클릭 추가, 우클릭 축소, Enter 확정, Esc 취소 창중
상태: 인터페이스 설계만 완료. 함수 본문은 미구현.
"""
from __future__ import annotations

from typing import Any
import json
import numpy as np
import cv2


def edit_zones(frame: np.ndarray) -> list[dict[str, Any]]:
    """[담당: 팀원 A]
    목적: 첫봇 영상에서 다각형 구역 편정
    매개변수 / 입력 타입: frame: 첫봇 BGR 영상
    반환 / 출력 타입: [{name: str, points: [[x,y], ...]}]
    구현 순서 TODO:
        1. 윈도 생성 후 마우스 콜백 등록
        2. 좌클릭 추가·우클릭 마지막 점 취소
        3. 3점 이상 다각형만 결과 반환
    예외 및 경계 조건: Esc는 []; 자기 교차·면적 0 거부; 확정 축소 시 좌표 소수점 반영
    모듈 연결: save_zones와 연결
    """
    zones: list[dict[str, Any]] = []
    current_points: list[list[int]] = []
    zone_index = 1

    display_frame = frame.copy()
    window_name = "구역 편집 (좌클릭:점추가, 우클릭:취소, Enter:확정, Esc:종료)"

    def redraw():
        nonlocal display_frame
        display_frame = frame.copy()
        for z in zones:
            pts = np.array(z["points"], dtype=np.int32)
            cv2.polylines(display_frame, [pts], True, (0, 255, 0), 2)
            cv2.putText(display_frame, z["name"], tuple(pts[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        if len(current_points) > 0:
            pts = np.array(current_points, dtype=np.int32)
            for p in current_points:
                cv2.circle(display_frame, tuple(p), 3, (0, 0, 255), -1)
            if len(current_points) > 1:
                cv2.polylines(display_frame, [pts], False, (0, 0, 255), 1)

    def mouse_callback(event, x, y, flags, param):
        nonlocal current_points
        if event == cv2.EVENT_LBUTTONDOWN:
            # 2. 좌클릭 추가
            current_points.append([x, y])
            redraw()
        elif event == cv2.EVENT_RBUTTONDOWN:
            # 2. 우클릭 마지막 점 취소
            if current_points:
                current_points.pop()
                redraw()

    cv2.namedWindow(window_name)
    cv2.setMouseCallback(window_name, mouse_callback)
    redraw()

    while True:
        cv2.imshow(window_name, display_frame)
        key = cv2.waitKey(30) & 0xFF

        if key == 27:  # Esc: 종료
            zones = []
            break
        elif key == 13:  # Enter: 확정
            # 3. 3점 이상 다각형만 결과 반영
            if len(current_points) >= 3:
                zones.append({
                    "name": f"zone{zone_index}",
                    "points": [p[:] for p in current_points],
                })
                zone_index += 1
                current_points = []
                redraw()

    cv2.destroyWindow(window_name)
    return zones


def save_zones(path: str, zones: list[dict[str, Any]], frame_size: tuple[int, int]) -> None:
    """[담당: 팀원 A]
    목적: 구역 JSON 저장
    매개변수 / 입력 타입: path: 경로; zones: 구역 목록; frame_size: 튜플 (width,height)
    반환 / 출력 타입: None; JSON 파일
    구현 순서 TODO:
        1. 좌표 배치화 후 이름 붙임
        2. schema_version=1, frame_size, zones 저장
    예외 및 경계 조건: 쓰기 실패 OSError; 기존 파일 존재하면 조용조각 최우량 저장 시안 수용
    모듈 연결: edit_zones 결과 저장
    """
    data = {
        "schema_version": 1,
        "frame_size": list(frame_size),
        "zones": zones,
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        raise OSError(f"구역 저장 실패: {path} ({e})")


def load_zones(path: str, frame_size: tuple[int, int]) -> list[dict[str, Any]]:
    """[담당: 팀원 A]
    목적: 저장 구역 로딩 및 확장성 점검
    매개변수 / 입력 타입: path: JSON 경로; frame_size: 현재 영상 크기
    반환 / 출력 타입: 구역 목록
    구현 순서 TODO:
        1. JSON 읽기 및 스키마 검사
        2. 저장 당시와 현재 크기 비교
        3. 구역 반환
    예외 및 경계 조건: 파일 안전 FileNotFoundError; 형식이 불일치 ValueError, 각도 스케일링 없음
    모듈 연결: pipeline 초기화에서 사용
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"구역 파일을 찾을 수 없습니다: {path}")

    # 1. 스키마 검사
    if data.get("schema_version") != 1:
        raise ValueError(f"지원하지 않는 schema_version입니다: {data.get('schema_version')}")

    zones = data.get("zones")
    if zones is None:
        raise ValueError("zones 필드가 없습니다.")

    # 2. 저장 당시와 현재 크기 비교 (불일치 시 경고성 예외, 크기 조정은 하지 않음)
    saved_size = data.get("frame_size")
    if saved_size is not None and tuple(saved_size) != tuple(frame_size):
        raise ValueError(
            f"저장 당시 영상 크기({saved_size})와 현재 영상 크기({list(frame_size)})가 다릅니다. "
            "구역 좌표가 맞지 않을 수 있습니다."
        )

    # 3. 구역 반환
    return zones


if __name__ == "__main__":
    print("zones.py 모듈이 정상적으로 로드됩니다.")