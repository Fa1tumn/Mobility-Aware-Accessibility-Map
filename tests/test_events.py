"""수동 이벤트: 종류 설정, 저장, 만료, 프로필별 효과, 경로 반영 테스트.

fixtures/routing_mini.geojson (합성 graph)
    A ──AB 0%, 40m── B
    │                │ BD +15%, 30m
    AE +3%, 60m      D
    │                │ CD -2%, 30m
    E ──EC 미측정, 40m── C
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.events.model import Event, EventType, load_types
from app.events.overlay import EventOverlay
from app.events.store import EventStore
from app.graph.loader import load_geojson
from app.profile.definitions import DEFAULT, LUGGAGE, WHEELCHAIR
from app.routing.alternatives import route_options
from app.routing.dijkstra import find_route
from app.routing.geojson import route_to_geojson

ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "tests" / "fixtures" / "routing_mini.geojson"
T0 = datetime(2026, 11, 21, 10, 0)


@pytest.fixture
def mini():
    return load_geojson(MINI)


@pytest.fixture
def store(tmp_path):
    return EventStore(tmp_path / "events.json")


def overlay(store, minutes=1):
    return EventOverlay.from_store(store, T0 + timedelta(minutes=minutes))


# ── 종류 설정
def test_EVT_01_기본_종류_설정을_읽는다():
    types = load_types()
    assert set(types) == {"construction", "barricade", "parked_vehicle", "crowd"}
    assert types["construction"].blocks("default") and types["construction"].ttl_min is None
    assert types["barricade"].blocks("wheelchair") and not types["barricade"].blocks("default")
    assert types["parked_vehicle"].penalty_for("wheelchair") == 2.0
    assert types["parked_vehicle"].penalty_for("default") == 0.0
    assert types["crowd"].record_only


def test_EVT_02_잘못된_종류_설정은_거부(tmp_path):
    bad = tmp_path / "types.json"
    bad.write_text(json.dumps({"x": {"label": "x", "ttl_min": -5}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_types(bad)
    bad.write_text(json.dumps({"x": {"label": "x", "colour": "red"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="정의되지 않은"):
        load_types(bad)


# ── 생성·저장·상태
def test_EVT_03_종료_시각은_until_minutes_기본값_순(store):
    a = store.add("barricade", "EC", T0)
    b = store.add("barricade", "EC", T0, minutes=5)
    c = store.add("barricade", "EC", T0, until=T0 + timedelta(hours=2))
    d = store.add("construction", "BD", T0)
    assert a.expires_at == T0 + timedelta(days=1)
    assert b.expires_at == T0 + timedelta(minutes=5)
    assert c.expires_at == T0 + timedelta(hours=2)
    assert d.expires_at is None                              # 해제할 때까지
    assert [e.event_id for e in store.events] == ["E001", "E002", "E003", "E004"]


def test_EVT_04_상태는_시각으로_계산한다(store):
    ev = store.add("parked_vehicle", "EC", T0)                # 30분
    assert ev.state_at(T0 - timedelta(seconds=1)) == "pending"
    assert ev.state_at(T0 + timedelta(minutes=29)) == "active"
    assert ev.state_at(T0 + timedelta(minutes=30)) == "expired"
    store.clear(ev.event_id, T0 + timedelta(minutes=10))
    assert ev.state_at(T0 + timedelta(minutes=5)) == "active"
    assert ev.state_at(T0 + timedelta(minutes=10)) == "cleared"


def test_EVT_05_없는_간선_종류_역방향_ID는_거부(store, mini):
    with pytest.raises(ValueError, match="없는 간선"):
        store.add("construction", "XX", T0, graph=mini)
    with pytest.raises(ValueError, match="종류"):
        store.add("flood", "BD", T0)
    with pytest.raises(ValueError, match="원래 간선"):
        store.add("construction", "BD:rev", T0)
    with pytest.raises(ValueError):
        store.add("construction", "BD", T0, until=T0 + timedelta(hours=1), minutes=10)


def test_EVT_06_저장했다_다시_읽어도_같다(store):
    store.add("construction", "BD", T0, until=T0 + timedelta(hours=1), note="보수")
    store.add("parked_vehicle", "EC", T0)
    store.clear("E002", T0 + timedelta(minutes=3))
    store.save()
    again = EventStore(store.path)
    assert [e.to_dict() for e in again.events] == [e.to_dict() for e in store.events]
    assert again.add("crowd", "AB", T0).event_id == "E003"


def test_EVT_07_시간대가_붙은_시각은_한국_시간으로(store):
    utc = datetime(2026, 11, 21, 1, 0, tzinfo=timezone.utc)
    ev = store.add("construction", "BD", utc)
    assert ev.created_at == T0 and ev.created_at.tzinfo is None


# ── 경로 반영
def test_EVT_08_차단_이벤트는_우회하고_사유를_남긴다(store, mini):
    store.add("construction", "BD", T0, until=T0 + timedelta(hours=1))
    r = find_route(mini, "A", "D", DEFAULT, events=overlay(store))
    assert r.node_path == ["A", "E", "C", "D"]
    assert "B→D: 공사·통제 E001 (11:00까지)" in r.blocked


def test_EVT_09_이벤트는_양방향에_적용된다(store, mini):
    store.add("construction", "BD", T0)
    assert find_route(mini, "D", "A", DEFAULT, events=overlay(store)).node_path == ["D", "C", "E", "A"]


def test_EVT_10_같은_이벤트도_프로필마다_효과가_다르다(store, mini):
    store.add("barricade", "EC", T0)
    ov = overlay(store)
    base = find_route(mini, "A", "D", LUGGAGE)
    assert not find_route(mini, "A", "D", WHEELCHAIR, events=ov).found
    assert find_route(mini, "A", "D", LUGGAGE, events=ov).node_path == base.node_path
    eff = ov.effect("EC", DEFAULT)
    assert not eff.block and eff.penalty == 0.5


def test_EVT_11_비용_이벤트는_간선을_지날_때_한_번_더한다(store, mini):
    store.add("parked_vehicle", "EC", T0)
    ov = overlay(store)
    plain = find_route(mini, "A", "D", WHEELCHAIR)
    with_ev = find_route(mini, "A", "D", WHEELCHAIR, events=ov)
    assert with_ev.total_cost == pytest.approx(plain.total_cost + 2.0)
    assert any("정차 차량·킥보드 E001" in r for r in with_ev.reasons)
    assert ov.effect("EC", DEFAULT) is None                   # 보행자에게는 영향 없음


def test_EVT_12_만료_해제_기록용_이벤트는_경로에_영향이_없다(store, mini):
    store.add("construction", "BD", T0, minutes=10)
    store.add("construction", "AB", T0)
    store.clear("E002", T0 + timedelta(minutes=1))
    store.add("crowd", "AE", T0)
    ov = overlay(store, minutes=11)
    assert ov.effect("BD", DEFAULT) is None and ov.effect("AB", DEFAULT) is None
    assert ov.events_on("AE") == []
    assert find_route(mini, "A", "D", DEFAULT, events=ov).node_path == ["A", "B", "D"]


def test_EVT_13_선택_이유에_이벤트_회피가_나온다(store, mini):
    store.add("construction", "BD", T0)
    opts = {o.label: o for o in route_options(mini, "A", "D", DEFAULT, events=overlay(store))}
    assert opts["추천"].path == ["A", "E", "C", "D"]
    assert "공사·통제 구간 회피 (E001)" in opts["추천"].why
    assert not opts["최단"].passable and opts["최단"].blocked == ["B→D: 공사·통제 E001"]


def test_EVT_14_경로_GeoJSON에_이벤트가_담긴다(store, mini):
    store.add("parked_vehicle", "EC", T0)
    ov = overlay(store)
    r = find_route(mini, "A", "D", WHEELCHAIR, events=ov)
    fc = route_to_geojson(mini, r, WHEELCHAIR, "A", "D", T0, ov)
    assert fc["properties"]["event_ids"] == ["E001"]
    ec = next(f["properties"] for f in fc["features"] if f["properties"]["edge_id"] == "EC")
    assert ec["events"] == ["정차 차량·킥보드 E001 (10:30까지)"]
    assert sum(f["properties"]["cost"] for f in fc["features"]) == pytest.approx(r.total_cost, abs=1e-3)


def test_EVT_15_종류를_직접_만들어_쓸_수_있다(tmp_path, mini):
    types = {"slow": EventType(name="slow", label="서행", ttl_min=5, penalty={"*": 1.0})}
    s = EventStore(tmp_path / "e.json", types=types)
    s.add("slow", "AB", T0)
    ov = EventOverlay.from_store(s, T0)
    assert ov.effect("AB", DEFAULT).penalty == 1.0
    with pytest.raises(ValueError):
        Event(event_id="X", type="slow", edge_id="AB", created_at=T0, expires_at=T0)


# ── 명령줄
def test_CLI_01_이벤트_추가_목록_해제(tmp_path):
    store = tmp_path / "events.json"

    def run(*args):
        return subprocess.run([sys.executable, "-m", "scripts.events", "--store", str(store),
                               "--now", "2026-11-21T10:00", *args],
                              cwd=ROOT, capture_output=True, text=True)

    done = run("add", "--type", "construction", "--edge", "BD", "--graph", str(MINI))
    assert done.returncode == 0, done.stderr
    assert "E001" in run("list").stdout
    assert run("add", "--type", "construction", "--edge", "XX", "--graph", str(MINI)).returncode == 1
    assert run("clear", "E001").returncode == 0
    assert "이벤트 없음" in run("list").stdout


def test_CLI_02_경로_계산에_이벤트_파일을_쓴다(tmp_path):
    store = EventStore(tmp_path / "events.json")
    store.add("construction", "BD", T0, until=T0 + timedelta(hours=1))
    store.save()
    out = tmp_path / "route.geojson"
    done = subprocess.run(
        [sys.executable, "-m", "scripts.route", "--graph", str(MINI), "--from", "A", "--to", "D",
         "--profile", "default", "--events", str(store.path), "--when", "2026-11-21T10:10",
         "--out", str(out)], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert json.loads(out.read_text(encoding="utf-8"))["properties"]["node_path"] == ["A", "E", "C", "D"]
