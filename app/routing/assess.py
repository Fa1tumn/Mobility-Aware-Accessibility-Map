"""간선 판정을 방향별로 한 번에 만든다(지도 색칠, 구간 정보용).

경사 간선은 방향에 따라 판정이 다르다. 예를 들어 오르막 한도가 낮은 프로필은
B→D 오르막은 못 가도 D→B 내리막은 갈 수 있다. 그래서 정방향·역방향을 따로 판정하고,
한 색으로 칠해야 할 때는 나쁜 쪽(worst)을 쓴다.

경로 탐색은 이 모듈을 거치지 않는다(verdict.py 설명 참고).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from app.graph.schema import Graph
from app.profile.definitions import Profile
from app.profile.verdict import Verdict, evaluate
from app.schedule.resolver import ScheduleBook

if TYPE_CHECKING:
    from app.events.overlay import EventOverlay

RANK = {"passable": 0, "difficult": 1, "impassable": 2}


@dataclass
class EdgeAssessment:
    edge_id: str
    forward: Verdict        # from_node → to_node
    backward: Verdict       # to_node → from_node

    @property
    def worst(self) -> Verdict:
        return self.backward if RANK[self.backward.level] > RANK[self.forward.level] else self.forward

    @property
    def symmetric(self) -> bool:
        return self.forward.level == self.backward.level


def assess_edges(
    graph: Graph,
    profile: Profile,
    when: Optional[datetime] = None,
    schedule: Optional[ScheduleBook] = None,
    events: Optional["EventOverlay"] = None,
) -> dict[str, EdgeAssessment]:
    out = {}
    for edge_id, e in graph.edges.items():
        out[edge_id] = EdgeAssessment(
            edge_id,
            forward=evaluate(e, profile, when, schedule, events),
            backward=evaluate(e.reversed(), profile, when, schedule, events))
    return out


def summarize(assessments: dict[str, EdgeAssessment]) -> dict[str, int]:
    """나쁜 쪽 기준 등급별 간선 수."""
    counts = {level: 0 for level in RANK}
    for a in assessments.values():
        counts[a.worst.level] += 1
    return counts
