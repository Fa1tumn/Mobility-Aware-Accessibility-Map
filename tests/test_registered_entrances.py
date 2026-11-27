"""웹앱 등록 출입구를 graph에 붙이는 규칙.

- 미확인은 0이나 가정값으로 바꾸지 않는다 → graph에 넣지 않고 needs_survey
- 보행로 연결은 확인 파일에 적힌 노드와만 → 그 전에는 후보만, needs_link
"""

import json

from app.graph.buildings import load_buildings, save_buildings
from app.graph.loader import load_geojson, save_geojson
from app.graph.registered_entrances import attach_entrances, missing_items, node_id_for
from app.graph.schema import Edge, Graph, Node
from app.map.campus_grid import load_campus_grid
from app.profile.definitions import DEFAULT, WHEELCHAIR
from app.routing.dijkstra import find_route
from scripts.build_entrance_buildings import convert
from scripts.import_entrances import main as import_main

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


def test_candidates_only_until_link_is_confirmed():
    g = walkway()
    _, reviews = attach_entrances(g, [record("11111111-aaaa", 38, 6)])
    r = reviews[0]
    assert r.status == "needs_link"
    assert [c["node_id"] for c in r.candidates] == ["B", "A"][:len(r.candidates)]
    assert r.candidates[0]["node_id"] == "B" and 5 < r.candidates[0]["distance_m"] < 8
    assert r.node_id not in g.nodes and r.node_id not in g.edges


def test_confirmed_link_attaches_with_measured_values():
    g = walkway()
    rec = record("22222222", 38, 6, stairs="yes", stairs_count=6, threshold="yes", threshold_cm=1.5, ramp="yes")
    book, reviews = attach_entrances(g, [rec], links={"22222222": "B"})
    r = reviews[0]
    edge = g.edges[r.node_id]
    assert r.status == "attached"
    assert (edge.to_node, edge.stairs, edge.threshold_cm, edge.ramp) == ("B", 6, 1.5, True)
    assert g.nodes[r.node_id].kind == "entrance"
    assert book["osm_way_1"].entrances == [r.node_id]
    assert g.validate() == []


def test_link_can_use_entrance_node_id():
    g = walkway()
    _, reviews = attach_entrances(g, [record("33333333", 38, 6)], links={node_id_for("33333333"): "B"})
    assert reviews[0].status == "attached"


def test_unknown_values_are_not_replaced():
    g = walkway()
    rec = record("44444444", 38, 6, stairs="unknown", threshold="unknown", ramp="unknown")
    _, reviews = attach_entrances(g, [rec], links={"44444444": "B"})
    r = reviews[0]
    assert r.status == "needs_survey"
    assert r.missing == ["계단", "문턱", "경사로"]
    assert r.node_id not in g.nodes
    assert r.candidates                                  # 후보는 그대로 보여준다


def test_yes_without_measurement_is_missing_not_assumed():
    assert missing_items(record("x", 0, 0, stairs="yes")) == ["계단 단수"]
    assert missing_items(record("x", 0, 0, threshold="yes")) == ["문턱 높이"]
    assert missing_items(record("x", 0, 0, threshold="yes", threshold_cm=0)) == ["문턱 높이"]
    assert missing_items(record("x", 0, 0)) == []


def test_no_candidate_beyond_radius():
    g = walkway()
    _, reviews = attach_entrances(g, [record("55555555", 20, 60)])
    assert reviews[0].candidates == []
    assert "보행로 노드 없음" in reviews[0].reason


def test_unknown_link_node_is_invalid():
    g = walkway()
    _, reviews = attach_entrances(g, [record("66666666", 38, 6)], links={"66666666": "Z"})
    assert reviews[0].status == "invalid" and "Z" in reviews[0].reason


def test_wheelchair_avoids_stair_entrance_once_attached():
    g = walkway()
    rows = [record("77777777-stairs", 2, 6, stairs="yes", stairs_count=5),
            record("88888888-flat", 38, 6)]
    _, reviews = attach_entrances(g, rows, links={"77777777-stairs": "A", "88888888-flat": "B"})
    stair_node, flat_node = (r.node_id for r in reviews)
    assert find_route(g, "A", stair_node, DEFAULT).found
    assert not find_route(g, "A", stair_node, WHEELCHAIR).found
    assert find_route(g, "A", flat_node, WHEELCHAIR).found


def test_same_record_twice_is_not_duplicated():
    g = walkway()
    rows, links = [record("99999999", 38, 6)], {"99999999": "B"}
    attach_entrances(g, rows, links)
    _, reviews = attach_entrances(g, rows, links)
    assert reviews[0].reason == "이미 붙어 있음" and len(g.edges) == 2


