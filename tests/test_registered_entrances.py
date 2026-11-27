"""웹앱 등록 출입구를 graph에 붙이는 규칙."""

import json

import pytest

from app.graph.buildings import load_buildings, save_buildings
from app.graph.loader import load_geojson, save_geojson
from app.graph.registered_entrances import ASSUMED_THRESHOLD_CM, attach_entrances
from app.graph.schema import Edge, Graph, Node
from app.map.campus_grid import load_campus_grid
from app.profile.definitions import DEFAULT, WHEELCHAIR
from app.routing.dijkstra import find_route
from scripts.build_entrance_buildings import convert

LAT, LON = 37.3825, 126.6705
DLAT = 1 / 111_000          # 약 1m
DLON = 1 / 88_400           # 약 1m (위도 37.38도)


def walkway() -> Graph:
    """A(서) — B(동) 40m 보행로. 건물은 B 북쪽에 있다."""
    g = Graph()
    g.add_node(Node(id="A", lat=LAT, lon=LON))
    g.add_node(Node(id="B", lat=LAT, lon=LON + 40 * DLON))
    g.add_edge(Edge(id="AB", from_node="A", to_node="B", distance_m=40, slope_pct=0, width_level="normal",
                    geometry=[[LON, LAT], [LON + 40 * DLON, LAT]]))
    return g


def record(rid, dx_m, dy_m, **kw):
    row = {"id": rid, "recorded_at": "2026-11-21T10:00:00Z", "building_id": "osm_way_1", "building_name": "진리관 B",
           "pin_lat": LAT + dy_m * DLAT, "pin_lon": LON + dx_m * DLON,
           "stairs": "no", "ramp": "no", "threshold": "no", "door_type": "automatic"}
    row.update(kw)
    return row


def test_entrance_node_connects_to_nearest_walkway_node():
    g = walkway()
    book, report = attach_entrances(g, [record("11111111-aaaa", 38, 6)])
    node_id = report.added[0]
    edge = g.edges[node_id]
    assert g.nodes[node_id].kind == "entrance"
    assert edge.to_node == "B"
    assert 5 < edge.distance_m < 8
    assert book["osm_way_1"].entrances == [node_id]
    assert g.validate() == []


def test_far_pin_is_skipped_not_forced():
    g = walkway()
    _, report = attach_entrances(g, [record("22222222", 20, 60)])
    assert report.added == []
    assert "가까운 보행로" in report.skipped[0][1]


def test_unknown_stays_unknown_with_lower_confidence():
    g = walkway()
    _, report = attach_entrances(g, [record("33333333", 38, 6, stairs="unknown", threshold="unknown", ramp="unknown")])
    edge = g.edges[report.added[0]]
    assert edge.stairs == 0 and edge.threshold_cm == 0
    assert edge.confidence < 0.5
    assert "미확인: 계단, 문턱, 경사로" in edge.note


def test_threshold_without_height_uses_conservative_value():
    g = walkway()
    _, report = attach_entrances(g, [record("44444444", 38, 6, threshold="yes")])
    edge = g.edges[report.added[0]]
    assert edge.threshold_cm == ASSUMED_THRESHOLD_CM > WHEELCHAIR.max_threshold_cm
    assert "문턱 높이" in edge.note


def test_measured_values_are_used():
    g = walkway()
    _, report = attach_entrances(g, [record("55555555", 38, 6, stairs="yes", stairs_count=6, threshold="yes", threshold_cm=1.5, ramp="yes")])
    edge = g.edges[report.added[0]]
    assert (edge.stairs, edge.threshold_cm, edge.ramp) == (6, 1.5, True)
    assert edge.confidence == 1.0


def test_wheelchair_avoids_stair_entrance_default_takes_shorter():
    g = walkway()
    rows = [record("66666666-stairs", 2, 6, stairs="yes", stairs_count=5),   # A 옆, 계단
            record("77777777-flat", 38, 6)]                                    # B 옆, 계단 없음
    _, report = attach_entrances(g, rows)
    stair_node, flat_node = report.added
    assert find_route(g, "A", stair_node, DEFAULT).found
    assert not find_route(g, "A", stair_node, WHEELCHAIR).found
    assert find_route(g, "A", flat_node, WHEELCHAIR).found


def test_same_record_twice_is_not_duplicated():
    g = walkway()
    rows = [record("88888888", 38, 6)]
    attach_entrances(g, rows)
    _, report = attach_entrances(g, rows)
    assert report.added == [] and report.skipped[0][1] == "이미 붙어 있음"


def test_building_without_id_groups_by_name():
    g = walkway()
    rows = [record("99999999-1", 38, 6, building_id=None, building_name="새 건물"),
            record("99999999-2", 37, 7, building_id=None, building_name="새 건물")]
    book, report = attach_entrances(g, rows)
    assert len(book) == 1 and book["새_건물"].entrances == report.added


def test_outputs_reload_with_existing_loaders(tmp_path):
    g = walkway()
    book, _ = attach_entrances(g, [record("12121212", 38, 6, entrance_name="정문")])
    save_geojson(g, tmp_path / "g.geojson")
    save_buildings(book, tmp_path / "b.json")
    g2 = load_geojson(tmp_path / "g.geojson")
    book2 = load_buildings(tmp_path / "b.json", g2)
    assert book2["osm_way_1"].entrances == book["osm_way_1"].entrances


def test_campus_building_list_keeps_only_buildings_inside_campus():
    campus = load_campus_grid()
    inside = campus.to_geographic(100, 100)
    def way(i, lat, lon, name):
        d = 0.0001
        return {"type": "way", "id": i, "tags": {"building": "yes", "name": name},
                "geometry": [{"lat": lat, "lon": lon}, {"lat": lat + d, "lon": lon}, {"lat": lat + d, "lon": lon + d}]}
    osm = {"elements": [way(1, *inside, "진리관 A"), way(2, 37.40, 126.70, "캠퍼스 밖")]}
    out = convert(osm, campus)
    assert [b["name"] for b in out] == ["진리관 A"]
    assert out[0]["id"] == "osm_way_1" and len(out[0]["outline"]) == 3
