"""출입구 개방 시간 해석.

물리적 속성은 센싱으로 얻지만, 개방 시간은 학습으로 알아낼 수 있는 정보가
아니라 게시된 규칙이다. 그래서 규칙으로 주입한다.

주의: 잘못된 개방 정보는 정보가 없는 것보다 위험하다. verified_at을 반드시
같이 보관하고, UI에 표시한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Optional

DAY_KEYS = ["monday", "tuesday", "wednesday", "thursday",
            "friday", "saturday", "sunday"]


def _parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


@dataclass
class Entrance:
    id: str
    name: str = ""
    building: str = ""
    # 요일별 개방 구간. 값이 빈 리스트면 그날은 종일 폐쇄.
    hours: dict[str, list[str]] = field(default_factory=dict)
    wheelchair_accessible: bool = True
    threshold_cm: float = 0.0
    verified_at: Optional[str] = None
    source: str = ""

    def is_open(self, when: datetime) -> bool:
        key = DAY_KEYS[when.weekday()]
        if key not in self.hours:          # 정보 없음 → 열려 있다고 가정하지 않는다
            return False
        now = when.time()
        for span in self.hours[key]:
            start_s, end_s = span.split("-")
            start, end = _parse_hhmm(start_s), _parse_hhmm(end_s)
            if start <= end:
                if start <= now < end:
                    return True
            else:                           # 자정을 넘기는 구간
                if now >= start or now < end:
                    return True
        return False


@dataclass
class ScheduleBook:
    entrances: dict[str, Entrance] = field(default_factory=dict)

    def add(self, e: Entrance) -> None:
        self.entrances[e.id] = e

    def is_open(self, entrance_id: Optional[str], when: Optional[datetime]) -> bool:
        """시간 제약이 없는 구간(entrance_id=None)은 항상 통행 가능.
        when이 None이면 시간 제약을 적용하지 않는다(시간 비의존 라우팅)."""
        if entrance_id is None or when is None:
            return True
        ent = self.entrances.get(entrance_id)
        if ent is None:
            return False          # 등록되지 않은 출입구는 닫힌 것으로 본다
        return ent.is_open(when)

    def reason(self, entrance_id: str, when: datetime) -> str:
        ent = self.entrances.get(entrance_id)
        if ent is None:
            return f"출입구 정보 없음 ({entrance_id})"
        key = DAY_KEYS[when.weekday()]
        spans = ent.hours.get(key, [])
        if not spans:
            return f"{ent.name}: 해당 요일 폐쇄"
        return f"{ent.name}: 개방 {', '.join(spans)} (확인 {ent.verified_at or '미상'})"

    # ------------------------------------------------------------ 입출력
    @classmethod
    def load(cls, path: str | Path) -> "ScheduleBook":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        book = cls()
        for row in data.get("entrances", []):
            book.add(Entrance(**row))
        return book

    def save(self, path: str | Path) -> None:
        payload = {"entrances": [e.__dict__ for e in self.entrances.values()]}
        Path(path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
