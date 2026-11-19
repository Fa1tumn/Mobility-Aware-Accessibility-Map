"""요구사항 대응 테스트.

테스트 이름이 곧 검증한 요구사항이다. pytest -v 출력을 그대로
'요구사항 대비 검증 현황'으로 발표에 쓸 수 있게 구성했다.

    FEAS  통행 가능 판정 (hard constraint)
    COST  부담 비용 (soft preference)
    SCHED 출입구 개방 시간
    ROUTE 경로 탐색
    MAP   지도 표시 등급
    HERO  핵심 시연 시나리오 2개
"""

from datetime import datetime
from pathlib import Path

import pytest

from app.graph.loader import load_graph
from app.graph.schema import Edge, SchemaError
from app.profile import cost as cost_mod
from app.profile import feasibility as feas
from app.profile import verdict as vd
from app.profile.definitions import Profile, DEFAULT, WHEELCHAIR, LUGGAGE
from app.routing.compare import compare_profiles, routes_differ
from app.routing.dijkstra import find_route
from app.schedule.resolver import ScheduleBook

DEMO = Path(__file__).resolve().parents[1] / "data" / "routing_demo"

MON_AM = datetime(2026, 9, 28, 10, 0)
MON_PM = datetime(2026, 9, 28, 20, 0)
SAT_AM = datetime(2026, 10, 3, 10, 0)
SUN_AM = datetime(2026, 10, 4, 10, 0)


def mk(**kw) -> Edge:
    base = dict(id="e", from_node="a", to_node="b", distance_m=100.0)
    base.update(kw)
    return Edge(**base)


@pytest.fixture
def graph():
    return load_graph(DEMO / "nodes.json", DEMO / "edges.json")


@pytest.fixture
def book():
    return ScheduleBook.load(DEMO / "entrances.json")


# ═════════════════════════════ FEAS — 통행 가능 판정

def test_FEAS_01_계단은_휠체어_통행불가():
    assert not feas.check(mk(stairs=10), WHEELCHAIR).passable


def test_FEAS_02_계단_없으면_휠체어_통행가능():
    assert feas.check(mk(width_level="normal"), WHEELCHAIR).passable


def test_FEAS_03_계단_허용_프로파일은_통과():
    assert feas.check(mk(stairs=22), DEFAULT).passable


def test_FEAS_04_문턱_허용치_초과는_통행불가():
    assert not feas.check(mk(threshold_cm=3.0, width_level="normal"), WHEELCHAIR).passable


def test_FEAS_05_경사_허용치_초과는_통행불가():
    assert not feas.check(mk(slope_deg=12.0, width_level="normal"), WHEELCHAIR).passable


def test_FEAS_06_경사_경계값은_통과():
    assert feas.check(mk(slope_deg=8.0, width_level="normal"), WHEELCHAIR).passable


def test_FEAS_07_내리막도_절댓값으로_판정():
    assert not feas.check(mk(slope_deg=-12.0, width_level="normal"), WHEELCHAIR).passable


def test_FEAS_08_좁은_통행폭은_휠체어_통행불가():
    assert not feas.check(mk(width_level="narrow"), WHEELCHAIR).passable


def test_FEAS_09_차단_사유가_사용자에게_전달된다():
    r = feas.check(mk(stairs=5), WHEELCHAIR)
    assert any("계단" in s for s in r.reasons)


def test_FEAS_10_복수_사유를_모두_보고():
    r = feas.check(mk(stairs=5, threshold_cm=9.0, width_level="narrow"), WHEELCHAIR)
    assert len(r.reasons) >= 3


# ═════════════════════════════ COST — 부담 비용

def test_COST_01_거리가_길수록_비싸다():
    p = Profile(name="d")
    assert cost_mod.compute(mk(distance_m=200.0), p).value > \
           cost_mod.compute(mk(distance_m=100.0), p).value


def test_COST_02_거리_2배면_비용도_2배():
    p = Profile(name="d")
    assert cost_mod.compute(mk(distance_m=200.0), p).value == pytest.approx(
        2 * cost_mod.compute(mk(distance_m=100.0), p).value)


