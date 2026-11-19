"""이미 정해진 경로(간선 목록)를 지금 조건으로 다시 평가한다.

탐색(dijkstra)은 경로를 찾고, 이 모듈은 주어진 경로를 판정한다. 쓰는 곳:
- 거리만 보고 찾은 최단 경로를 이 프로필로 갈 수 있는지
- 비용을 부풀려 찾은 대안 경로의 실제 비용
- 안내 중인 경로의 남은 구간을 지금도 갈 수 있는지(재탐색)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Optional

from app.graph.schema import Edge
from app.profile import cost as cost_mod
from app.profile import feasibility as feas_mod
from app.profile.definitions import Profile
from app.schedule.resolver import ScheduleBook

INF = float("inf")


def edge_label(e: Edge) -> str:
    """진행 방향 표기. 역방향 간선도 실제로 지나는 방향으로 쓴다."""
    return f"{e.from_node}→{e.to_node}"


@dataclass
class PathCheck:
    passable: bool
    cost: float                                         # 막힌 구간이 있으면 inf
    blocked: list[str] = field(default_factory=list)    # "B→D: 오르막 경사 15.0% > 허용 14.1%"
    reasons: list[str] = field(default_factory=list)    # 비용 사유 "E→C: 경사 미측정"


def evaluate_path(
    edges: Iterable[Edge],
    profile: Profile,
    when: Optional[datetime] = None,
    schedule: Optional[ScheduleBook] = None,
) -> PathCheck:
    blocked: list[str] = []
    reasons: list[str] = []
    total = 0.0
    for e in edges:
        f = feas_mod.check(e, profile, when, schedule)
        if not f.passable:
            blocked.extend(f"{edge_label(e)}: {r}" for r in f.reasons)
            continue
        c = cost_mod.compute(e, profile)
        total += c.value
        reasons.extend(f"{edge_label(e)}: {r}" for r in c.reasons)
    return PathCheck(passable=not blocked, cost=INF if blocked else total,
                     blocked=blocked, reasons=reasons)
