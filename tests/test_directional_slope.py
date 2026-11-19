"""오르막·내리막 분리 테스트: 방향별 한도(통행 판정)와 방향별 제곱 비용.

fixtures/routing_mini.geojson은 시험용 합성 graph다(실제 캠퍼스 데이터 아님).

    A ──AB 0%, 40m── B
    │                │ BD +15%, 30m (B→D 오르막)
    AE +3%, 60m      D
    │                │ CD -2%, 30m
    E ──EC 미측정, 40m── C
"""

import math
from pathlib import Path

import pytest

from app.graph.geo import deg_to_pct
from app.graph.loader import load_geojson
from app.graph.schema import Edge
from app.profile import cost as cost_mod
from app.profile import feasibility as feas
from app.profile.definitions import PRESETS, RAMP_LIMIT_PCT, WHEELCHAIR, Profile
from app.routing.dijkstra import find_route

MINI = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "routing_mini.geojson"
PROXY_PCT = deg_to_pct(cost_mod.UNKNOWN_SLOPE_PROXY_DEG)   # 미측정 경사 보수값 약 5.24%


@pytest.fixture
def mini():
    return load_geojson(MINI)


def mk(**kw) -> Edge:
    base = dict(id="e", from_node="a", to_node="b", distance_m=100.0, width_level="normal")
    base.update(kw)
    return Edge(**base)


def slope_part(edge: Edge, profile: Profile) -> float:
    """비용에서 거리 항을 뺀 나머지(이 테스트의 프로필은 경사 외 가중치가 0)."""
    d = edge.distance_m / cost_mod.DISTANCE_UNIT_M
    return cost_mod.compute(edge, profile).value - profile.w_distance * d


# ── 통행 판정: 방향별 한도
def test_DIR_01_방향_한도가_없으면_기존_한도로_폴백():
    for p in PRESETS.values():
        assert p.max_up_pct is None and p.max_down_pct is None
        assert p.uphill_limit_pct == p.max_slope_pct
        assert p.downhill_limit_pct == p.max_slope_pct
        assert not p.uses_directional_slope_cost


def test_DIR_02_오르막과_내리막_한도를_따로_적용():
    p = WHEELCHAIR.with_overrides(max_up_pct=6.0, max_down_pct=10.0)
    assert feas.check(mk(slope_pct=5.9), p).passable
    assert not feas.check(mk(slope_pct=8.0), p).passable      # 오르막 6% 초과
    assert feas.check(mk(slope_pct=-8.0), p).passable         # 내리막 10% 이내
    assert not feas.check(mk(slope_pct=-11.0), p).passable


def test_DIR_03_차단_사유에_방향과_그_방향_한도가_나온다():
    p = WHEELCHAIR.with_overrides(max_up_pct=6.0, max_down_pct=10.0)
    assert feas.check(mk(slope_pct=8.0), p).reasons == ["오르막 경사 8.0% > 허용 6.0%"]
    assert feas.check(mk(slope_pct=-11.0), p).reasons == ["내리막 경사 11.0% > 허용 10.0%"]


def test_DIR_04_오르막_한도만_낮으면_갈_때는_우회_올_때는_통과(mini):
    p = Profile(name="up_limited", max_up_pct=10.0, max_down_pct=20.0)
    go = find_route(mini, "A", "D", p)
    back = find_route(mini, "D", "A", p)
    assert go.node_path == ["A", "E", "C", "D"]
    assert any("오르막 경사 15.0% > 허용 10.0%" in b for b in go.blocked)
    assert back.node_path == ["D", "B", "A"]                 # D→B는 15% 내리막, 한도 20%


# ── 비용: 기존 동작 유지
def test_DIR_05_방향_가중치가_없으면_기존_선형_비용_그대로():
    p = Profile(name="linear", max_slope_deg=8.0, w_slope=1.0)
    for pct in (-10.0, -2.0, 0.0, 4.0, 10.0):
        e = mk(slope_pct=pct)
        expected = 1.0 + 1.0 * e.abs_slope_deg / 8.0          # 100m, w_distance 1
        assert cost_mod.compute(e, p).value == pytest.approx(expected)
    unknown = cost_mod.compute(mk(), p).value
    assert unknown == pytest.approx(1.0 + cost_mod.UNKNOWN_SLOPE_PROXY_DEG / 8.0)


