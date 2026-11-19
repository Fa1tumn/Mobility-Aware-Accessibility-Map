"""경로 선택지: 추천, 최단, 대안.

추천   프로필 비용이 가장 낮은 경로.
최단   제약을 모두 끄고 거리만 본 경로. 이 프로필로 못 가면 막힌 이유를 함께 준다.
       추천과 같으면 따로 만들지 않고 추천에 is_shortest 표시만 한다.
대안   추천 경로가 쓴 간선의 비용을 ALT_FACTOR배로 올리고 다시 찾는다. 새로 찾은
       경로의 간선도 다음 반복에서 함께 부풀린다. 아래 경우는 버린다.
       - 실제 비용이 추천보다 max_extra(기본 30%) 넘게 비쌈
       - 이미 있는 선택지와 max_overlap(기본 80%) 넘게 겹침

선택 이유(why)는 추천은 최단과 비교해서, 나머지는 추천과 비교해서 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from app.graph.schema import Graph
from app.profile.definitions import Profile
from app.routing.dijkstra import RouteResult, find_route
from app.routing.evaluate import evaluate_path
from app.routing.explain import explain
from app.routing.metrics import RouteMetrics, overlap_ratio, route_metrics
from app.schedule.resolver import ScheduleBook

if TYPE_CHECKING:
    from app.events.overlay import EventOverlay

# 거리만 보는 기준 프로필. 계단·문턱·경사·통행폭 제약이 모두 꺼져 있다.
SHORTEST = Profile(name="shortest")

ALT_FACTOR = 1.5          # 대안 탐색 때 이미 쓴 간선의 비용 배율
ALT_MAX_EXTRA = 0.30      # 추천 대비 허용하는 추가 비용 비율
ALT_MAX_OVERLAP = 0.80    # 이보다 많이 겹치면 같은 경로로 본다
ALT_TRIES_PER_OPTION = 3  # 대안 1개를 찾기 위해 다시 탐색하는 최대 횟수


@dataclass
class RouteOption:
    label: str                      # "추천" | "최단" | "대안 1" ...
    result: RouteResult             # total_cost는 이 프로필 기준 실제 비용
    metrics: RouteMetrics
    passable: bool                  # 이 프로필로 갈 수 있는지
    blocked: list[str] = field(default_factory=list)   # 못 가는 이유
    why: list[str] = field(default_factory=list)       # 비교 대상과의 차이
    is_shortest: bool = False       # 추천이 곧 최단인지

    @property
    def path(self) -> list[str]:
        return self.result.node_path


def _same(a: RouteResult, b: RouteResult) -> bool:
    return [e.id for e in a.edges] == [e.id for e in b.edges]


def route_options(
    graph: Graph,
    start: str,
    goal: str,
    profile: Profile,
    when: Optional[datetime] = None,
    schedule: Optional[ScheduleBook] = None,
    k: int = 3,
    max_extra: float = ALT_MAX_EXTRA,
    max_overlap: float = ALT_MAX_OVERLAP,
    events: Optional["EventOverlay"] = None,
) -> list[RouteOption]:
    """events를 주면 추천·대안은 이벤트를 반영해 찾고, 최단은 거리만으로 찾은 뒤
    이벤트까지 넣어 다시 판정한다("최단 경로는 공사 통제로 통행 불가")."""
    options: list[RouteOption] = []
    rec = find_route(graph, start, goal, profile, when, schedule, events=events)
    short = find_route(graph, start, goal, SHORTEST)

    rec_opt: Optional[RouteOption] = None
    if rec.found:
        rec_opt = RouteOption("추천", rec, route_metrics(rec.edges, events), passable=True,
                              is_shortest=short.found and _same(rec, short))
        options.append(rec_opt)

    if short.found and not (rec_opt and rec_opt.is_shortest):
        chk = evaluate_path(short.edges, profile, when, schedule, events)
        sm = route_metrics(short.edges, events)
        options.append(RouteOption(
            "최단", replace(short, total_cost=chk.cost, reasons=chk.reasons), sm,
            passable=chk.passable, blocked=chk.blocked,
            why=explain(sm, rec_opt.metrics) if rec_opt else []))
        if rec_opt:
            rec_opt.why = explain(rec_opt.metrics, sm)

    if rec_opt is None or k <= 0:
        return options

    scale: dict[str, float] = {}
    penalized = {e.base_id for e in rec.edges}
    found = 0
    for _ in range(k * ALT_TRIES_PER_OPTION):
        for edge_id in penalized:
            scale[edge_id] = scale.get(edge_id, 1.0) * ALT_FACTOR
        cand = find_route(graph, start, goal, profile, when, schedule, cost_scale=scale, events=events)
        if not cand.found:
            break
        penalized |= {e.base_id for e in cand.edges}
        if any(overlap_ratio(cand.edges, o.result.edges) > max_overlap for o in options):
            continue
        chk = evaluate_path(cand.edges, profile, when, schedule, events)
        if not chk.passable or chk.cost > rec.total_cost * (1.0 + max_extra):
            continue
        found += 1
        m = route_metrics(cand.edges, events)
        options.append(RouteOption(
            f"대안 {found}", replace(cand, total_cost=chk.cost, reasons=chk.reasons), m,
            passable=True, why=explain(m, rec_opt.metrics)))
        if found >= k:
            break
    return options


def format_options(options: list[RouteOption], profile_name: str = "") -> str:
    head = f"[{profile_name}] " if profile_name else ""
    if not options:
        return head + "경로 없음 (출발·도착이 연결돼 있지 않음)"
    lines = []
    if not any(o.label == "추천" for o in options):
        lines.append(head + "통행 가능한 경로 없음")
    for o in options:
        label = o.label + (" · 최단" if o.is_shortest else "")
        state = f"비용 {o.result.total_cost:.2f}" if o.passable else "통행 불가"
        lines.append(f"{head}{label:<8} {' → '.join(o.path)}  {o.metrics.distance_m:.0f}m  {state}")
        notes = o.blocked[:3] if not o.passable else o.why
        if notes:
            lines.append("    · " + " · ".join(notes))
    return "\n".join(lines)
