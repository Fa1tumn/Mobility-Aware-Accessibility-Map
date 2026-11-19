"""안내 중 재탐색 판단 테스트.

fixtures/routing_mini.geojson (합성 graph). 일반 프로필 기준 비용
    A-B-D 0.70 (70m)   A-E-C-D 1.30 (130m)
"""

import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.events.model import EventType
from app.events.overlay import EventOverlay
from app.events.store import EventStore
from app.graph.loader import load_geojson
from app.nav.reroute import check_reroute, remaining
from app.profile.definitions import DEFAULT, LUGGAGE, WHEELCHAIR
from app.routing.dijkstra import find_route
from scripts.event_demo import run_scenario

ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "tests" / "fixtures" / "routing_mini.geojson"
DEMO = ROOT / "data" / "events" / "demo_mini.json"
T0 = datetime(2026, 11, 21, 10, 0)


@pytest.fixture
def mini():
    return load_geojson(MINI)


@pytest.fixture
def store(tmp_path):
    return EventStore(tmp_path / "events.json")


def ov(store, minutes=1):
    return EventOverlay.from_store(store, T0 + timedelta(minutes=minutes))


def test_RR_01_앞_구간이_막히면_바로_재탐색(mini, store):
    route = find_route(mini, "A", "D", DEFAULT)
    store.add("construction", "BD", T0)
    d = check_reroute(route, "A", mini, DEFAULT, ov(store))
    assert d.action == "reroute" and d.changed
    assert d.route.node_path == ["A", "E", "C", "D"]
    assert d.reasons == ["앞 구간 B→D: 공사·통제 E001"]


def test_RR_02_지나온_구간의_이벤트는_무시(mini, store):
    route = find_route(mini, "A", "D", DEFAULT)
    store.add("construction", "AB", T0)
    d = check_reroute(route, "B", mini, DEFAULT, ov(store))
    assert d.action == "keep" and d.route.node_path == ["B", "D"]


def _slow(tmp_path, penalty):
    types = {"slow": EventType(name="slow", label="서행", ttl_min=60, penalty={"*": penalty})}
    s = EventStore(tmp_path / f"slow_{penalty}.json", types=types)
    s.add("slow", "BD", T0)
    return EventOverlay.from_store(s, T0 + timedelta(minutes=1))


def test_RR_03_10퍼센트_넘게_좋아질_때만_바꾼다(mini, tmp_path):
    route = find_route(mini, "A", "D", DEFAULT)
    keep = check_reroute(route, "A", mini, DEFAULT, _slow(tmp_path, 0.72))    # 1.42 → 1.30, 약 8%
    swap = check_reroute(route, "A", mini, DEFAULT, _slow(tmp_path, 0.80))    # 1.50 → 1.30, 약 13%
    assert keep.action == "keep" and keep.route.node_path == ["A", "B", "D"]
    assert swap.action == "reroute" and swap.route.node_path == ["A", "E", "C", "D"]
    assert swap.reasons == ["새 경로가 비용 13% 낮음"]


def test_RR_04_이벤트가_만료되면_원래_길로_돌아온다(mini, store):
    store.add("construction", "BD", T0, minutes=5)
    detour = find_route(mini, "A", "D", DEFAULT, events=ov(store, 1))
    assert detour.node_path == ["A", "E", "C", "D"]
    d = check_reroute(detour, "A", mini, DEFAULT, ov(store, 6))
    assert d.action == "reroute" and d.route.node_path == ["A", "B", "D"]


def test_RR_05_경로_밖_노드면_그곳에서_다시_찾는다(mini):
    route = find_route(mini, "A", "D", DEFAULT)
    d = check_reroute(route, "E", mini, DEFAULT)
    assert d.action == "reroute" and d.route.node_path == ["E", "C", "D"]
    assert d.reasons[0].startswith("경로 이탈")


def test_RR_06_돌아갈_길이_없으면_no_route(mini, store):
    route = find_route(mini, "A", "D", WHEELCHAIR)
    store.add("barricade", "EC", T0)
    d = check_reroute(route, "A", mini, WHEELCHAIR, ov(store))
    assert d.action == "no_route"
    assert d.reasons[0].startswith("앞 구간 E→C: 임시 설치물 E001")


def test_RR_07_도착(mini):
    route = find_route(mini, "A", "D", DEFAULT)
    assert check_reroute(route, "D", mini, DEFAULT).action == "arrived"


def test_RR_08_유지할_때_앞_구간_비용_이벤트를_알려준다(mini, store):
    route = find_route(mini, "A", "D", LUGGAGE)
    store.add("parked_vehicle", "BD", T0)
    d = check_reroute(route, "A", mini, LUGGAGE, ov(store))
    assert d.action == "keep"
    assert d.reasons == ["앞 구간 B→D: 정차 차량·킥보드 E001 (10:30까지)"]


def test_RR_09_남은_경로_자르기(mini):
    route = find_route(mini, "A", "D", WHEELCHAIR)
    rest = remaining(route, "C")
    assert rest.node_path == ["C", "D"] and [e.base_id for e in rest.edges] == ["CD"]
    assert remaining(route, "B") is None


def test_DEMO_01_시나리오_재생(tmp_path):
    log = run_scenario(DEMO, out_dir=tmp_path)
    assert [x["action"] for x in log] == ["depart", "reroute", "keep", "reroute", "keep", "arrived"]
    assert log[1]["route"].node_path == ["A", "E", "C", "D"]
    assert log[3]["route"].node_path == ["A", "B", "D"]
    assert len(list(tmp_path.glob("step_*.geojson"))) == 5


def test_DEMO_02_명령줄로_재생한다():
    done = subprocess.run([sys.executable, "-m", "scripts.event_demo", str(DEMO)],
                          cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert "재탐색" in done.stdout and "도착" in done.stdout
