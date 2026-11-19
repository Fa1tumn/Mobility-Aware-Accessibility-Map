"""그래프 입출력.

두 형식을 읽는다.
    load_graph(nodes.json, edges.json)  9월 PoC 형식(좌표 없음 가능)
    load_geojson(graph.geojson)         좌표가 있는 실험 구역 graph

GeoJSON 형식 (docs/routing-data-contract.md 참고)
    Point 피처      = 노드. properties: id, name, kind, level
    LineString 피처 = 간선. properties: id, from_node, to_node, slope_pct, surface ...
                      좌표는 from_node에서 to_node 순서. distance_m을 생략하면 선 길이로 채운다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, fields
from pathlib import Path

from app.graph.geo import polyline_length_m
from app.graph.schema import Graph, Node, Edge, SchemaError

_NODE_FIELDS = {f.name for f in fields(Node)}
_EDGE_FIELDS = {f.name for f in fields(Edge)}


def _check(g: Graph) -> Graph:
    problems = g.validate()
    if problems:
        raise SchemaError("그래프 참조 오류:\n  " + "\n  ".join(problems))
    return g


def load_graph(nodes_path: str | Path, edges_path: str | Path) -> Graph:
    g = Graph()
    for row in json.loads(Path(nodes_path).read_text(encoding="utf-8")):
        g.add_node(Node(**row))
    for row in json.loads(Path(edges_path).read_text(encoding="utf-8")):
        g.add_edge(Edge(**row))
    return _check(g)


def save_graph(g: Graph, nodes_path: str | Path, edges_path: str | Path) -> None:
    Path(nodes_path).write_text(
        json.dumps([asdict(n) for n in g.nodes.values()],
                   ensure_ascii=False, indent=2), encoding="utf-8")
    Path(edges_path).write_text(
        json.dumps([asdict(e) for e in g.edges.values()],
                   ensure_ascii=False, indent=2), encoding="utf-8")


def load_geojson(path: str | Path) -> Graph:
    """좌표가 있는 GeoJSON graph를 읽는다. 모르는 속성은 무시하지 않고 오류로 알린다."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("type") != "FeatureCollection":
        raise SchemaError("GeoJSON FeatureCollection이 아니다")

    g = Graph()
    edge_rows = []
    for i, feature in enumerate(data.get("features", [])):
        geometry = feature.get("geometry") or {}
        props = dict(feature.get("properties") or {})
        kind = geometry.get("type")
        unknown = set()
        if kind == "Point":
            lon, lat = geometry["coordinates"][:2]
            unknown = set(props) - _NODE_FIELDS
            if not unknown:
                g.add_node(Node(**{**props, "lon": float(lon), "lat": float(lat)}))
        elif kind == "LineString":
            unknown = set(props) - _EDGE_FIELDS
            if not unknown:
                edge_rows.append({**props, "geometry": geometry["coordinates"]})
        else:
            raise SchemaError(f"피처 {i}: Point 또는 LineString만 지원 (받은 값: {kind})")
        if unknown:
            raise SchemaError(f"피처 {i}: 정의되지 않은 속성 {sorted(unknown)}")

    for row in edge_rows:
        if row.get("distance_m") is None:
            row["distance_m"] = round(polyline_length_m(row["geometry"]), 2)
        g.add_edge(Edge(**row))
    return _check(g)


def save_geojson(g: Graph, path: str | Path) -> None:
    """graph를 GeoJSON으로 쓴다. 좌표가 없는 노드·간선은 geometry를 null로 둔다."""
    features = []
    for n in g.nodes.values():
        props = {k: v for k, v in asdict(n).items() if k not in ("lat", "lon")}
        geometry = None if n.lat is None or n.lon is None else {
            "type": "Point", "coordinates": [n.lon, n.lat]}
        features.append({"type": "Feature", "geometry": geometry, "properties": props})
    for e in g.edges.values():
        props = {k: v for k, v in asdict(e).items() if k != "geometry"}
        geometry = None if e.geometry is None else {
            "type": "LineString", "coordinates": e.geometry}
        features.append({"type": "Feature", "geometry": geometry, "properties": props})
    Path(path).write_text(
        json.dumps({"type": "FeatureCollection", "features": features},
                   ensure_ascii=False, indent=2), encoding="utf-8")
