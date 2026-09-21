"""목적: 구역별 IDLE, DETECTING, ALERT, CLEARED 상태 및 사건 메타데이터
담당 팀원: A
입력 데이터: 구역별 감지 bool 또는 None, 영상 시각
출력 데이터: 상태 dict와 사건 전이 목록
의존 관계: 표준 라이브러리; pipeline이 recorder와 CSV 연결
구현 TODO: 연속 감지, 해제, 독립 구역 상태; 파일 저장 금지
상태: 인터페이스 설계만 완료. 함수 본문은 미구현.
"""
from __future__ import annotations

from typing import Any
import numpy as np

STATES = ("IDLE", "DETECTING", "ALERT", "CLEARED")

def update_state(states: dict[str, dict[str, Any]], intrusions: dict[str, bool] | None, frame_index: int, media_time_s: float, config: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """[담당: 팀원 A]
    목적: 구역별 상태 전이 계산
    매개변수 / 입력 타입: states: 초기 {}; intrusions: 구역 bool 또는 미분석 None; frame_index: 원본 인덱스; media_time_s: 영상 초; config: 설정
    반환 / 출력 타입: (새 states, 사건 목록); 상세 필드는 README 참조
    구현 순서 TODO:
        1. IDLE에서 True면 DETECTING, N번째 연속 True에서 ALERT (N=1 즉시)
        2. False면 감지 카운터 초기화; ALERT 중 해제 기준 연속 False면 CLEARED
        3. CLEARED 다음 분석에서 IDLE 기준으로 재판정
        4. alert/cleared 사건 생성; 지속 시간은 clear 시각-alert 시각
    예외 및 경계 조건: None은 카운터 증가 금지, 연속 카운터 초기화·ALERT 유지; 인덱스 공백에도 초기화; 시각 역행 ValueError
    모듈 연결: pipeline이 전이를 recorder에 전달하고 CSV 기록
    """
    raise NotImplementedError("구역별 상태 전이 계산: 구현 예정")


