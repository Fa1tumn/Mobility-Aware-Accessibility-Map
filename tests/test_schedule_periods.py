"""출입구 운영 시간: 기간(학기·방학), 공휴일, 24:00, 요일 묶음 테스트.

fixtures/schedule_buildings.json은 시험용 합성 값이다(실제 도서관 시간과 별개).
    학기 2026-09-01~12-19, 방학 12-20~2027-02-28, 공휴일 12-25
    lib_ground_stepfree  학기 평일·토 09-18, 일 12-18 / 방학 닫힘
    lib_underground      학기 평일 08:30-24:00, 토 09-18, 일 12-18 / 방학 평일 09-17
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.graph.schema import Edge
from app.profile import feasibility as feas
from app.profile.definitions import WHEELCHAIR
from app.schedule.resolver import Entrance, ScheduleBook

ROOT = Path(__file__).resolve().parents[1]
BOOK = ROOT / "tests" / "fixtures" / "schedule_buildings.json"
LEGACY = ROOT / "data" / "routing_demo" / "entrances.json"

FRI_SEM = datetime(2026, 11, 20, 14, 0)      # 학기 중 금요일
MON_VAC = datetime(2027, 1, 4, 10, 0)        # 방학 중 월요일


@pytest.fixture
def book():
    return ScheduleBook.load(BOOK)


def test_SCH_01_학기_평일_지상문은_18시에_닫힌다(book):
    assert book.is_open("lib_ground_stepfree", FRI_SEM)
    late = book.status("lib_ground_stepfree", FRI_SEM.replace(hour=19))
    assert not late.open
    assert late.reason == "도서관 지상 계단 없는 문: 학기 중 금요일 09:00-18:00 개방, 지금 19:00 닫힘"


def test_SCH_02_방학에는_지상문이_닫히고_지하만_연다(book):
    shut = book.status("lib_ground_stepfree", MON_VAC)
    assert not shut.open and shut.reason == "도서관 지상 계단 없는 문: 방학 중 월요일 닫힘"
    assert book.is_open("lib_underground", MON_VAC)
    assert not book.is_open("lib_underground", MON_VAC.replace(hour=17))     # 끝 시각은 포함 안 함


def test_SCH_03_24시_표기를_읽는다(book):
    assert book.is_open("lib_underground", datetime(2026, 11, 20, 23, 59))
    assert not book.is_open("lib_underground", datetime(2026, 11, 21, 0, 0))   # 토요일 0시


def test_SCH_04_공휴일은_holiday_키가_없으면_닫힌다(book):
    st = book.status("lib_underground", datetime(2026, 12, 25, 10, 0))
    assert not st.open and "공휴일 닫힘" in st.reason


def test_SCH_05_기간_밖의_날짜는_닫힌_것으로_본다(book):
    st = book.status("lib_underground", datetime(2027, 3, 2, 10, 0))
    assert not st.open and "운영 기간 정보 없음" in st.reason


def test_SCH_06_개별_요일이_묶음보다_우선(book):
    e = Entrance(id="x", hours={"weekdays": ["09:00-18:00"], "friday": ["09:00-12:00"]})
    assert e.is_open(datetime(2026, 11, 23, 13, 0))          # 월요일
    assert not e.is_open(datetime(2026, 11, 20, 13, 0))      # 금요일


def test_SCH_07_자정을_넘는_구간(book):
    e = Entrance(id="x", hours={"daily": ["22:00-02:00"]})
    assert e.is_open(datetime(2026, 11, 20, 23, 0))
    assert e.is_open(datetime(2026, 11, 20, 1, 0))
    assert not e.is_open(datetime(2026, 11, 20, 3, 0))


@pytest.mark.parametrize("hours", [
    {"daily": ["25:00-26:00"]},
    {"daily": ["09:00-09:00"]},
    {"daily": ["9시-18시"]},
    {"mon": ["09:00-18:00"]},
    {"semester": {"mon": ["09:00-18:00"]}},
])
def test_SCH_08_잘못된_시간표는_거부(hours):
    with pytest.raises(ValueError):
        Entrance(id="bad", hours=hours)


def test_SCH_09_정의되지_않은_기간을_쓰면_거부(tmp_path):
    data = json.loads(BOOK.read_text(encoding="utf-8"))
    data["entrances"][0]["hours"]["exam"] = {"daily": ["08:00-24:00"]}
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="정의되지 않은 기간"):
        ScheduleBook.load(bad)


def test_SCH_10_확인하지_않은_기간은_사유에_표시(tmp_path):
    data = json.loads(BOOK.read_text(encoding="utf-8"))
    data["periods"][0]["verified"] = False
    path = tmp_path / "unverified.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert "학기 중(기간 미확인)" in ScheduleBook.load(path).reason("lib_underground", FRI_SEM)


def test_SCH_11_저장했다_다시_읽어도_같다(book, tmp_path):
    out = tmp_path / "round.json"
    book.save(out)
    again = ScheduleBook.load(out)
    for t in (FRI_SEM, FRI_SEM.replace(hour=19), MON_VAC, datetime(2026, 12, 25, 10, 0)):
        for entrance_id in book.entrances:
            assert again.status(entrance_id, t) == book.status(entrance_id, t)


def test_SCH_12_9월_요일형_파일도_그대로_읽는다():
    legacy = ScheduleBook.load(LEGACY)
    assert legacy.is_open("underwood_ground_west", datetime(2026, 9, 28, 10, 0))
    assert not legacy.is_open("underwood_ground_west", datetime(2026, 9, 28, 20, 0))


def test_SCH_13_통행_불가_사유에_출입구_이름과_시간이_나온다(book):
    e = Edge(id="e", from_node="a", to_node="b", distance_m=10.0, width_level="normal",
             entrance_id="lib_ground_stepfree")
    f = feas.check(e, WHEELCHAIR, FRI_SEM.replace(hour=19), book)
    assert f.reasons == ["출입 불가 — 도서관 지상 계단 없는 문: 학기 중 금요일 09:00-18:00 개방, 지금 19:00 닫힘"]
