"""프로파일 인지 최단경로.

통행 불가(INF) 간선은 아예 확장하지 않는다. 경로가 없으면 그 사실과 함께
'무엇이 막았는지'를 돌려준다. 사용자에게 이유를 보여주기 위해서다.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.graph.schema import Graph, Edge
from app.profile import cost as cost_mod
from app.profile import feasibility as feas_mod

INF = float("inf")
from app.profile.definitions import Profile
from app.schedule.resolver import ScheduleBook


@dataclass
class RouteResult:
    found: bool
    total_cost: float = INF
    total_distance_m: float = 0.0
    node_path: list[str] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)      # 구간별 페널티 요약
    blocked: list[str] = field(default_factory=list)      # 막힌 간선 사유

    def summary(self) -> str:
        if not self.found:
            head = "통행 가능한 경로 없음"
            if self.blocked:
                head += " — " + "; ".join(self.blocked[:3])
            return head
        return (f"{' → '.join(self.node_path)}  "
                f"거리 {self.total_distance_m:.0f}m  비용 {self.total_cost:.2f}")


def find_route(
    graph: Graph,
    start: str,
    goal: str,
    profile: Profile,
    when: Optional[datetime] = None,
    schedule: Optional[ScheduleBook] = None,
    cost_scale: Optional[dict[str, float]] = None,
) -> RouteResult:
    """cost_scale: 간선 ID(역방향 포함 원래 ID) → 비용 배율. 대안 경로를 찾을 때
    이미 쓴 간선의 비용을 부풀리는 용도다. 돌려주는 total_cost에도 배율이 들어가므로
    실제 비용은 app.routing.evaluate.evaluate_path로 다시 계산한다."""
    if start not in graph.nodes:
        raise KeyError(f"출발 노드 '{start}' 없음")
    if goal not in graph.nodes:
        raise KeyError(f"도착 노드 '{goal}' 없음")

    dist: dict[str, float] = {start: 0.0}
    prev: dict[str, tuple[str, Edge]] = {}
    blocked: list[str] = []
    seen: set[str] = set()
    pq: list[tuple[float, str]] = [(0.0, start)]

    while pq:
        d, u = heapq.heappop(pq)
        if u in seen:
            continue
        seen.add(u)
        if u == goal:
            break

        for e in graph.outgoing(u):
            f = feas_mod.check(e, profile, when, schedule)
            if not f.passable:
                blocked.append(f"{e.from_node}→{e.to_node}: {f.reasons[0]}")
                continue
            c = cost_mod.compute(e, profile).value
            if cost_scale:
                c *= cost_scale.get(e.base_id, 1.0)
            nd = d + c
            if nd < dist.get(e.to_node, INF):
                dist[e.to_node] = nd
                prev[e.to_node] = (u, e)
                heapq.heappush(pq, (nd, e.to_node))

    if goal not in dist:
        # 중복 사유 제거하되 순서 유지
        uniq = list(dict.fromkeys(blocked))
        return RouteResult(found=False, blocked=uniq)

    # 역추적
    path_nodes = [goal]
    path_edges: list[Edge] = []
    cur = goal
    while cur != start:
        p, e = prev[cur]
        path_edges.append(e)
        path_nodes.append(p)
        cur = p
    path_nodes.reverse()
    path_edges.reverse()

    reasons: list[str] = []
    total_d = 0.0
    for e in path_edges:
        total_d += e.distance_m
        for pr in cost_mod.compute(e, profile).reasons:
            reasons.append(f"{e.from_node}→{e.to_node}: {pr}")

    return RouteResult(
        found=True,
        total_cost=dist[goal],
        total_distance_m=total_d,
        node_path=path_nodes,
        edges=path_edges,
        reasons=reasons,
        blocked=list(dict.fromkeys(blocked)),
    )
