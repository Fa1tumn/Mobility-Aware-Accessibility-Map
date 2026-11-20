"""간선 판정 방향별 테스트.

fixtures/routing_mini.geojson (합성 graph): BD +15%(B→D 오르막), CD -2%, EC 미측정.
휠체어 기본 한도는 방향 구분 없이 약 14.1%라서 BD는 양방향 모두 불가다.
방향이 갈리는 경우는 오르막·내리막 한도를 따로 준 프로필로 본다.
"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.events.overlay import EventOverlay
from app.events.store import EventStore
from app.graph.loader import load_geojson
from app.graph.schema import SchemaError
from app.profile.definitions import DEFAULT, WHEELCHAIR, Profile
from app.routing.assess import assess_edges, summarize

MINI = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "routing_mini.geojson"
T0 = datetime(2026, 11, 21, 10, 0)
UP_LIMITED = Profile(name="up_limited", max_up_pct=10.0, max_down_pct=20.0)


@pytest.fixture
def mini():
    return load_geojson(MINI)


def test_ASSESS_01_방향별_한도면_오르막만_불가(mini):
    bd = assess_edges(mini, UP_LIMITED)["BD"]
    assert bd.forward.level == "impassable" and "오르막 경사 15.0%" in bd.forward.reasons[0]
    assert bd.backward.level == "passable"
    assert bd.worst.level == "impassable" and bd.worst.color == "red"
    assert not bd.symmetric


def test_ASSESS_02_휠체어_기본_한도는_양방향_모두_불가(mini):
    bd = assess_edges(mini, WHEELCHAIR)["BD"]
    assert bd.forward.level == bd.backward.level == "impassable"
    assert "내리막" in bd.backward.reasons[0]


def test_ASSESS_03_일반_프로필은_전부_통행_가능(mini):
    assert summarize(assess_edges(mini, DEFAULT)) == {"passable": 5, "difficult": 0, "impassable": 0}


def test_ASSESS_04_이벤트를_판정에_반영(mini, tmp_path):
    store = EventStore(tmp_path / "e.json")
    store.add("construction", "AB", T0)
    store.add("parked_vehicle", "EC", T0)
    ov = EventOverlay.from_store(store, T0 + timedelta(minutes=1))
    res = assess_edges(mini, WHEELCHAIR, events=ov)
    assert res["AB"].forward.level == res["AB"].backward.level == "impassable"
    assert res["AB"].forward.reasons == ["공사·통제 E001"]
    ec = res["EC"].forward
    assert ec.level == "difficult" and any("정차 차량" in r for r in ec.reasons)
    assert assess_edges(mini, DEFAULT, events=ov)["EC"].forward.level == "passable"   # 보행자는 영향 없음


def test_ASSESS_05_역방향_간선을_다시_뒤집지_않는다(mini):
    with pytest.raises(SchemaError):
        mini.edges["BD"].reversed().reversed()
