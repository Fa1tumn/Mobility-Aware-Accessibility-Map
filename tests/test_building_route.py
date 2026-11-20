"""건물 간 경로 테스트: 출입구 여러 개, 운영 시간, 방향별 경사.

fixtures/routing_buildings.geojson (시험용 합성 graph)

    E1 공학관
    │ 40m
    S1 ──40m── J1 ──60m── J2 ──10m 계단 6단── L1 도서관 지상 계단 입구
    학생회관     │           └─25m J2→L2 +7% (lib_ground_stepfree)── L2 도서관 지상 계단 없는 문
               30m J1→U1 -10%
               U1 지하 광장 ──80m 지하 통로 (lib_underground)── L3 도서관 지하 입구

운영 시간(fixtures/schedule_buildings.json): L2 학기 09-18·방학 닫힘, L3 학기 평일 08:30-24, 방학 평일 09-17
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.events.overlay import EventOverlay
from app.events.store import EventStore
from app.graph.buildings import load_buildings
from app.graph.loader import load_geojson
from app.graph.schema import SchemaError
from app.profile.definitions import DEFAULT, LUGGAGE, RAMP_LIMIT_PCT, WHEELCHAIR
from app.routing.buildings import all_building_routes, building_route, format_building_route
from app.schedule.resolver import ScheduleBook

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
GRAPH = FIX / "routing_buildings.geojson"
BUILDINGS = FIX / "buildings_mini.json"
SCHEDULE = FIX / "schedule_buildings.json"

SEM_14 = datetime(2026, 11, 20, 14, 0)     # 학기 중 금요일 오후
SEM_19 = datetime(2026, 11, 20, 19, 0)     # 학기 중 금요일 저녁
VAC_10 = datetime(2027, 1, 4, 10, 0)       # 방학 중 월요일 오전
VAC_18 = datetime(2027, 1, 4, 18, 0)       # 방학 중 월요일 저녁
STRICT = WHEELCHAIR.with_overrides(name="wheelchair_strict", max_up_pct=RAMP_LIMIT_PCT, max_down_pct=14.0)


@pytest.fixture
def g():
    return load_geojson(GRAPH)


@pytest.fixture
def bb(g):
    return load_buildings(BUILDINGS, g)


@pytest.fixture
def book():
    return ScheduleBook.load(SCHEDULE)


def route(g, bb, book, a, b, profile, when):
    return building_route(g, bb, a, b, profile, when, book)


# ── 건물 파일
def test_BLD_01_건물을_읽고_대표_좌표를_출입구_평균으로(g, bb):
    assert [b.id for b in bb] == ["student_hall", "library", "engineering"]
    assert bb["library"].entrances == ["L1", "L2", "L3"]
    lon, lat = bb["library"].point
    assert lon == pytest.approx(sum(g.nodes[n].lon for n in ("L1", "L2", "L3")) / 3)


@pytest.mark.parametrize("change, message", [
    (lambda d: d["buildings"][0].update(entrances=["NOPE"]), "graph에 없다"),
    (lambda d: d["buildings"][2].update(entrances=["L1"]), "두 건물"),
    (lambda d: d["buildings"][0].update(entrances=[]), "하나 이상"),
    (lambda d: d["buildings"][0].update(colour="red"), "정의되지 않은 속성"),
    (lambda d: d["buildings"].append(dict(d["buildings"][0])), "중복"),
])
def test_BLD_02_잘못된_건물_파일은_거부(g, tmp_path, change, message):
    data = json.loads(BUILDINGS.read_text(encoding="utf-8"))
    change(data)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SchemaError, match=message):
        load_buildings(bad, g)


# ── 출입구 선택
def test_ROUTE_B01_일반은_가까운_계단_입구(g, bb, book):
    rec = route(g, bb, book, "student_hall", "library", DEFAULT, SEM_14).recommended
    assert rec.path == ["S1", "J1", "J2", "L1"] and rec.is_shortest


def test_ROUTE_B02_휠체어는_계단_없는_문으로_가고_이유가_붙는다(g, bb, book):
    br = route(g, bb, book, "student_hall", "library", WHEELCHAIR, SEM_14)
    assert (br.recommended.from_entrance, br.recommended.to_entrance) == ("S1", "L2")
    assert "계단 6단 회피" in br.recommended.why
    assert br.entrance_notes == ["도서관 지상 계단 입구: J2→L1: 계단 6단"]


def test_ROUTE_B03_지상문이_닫히는_18시_이후는_지하로(g, bb, book):
    br = route(g, bb, book, "student_hall", "library", WHEELCHAIR, SEM_19)
    assert br.recommended.to_entrance == "L3"
    assert any("계단 없는 문" in n and "지금 19:00 닫힘" in n for n in br.entrance_notes)


def test_ROUTE_B04_방학에는_지상문이_닫혀_지하로(g, bb, book):
    br = route(g, bb, book, "student_hall", "library", WHEELCHAIR, VAC_10)
    assert br.recommended.to_entrance == "L3"
    assert any("방학 중 월요일 닫힘" in n for n in br.entrance_notes)


def test_ROUTE_B05_모든_입구가_닫히면_경로없음과_이유(g, bb, book):
    br = route(g, bb, book, "student_hall", "library", WHEELCHAIR, VAC_18)
    assert not br.found
    assert len(br.entrance_notes) == 3
    assert "통행 가능한 경로 없음" in format_building_route(g, br)


def test_ROUTE_B06_같은_건물_쌍도_방향에_따라_결과가_다르다(g, bb, book):
    go = route(g, bb, book, "student_hall", "library", STRICT, SEM_19)
    back = route(g, bb, book, "library", "student_hall", STRICT, SEM_19)
    assert go.recommended.to_entrance == "L3"            # J1→U1 10% 내리막은 한도 14% 안
    assert not back.found                                # U1→J1 10% 오르막은 한도 8.33% 초과
    assert any("U1→J1: 오르막 경사 10.0%" in b for b in back.blocked)


def test_ROUTE_B07_가상_노드는_결과에_남지_않는다(g, bb, book):
    br = route(g, bb, book, "engineering", "library", LUGGAGE, SEM_14)
    for o in br.options:
        assert all(not n.startswith("@") for n in o.path)
        assert all(not e.base_id.startswith("@") and "@" not in e.base_id for e in o.result.edges)
        assert o.metrics.distance_m == pytest.approx(o.result.total_distance_m)


def test_ROUTE_B08_대안은_30퍼센트_규칙을_지킨다(g, bb, book):
    br = route(g, bb, book, "student_hall", "library", WHEELCHAIR, SEM_14)
    rec = br.recommended.result.total_cost
    for o in br.options:
        if o.label.startswith("대안"):
            assert o.result.total_cost <= rec * 1.3 + 1e-9


def test_ROUTE_B09_이벤트로_막히면_다른_입구(g, bb, book, tmp_path):
    store = EventStore(tmp_path / "e.json")
    store.add("construction", "J2L2", SEM_14 - timedelta(minutes=5))
    ov = EventOverlay.from_store(store, SEM_14)
    br = building_route(g, bb, "student_hall", "library", WHEELCHAIR, SEM_14, book, ov)
    assert br.recommended.to_entrance == "L3"
    assert any("공사·통제 E001" in n for n in br.entrance_notes)


def test_ROUTE_B10_같은_건물은_거부(g, bb, book):
    with pytest.raises(ValueError):
        route(g, bb, book, "library", "library", DEFAULT, SEM_14)


def test_ROUTE_B11_모든_건물_쌍을_방향별로(g, bb, book):
    res = all_building_routes(g, bb, [DEFAULT, WHEELCHAIR], SEM_14, book)
    assert len(res) == 2 * 3 * 2                          # 프로필 2 × 순서 있는 쌍 6
    assert ("wheelchair", "library", "student_hall") in res


# ── 명령줄
def test_CLI_B01_건물_간_경로를_파일로(tmp_path):
    out = tmp_path / "b.geojson"
    done = subprocess.run(
        [sys.executable, "-m", "scripts.building_route", "--graph", str(GRAPH),
         "--buildings", str(BUILDINGS), "--schedule", str(SCHEDULE),
         "--from", "student_hall", "--to", "library", "--profile", "wheelchair",
         "--when", "2026-11-20T19:00", "--out", str(out)],
        cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    props = json.loads(out.read_text(encoding="utf-8"))["properties"]
    assert props["to_entrance"] == "L3" and props["origin_building"] == "student_hall"
    assert props["node_path"] == ["S1", "J1", "U1", "L3"]


def test_CLI_B02_건물_목록():
    done = subprocess.run(
        [sys.executable, "-m", "scripts.building_route", "--graph", str(GRAPH),
         "--buildings", str(BUILDINGS), "--list"], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0 and "library" in done.stdout and "L3(도서관 지하 입구)" in done.stdout
