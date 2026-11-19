"""동적 이벤트의 종류와 구조.

종류(EventType)는 config/events.json에서 읽는다. 종류마다 유효시간, 막는 프로필,
프로필별 추가 비용을 정한다. 같은 정차 차량도 보행자에게는 영향이 없고 휠체어에는
큰 부담인 것처럼, 효과는 프로필마다 다르다.

상태는 두 가지로 나눠 본다.
    저장하는 상태 status   candidate | confirmed | active | cleared
                           수동 이벤트는 만들 때부터 active다. candidate·confirmed는
                           카메라 이벤트용으로 자리만 둔다(이번 범위 밖).
    시각으로 계산 state_at  pending | active | expired | cleared | candidate | confirmed
                           만료는 저장하지 않는다. expires_at을 지났는지로 판단한다.

시각은 한국 시간(시간대 없는 ISO 문자열)으로 저장한다. 시간대가 붙은 값은 한국
시간으로 바꿔서 받는다. 출입구 개방 시간(app/schedule)과 같은 기준이다.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TYPES_PATH = ROOT / "config" / "events.json"

KST = timezone(timedelta(hours=9))
STATUSES = {"candidate", "confirmed", "active", "cleared"}
SOURCES = {"manual", "camera", "schedule"}
ALL_PROFILES = "*"


def to_local(dt: datetime) -> datetime:
    """시간대가 붙은 시각은 한국 시간으로 바꾸고 시간대 표기를 뗀다."""
    return dt.astimezone(KST).replace(tzinfo=None) if dt.tzinfo else dt


def parse_time(value: Optional[str]) -> Optional[datetime]:
    return None if value in (None, "") else to_local(datetime.fromisoformat(value))


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return None if dt is None else dt.isoformat(timespec="seconds")


@dataclass(frozen=True)
class EventType:
    name: str
    label: str
    ttl_min: Optional[float] = None          # None: 종료 시각을 직접 주거나 해제할 때까지
    block: tuple[str, ...] = ()              # 막는 프로필 이름. "*"는 전부
    penalty: dict[str, float] = field(default_factory=dict)   # 프로필 이름 → 추가 비용. "*"는 나머지
    record_only: bool = False                # 기록만 하고 경로에는 반영하지 않음

    def __post_init__(self) -> None:
        if self.ttl_min is not None and not (math.isfinite(self.ttl_min) and self.ttl_min > 0):
            raise ValueError(f"{self.name}: ttl_min은 양수이거나 null ({self.ttl_min!r})")
        for key, value in self.penalty.items():
            if not (math.isfinite(value) and value >= 0):
                raise ValueError(f"{self.name}: penalty[{key}]는 0 이상 ({value!r})")

    def blocks(self, profile_name: str) -> bool:
        return ALL_PROFILES in self.block or profile_name in self.block

    def penalty_for(self, profile_name: str) -> float:
        return self.penalty.get(profile_name, self.penalty.get(ALL_PROFILES, 0.0))


def load_types(path: Path = DEFAULT_TYPES_PATH) -> dict[str, EventType]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    types = {}
    for name, spec in raw.items():
        unknown = set(spec) - {"label", "ttl_min", "block", "penalty", "record_only"}
        if unknown:
            raise ValueError(f"{name}: 정의되지 않은 설정 {sorted(unknown)}")
        types[name] = EventType(
            name=name, label=spec.get("label", name), ttl_min=spec.get("ttl_min"),
            block=tuple(spec.get("block", ())), penalty=dict(spec.get("penalty", {})),
            record_only=bool(spec.get("record_only", False)))
    return types


@dataclass
class Event:
    event_id: str
    type: str
    edge_id: str                              # graph의 간선 ID(역방향 ':rev' 아님). 양방향에 적용
    created_at: datetime
    expires_at: Optional[datetime] = None     # None이면 해제할 때까지
    status: str = "active"
    source: str = "manual"
    note: str = ""
    cleared_at: Optional[datetime] = None
    # 카메라 이벤트용. 지금은 간선 전체에 적용하고 아래 값은 저장만 한다.
    offset_from_m: Optional[float] = None
    offset_to_m: Optional[float] = None
    confidence: float = 1.0
    evidence: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.created_at = to_local(self.created_at)
        self.expires_at = None if self.expires_at is None else to_local(self.expires_at)
        self.cleared_at = None if self.cleared_at is None else to_local(self.cleared_at)
        if self.status not in STATUSES:
            raise ValueError(f"{self.event_id}: status '{self.status}' 미정의. 허용: {sorted(STATUSES)}")
        if self.source not in SOURCES:
            raise ValueError(f"{self.event_id}: source '{self.source}' 미정의. 허용: {sorted(SOURCES)}")
        if self.edge_id.endswith(":rev"):
            raise ValueError(f"{self.event_id}: 역방향 ID가 아니라 원래 간선 ID를 쓴다 ({self.edge_id})")
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError(f"{self.event_id}: expires_at이 created_at보다 늦어야 한다")

    def state_at(self, now: datetime) -> str:
        now = to_local(now)
        if now < self.created_at:
            return "pending"
        if self.status == "cleared" and (self.cleared_at is None or now >= self.cleared_at):
            return "cleared"
        if self.expires_at is not None and now >= self.expires_at:
            return "expired"
        if self.status in ("candidate", "confirmed"):
            return self.status
        return "active"

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id, "type": self.type, "edge_id": self.edge_id,
            "created_at": _iso(self.created_at), "expires_at": _iso(self.expires_at),
            "status": self.status, "source": self.source, "note": self.note,
            "cleared_at": _iso(self.cleared_at),
            "offset_from_m": self.offset_from_m, "offset_to_m": self.offset_to_m,
            "confidence": self.confidence, "evidence": list(self.evidence),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Event":
        d = dict(d)
        for key in ("created_at", "expires_at", "cleared_at"):
            d[key] = parse_time(d.get(key))
        return cls(**d)
