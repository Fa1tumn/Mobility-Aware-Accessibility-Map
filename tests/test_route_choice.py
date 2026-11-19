"""경로 선택지(추천·최단·대안)와 선택 이유 테스트.

fixtures/routing_mini.geojson은 시험용 합성 graph다(실제 캠퍼스 데이터 아님).

    A ──AB 0%, 40m── B
    │                │ BD +15%, 30m (B→D 오르막, 휠체어 기본 한도 약 14.1% 초과)
    AE +3%, 60m      D
    │                │ CD -2%, 30m
    E ──EC 미측정, 40m── C
"""

import subprocess
import sys
from pathlib import Path

import pytest

from app.graph.loader import load_geojson
from app.profile.definitions import DEFAULT, WHEELCHAIR
from app.routing.alternatives import format_options, route_options
from app.routing.dijkstra import find_route
from app.routing.evaluate import evaluate_path
from app.routing.explain import explain
from app.routing.metrics import overlap_ratio, route_metrics

ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "tests" / "fixtures" / "routing_mini.geojson"


@pytest.fixture
def mini():
    return load_geojson(MINI)


def by_label(options):
    return {o.label: o for o in options}


# ── 선택지
def test_CHOICE_01_휠체어는_추천과_통행불가_최단을_함께_받는다(mini):
    opts = by_label(route_options(mini, "A", "D", WHEELCHAIR))
    assert opts["추천"].path == ["A", "E", "C", "D"]
    assert opts["최단"].path == ["A", "B", "D"]
    assert not opts["최단"].passable
    assert opts["최단"].blocked == ["B→D: 오르막 경사 15.0% > 허용 14.1%"]


def test_CHOICE_02_추천_이유는_최단과의_차이로_쓴다(mini):
    rec = by_label(route_options(mini, "A", "D", WHEELCHAIR))["추천"]
    assert rec.why == ["60m 더 걸음", "오르막 15.0% 1곳 회피", "경사 미측정 40m 포함"]


def test_CHOICE_03_추천이_곧_최단이면_하나로_합친다(mini):
    opts = route_options(mini, "A", "D", DEFAULT)
    assert [o.label for o in opts] == ["추천"]
    assert opts[0].is_shortest and opts[0].why == []


def test_CHOICE_04_대안은_추천과의_차이를_보여준다(mini):
    opts = by_label(route_options(mini, "A", "D", DEFAULT, max_extra=1.0))
    alt = opts["대안 1"]
    assert alt.path == ["A", "E", "C", "D"]
    assert alt.result.total_cost == pytest.approx(1.3, abs=0.01)   # 배율이 빠진 실제 비용(130m)
    assert alt.why[0] == "60m 더 걸음"


def test_CHOICE_05_추천보다_30퍼센트_넘게_비싼_대안은_버린다(mini):
    assert [o.label for o in route_options(mini, "A", "D", DEFAULT)] == ["추천"]


def test_CHOICE_06_같은_경로는_대안으로_다시_내지_않는다(mini):
    labels = [o.label for o in route_options(mini, "A", "D", WHEELCHAIR, max_extra=10.0)]
    assert labels == ["추천", "최단"]


def test_CHOICE_07_갈_수_있는_길이_없으면_최단만_이유와_함께(mini):
    strict = WHEELCHAIR.with_overrides(max_up_pct=2.0)       # AE +3%도 막힘
    opts = route_options(mini, "A", "D", strict)
    assert [o.label for o in opts] == ["최단"]
    assert not opts[0].passable
    assert "통행 가능한 경로 없음" in format_options(opts, strict.name)


def test_CHOICE_08_반대_방향은_내리막으로_설명한다(mini):
    rec = by_label(route_options(mini, "D", "A", WHEELCHAIR))["추천"]
    assert "내리막 15.0% 1곳 회피" in rec.why


# ── 요약값, 이유 문장, 재평가
def test_METRIC_01_경로_요약값(mini):
    r = find_route(mini, "A", "D", DEFAULT)
    m = route_metrics(r.edges)
    assert m.distance_m == pytest.approx(70.0, abs=0.5)
    assert m.max_uphill_pct == 15.0 and m.unknown_slope_m == 0.0
    assert [(s.edge, s.slope_pct) for s in m.steep] == [("B→D", 15.0)]


def test_METRIC_02_겹침_비율은_방향과_무관(mini):
    go = find_route(mini, "A", "D", DEFAULT).edges
    back = find_route(mini, "D", "A", DEFAULT).edges
    other = find_route(mini, "A", "D", WHEELCHAIR).edges
    assert overlap_ratio(go, back) == pytest.approx(1.0)
    assert overlap_ratio(go, other) == 0.0


def test_EXPLAIN_01_반대로_비교하면_반대로_말한다(mini):
    short = route_metrics(find_route(mini, "A", "D", DEFAULT).edges)
    rec = route_metrics(find_route(mini, "A", "D", WHEELCHAIR).edges)
    assert explain(short, rec) == ["60m 더 짧음", "오르막 15.0% 1곳 지남", "경사 미측정 40m 적음"]
    assert explain(rec, rec) == []


def test_EVAL_01_정해진_경로를_프로필로_다시_판정(mini):
    edges = find_route(mini, "A", "D", DEFAULT).edges
    assert evaluate_path(edges, DEFAULT).passable
    chk = evaluate_path(edges, WHEELCHAIR)
    assert not chk.passable and chk.cost == float("inf")


def test_SCALE_01_비용_배율로_쓴_간선을_피한다(mini):
    r = find_route(mini, "A", "D", DEFAULT, cost_scale={"AB": 3.0, "BD": 3.0})
    assert r.node_path == ["A", "E", "C", "D"]


def test_CLI_01_명령줄에서_선택_이유를_출력한다():
    done = subprocess.run(
        [sys.executable, "-m", "scripts.route", "--graph", str(MINI),
         "--from", "A", "--to", "D", "--profile", "wheelchair", "--explain"],
        cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert "추천" in done.stdout and "통행 불가" in done.stdout
    assert "오르막 15.0% 1곳 회피" in done.stdout
