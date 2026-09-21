"""목적: MOG2 움직임 검출 및 다각형 침입 판정만 담당
담당 팀원: A
입력 데이터: 분석 프레임, MOG2, 원본 박스와 구역
출력 데이터: 박스 목록, 구역별 bool
의존 관계: preprocess 결과; 구현 시 OpenCV; state/recorder에 직접 의존하지 않음
구현 TODO: MOG2, 외곽선 필터, 하단 중앙점 침입
상태: 인터페이스 설계만 완료. 함수 본문은 미구현.
"""
from __future__ import annotations

from typing import Any
import numpy as np

def create_background_subtractor(config: dict[str, Any]) -> Any:
    """[담당: 팀원 A]
    목적: 실행별 MOG2 인스턴스 생성
    매개변수 / 입력 타입: config: 전체 설정 dict
    반환 / 출력 타입: OpenCV BackgroundSubtractorMOG2
    구현 순서 TODO:
        1. history, var_threshold, detect_shadows 적용
        2. 각 실험 시작마다 새 인스턴스 생성
    예외 및 경계 조건: 잘못된 설정은 ValueError
    모듈 연결: pipeline에서 1회 생성
    """
    raise NotImplementedError("실행별 MOG2 인스턴스 생성: 구현 예정")


def detect_motion(frame: np.ndarray, background_subtractor: Any, min_area: float) -> list[tuple[int, int, int, int]]:
    """[담당: 팀원 A]
    목적: 움직이는 객체 영역 검출
    매개변수 / 입력 타입: frame: 분석 BGR uint8; background_subtractor: MOG2; min_area: 분석 픽셀 면적
    반환 / 출력 타입: 분석 좌표 (x,y,w,h) 목록
    구현 순서 TODO:
        1. MOG2 적용
        2. 그림자 127 제외하고 이진화 및 노이즈 제거
        3. 외곽선 추출 및 면적 필터
        4. 바운딩 박스 반환
    예외 및 경계 조건: 없으면 []; 원본 min_area에 scale_x*scale_y를 곱해 전달
    모듈 연결: pipeline에서 공통 호출; 저장·상태 관리 금지
    """
    raise NotImplementedError("움직이는 객체 영역 검출: 구현 예정")


def check_intrusion(boxes: list[tuple[int, int, int, int]], zones: list[dict[str, Any]]) -> dict[str, bool]:
    """[담당: 팀원 A]
    목적: 위험 구역별 침입 여부 판정
    매개변수 / 입력 타입: boxes: 원본 좌표; zones: name, points를 가진 목록
    반환 / 출력 타입: {구역 이름: 침입 bool} (모든 구역 포함)
    구현 순서 TODO:
        1. 박스 하단 중앙점 계산
        2. pointPolygonTest로 경계 포함 내부 판정
        3. 구역별 하나 이상이면 True
    예외 및 경계 조건: 박스 없으면 모두 False; 중복 구역명은 ValueError
    모듈 연결: pipeline → state; 모든 버전 동일 기준
    """
    raise NotImplementedError("위험 구역별 침입 여부 판정: 구현 예정")


