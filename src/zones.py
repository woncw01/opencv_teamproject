from __future__ import annotations

from typing import Any

import cv2
import numpy as np


def _polygon_area(points: list[list[int]]) -> float:
    """Shoelace 공식으로 다각형 면적 계산 (자기 교차 여부와 무관하게 부호 있는 면적)."""
    n = len(points)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _segments_intersect(p1, p2, p3, p4) -> bool:
    """두 선분이 서로 교차하는지 판정 (자기 교차 검사용)."""
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    d1 = cross(p3, p4, p1)
    d2 = cross(p3, p4, p2)
    d3 = cross(p1, p2, p3)
    d4 = cross(p1, p2, p4)

    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True
    return False


def _is_self_intersecting(points: list[list[int]]) -> bool:
    """인접하지 않은 변끼리 교차하면 자기 교차로 판정."""
    n = len(points)
    if n < 4:
        return False
    for i in range(n):
        for j in range(i + 1, n):
            # 인접한 변(꼭짓점을 공유하는 변)은 검사에서 제외
            if j == i or j == (i + 1) % n or i == (j + 1) % n:
                continue
            a1, a2 = points[i], points[(i + 1) % n]
            b1, b2 = points[j], points[(j + 1) % n]
            if _segments_intersect(a1, a2, b1, b2):
                return True
    return False


def edit_zones(frame: np.ndarray) -> list[dict[str, Any]]:
    """[담당: 팀원 A]
    목적: 원본 영상에서 다각형 구역 편집
    입력: frame(원본 BGR 영상)
    반환: [{name: str, points: [[x,y], ...]}]
    조작법:
      - 좌클릭: 현재 다각형에 점 추가
      - 우클릭: 마지막 점 취소
      - Enter: 현재 다각형(3점 이상) 확정 -> 콘솔에서 구역 이름 입력받고 다음 다각형 시작
      - Esc: 전체 편집 취소 -> [] 반환 (진행 중이던 미확정 다각형만 취소하려면 다시 Esc 없이 Enter로 넘어가면 됨)
      - q: 지금까지 확정된 구역들로 편집 종료
    """
    orig_h, orig_w = frame.shape[:2]

    # 화면이 너무 크면 축소해서 보여주고, 클릭 좌표는 원본 스케일로 복원한다.
    max_display_w = 1280
    scale = min(1.0, max_display_w / orig_w)
    disp_w, disp_h = int(orig_w * scale), int(orig_h * scale)

    zones: list[dict[str, Any]] = []
    current_points: list[list[int]] = []
    cancelled = {"value": False}

    window_name = "Edit Zones (LClick: add, RClick: undo, Enter: confirm, Esc: cancel all, q: finish)"
    cv2.namedWindow(window_name)

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            # 화면 좌표 -> 원본 좌표로 복원
            ox, oy = int(x / scale), int(y / scale)
            current_points.append([ox, oy])
        elif event == cv2.EVENT_RBUTTONDOWN:
            if current_points:
                current_points.pop()

    cv2.setMouseCallback(window_name, on_mouse)

    try:
        while True:
            canvas = cv2.resize(frame, (disp_w, disp_h)) if scale != 1.0 else frame.copy()

            # 확정된 구역들 그리기
            for zone in zones:
                pts = np.array(
                    [[int(px * scale), int(py * scale)] for px, py in zone["points"]],
                    dtype=np.int32,
                )
                cv2.polylines(canvas, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
                if len(pts) > 0:
                    cv2.putText(canvas, zone["name"], tuple(pts[0]),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

            # 편집 중인 다각형 그리기
            if current_points:
                disp_pts = [[int(px * scale), int(py * scale)] for px, py in current_points]
                for i, p in enumerate(disp_pts):
                    cv2.circle(canvas, tuple(p), 4, (0, 0, 255), -1)
                    if i > 0:
                        cv2.line(canvas, tuple(disp_pts[i - 1]), tuple(p), (0, 0, 255), 2)

            cv2.imshow(window_name, canvas)
            key = cv2.waitKey(20) & 0xFF

            if key == 27:  # Esc: 전체 취소
                cancelled["value"] = True
                zones = []
                break
            elif key == 13:  # Enter: 현재 다각형 확정
                if len(current_points) < 3:
                    continue  # 3점 미만이면 무시
                if _polygon_area(current_points) <= 0:
                    continue  # 면적 0 거부
                if _is_self_intersecting(current_points):
                    continue  # 자기 교차 거부
                name = input(f"구역 이름을 입력하세요 (zone_{len(zones) + 1}): ").strip()
                if not name:
                    name = f"zone_{len(zones) + 1}"
                zones.append({"name": name, "points": [list(p) for p in current_points]})
                current_points = []
            elif key == ord('q'):
                break
    finally:
        cv2.destroyWindow(window_name)

    if cancelled["value"]:
        return []
    return zones


def save_zones(path: str, zones: list[dict[str, Any]], frame_size: tuple[int, int]) -> None:
    """[담당: 팀원 A]
    목적: 구역 JSON 저장
    입력: path(경로), zones(구역 목록), frame_size(원본 width,height)
    """
    import json
    from pathlib import Path

    width, height = frame_size

    names_seen: set[str] = set()
    for zone in zones:
        name = zone.get("name")
        points = zone.get("points", [])
        if not name or name in names_seen:
            raise ValueError(f"구역 이름이 비어있거나 중복됩니다: {name!r}")
        names_seen.add(name)
        if len(points) < 3:
            raise ValueError(f"구역 '{name}'의 좌표가 3개 미만입니다")
        for x, y in points:
            if not (0 <= x <= width and 0 <= y <= height):
                raise ValueError(f"구역 '{name}'의 좌표가 프레임 범위를 벗어났습니다: ({x},{y})")

    payload = {
        "schema_version": 1,
        "frame_size": [width, height],
        "zones": zones,
    }

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        raise OSError(f"구역 JSON 저장 실패: {path}") from exc


def load_zones(path: str, frame_size: tuple[int, int]) -> list[dict[str, Any]]:
    """[담당: 팀원 A]
    목적: 저장 구역 로딩 및 해상도 검증
    입력: path(JSON 경로), frame_size(입력 원본 크기)
    반환: 구역 목록
    """
    import json
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"구역 파일을 찾을 수 없습니다: {path}")

    data = json.loads(p.read_text(encoding="utf-8"))

    if data.get("schema_version") != 1:
        raise ValueError(f"지원하지 않는 zones 스키마 버전입니다: {data.get('schema_version')}")

    saved_w, saved_h = data.get("frame_size", [None, None])
    width, height = frame_size
    if (saved_w, saved_h) != (width, height):
        # 설계상 자동 스케일은 금지 -> 해상도가 다르면 그냥 에러
        raise ValueError(
            f"저장된 구역의 해상도({saved_w}x{saved_h})가 "
            f"현재 입력 해상도({width}x{height})와 일치하지 않습니다"
        )

    return data.get("zones", [])