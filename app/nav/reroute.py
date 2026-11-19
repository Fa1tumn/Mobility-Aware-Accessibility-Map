"""안내 중 재탐색 판단.

현재 위치(노드)와 따라가던 경로를 받아 지금 조건(시각, 이벤트)으로 다시 본다.
    1. 앞으로 갈 구간이 막혔다      → 바로 다시 찾는다(reroute). 갈 길이 없으면 no_route
    2. 다시 찾은 경로가 hysteresis(10%) 넘게 싸다 → 바꾼다. 이벤트가 만료돼
       원래 길이 다시 좋아진 경우도 여기서 잡힌다
    3. 그 외                        → 그대로 간다(keep). 앞 구간의 비용 이벤트는 주의 문구로
이미 지나온 구간의 이벤트는 보지 않는다.

얼마나 자주 부를지(30초마다, 이벤트가 바뀔 때마다)는 호출하는 쪽(웹 화면, 기록 재생)이
정한다. GPS를 경로 위 노드로 맞추는 일(L2·L7 위치 추적)도 호출하는 쪽 몫이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Optional

from app.events.overlay import EventOverlay
from app.graph.schema import Graph
from app.profile.definitions import Profile
from app.routing.dijkstra import INF, RouteResult, find_route
from app.routing.evaluate import edge_label, evaluate_path
from app.schedule.resolver import ScheduleBook

# 새 경로가 남은 경로보다 이 비율 넘게 싸야 바꾼다. 경로가 왔다 갔다 하지 않게 한다.
HYSTERESIS = 0.10


@dataclass
class RerouteDecision:
    action: str                     # keep | reroute | no_route | arrived
    route: RouteResult              # 지금부터 따라갈 경로(현재 위치 → 도착)
    reasons: list[str] = field(default_factory=list)
    remaining_cost: float = INF     # 원래 경로 남은 구간의 지금 비용(막혔으면 inf)
    best_cost: float = INF          # 지금 다시 찾은 최적 비용(없으면 inf)

    @property
    def changed(self) -> bool:
        return self.action == "reroute"


def remaining(route: RouteResult, node: str) -> Optional[RouteResult]:
    """경로에서 node 이후 부분. node가 경로에 없으면 None. 같은 노드를 두 번
    지나는 경로라면 처음 나오는 위치를 쓴다."""
    if node not in route.node_path:
        return None
    i = route.node_path.index(node)
    edges = route.edges[i:]
    return replace(route, node_path=route.node_path[i:], edges=edges,
                   total_distance_m=sum(e.distance_m for e in edges), blocked=[])


def _same(a: RouteResult, b: RouteResult) -> bool:
    return [e.id for e in a.edges] == [e.id for e in b.edges]


def _warnings(route: RouteResult, profile: Profile, events: Optional[EventOverlay]) -> list[str]:
    if not events:
        return []
    out = []
    for e in route.edges:
        eff = events.effect(e.base_id, profile)
        if eff:
            out.extend(f"앞 구간 {edge_label(e)}: {r}" for r in eff.reasons)
    return out


def check_reroute(
    route: RouteResult,
    current_node: str,
    graph: Graph,
    profile: Profile,
    events: Optional[EventOverlay] = None,
    when: Optional[datetime] = None,
    schedule: Optional[ScheduleBook] = None,
    hysteresis: float = HYSTERESIS,
) -> RerouteDecision:
    if not route.found or not route.node_path:
        raise ValueError("따라가던 경로가 없다")
    goal = route.node_path[-1]
    if current_node == goal:
        return RerouteDecision("arrived", replace(route, node_path=[goal], edges=[],
                                                  total_cost=0.0, total_distance_m=0.0),
                               [], 0.0, 0.0)

    best = find_route(graph, current_node, goal, profile, when, schedule, events=events)
    best_cost = best.total_cost if best.found else INF
    rest = remaining(route, current_node)

    if rest is None:
        reasons = [f"경로 이탈: {current_node}에서 다시 찾음"]
        if best.found:
            return RerouteDecision("reroute", best, reasons, INF, best_cost)
        return RerouteDecision("no_route", best, reasons + ["갈 수 있는 경로 없음"], INF, INF)

    chk = evaluate_path(rest.edges, profile, when, schedule, events)
    rest = replace(rest, total_cost=chk.cost, reasons=chk.reasons)

    if not chk.passable:
        reasons = [f"앞 구간 {b}" for b in chk.blocked]
        if best.found:
            return RerouteDecision("reroute", best, reasons, INF, best_cost)
        return RerouteDecision("no_route", rest, reasons + ["돌아갈 경로 없음"], INF, INF)

    if best.found and not _same(best, rest) and best_cost < chk.cost * (1.0 - hysteresis):
        gain = 1.0 - best_cost / chk.cost
        return RerouteDecision("reroute", best, [f"새 경로가 비용 {gain:.0%} 낮음"], chk.cost, best_cost)

    return RerouteDecision("keep", rest, _warnings(rest, profile, events), chk.cost, best_cost)
