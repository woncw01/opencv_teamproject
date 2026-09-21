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

def preprocess_frame(frame: np.ndarray, config: dict[str, Any], roi: tuple[int, int, int, int] | None = None) -> tuple[np.ndarray, dict[str, float]]:
    """[담당: 팀원 A]
    목적: 공통 전처리 수행
    매개변수 / 입력 타입: frame: H×W×3 uint8; config: 설정; roi: 원본 x,y,w,h 또는 None
    반환 / 출력 타입: (분석 BGR 영상, {offset_x, offset_y, scale_x, scale_y}); scale은 분석/원본 비율
    구현 순서 TODO:
        1. 프레임 및 ROI 검증
        2. ROI crop 후 종횡비를 유지하여 분석 해상도 이내로 축소
        3. 동일 blur_kernel로 블러
        4. 실제 축소 비율과 원본 오프셋 반환
    예외 및 경계 조건: 빈 프레임·범위 밖 ROI는 ValueError; 커널은 양의 홀수
    모듈 연결: 모든 버전 pipeline → preprocess → detect
    """
    raise NotImplementedError("공통 전처리 수행: 구현 예정")


def restore_boxes(boxes: list[tuple[int, int, int, int]], transform: dict[str, float]) -> list[tuple[int, int, int, int]]:
    """[담당: 팀원 A]
    목적: 분석 좌표를 원본 좌표로 복원
    매개변수 / 입력 타입: boxes: 분석 x,y,w,h; transform: 전처리 변환 정보
    반환 / 출력 타입: 원본 x,y,w,h 목록
    구현 순서 TODO:
        1. x/scale_x+offset_x 등 역변환
        2. 정수 반올림 규칙 통일
    예외 및 경계 조건: 빈 목록은 []; scale은 양수
    모듈 연결: detect의 결과를 pipeline이 복원 후 침입 판정
    """
    raise NotImplementedError("분석 좌표를 원본 좌표로 복원: 구현 예정")


