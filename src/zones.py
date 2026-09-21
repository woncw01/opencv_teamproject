"""목적: 마우스 다각형 위험 구역 편집 및 JSON 입출력
담당 팀원: A
입력 데이터: 원본 프레임 또는 JSON 경로
출력 데이터: 이름과 꼭짓점 목록
의존 관계: 구현 시 OpenCV, json; detect에서 구역 사용
구현 TODO: 좌클릭 추가, 우클릭 취소, Enter 확정, Esc 취소, 저장 검증
상태: 인터페이스 설계만 완료. 함수 본문은 미구현.
"""
from __future__ import annotations

from typing import Any
import numpy as np

def edit_zones(frame: np.ndarray) -> list[dict[str, Any]]:
    """[담당: 팀원 A]
    목적: 원본 영상에서 다각형 구역 편집
    매개변수 / 입력 타입: frame: 원본 BGR 영상
    반환 / 출력 타입: [{name: str, points: [[x,y], ...]}]
    구현 순서 TODO:
        1. 메인 스레드 마우스 콜백 등록
        2. 점 추가·취소 및 구역 이름 지정
        3. 3점 이상 다각형 검증 후 반환
    예외 및 경계 조건: Esc는 []; 자기 교차·면적 0 거부; 화면 축소 시 좌표 복원
    모듈 연결: save_zones에 전달
    """
    raise NotImplementedError("원본 영상에서 다각형 구역 편집: 구현 예정")


def save_zones(path: str, zones: list[dict[str, Any]], frame_size: tuple[int, int]) -> None:
    """[담당: 팀원 A]
    목적: 구역 JSON 저장
    매개변수 / 입력 타입: path: 경로; zones: 구역 목록; frame_size: 원본 (width,height)
    반환 / 출력 타입: None; JSON 파일
    구현 순서 TODO:
        1. 좌표 범위와 중복 이름 검증
        2. schema_version=1, frame_size, zones 기록
    예외 및 경계 조건: 쓰기 실패 OSError; 기존 파일 교체는 호출자가 의도한 저장 시만 수행
    모듈 연결: edit_zones 결과 저장
    """
    raise NotImplementedError("구역 JSON 저장: 구현 예정")


def load_zones(path: str, frame_size: tuple[int, int]) -> list[dict[str, Any]]:
    """[담당: 팀원 A]
    목적: 저장 구역 로딩 및 해상도 검증
    매개변수 / 입력 타입: path: JSON; frame_size: 입력 원본 크기
    반환 / 출력 타입: 구역 목록
    구현 순서 TODO:
        1. JSON 읽기 및 스키마 검증
        2. 원본 해상도 일치 검사
        3. 구역 반환
    예외 및 경계 조건: 파일 없음 FileNotFoundError; 해상도 불일치 ValueError, 자동 스케일 금지
    모듈 연결: pipeline 초기화에서 사용
    """
    raise NotImplementedError("저장 구역 로딩 및 해상도 검증: 구현 예정")


