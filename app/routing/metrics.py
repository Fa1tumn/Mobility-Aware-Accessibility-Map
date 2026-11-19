"""경로 요약값. 경로 비교, 선택 이유, 경로 GeoJSON이 같은 값을 쓴다."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable, Optional, Sequence

from app.graph.schema import Edge

if TYPE_CHECKING:
    from app.events.overlay import EventOverlay
from app.profile.cost import SLOPE_REASON_PCT
from app.routing.evaluate import edge_label

# 이 이상인 경사 구간을 "가파른 구간"으로 따로 센다(%). 비용 사유 기준과 같다.
STEEP_PCT = SLOPE_REASON_PCT


@dataclass(frozen=True)
class SteepSegment:
    edge: str            # 진행 방향 표기 "B→D"
    slope_pct: float     # 진행 방향 기준(+ 오르막)
    length_m: float

    @property
    def direction(self) -> str:
        return "오르막" if self.slope_pct > 0 else "내리막"


@dataclass
class RouteMetrics:
    distance_m: float = 0.0
    max_uphill_pct: float = 0.0
    max_downhill_pct: float = 0.0
    unknown_slope_m: float = 0.0
    stairs: int = 0
    steep: list[SteepSegment] = field(default_factory=list)
    events: list[tuple[str, str]] = field(default_factory=list)   # (event_id, 종류 이름)


def route_metrics(edges: Iterable[Edge], events: Optional["EventOverlay"] = None) -> RouteMetrics:
    """events를 주면 경로 위 활성 이벤트도 센다(프로필과 무관하게 걸린 것 전부)."""
    m = RouteMetrics()
    for e in edges:
        m.distance_m += e.distance_m
        m.stairs += e.stairs
        if events:
            for ev in events.events_on(e.base_id):
                if ev.event_id not in {i for i, _ in m.events}:
                    m.events.append((ev.event_id, events.types[ev.type].label))
        if e.slope_pct is None:
            m.unknown_slope_m += e.distance_m
            continue
        m.max_uphill_pct = max(m.max_uphill_pct, e.slope_pct)
        m.max_downhill_pct = max(m.max_downhill_pct, -e.slope_pct)
        if abs(e.slope_pct) >= STEEP_PCT:
            m.steep.append(SteepSegment(edge_label(e), e.slope_pct, e.distance_m))
    return m


def overlap_ratio(a: Sequence[Edge], b: Sequence[Edge]) -> float:
    """두 경로가 같은 간선(방향 무관)을 지나는 거리 비율. 짧은 쪽 길이 기준."""
    ids_b = {e.base_id for e in b}
    shared = sum(e.distance_m for e in a if e.base_id in ids_b)
    shorter = min(sum(e.distance_m for e in a), sum(e.distance_m for e in b))
    return shared / shorter if shorter > 0 else 1.0
