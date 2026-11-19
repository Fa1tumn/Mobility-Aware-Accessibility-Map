"""좌표 graph, 경사 %, 경로 GeoJSON 테스트.

fixtures/routing_mini.geojson은 시험용 합성 graph다(실제 캠퍼스 데이터 아님).

    A ──AB 0%── B
    │           │ BD +15% (B→D 오르막, 휠체어 기본 한도 약 14.1% 초과)
    AE +3%      D
    │           │ CD -2%
    E ──EC 미측정── C
"""

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from app.graph.geo import deg_to_pct, haversine_m, pct_to_deg
from app.graph.loader import load_geojson, save_geojson
from app.graph.schema import Edge, SchemaError
from app.profile import feasibility as feas
from app.profile.definitions import DEFAULT, RAMP_LIMIT_PCT, WHEELCHAIR
from app.routing.dijkstra import find_route
from app.routing.geojson import route_to_geojson

ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "tests" / "fixtures" / "routing_mini.geojson"


@pytest.fixture
def mini():
    return load_geojson(MINI)


def mk(**kw) -> Edge:
    base = dict(id="e", from_node="a", to_node="b", distance_m=100.0, width_level="normal")
    base.update(kw)
    return Edge(**base)


# ── 단위
def test_UNIT_01_경사율과_각도_변환():
    assert math.isclose(pct_to_deg(100.0), 45.0)
    assert math.isclose(deg_to_pct(pct_to_deg(8.33)), 8.33)


def test_UNIT_02_slope_pct만_주면_각도가_채워진다():
    e = mk(slope_pct=10.0)
    assert math.isclose(e.slope_deg, pct_to_deg(10.0))


def test_UNIT_03_slope_deg만_주면_경사율이_채워진다():
    e = mk(slope_deg=4.0)
    assert math.isclose(e.slope_pct, deg_to_pct(4.0))


def test_UNIT_04_서로_다른_경사값은_거부():
    with pytest.raises(SchemaError):
        mk(slope_pct=10.0, slope_deg=10.0)


# ── 휠체어 경사 한도
def test_LIMIT_01_기본_한도는_9월값_8도_약14퍼센트():
    assert WHEELCHAIR.max_slope_pct == pytest.approx(deg_to_pct(8.0))


def test_LIMIT_02_경사로_기준_1_12로_바꾸면_경계가_8_33퍼센트():
    strict = WHEELCHAIR.with_overrides(max_slope_pct=RAMP_LIMIT_PCT)
    assert feas.check(mk(slope_pct=8.3), strict).passable
    assert not feas.check(mk(slope_pct=8.5), strict).passable


def test_LIMIT_03_차단_사유는_퍼센트로_표시():
    reasons = feas.check(mk(slope_pct=-15.0), WHEELCHAIR).reasons
    assert any("내리막" in r and "%" in r for r in reasons)


def test_LIMIT_04_프로필_한도를_퍼센트로_바꿀_수_있다():
    relaxed = WHEELCHAIR.with_overrides(max_slope_pct=20.0)
    assert feas.check(mk(slope_pct=15.0), relaxed).passable


# ── GeoJSON graph
def test_GEO_01_노드와_간선을_읽는다(mini):
    assert set(mini.nodes) == {"A", "B", "C", "D", "E"}
    assert set(mini.edges) == {"AB", "BD", "AE", "EC", "CD"}


def test_GEO_02_거리를_좌표로_계산한다(mini):
    assert abs(mini.edges["AB"].distance_m - 40.0) < 0.5
    assert abs(mini.edges["AE"].distance_m - 60.0) < 0.5


def test_GEO_03_미측정_경사는_None으로_남는다(mini):
    assert mini.edges["EC"].slope_pct is None


def test_GEO_04_역방향은_경사_부호와_geometry가_뒤집힌다(mini):
    rev = next(e for e in mini.outgoing("D") if e.base_id == "BD")
    assert rev.is_reverse and rev.slope_pct == -15.0
    assert rev.geometry[0] == mini.edges["BD"].geometry[-1]