def test_DIR_06_방향_가중치가_있으면_w_slope는_쓰지_않는다():
    p = Profile(name="dir", w_slope=100.0, w_up=0.0, w_down=0.0)
    assert cost_mod.compute(mk(slope_pct=10.0), p).value == pytest.approx(1.0)


# ── 비용: 오르막·내리막 제곱
def test_DIR_07_경사_비용은_제곱으로_커지고_한도에서_가중치와_같다():
    p = Profile(name="quad", max_up_pct=10.0, max_down_pct=10.0, w_up=2.0, w_down=1.0)
    assert slope_part(mk(slope_pct=8.0), p) == pytest.approx(4 * slope_part(mk(slope_pct=4.0), p))
    assert slope_part(mk(slope_pct=10.0), p) == pytest.approx(2.0)     # 100m, 한도에서 w_up
    assert slope_part(mk(slope_pct=-10.0), p) == pytest.approx(1.0)    # 100m, 한도에서 w_down
    assert slope_part(mk(slope_pct=0.0), p) == 0.0
    # 한도가 없으면(무한대) 법규 참고값 1/12를 기준으로 쓴다.
    free = Profile(name="free", w_up=1.0)
    assert slope_part(mk(slope_pct=RAMP_LIMIT_PCT), free) == pytest.approx(1.0)


def test_DIR_08_미측정_경사는_완만한_실측보다_싸지_않다():
    p = Profile(name="dir", max_up_pct=10.0, max_down_pct=10.0, w_up=2.0, w_down=1.0)
    unknown = cost_mod.compute(mk(), p)
    assert "경사 미측정" in unknown.reasons
    up = slope_part(mk(slope_pct=PROXY_PCT), p)
    down = slope_part(mk(slope_pct=-PROXY_PCT), p)
    assert slope_part(mk(), p) == pytest.approx(max(up, down))
    for pct in (-3.0, -1.0, 0.0, 1.0, 3.0):
        assert unknown.value > cost_mod.compute(mk(slope_pct=pct), p).value
    # 한쪽 가중치만 있어도 미측정은 0이 아니다.
    up_only = Profile(name="up_only", w_up=1.0)
    assert slope_part(mk(), up_only) > 0.0


def test_DIR_09_오르막만_부담이면_갈_때와_올_때_경로가_다르다(mini):
    p = Profile(name="uphill_averse", max_up_pct=20.0, max_down_pct=20.0, w_up=10.0, w_down=0.0)
    go = find_route(mini, "A", "D", p)
    back = find_route(mini, "D", "A", p)
    assert go.node_path == ["A", "E", "C", "D"]              # 15% 오르막 회피
    assert back.node_path == ["D", "B", "A"]                 # 같은 길이 내리막이면 짧은 길
    assert not go.blocked and not back.blocked               # 판정이 아니라 비용으로 갈림


def test_DIR_10_비용_사유는_진행_방향으로_표시(mini):
    p = Profile(name="dir", max_up_pct=20.0, max_down_pct=20.0, w_up=1.0, w_down=1.0)
    assert "내리막 7.0%" in cost_mod.compute(mk(slope_pct=-7.0), p).reasons
    assert "오르막 5.0%" in cost_mod.compute(mk(slope_pct=5.0), p).reasons
    assert not cost_mod.compute(mk(slope_pct=3.0), p).reasons
    back = find_route(mini, "D", "A", p.with_overrides(w_up=10.0, w_down=0.0))
    assert any("D→B" in r and "내리막 15.0%" in r for r in back.reasons)


@pytest.mark.parametrize("kw", [
    {"max_up_pct": 0.0},
    {"max_up_pct": -5.0},
    {"max_down_pct": math.nan},
    {"max_down_pct": math.inf},
    {"w_up": -0.1},
    {"w_down": math.nan},
])
def test_DIR_11_잘못된_한도와_가중치는_거부(kw):
    with pytest.raises(ValueError):
        Profile(name="bad", **kw)
    with pytest.raises(ValueError):
        WHEELCHAIR.with_overrides(**kw)
