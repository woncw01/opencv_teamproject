from __future__ import annotations

from typing import Any

STATES = ("IDLE", "DETECTING", "ALERT", "CLEARED")


def update_state(
    states: dict[str, dict[str, Any]],
    intrusions: dict[str, bool] | None,
    frame_index: int,
    media_time_s: float,
    config: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """[담당: 팀원 A]
    목적: 구역별 상태 전이 계산
    """
    consecutive_frames = config.get("consecutive_frames", 1)
    clear_frames = config.get("clear_frames", 10)
    timestamp = media_time_s

    if intrusions is None:
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
                        "event_id": f"{zone_name}_{frame_index}",
                        "zone_name": zone_name,
                        "frame_index": frame_index,
                        "media_time_s": timestamp,
                    })

        elif state == "DETECTING":
            if is_intruding:
                zone_state["consec_true"] += 1
                if zone_state["consec_true"] >= consecutive_frames:
                    zone_state["state"] = "ALERT"
                    zone_state["alert_time_s"] = timestamp
                    events.append({
                        "type": "alert",
                        "event_id": f"{zone_name}_{frame_index}",
                        "zone_name": zone_name,
                        "frame_index": frame_index,
                        "media_time_s": timestamp,
                    })
            else:
                zone_state["state"] = "IDLE"
                zone_state["consec_true"] = 0

        elif state == "ALERT":
            if is_intruding:
                zone_state["consec_false"] = 0
            else:
                zone_state["consec_false"] += 1
                if zone_state["consec_false"] >= clear_frames:
                    zone_state["state"] = "CLEARED"
                    events.append({
                        "type": "cleared",
                        "event_id": f"{zone_name}_{frame_index}",
                        "zone_name": zone_name,
                        "frame_index": frame_index,
                        "media_time_s": timestamp,
                        "alert_time_s": zone_state["alert_time_s"],
                    })
                    zone_state["consec_false"] = 0

        new_states[zone_name] = zone_state

    return new_states, events