def test_outputs_reload_with_existing_loaders(tmp_path):
    g = walkway()
    book, _ = attach_entrances(g, [record("12121212", 38, 6, entrance_name="정문")], links={"12121212": "B"})
    save_geojson(g, tmp_path / "g.geojson")
    save_buildings(book, tmp_path / "b.json")
    g2 = load_geojson(tmp_path / "g.geojson")
    assert load_buildings(tmp_path / "b.json", g2)["osm_way_1"].entrances == book["osm_way_1"].entrances


def test_import_script_writes_review_and_skips_graph_without_confirmation(tmp_path, capsys):
    g = walkway()
    save_geojson(g, tmp_path / "g.geojson")
    (tmp_path / "rec.json").write_text(json.dumps([record("abcdef12", 38, 6, threshold="unknown")]), encoding="utf-8")
    code = import_main(["--input", str(tmp_path / "rec.json"), "--graph", str(tmp_path / "g.geojson"),
                        "--links", str(tmp_path / "none.json"), "--review", str(tmp_path / "review.json"),
                        "--out-graph", str(tmp_path / "out.geojson"), "--out-buildings", str(tmp_path / "b.json")])
    assert code == 0
    review = json.loads((tmp_path / "review.json").read_text(encoding="utf-8"))
    assert review[0]["status"] == "needs_survey" and review[0]["missing"] == ["문턱"]
    assert review[0]["candidates"][0]["node_id"] == "B"
    assert not (tmp_path / "out.geojson").exists()
    assert "현장 보완 필요" in capsys.readouterr().out


def test_campus_building_list_keeps_only_buildings_inside_campus():
    campus = load_campus_grid()
    inside = campus.to_geographic(100, 100)

    def way(i, lat, lon, name):
        d = 0.0001
        return {"type": "way", "id": i, "tags": {"building": "yes", "name": name},
                "geometry": [{"lat": lat, "lon": lon}, {"lat": lat + d, "lon": lon}, {"lat": lat + d, "lon": lon + d}]}

    out = convert({"elements": [way(1, *inside, "진리관 A"), way(2, 37.40, 126.70, "캠퍼스 밖")]}, campus)
    assert [b["name"] for b in out] == ["진리관 A"]
    assert out[0]["id"] == "osm_way_1" and len(out[0]["outline"]) == 3


def test_building_list_names_margin_and_apartment_filter():
    campus = load_campus_grid()

    def way(i, down, across, name=""):
        lat, lon = campus.to_geographic(down, across)
        d = 0.00005
        tags = {"building": "yes"} | ({"name": name} if name else {})
        return {"type": "way", "id": i, "tags": tags,
                "geometry": [{"lat": lat, "lon": lon}, {"lat": lat + d, "lon": lon}, {"lat": lat, "lon": lon + d}]}

    osm = {"elements": [way(1, 50, 50), way(2, -40, 50), way(3, -40, 60, "212"), way(4, -200, 50)]}
    out = {b["id"]: b for b in convert(osm, campus, names={"1": "자유관"})}
    assert out["osm_way_1"]["name"] == "자유관" and out["osm_way_1"]["named"]
    assert "osm_way_2" in out and not out["osm_way_2"]["named"]       # 가장자리 60m 안
    assert "osm_way_3" not in out                                      # 숫자 이름(아파트 동)
    assert "osm_way_4" not in out                                      # 200m 밖


def test_building_relation_is_included_and_deduplicated():
    campus = load_campus_grid()
    lat, lon = campus.to_geographic(80, 80)
    ring = [{"lat": lat, "lon": lon}, {"lat": lat + 0.0001, "lon": lon}, {"lat": lat, "lon": lon + 0.0001}]
    rel = {"type": "relation", "id": 9, "tags": {"building": "dormitory", "name": "송도학사 F"},
           "members": [{"type": "way", "role": "outer", "geometry": ring}]}
    dup = {"type": "relation", "id": 10, "tags": {"building": "yes", "name": "자유관 A"},
           "members": [{"type": "way", "role": "outer", "geometry": ring}]}
    way = {"type": "way", "id": 5, "tags": {"building": "yes"}, "geometry": ring}
    out = convert({"elements": [rel, dup, way]}, campus, names={"5": "자유관 A"})
    assert {b["id"]: b["name"] for b in out} == {"osm_relation_9": "송도학사 F", "osm_way_5": "자유관 A"}
