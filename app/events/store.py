"""이벤트 저장소: JSON 파일 하나에 이벤트 목록을 둔다.

    {"events": [{"event_id": "E001", "type": "construction", "edge_id": "BD", ...}]}

기본 위치 data/events/events.json은 실행 중에 바뀌는 파일이라 git에 올리지 않는다.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from app.events.model import ROOT, Event, EventType, load_types, to_local
from app.graph.schema import Graph

DEFAULT_STORE_PATH = ROOT / "data" / "events" / "events.json"


class EventStore:
    def __init__(self, path: Optional[Path] = None, types: Optional[dict[str, EventType]] = None,
                 load: bool = True):
        """load=False면 파일을 읽지 않고 빈 목록으로 시작한다(시연·테스트용)."""
        self.path = Path(path) if path else DEFAULT_STORE_PATH
        self.types = types if types is not None else load_types()
        self.events: list[Event] = []
        if load and self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.events = [Event.from_dict(d) for d in raw.get("events", [])]
            for ev in self.events:
                self._check_type(ev.type)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"events": [ev.to_dict() for ev in self.events]}
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _check_type(self, name: str) -> EventType:
        if name not in self.types:
            raise ValueError(f"알 수 없는 이벤트 종류 '{name}'. 사용 가능: {sorted(self.types)}")
        return self.types[name]

    def _next_id(self) -> str:
        numbers = [int(m.group(1)) for ev in self.events if (m := re.fullmatch(r"E(\d+)", ev.event_id))]
        return f"E{max(numbers, default=0) + 1:03d}"

    def add(
        self,
        type: str,
        edge_id: str,
        now: datetime,
        *,
        until: Optional[datetime] = None,
        minutes: Optional[float] = None,
        note: str = "",
        graph: Optional[Graph] = None,
        source: str = "manual",
    ) -> Event:
        """이벤트를 만든다. 종료 시각은 until > minutes > 종류별 ttl_min 순으로 정한다."""
        t = self._check_type(type)
        if graph is not None and edge_id not in graph.edges:
            raise ValueError(f"graph에 없는 간선 '{edge_id}'")
        if until is not None and minutes is not None:
            raise ValueError("until과 minutes 중 하나만 지정한다")
        now = to_local(now)
        if until is not None:
            expires = to_local(until)
        elif minutes is not None:
            expires = now + timedelta(minutes=minutes)
        elif t.ttl_min is not None:
            expires = now + timedelta(minutes=t.ttl_min)
        else:
            expires = None
        ev = Event(event_id=self._next_id(), type=type, edge_id=edge_id, created_at=now,
                   expires_at=expires, note=note, source=source)
        self.events.append(ev)
        return ev

    def get(self, event_id: str) -> Event:
        for ev in self.events:
            if ev.event_id == event_id:
                return ev
        raise KeyError(f"이벤트 '{event_id}' 없음")

    def clear(self, event_id: str, now: datetime) -> Event:
        ev = self.get(event_id)
        ev.status = "cleared"
        ev.cleared_at = to_local(now)
        return ev

    def active_at(self, now: datetime) -> list[Event]:
        return [ev for ev in self.events if ev.state_at(now) == "active"]
