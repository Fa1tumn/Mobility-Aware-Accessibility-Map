"""특정 시각의 활성 이벤트를 간선별로 묶어 경로 탐색에 넘긴다.

탐색 한 번 동안은 같은 시각을 쓴다. 시각이 바뀌면(재탐색) 새로 만든다.
feasibility·cost 모듈은 그대로 두고, 탐색과 경로 재평가에서 이 효과를 더한다.
    block    그 프로필은 이 간선을 지날 수 없다
    penalty  간선을 지날 때 한 번 더하는 비용(평지 100m = 1.0)
이벤트는 원래 간선 ID에 붙으므로 양방향에 똑같이 적용된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Optional

from app.events.model import Event, EventType, to_local
from app.profile.definitions import Profile


@dataclass
class EdgeEffect:
    block: bool = False
    penalty: float = 0.0
    reasons: list[str] = field(default_factory=list)        # 막는 이벤트가 앞
    event_ids: list[str] = field(default_factory=list)
    block_reasons: list[str] = field(default_factory=list)  # 막는 이벤트만


class EventOverlay:
    def __init__(self, events: Iterable[Event], types: dict[str, EventType], now: datetime):
        self.now = to_local(now)
        self.types = types
        self._by_edge: dict[str, list[Event]] = {}
        for ev in events:
            if ev.state_at(self.now) != "active" or types[ev.type].record_only:
                continue
            self._by_edge.setdefault(ev.edge_id, []).append(ev)

    @classmethod
    def from_store(cls, store, now: datetime) -> "EventOverlay":
        return cls(store.events, store.types, now)

    def describe(self, ev: Event) -> str:
        """화면·사유용 표기. 예: '공사·통제 E001 (10:05까지)'"""
        label = self.types[ev.type].label
        if ev.expires_at is None:
            return f"{label} {ev.event_id}"
        fmt = "%H:%M" if ev.expires_at.date() == self.now.date() else "%m-%d %H:%M"
        return f"{label} {ev.event_id} ({ev.expires_at.strftime(fmt)}까지)"

    def events_on(self, edge_id: str) -> list[Event]:
        """프로필과 무관하게 이 간선에 걸린 활성 이벤트."""
        return list(self._by_edge.get(edge_id, ()))

    def effect(self, edge_id: str, profile: Profile) -> Optional[EdgeEffect]:
        """이 프로필에 영향이 있을 때만 효과를 돌려준다."""
        blocking: list[Event] = []
        penalizing: list[tuple[Event, float]] = []
        for ev in self._by_edge.get(edge_id, ()):
            t = self.types[ev.type]
            if t.blocks(profile.name):
                blocking.append(ev)
            elif (p := t.penalty_for(profile.name)) > 0:
                penalizing.append((ev, p))
        if not blocking and not penalizing:
            return None
        ordered = blocking + [ev for ev, _ in penalizing]      # 막는 이벤트 사유를 앞에
        return EdgeEffect(block=bool(blocking), penalty=sum(p for _, p in penalizing),
                          reasons=[self.describe(ev) for ev in ordered],
                          event_ids=[ev.event_id for ev in ordered],
                          block_reasons=[self.describe(ev) for ev in blocking])
