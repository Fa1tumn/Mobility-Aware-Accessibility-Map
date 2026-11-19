"""Feasibility Filter — hard constraint만 본다.

통과하면 그 구간은 '지나갈 수 있다'. 얼마나 편한지는 cost.py가 맡는다.
이 분리가 중요한 이유: 라우팅은 여기서 걸린 간선을 아예 확장하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.graph.schema import Edge
from app.profile.definitions import Profile, WIDTH_RANK
from app.schedule.resolver import ScheduleBook


@dataclass
class Feasibility:
    passable: bool
    reasons: list[str] = field(default_factory=list)   # 막힌 이유


def check(
    edge: Edge,
    profile: Profile,
    when: Optional[datetime] = None,
    schedule: Optional[ScheduleBook] = None,
) -> Feasibility:
    reasons: list[str] = []

    if edge.stairs > 0 and not profile.stairs_allowed:
        reasons.append(f"계단 {edge.stairs}단")

    if edge.threshold_cm is not None and edge.threshold_cm > profile.max_threshold_cm:
        reasons.append(
            f"문턱 {edge.threshold_cm:.1f}cm > 허용 {profile.max_threshold_cm:.1f}cm")

    s = edge.abs_slope_deg
    if s is not None and s > profile.max_slope_deg:
        reasons.append(f"경사 {s:.1f}° > 허용 {profile.max_slope_deg:.1f}°")

    if WIDTH_RANK[edge.width_level] < WIDTH_RANK[profile.min_width_level]:
        reasons.append(f"통행폭 {edge.width_level} (최소 {profile.min_width_level})")

    if schedule is not None and edge.entrance_id is not None:
        if not schedule.is_open(edge.entrance_id, when):
            when_s = when.strftime("%a %H:%M") if when else "?"
            reasons.append(f"{when_s} 출입 불가 ({edge.entrance_id})")

    return Feasibility(passable=not reasons, reasons=reasons)
