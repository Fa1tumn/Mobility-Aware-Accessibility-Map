"""출입구 개방 시간 해석.

물리적 속성은 센싱으로 얻지만, 개방 시간은 학습으로 알아낼 수 있는 정보가
아니라 게시된 규칙이다. 그래서 규칙으로 주입한다.

주의: 잘못된 개방 정보는 정보가 없는 것보다 위험하다. verified_at을 반드시
같이 보관하고, UI에 표시한다.

시간표 형식 두 가지를 읽는다.

    요일형(9월 형식)   "hours": {"monday": ["09:00-18:00"], ..., "sunday": []}
    기간형            "hours": {"semester": {"weekdays": ["08:30-24:00"], "sunday": ["12:00-18:00"]},
                                 "vacation": {"weekdays": ["09:00-17:00"]}}
                      기간 ID는 파일 최상위 "periods"에 날짜 범위로 정의한다.

규칙
- 요일 키: monday~sunday, 묶음 weekdays(월~금)·weekend(토·일)·daily(매일), 공휴일 holiday.
  같은 요일이 묶음과 개별 키에 모두 있으면 개별 키가 이긴다.
- 시간은 "HH:MM-HH:MM", 끝 시각 24:00 허용. 시작 > 끝이면 자정을 넘기는 구간.
- 정보가 없으면 닫힌 것으로 본다: 시간표에 없는 요일, 어느 기간에도 속하지 않는 날짜,
  공휴일인데 holiday 키가 없는 경우.
- 기간이 겹치면 "periods"에 먼저 적은 기간이 우선한다(예: 시험기간을 학기보다 앞에).
- 시각은 한국 시간(시간대 없는 값)으로 해석한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Optional

DAY_KEYS = ["monday", "tuesday", "wednesday", "thursday",
            "friday", "saturday", "sunday"]
DAY_GROUPS = {"weekdays": DAY_KEYS[:5], "weekend": DAY_KEYS[5:], "daily": DAY_KEYS}
HOLIDAY = "holiday"
DAY_LABEL = dict(zip(DAY_KEYS, ["월", "화", "수", "목", "금", "토", "일"]))
LEGACY_PERIOD = "*"
DAY_MINUTES = 24 * 60


def _minutes(s: str) -> int:
    """'HH:MM' → 자정부터의 분. '24:00'은 하루 끝(1440)."""
    try:
        h_s, m_s = s.strip().split(":")
        h, m = int(h_s), int(m_s)
    except ValueError as error:
        raise ValueError(f"시각 형식은 HH:MM ({s!r})") from error
    if not (0 <= m < 60) or not (0 <= h < 24 or (h == 24 and m == 0)):
        raise ValueError(f"시각 범위 오류 ({s!r})")
    return h * 60 + m


def _parse_hhmm(s: str) -> time:
    """하위 호환용. 24:00은 time으로 표현할 수 없으므로 23:59:59로 돌려준다."""
    m = _minutes(s)
    return time(23, 59, 59) if m == DAY_MINUTES else time(m // 60, m % 60)


def _span(s: str) -> tuple[int, int]:
    try:
        a, b = s.split("-")
    except ValueError as error:
        raise ValueError(f"시간 구간 형식은 HH:MM-HH:MM ({s!r})") from error
    start, end = _minutes(a), _minutes(b)
    if start == end or start == DAY_MINUTES:
        raise ValueError(f"길이가 0이거나 잘못된 구간 ({s!r})")
    return start, end


def _in_span(minute: int, start: int, end: int) -> bool:
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end          # 자정을 넘기는 구간


def _day_table(raw: dict[str, list[str]], where: str) -> dict[str, list[tuple[int, int]]]:
    """요일 묶음을 풀고 구간을 검사한다. 개별 요일 키가 묶음보다 우선한다."""
    table: dict[str, list[tuple[int, int]]] = {}
    for key, spans in raw.items():
        if key in DAY_GROUPS:
            for day in DAY_GROUPS[key]:
                if day not in raw:
                    table[day] = [_span(s) for s in spans]
        elif key in DAY_KEYS or key == HOLIDAY:
            table[key] = [_span(s) for s in spans]
        else:
            raise ValueError(f"{where}: 알 수 없는 요일 키 '{key}'")
    return table


def _is_day_table(raw: dict[str, Any]) -> bool:
    return all(k in DAY_KEYS or k in DAY_GROUPS or k == HOLIDAY for k in raw)


@dataclass(frozen=True)
class Period:
    id: str
    start: date
    end: date                      # 포함
    label: str = ""
    verified: bool = True          # 학사일정으로 확인한 날짜인지
    note: str = ""

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"기간 {self.id}: end가 start보다 빠르다")

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Period":
        unknown = set(d) - {"id", "from", "to", "label", "verified", "note"}
        if unknown:
            raise ValueError(f"기간 {d.get('id')}: 정의되지 않은 속성 {sorted(unknown)}")
        return cls(id=d["id"], start=date.fromisoformat(d["from"]), end=date.fromisoformat(d["to"]),
                   label=d.get("label", d["id"]), verified=bool(d.get("verified", True)),
                   note=d.get("note", ""))

    def to_dict(self) -> dict[str, Any]:
        out = {"id": self.id, "from": self.start.isoformat(), "to": self.end.isoformat(), "label": self.label}
        if not self.verified:
            out["verified"] = False
        if self.note:
            out["note"] = self.note
        return out


@dataclass
class Status:
    open: bool
    reason: str                    # 사람이 읽는 설명


@dataclass
class Entrance:
    id: str
    name: str = ""
    building: str = ""
    # 요일형 또는 기간형 시간표(모듈 설명 참고)
    hours: dict[str, Any] = field(default_factory=dict)
    wheelchair_accessible: bool = True
    threshold_cm: float = 0.0
    verified_at: Optional[str] = None
    source: str = ""

    def __post_init__(self) -> None:
        if _is_day_table(self.hours):
            self._tables = {LEGACY_PERIOD: _day_table(self.hours, self.id)}
        else:
            self._tables = {}
            for period_id, raw in self.hours.items():
                if not isinstance(raw, dict) or not _is_day_table(raw):
                    raise ValueError(f"{self.id}: 기간 '{period_id}'의 값은 요일별 시간표여야 한다")
                self._tables[period_id] = _day_table(raw, f"{self.id}/{period_id}")

    @property
    def period_ids(self) -> set[str]:
        return set(self._tables) - {LEGACY_PERIOD}

    def status(self, when: datetime, periods: tuple[Period, ...] = (),
               holidays: frozenset[date] = frozenset()) -> Status:
        name = self.name or self.id
        d = when.date()
        minute = when.hour * 60 + when.minute
        now = when.strftime("%H:%M")

        if LEGACY_PERIOD in self._tables:
            table, period_text = self._tables[LEGACY_PERIOD], ""
        else:
            period = next((p for p in periods if p.id in self._tables and p.contains(d)), None)
            if period is None:
                return Status(False, f"{name}: {d.isoformat()}에 해당하는 운영 기간 정보 없음")
            table = self._tables[period.id]
            period_text = period.label + ("(기간 미확인)" if not period.verified else "") + " "

        if d in holidays:
            key, day_text = HOLIDAY, "공휴일"
        else:
            key = DAY_KEYS[when.weekday()]
            day_text = DAY_LABEL[key] + "요일"
        spans = table.get(key)
        if not spans:
            return Status(False, f"{name}: {period_text}{day_text} 닫힘")
        is_open = any(_in_span(minute, a, b) for a, b in spans)
        text = ", ".join(f"{a // 60:02d}:{a % 60:02d}-{b // 60:02d}:{b % 60:02d}" for a, b in spans)
        state = "열림" if is_open else "닫힘"
        return Status(is_open, f"{name}: {period_text}{day_text} {text} 개방, 지금 {now} {state}")

    def is_open(self, when: datetime, periods: tuple[Period, ...] = (),
                holidays: frozenset[date] = frozenset()) -> bool:
        return self.status(when, periods, holidays).open

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "building": self.building, "hours": self.hours,
                "wheelchair_accessible": self.wheelchair_accessible,
                "threshold_cm": self.threshold_cm, "verified_at": self.verified_at,
                "source": self.source}


@dataclass
class ScheduleBook:
    entrances: dict[str, Entrance] = field(default_factory=dict)
    periods: tuple[Period, ...] = ()
    holidays: frozenset[date] = frozenset()

    def add(self, e: Entrance) -> None:
        missing = e.period_ids - {p.id for p in self.periods}
        if missing:
            raise ValueError(f"{e.id}: 정의되지 않은 기간 {sorted(missing)}")
        self.entrances[e.id] = e

    def status(self, entrance_id: str, when: datetime) -> Status:
        ent = self.entrances.get(entrance_id)
        if ent is None:
            return Status(False, f"출입구 정보 없음 ({entrance_id})")
        return ent.status(when, self.periods, self.holidays)

    def is_open(self, entrance_id: Optional[str], when: Optional[datetime]) -> bool:
        """시간 제약이 없는 구간(entrance_id=None)은 항상 통행 가능.
        when이 None이면 시간 제약을 적용하지 않는다(시간 비의존 라우팅)."""
        if entrance_id is None or when is None:
            return True
        return self.status(entrance_id, when).open

    def reason(self, entrance_id: str, when: datetime) -> str:
        return self.status(entrance_id, when).reason

    # ------------------------------------------------------------ 입출력
    @classmethod
    def load(cls, path: str | Path) -> "ScheduleBook":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        periods = tuple(Period.from_dict(p) for p in data.get("periods", []))
        ids = [p.id for p in periods]
        if len(ids) != len(set(ids)):
            raise ValueError("기간 ID가 중복된다")
        book = cls(periods=periods,
                   holidays=frozenset(date.fromisoformat(s) for s in data.get("holidays", [])))
        for row in data.get("entrances", []):
            book.add(Entrance(**row))
        return book

    def save(self, path: str | Path) -> None:
        payload: dict[str, Any] = {}
        if self.periods:
            payload["periods"] = [p.to_dict() for p in self.periods]
        if self.holidays:
            payload["holidays"] = sorted(d.isoformat() for d in self.holidays)
        payload["entrances"] = [e.to_dict() for e in self.entrances.values()]
        Path(path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
