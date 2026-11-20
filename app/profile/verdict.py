"""Verdict — 지도 표시용 3단계 등급.

CR-02(구간별 Passable/Difficult/Impassable 표시)와 CR-03(판단 원인 제공)을
담당한다. 사용자가 경로를 요청하지 않고 지도만 열었을 때 구간에 색을 칠하려면
이 층이 필요하다. cost 값 3.1을 사용자에게 그대로 보여줄 수는 없다.

중요: 라우팅은 이 모듈을 거치지 않는다. dijkstra는 feasibility + cost를
직접 쓴다. verdict가 경로 계산에 끼어들면 3단계로 뭉개진 정보로 최단경로를
구하게 되므로, 용도를 분리해 둔다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from app.graph.schema import Edge
from app.profile import cost as cost_mod
from app.profile import feasibility as feas_mod
from app.profile.definitions import Profile
from app.schedule.resolver import ScheduleBook

if TYPE_CHECKING:
    from app.events.overlay import EventOverlay

# 100m 환산 비용이 이 값을 넘으면 '어려움'으로 본다.
DIFFICULT_THRESHOLD = 2.0

COLOR = {"passable": "green", "difficult": "yellow", "impassable": "red"}


@dataclass
class Verdict:
    level: str                                     # passable|difficult|impassable
    reasons: list[str] = field(default_factory=list)
    cost: Optional[float] = None

    @property
    def color(self) -> str:
        return COLOR[self.level]


def evaluate(
    edge: Edge,
    profile: Profile,
    when: Optional[datetime] = None,
    schedule: Optional[ScheduleBook] = None,
    events: Optional["EventOverlay"] = None,
) -> Verdict:
    """events를 주면 막는 이벤트는 '불가', 비용 이벤트는 최소 '어려움'으로 본다.
    비용 이벤트는 간선 길이와 무관한 지점 비용이라 100m 정규화에 넣지 않는다."""
    f = feas_mod.check(edge, profile, when, schedule)
    eff = events.effect(edge.base_id, profile) if events else None
    if not f.passable or (eff and eff.block):
        return Verdict(level="impassable",
                       reasons=f.reasons + (eff.block_reasons if eff and eff.block else []))

    c = cost_mod.compute(edge, profile)
    # 구간 길이에 비례해 커지는 값이므로 100m 기준으로 정규화해 비교한다
    norm = c.value / max(edge.distance_m / cost_mod.DISTANCE_UNIT_M, 1e-6)
    level = "difficult" if norm >= DIFFICULT_THRESHOLD else "passable"
    if eff:
        return Verdict(level="difficult", reasons=c.reasons + eff.reasons, cost=c.value + eff.penalty)
    return Verdict(level=level, reasons=c.reasons, cost=c.value)