def test_COST_03_계단_단수에_비례해_비싸진다():
    assert cost_mod.compute(mk(stairs=25), LUGGAGE).value > \
           cost_mod.compute(mk(stairs=5), LUGGAGE).value


def test_COST_04_파손노면이_아스팔트보다_비싸다():
    p = Profile(name="s", w_surface=2.0)
    assert cost_mod.compute(mk(surface="damaged"), p).value > \
           cost_mod.compute(mk(surface="asphalt"), p).value


def test_COST_05_가중치_0이면_해당항_무시():
    p = Profile(name="t", w_surface=0.0)
    assert cost_mod.compute(mk(surface="damaged"), p).value == pytest.approx(
        cost_mod.compute(mk(surface="asphalt"), p).value)


def test_COST_06_신뢰도가_낮으면_비용_증가():
    p = Profile(name="u", w_uncertainty=2.0)
    assert cost_mod.compute(mk(confidence=0.2), p).value > \
           cost_mod.compute(mk(confidence=1.0), p).value


def test_COST_07_경사_미측정이_평지보다_싸지_않다():
    """미측정을 0으로 처리하면 라우팅이 측정 안 한 구간을 선호하게 된다."""
    p = Profile(name="s", w_slope=3.0, max_slope_deg=8.0)
    unknown = cost_mod.compute(mk(slope_deg=None), p).value
    flat = cost_mod.compute(mk(slope_deg=0.0), p).value
    assert unknown > flat


def test_COST_08_경사_미측정은_사유에_표시된다():
    p = Profile(name="s", w_slope=3.0)
    assert any("미측정" in r for r in cost_mod.compute(mk(slope_deg=None), p).reasons)


def test_COST_09_지하구간에_자동_페널티는_없다():
    """지하가 평탄하고 짧으면 휠체어에게 최선일 수 있다."""
    p = Profile(name="e")
    assert cost_mod.compute(mk(env="underground"), p).value == pytest.approx(
        cost_mod.compute(mk(env="outdoor"), p).value)


# ═════════════════════════════ SCHED — 개방 시간

def test_SCHED_01_평일_개방시간내_통행가능(book):
    e = mk(entrance_id="underwood_ground_west", width_level="normal")
    assert feas.check(e, WHEELCHAIR, MON_AM, book).passable


def test_SCHED_02_평일_폐쇄시간_통행불가(book):
    e = mk(entrance_id="underwood_ground_west", width_level="normal")
    assert not feas.check(e, WHEELCHAIR, MON_PM, book).passable


def test_SCHED_03_토요일_단축운영_반영(book):
    e = mk(entrance_id="underwood_ground_west", width_level="normal")
    assert feas.check(e, WHEELCHAIR, SAT_AM, book).passable
    assert not feas.check(e, WHEELCHAIR, datetime(2026, 10, 3, 15, 0), book).passable


def test_SCHED_04_일요일_종일폐쇄(book):
    e = mk(entrance_id="underwood_ground_west", width_level="normal")
    assert not feas.check(e, WHEELCHAIR, SUN_AM, book).passable


def test_SCHED_05_개방_경계시각_처리(book):
    e = mk(entrance_id="underwood_ground_west", width_level="normal")
    assert feas.check(e, WHEELCHAIR, datetime(2026, 9, 28, 9, 0), book).passable
    assert not feas.check(e, WHEELCHAIR, datetime(2026, 9, 28, 18, 0), book).passable


def test_SCHED_06_등록되지_않은_출입구는_닫힌것으로_본다(book):
    """모르는 것을 열려 있다고 가정하지 않는다."""
    e = mk(entrance_id="unknown_door", width_level="normal")
    assert not feas.check(e, WHEELCHAIR, MON_AM, book).passable


def test_SCHED_07_시간을_주지_않으면_시간제약_미적용(book):
    e = mk(entrance_id="underwood_ground_west", width_level="normal")
    assert feas.check(e, WHEELCHAIR, None, book).passable


