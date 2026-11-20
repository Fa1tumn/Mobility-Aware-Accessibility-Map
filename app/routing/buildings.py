"""건물 간 경로: 출입구가 여러 개인 건물 사이의 추천·최단·대안 경로.

방법: 가상 출발 노드(@origin)를 출발 건물의 모든 출입구에, 가상 도착 노드(@dest)를
도착 건물의 모든 출입구에 길이 0인 간선으로 잇고, 기존 route_options()를 한 번 돌린다.
그러면 출입구 조합 전체에서 비용이 가장 낮은 경로가 한 번의 탐색으로 나온다.
결과에서 가상 노드·간선을 떼어 내면 "어느 출입구로 나가서 어느 출입구로 들어가는지"가 남는다.

    - 경사·출입 시간·이벤트는 방향과 시각에 따라 달라지므로 A→B와 B→A는 따로 계산한다.
    - 추천 경로가 쓰지 않은 출입구가 이 프로필로 들어갈(나갈) 수 없으면 그 이유를 함께 준다.
      예: "언더우드기념도서관 L2: 출입 불가 — … 09:00-18:00 개방, 지금 19:00 닫힘"
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from itertools import permutations
from typing import TYPE_CHECKING, Iterable, Optional

from app.graph.buildings import Building, BuildingBook
from app.graph.schema import Edge, Graph, Node
from app.profile import feasibility as feas_mod
from app.profile.definitions import Profile
from app.routing.alternatives import RouteOption, route_options
from app.routing.dijkstra import RouteResult, find_route
from app.routing.evaluate import edge_label
from app.routing.metrics import RouteMetrics
from app.schedule.resolver import ScheduleBook

if TYPE_CHECKING:
    from app.events.overlay import EventOverlay

ORIGIN = "@origin"
DEST = "@dest"


@dataclass
class BuildingOption:
    label: str                      # 추천 | 최단 | 대안 n
    path: list[str]                 # 실제 노드만
    from_entrance: str
    to_entrance: str
    result: RouteResult             # 가상 간선을 뗀 결과
    metrics: RouteMetrics
    passable: bool
    blocked: list[str] = field(default_factory=list)
    why: list[str] = field(default_factory=list)
    is_shortest: bool = False


@dataclass
class BuildingRoute:
    origin: Building
    dest: Building
    profile: str
    when: Optional[datetime]
    options: list[BuildingOption]
    entrance_notes: list[str]       # 쓸 수 없는 출입구와 이유
    blocked: list[str] = field(default_factory=list)   # 경로가 없을 때 탐색 중 막힌 곳

    @property
    def recommended(self) -> Optional[BuildingOption]:
        return next((o for o in self.options if o.label == "추천"), None)

    @property
    def found(self) -> bool:
        return self.recommended is not None


def _virtual_edge(edge_id: str, a: str, b: str) -> Edge:
    # 길이 0, 평지, 넓음: 비용·판정·사유 어디에도 흔적이 남지 않는다
    return Edge(id=edge_id, from_node=a, to_node=b, distance_m=0.0, slope_pct=0.0,
                surface="asphalt", width_level="wide", source="virtual")


def _augment(graph: Graph, origin: Building, dest: Building) -> Graph:
    for v in (ORIGIN, DEST):
        if v in graph.nodes:
            raise ValueError(f"노드 ID '{v}'는 가상 노드용으로 예약되어 있다")
    aug = Graph(nodes=dict(graph.nodes), edges=dict(graph.edges))
    aug.add_node(Node(id=ORIGIN, name=origin.name, kind="destination"))
    aug.add_node(Node(id=DEST, name=dest.name, kind="destination"))
    for n in origin.entrances:
        aug.add_edge(_virtual_edge(f"{ORIGIN}>{n}", ORIGIN, n))
    for n in dest.entrances:
        aug.add_edge(_virtual_edge(f"{n}>{DEST}", n, DEST))
    return aug


def _is_virtual(e: Edge) -> bool:
    return e.base_id.startswith(ORIGIN) or e.base_id.endswith(DEST)


def _strip(opt: RouteOption) -> BuildingOption:
    edges = [e for e in opt.result.edges if not _is_virtual(e)]
    path = [n for n in opt.result.node_path if n not in (ORIGIN, DEST)]
    result = replace(opt.result, edges=edges, node_path=path,
                     total_distance_m=sum(e.distance_m for e in edges),
                     reasons=[r for r in opt.result.reasons if not r.startswith("@")])
    return BuildingOption(label=opt.label, path=path, from_entrance=path[0], to_entrance=path[-1],
                          result=result, metrics=opt.metrics, passable=opt.passable,
                          blocked=opt.blocked, why=opt.why, is_shortest=opt.is_shortest)


def entrance_access(
    graph: Graph,
    node_id: str,
    profile: Profile,
    arriving: bool,
    when: Optional[datetime] = None,
    schedule: Optional[ScheduleBook] = None,
    events: Optional["EventOverlay"] = None,
) -> list[str]:
    """출입구 노드에 닿는 간선이 이 프로필에 모두 막혀 있으면 그 이유들. 하나라도 열려 있으면 []."""
    reasons: list[str] = []
    for e in graph.edges.values():
        if node_id not in (e.from_node, e.to_node):
            continue
        into = (e.to_node == node_id) == arriving          # 들어갈 때는 node로 향하는 방향
        step = e if into else e.reversed()
        f = feas_mod.check(step, profile, when, schedule)
        eff = events.effect(step.base_id, profile) if events else None
        if f.passable and not (eff and eff.block):
            return []
        reasons.extend(f"{edge_label(step)}: {r}" for r in f.reasons)
        if eff and eff.block:
            reasons.extend(f"{edge_label(step)}: {r}" for r in eff.block_reasons)
    return reasons


def _notes(graph: Graph, building: Building, used: Optional[str], arriving: bool, profile: Profile,
           when, schedule, events) -> list[str]:
    notes = []
    for n in building.entrances:
        if n == used:
            continue
        why = entrance_access(graph, n, profile, arriving, when, schedule, events)
        if why:
            name = graph.nodes[n].name or n
            if not name.startswith(building.name):
                name = f"{building.name} {name}"
            notes.append(f"{name}: " + "; ".join(dict.fromkeys(why)))
    return notes


def building_route(
    graph: Graph,
    buildings: BuildingBook,
    origin_id: str,
    dest_id: str,
    profile: Profile,
    when: Optional[datetime] = None,
    schedule: Optional[ScheduleBook] = None,
    events: Optional["EventOverlay"] = None,
    k: int = 3,
) -> BuildingRoute:
    if origin_id == dest_id:
        raise ValueError("출발 건물과 도착 건물이 같다")
    origin, dest = buildings[origin_id], buildings[dest_id]
    aug = _augment(graph, origin, dest)
    options = [_strip(o) for o in route_options(aug, ORIGIN, DEST, profile, when, schedule,
                                                k=k, events=events)]
    rec = next((o for o in options if o.label == "추천"), None)
    notes = (_notes(graph, origin, rec.from_entrance if rec else None, False, profile, when, schedule, events)
             + _notes(graph, dest, rec.to_entrance if rec else None, True, profile, when, schedule, events))
    blocked: list[str] = []
    if rec is None:
        failed = find_route(aug, ORIGIN, DEST, profile, when, schedule, events=events)
        blocked = [b for b in failed.blocked if not b.startswith("@")]
    return BuildingRoute(origin, dest, profile.name, when, options, notes, blocked)


def all_building_routes(
    graph: Graph,
    buildings: BuildingBook,
    profiles: Iterable[Profile],
    when: Optional[datetime] = None,
    schedule: Optional[ScheduleBook] = None,
    events: Optional["EventOverlay"] = None,
    k: int = 3,
) -> dict[tuple[str, str, str], BuildingRoute]:
    """프로필 × 순서 있는 건물 쌍 전부. (profile, origin, dest) → BuildingRoute"""
    out = {}
    for p in profiles:
        for a, b in permutations(buildings.buildings, 2):
            out[(p.name, a, b)] = building_route(graph, buildings, a, b, p, when, schedule, events, k)
    return out


def format_building_route(graph: Graph, br: BuildingRoute) -> str:
    def name(n: str) -> str:
        return graph.nodes[n].name or n

    head = f"[{br.profile}] {br.origin.name} → {br.dest.name}"
    if br.when:
        head += f"  ({br.when:%Y-%m-%d %a %H:%M})"
    lines = [head]
    if not br.found:
        lines.append("  통행 가능한 경로 없음")
        for b in br.blocked[:5]:
            lines.append(f"  [막힘] {b}")
    for o in br.options:
        label = o.label + (" · 최단" if o.is_shortest else "")
        state = f"비용 {o.result.total_cost:.2f}" if o.passable else "통행 불가"
        lines.append(f"  {label:<8} {name(o.from_entrance)} → {name(o.to_entrance)}  "
                     f"{' → '.join(o.path)}  {o.metrics.distance_m:.0f}m  {state}")
        notes = o.why if o.passable else o.blocked[:3]
        if notes:
            lines.append("      · " + " · ".join(notes))
    for note in br.entrance_notes:
        lines.append(f"  [출입구] {note}")
    return "\n".join(lines)
