"""Route graph 스키마.

모든 모듈이 공유하는 데이터 계약. 여기가 바뀌면 나머지가 전부 바뀌므로
필드 추가는 신중하게, 삭제는 하지 않는다.

주의: 이 Edge는 **의미 단위** 구간이다. 노드는 분기점, 출입구, 계단 끝처럼
속성이 바뀌는 지점에 둔다. trajectory 모듈의 20m 분석 윈도우와는 다른 개념이며,
서로 1:1로 대응하지 않는다. 섞으면 GPS 샘플링을 바꿀 때 그래프가 깨진다.

단위 규약 (혼동 방지를 위해 필드명에 단위를 넣는다):
    distance_m     미터
    slope_deg      도(degree). 진행 방향 오르막이 +, 내리막이 -
    threshold_cm   센티미터
    stairs         계단 단수(개수). 0이면 계단 없음
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

# 허용값
SURFACES = {"unknown", "asphalt", "block", "tile", "concrete", "tactile", "damaged"}
WIDTHS = {"unknown", "narrow", "normal", "wide"}
ENVS = {"outdoor", "indoor", "underground"}


class SchemaError(ValueError):
    """스키마 위반."""


@dataclass
class Node:
    id: str
    name: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    level: int = 0            # 층. 지상 0, 지하 -1
    kind: str = "junction"    # junction | entrance | destination | stair_end

    def __post_init__(self) -> None:
        if not self.id:
            raise SchemaError("Node.id는 비울 수 없다")


@dataclass
class Edge:
    """두 노드를 잇는 통행 구간. 방향이 있다(from -> to)."""

    id: str
    from_node: str
    to_node: str
    distance_m: float

    # --- 현장 실측 ---
    stairs: int = 0                       # 단수
    ramp: bool = False                    # 경사로 존재 여부
    threshold_cm: float = 0.0             # 문턱 높이
    slope_deg: Optional[float] = None     # 미측정이면 None

    # --- 카메라 추정 ---
    surface: str = "unknown"
    width_level: str = "unknown"

    # --- 환경 ---
    env: str = "outdoor"
    entrance_id: Optional[str] = None     # schedule 참조 키

    # --- 메타 ---
    source: str = "unknown"               # gps | survey | camera | official | unknown
    confidence: float = 1.0               # 0~1. 관측 횟수·품질 기반
    verified_at: Optional[str] = None     # ISO 날짜
    note: str = ""

    def __post_init__(self) -> None:
        if self.distance_m < 0:
            raise SchemaError(f"{self.id}: distance_m은 음수일 수 없다 ({self.distance_m})")
        if self.stairs < 0:
            raise SchemaError(f"{self.id}: stairs는 음수일 수 없다 ({self.stairs})")
        if self.threshold_cm < 0:
            raise SchemaError(f"{self.id}: threshold_cm은 음수일 수 없다")
        if self.surface not in SURFACES:
            raise SchemaError(f"{self.id}: surface '{self.surface}' 미정의. 허용: {sorted(SURFACES)}")
        if self.width_level not in WIDTHS:
            raise SchemaError(f"{self.id}: width_level '{self.width_level}' 미정의")
        if self.env not in ENVS:
            raise SchemaError(f"{self.id}: env '{self.env}' 미정의")
        if not 0.0 <= self.confidence <= 1.0:
            raise SchemaError(f"{self.id}: confidence는 0~1 ({self.confidence})")

    @property
    def abs_slope_deg(self) -> Optional[float]:
        """미측정이면 None. None은 '평평하다'가 아니라 '모른다'이다."""
        return None if self.slope_deg is None else abs(self.slope_deg)

    @property
    def is_uphill(self) -> bool:
        return self.slope_deg is not None and self.slope_deg > 0


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[str, Edge] = field(default_factory=dict)

    def add_node(self, n: Node) -> None:
        self.nodes[n.id] = n

    def add_edge(self, e: Edge) -> None:
        self.edges[e.id] = e

    def validate(self) -> list[str]:
        """참조 무결성 확인. 문제 목록을 돌려준다(예외 아님)."""
        problems = []
        for e in self.edges.values():
            if e.from_node not in self.nodes:
                problems.append(f"{e.id}: from_node '{e.from_node}' 없음")
            if e.to_node not in self.nodes:
                problems.append(f"{e.id}: to_node '{e.to_node}' 없음")
        return problems

    def outgoing(self, node_id: str) -> list[Edge]:
        """무향 그래프로 취급한다. 역방향 통행 시 slope 부호를 뒤집어 돌려준다."""
        out = []
        for e in self.edges.values():
            if e.from_node == node_id:
                out.append(e)
            elif e.to_node == node_id:
                rev = Edge(**{**asdict(e),
                              "id": e.id + ":rev",
                              "from_node": e.to_node,
                              "to_node": e.from_node,
                              "slope_deg": None if e.slope_deg is None else -e.slope_deg})
                out.append(rev)
        return out
