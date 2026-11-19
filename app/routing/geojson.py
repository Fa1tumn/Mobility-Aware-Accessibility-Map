"""경로 결과를 지도에 그릴 수 있는 GeoJSON으로 바꾼다.

피처 하나가 경로의 간선 하나다. 경로 전체 요약은 FeatureCollection의
`properties`(GeoJSON이 허용하는 추가 멤버)에 둔다. Leaflet은 이 값을 무시하고
피처만 그리며, 화면 코드는 요약을 따로 읽어 표시하면 된다.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from app.graph.schema import Edge, Graph
from app.profile import cost as cost_mod
from app.profile.definitions import Profile
from app.routing.dijkstra import RouteResult
from app.routing.metrics import route_metrics

if TYPE_CHECKING:
    from app.events.overlay import EventOverlay


def _edge_coords(graph: Graph, e: Edge) -> Optional[list[list[float]]]:
    if e.geometry is not None:
        return e.geometry
    a, b = graph.nodes.get(e.from_node), graph.nodes.get(e.to_node)
    if a is None or b is None or None in (a.lon, a.lat, b.lon, b.lat):
        return None
    return [[a.lon, a.lat], [b.lon, b.lat]]


def route_to_geojson(
    graph: Graph,
    result: RouteResult,
    profile: Profile,
    start: str,
    goal: str,
    when: Optional[datetime] = None,
    events: Optional["EventOverlay"] = None,
) -> dict:
    """events를 주면 간선마다 걸린 활성 이벤트(events)와 그 비용(cost에 포함)을 넣는다."""
    features = []
    m = route_metrics(result.edges, events)
    for seq, e in enumerate(result.edges):
        c = cost_mod.compute(e, profile)
        eff = events.effect(e.base_id, profile) if events else None
        on_edge = events.events_on(e.base_id) if events else []
        coords = _edge_coords(graph, e)
        features.append({
            "type": "Feature",
            "geometry": None if coords is None else {"type": "LineString", "coordinates": coords},
            "properties": {
                "seq": seq,
                "edge_id": e.base_id,
                "reverse": e.is_reverse,
                "from_node": e.from_node,
                "to_node": e.to_node,
                "distance_m": round(e.distance_m, 1),
                "slope_pct": None if e.slope_pct is None else round(e.slope_pct, 2),
                "surface": e.surface,
                "stairs": e.stairs,
                "cost": round(c.value + (eff.penalty if eff else 0.0), 4),
                "reasons": c.reasons + (eff.reasons if eff else []),
                "events": [events.describe(ev) for ev in on_edge],
            },
        })

    summary = {
        "profile": profile.name,
        "found": result.found,
        "start": start,
        "goal": goal,
        "when": when.isoformat() if when else None,
        "node_path": result.node_path,
        "total_distance_m": round(result.total_distance_m, 1) if result.found else None,
        "total_cost": round(result.total_cost, 4) if result.found else None,
        "unknown_slope_m": round(m.unknown_slope_m, 1),
        "max_uphill_pct": round(m.max_uphill_pct, 2),
        "max_downhill_pct": round(m.max_downhill_pct, 2),
        "blocked": result.blocked,
        "event_ids": [event_id for event_id, _ in m.events],
    }
    return {"type": "FeatureCollection", "properties": summary, "features": features}