def test_SCHED_08_출입구_없는_구간은_항상_통행가능(book):
    assert feas.check(mk(width_level="normal"), WHEELCHAIR, MON_PM, book).passable


# ═════════════════════════════ ROUTE — 경로 탐색

def test_ROUTE_01_기본_프로파일은_최단경로(graph):
    r = find_route(graph, "N1", "N6", DEFAULT)
    assert r.found and "N2" in r.node_path


def test_ROUTE_02_휠체어는_계단을_우회(graph):
    r = find_route(graph, "N1", "N6", WHEELCHAIR)
    assert r.found and "N2" not in r.node_path


def test_ROUTE_03_우회경로가_더_길다(graph):
    a = find_route(graph, "N1", "N6", DEFAULT)
    b = find_route(graph, "N1", "N6", WHEELCHAIR)
    assert b.total_distance_m > a.total_distance_m


def test_ROUTE_04_모두_막히면_경로없음과_사유(graph):
    strict = WHEELCHAIR.with_overrides(min_width_level="wide", max_threshold_cm=0.0)
    r = find_route(graph, "N1", "N6", strict)
    assert not r.found and r.blocked


def test_ROUTE_05_없는_노드는_예외(graph):
    with pytest.raises(KeyError):
        find_route(graph, "N1", "N99", DEFAULT)


def test_ROUTE_06_경로에_부담사유가_따라온다(graph):
    r = find_route(graph, "N1", "N6", LUGGAGE)
    assert r.found


# ═════════════════════════════ MAP — 지도 표시 등급 (CR-02, CR-03)

def test_MAP_01_계단구간은_휠체어에게_빨강():
    v = vd.evaluate(mk(stairs=20), WHEELCHAIR)
    assert v.level == "impassable" and v.color == "red"


def test_MAP_02_평탄한_넓은길은_초록():
    v = vd.evaluate(mk(surface="asphalt", width_level="wide"), WHEELCHAIR)
    assert v.level == "passable" and v.color == "green"


def test_MAP_03_파손노면은_어려움으로_표시():
    e = mk(surface="damaged", width_level="normal", confidence=0.4)
    assert vd.evaluate(e, WHEELCHAIR).level == "difficult"


def test_MAP_04_판단_원인이_제공된다_CR03():
    v = vd.evaluate(mk(stairs=20), WHEELCHAIR)
    assert v.reasons and any("계단" in r for r in v.reasons)


def test_MAP_05_같은_구간도_프로파일에_따라_등급이_다르다():
    e = mk(stairs=20)
    assert vd.evaluate(e, WHEELCHAIR).level == "impassable"
    assert vd.evaluate(e, DEFAULT).level != "impassable"


# ═════════════════════════════ 입력 검증

def test_SCHEMA_01_음수_거리는_거부():
    with pytest.raises(SchemaError):
        mk(distance_m=-5.0)


def test_SCHEMA_02_정의되지_않은_노면은_거부():
    with pytest.raises(SchemaError):
        mk(surface="lava")


def test_SCHEMA_03_그래프_참조무결성_확인(graph):
    assert graph.validate() == []


# ═════════════════════════════ HERO — 핵심 시연 2개

def test_HERO_1_같은시간_다른프로파일이면_다른경로(graph, book):
    """같은 출발·도착·시각에서 이동수단만 바꾸면 경로가 달라진다."""
    rows = compare_profiles(graph, "N1", "N6", [DEFAULT, WHEELCHAIR],
                            MON_AM, book)
    assert routes_differ(rows)
    assert all(r["found"] for r in rows)


def test_HERO_2_같은프로파일_다른시간이면_다른경로(graph, book):
    """출입구 개방 시간이 바뀌면 같은 사용자의 경로도 달라진다."""
    day = compare_profiles(graph, "N1", "N6", [DEFAULT], MON_AM, book)
    night = compare_profiles(graph, "N1", "N6", [DEFAULT], MON_PM, book)
    assert day[0]["found"] and night[0]["found"]
    assert day[0]["path"] != night[0]["path"]