def test_GEO_05_끝점이_노드에서_멀면_거부(tmp_path):
    data = json.loads(MINI.read_text(encoding="utf-8"))
    for feature in data["features"]:
        if feature["properties"].get("id") == "AB":
            feature["geometry"]["coordinates"][0][1] += 0.0003   # 약 33m 북쪽
    bad = tmp_path / "bad.geojson"
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SchemaError, match="떨어져"):
        load_geojson(bad)


def test_GEO_06_정의되지_않은_속성은_거부(tmp_path):
    data = json.loads(MINI.read_text(encoding="utf-8"))
    data["features"][0]["properties"]["colour"] = "red"
    bad = tmp_path / "bad.geojson"
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SchemaError, match="정의되지 않은 속성"):
        load_geojson(bad)


def test_GEO_07_저장했다_다시_읽어도_같다(mini, tmp_path):
    out = tmp_path / "round.geojson"
    save_geojson(mini, out)
    again = load_geojson(out)
    assert set(again.edges) == set(mini.edges)
    assert again.edges["BD"].slope_pct == 15.0


# ── 경로
def test_NAV_01_일반은_짧은_길(mini):
    r = find_route(mini, "A", "D", DEFAULT)
    assert r.node_path == ["A", "B", "D"]


def test_NAV_02_휠체어는_한도_초과_오르막을_우회(mini):
    r = find_route(mini, "A", "D", WHEELCHAIR)
    assert r.node_path == ["A", "E", "C", "D"]
    assert any("15.0%" in b for b in r.blocked)


def test_NAV_03_반대_방향_내리막도_휠체어는_우회(mini):
    r = find_route(mini, "D", "A", WHEELCHAIR)
    assert r.node_path == ["D", "C", "E", "A"]


def test_NAV_04_경로_GeoJSON에_요약과_구간이_담긴다(mini):
    r = find_route(mini, "A", "D", WHEELCHAIR)
    fc = route_to_geojson(mini, r, WHEELCHAIR, "A", "D")
    summary = fc["properties"]
    assert len(fc["features"]) == 3
    assert summary["unknown_slope_m"] == pytest.approx(40.0, abs=0.5)
    assert summary["max_uphill_pct"] == 3.0 and summary["max_downhill_pct"] == 2.0
    first = fc["features"][0]["geometry"]["coordinates"][0]
    a = mini.nodes["A"]
    assert haversine_m(first[0], first[1], a.lon, a.lat) < 0.5


def test_NAV_05_역방향_구간은_원래_간선_ID를_남긴다(mini):
    r = find_route(mini, "D", "A", WHEELCHAIR)
    fc = route_to_geojson(mini, r, WHEELCHAIR, "D", "A")
    first = fc["features"][0]["properties"]
    assert first["edge_id"] == "CD" and first["reverse"] is True and first["slope_pct"] == 2.0


def test_NAV_06_명령줄로_경로_파일을_만든다(tmp_path):
    out = tmp_path / "route.geojson"
    done = subprocess.run(
        [sys.executable, "-m", "scripts.route", "--graph", str(MINI),
         "--from", "A", "--to", "D", "--profile", "wheelchair", "--out", str(out)],
        cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    fc = json.loads(out.read_text(encoding="utf-8"))
    assert fc["properties"]["node_path"] == ["A", "E", "C", "D"]


def test_NAV_07_모든_프로필_비교는_프로필별_파일을_만든다(tmp_path):
    out = tmp_path / "route.geojson"
    done = subprocess.run(
        [sys.executable, "-m", "scripts.route", "--graph", str(MINI),
         "--from", "A", "--to", "D", "--profile", "all", "--out", str(out)],
        cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert {p.name for p in tmp_path.glob("route_*.geojson")} == {
        "route_default.geojson", "route_wheelchair.geojson", "route_luggage.geojson"}
