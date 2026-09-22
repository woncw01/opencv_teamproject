from __future__ import annotations

from typing import Any

STATES = ("IDLE", "DETECTING", "ALERT", "CLEARED")


def update_state(
    states: dict[str, dict[str, Any]],
    intrusions: dict[str, bool] | None,
    frame_index: int,
    timestamp: float,
    consecutive_frames: int = 1,
    clear_frames: int = 10,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """[담당: 팀원 A]
    목적: 구역별 상태 전이 계산
    입력:
      states: 구역별 상태 dict. 최초 호출 시 {} 전달 (내부에서 구역별로 자동 초기화)
      intrusions: {구역 이름: bool} 또는 미분석 프레임이면 None
      frame_index: 현재 프레임 인덱스
      timestamp: 현재 프레임 시각(초)
      consecutive_frames: ALERT로 전환하기 위한 연속 True 프레임 수 (기본 1 = 즉시 ALERT)
      clear_frames: ALERT에서 CLEARED로 전환하기 위한 연속 False 프레임 수
    반환:
      (새 states, 이번 호출에서 새로 발생한 사건 목록)
      사건 형태: {"type": "alert"|"cleared", "zone_name": str,
                 "frame_index": int, "media_time_s": float}

    상태 전이 규칙:
      1. IDLE에서 True 들어오면 DETECTING 진입, 연속 True가 consecutive_frames번째가 되는
         순간 ALERT로 전환하고 alert 사건 발행 (consecutive_frames=1이면 즉시 ALERT)
      2. ALERT 중 False가 연속 clear_frames번 들어오면 CLEARED로 전환하고 cleared 사건 발행
      3. CLEARED 상태에서 다음 분석 프레임은 IDLE 기준으로 재판정
      4. intrusions가 None(미분석 프레임)이면 카운터를 초기화하지 않고 현재 상태를 그대로 유지
    """
    if intrusions is None:
        # 미분석 프레임: 상태와 카운터 모두 그대로 유지
        return states, []

    events: list[dict[str, Any]] = []
    new_states = dict(states)

    for zone_name, is_intruding in intrusions.items():
        zone_state = new_states.get(zone_name, {
            "state": "IDLE",
            "consec_true": 0,
            "consec_false": 0,
            "alert_time_s": None,
        })
        # CLEARED는 다음 판정 시점에 IDLE 기준으로 재시작
        if zone_state["state"] == "CLEARED":
            zone_state = {
                "state": "IDLE",
                "consec_true": 0,
                "consec_false": 0,
                "alert_time_s": None,
            }

        state = zone_state["state"]

        if state == "IDLE":
            if is_intruding:
                zone_state["consec_true"] = 1
                zone_state["state"] = "DETECTING"
                if zone_state["consec_true"] >= consecutive_frames:
                    zone_state["state"] = "ALERT"
                    zone_state["alert_time_s"] = timestamp
                    events.append({
                        "type": "alert",
                        "zone_name": zone_name,
                        "frame_index": frame_index,
                        "media_time_s": timestamp,
                    })
            # False면 IDLE 유지, 카운터 변화 없음

        elif state == "DETECTING":
            if is_intruding:
                zone_state["consec_true"] += 1
                if zone_state["consec_true"] >= consecutive_frames:
                    zone_state["state"] = "ALERT"
                    zone_state["alert_time_s"] = timestamp
                    events.append({
                        "type": "alert",
                        "zone_name": zone_name,
                        "frame_index": frame_index,
                        "media_time_s": timestamp,
                    })
            else:
                # 연속이 끊기면 DETECTING 취소하고 IDLE로 복귀
                zone_state["state"] = "IDLE"
                zone_state["consec_true"] = 0

        elif state == "ALERT":
            if is_intruding:
                zone_state["consec_false"] = 0  # 여전히 침입 중 -> 해제 카운터 리셋
            else:
                zone_state["consec_false"] += 1
                if zone_state["consec_false"] >= clear_frames:
                    zone_state["state"] = "CLEARED"
                    events.append({
                        "type": "cleared",
                        "zone_name": zone_name,
                        "frame_index": frame_index,
                        "media_time_s": timestamp,
                        "alert_time_s": zone_state["alert_time_s"],
                    })
                    zone_state["consec_false"] = 0

        new_states[zone_name] = zone_state

    return new_states, events