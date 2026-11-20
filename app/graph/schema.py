"""Route graph 스키마.

모든 모듈이 공유하는 데이터 계약. 여기가 바뀌면 나머지가 전부 바뀌므로
필드 추가는 신중하게, 삭제는 하지 않는다.

주의: 이 Edge는 **의미 단위** 구간이다. 노드는 분기점, 출입구, 계단 끝처럼
속성이 바뀌는 지점에 둔다. trajectory 모듈의 20m 분석 윈도우와는 다른 개념이며,
서로 1:1로 대응하지 않는다. 섞으면 GPS 샘플링을 바꿀 때 그래프가 깨진다.

단위 규약 (혼동 방지를 위해 필드명에 단위를 넣는다):
    distance_m     미터
    slope_pct      경사율(%). 데이터의 기본 단위. from→to 방향 오르막이 +, 내리막이 -
    slope_deg      도(degree). slope_pct와 같은 값의 각도 표현(엔진 내부 비교용)
    threshold_cm   센티미터
    stairs         계단 단수(개수). 0이면 계단 없음
    geometry       [[경도, 위도], ...]. from_node에서 to_node 순서(GeoJSON 좌표 순서)

slope_pct와 slope_deg 중 하나만 주면 나머지는 자동으로 채운다. 둘 다 주면
같은 값이어야 한다. 역방향으로 지날 때는 둘 다 부호가 뒤집히고 geometry도 뒤집힌다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Optional

from app.graph.geo import deg_to_pct, pct_to_deg

# slope_pct와 slope_deg를 함께 줄 때 허용하는 불일치(도)
SLOPE_SYNC_TOLERANCE_DEG = 0.05

# 간선 geometry 끝점과 노드 좌표 사이에 허용하는 거리(m)
GEOMETRY_ENDPOINT_TOLERANCE_M = 5.0

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
    slope_pct: Optional[float] = None     # 미측정이면 None. 데이터 파일은 이 필드를 쓴다

    # --- 위치 ---
    geometry: Optional[list[list[float]]] = None   # [[lon, lat], ...] from→to

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
        self._sync_slope()
        if self.geometry is not None:
            if len(self.geometry) < 2 or any(len(p) < 2 for p in self.geometry):
                raise SchemaError(f"{self.id}: geometry는 [[lon, lat], ...] 형식의 점 2개 이상")
            self.geometry = [[float(p[0]), float(p[1])] for p in self.geometry]

    def _sync_slope(self) -> None:
        """slope_pct와 slope_deg를 같은 값으로 맞춘다."""
        if self.slope_pct is not None and not math.isfinite(self.slope_pct):
            raise SchemaError(f"{self.id}: slope_pct가 유한한 수가 아니다")
        if self.slope_deg is not None and not (math.isfinite(self.slope_deg) and abs(self.slope_deg) < 90):
            raise SchemaError(f"{self.id}: slope_deg는 -90~90 사이여야 한다 ({self.slope_deg})")
        if self.slope_pct is not None and self.slope_deg is None:
            self.slope_deg = pct_to_deg(self.slope_pct)
        elif self.slope_deg is not None and self.slope_pct is None:
            self.slope_pct = deg_to_pct(self.slope_deg)
        elif self.slope_pct is not None and self.slope_deg is not None:
            if abs(pct_to_deg(self.slope_pct) - self.slope_deg) > SLOPE_SYNC_TOLERANCE_DEG:
                raise SchemaError(
                    f"{self.id}: slope_pct {self.slope_pct}%와 slope_deg {self.slope_deg}°가 다르다")

    @property
    def abs_slope_deg(self) -> Optional[float]:
        """미측정이면 None. None은 '평평하다'가 아니라 '모른다'이다."""
        return None if self.slope_deg is None else abs(self.slope_deg)

    @property
    def abs_slope_pct(self) -> Optional[float]:
        """미측정이면 None."""
        return None if self.slope_pct is None else abs(self.slope_pct)

    @property
    def is_uphill(self) -> bool:
        return self.slope_deg is not None and self.slope_deg > 0

    @property
    def base_id(self) -> str:
        """역방향 간선(':rev')이면 원래 간선 ID."""
        return self.id[:-4] if self.id.endswith(":rev") else self.id

    @property
    def is_reverse(self) -> bool:
        return self.id.endswith(":rev")

    def reversed(self) -> "Edge":
        """반대 방향으로 지날 때의 간선. 경사 부호와 geometry를 뒤집고 ID에 ':rev'를 붙인다."""
        if self.is_reverse:
            raise SchemaError(f"{self.id}: 이미 역방향 간선이다")
        return Edge(**{**asdict(self),
                       "id": self.id + ":rev",
                       "from_node": self.to_node,
                       "to_node": self.from_node,
                       "slope_deg": None if self.slope_deg is None else -self.slope_deg,
                       "slope_pct": None if self.slope_pct is None else -self.slope_pct,
                       "geometry": None if self.geometry is None else list(reversed(self.geometry))})


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
        from app.graph.geo import haversine_m

        problems = []
        for e in self.edges.values():
            if e.from_node not in self.nodes:
                problems.append(f"{e.id}: from_node '{e.from_node}' 없음")
            if e.to_node not in self.nodes:
                problems.append(f"{e.id}: to_node '{e.to_node}' 없음")
            if e.geometry is None:
                continue
            for end, node_id in ((e.geometry[0], e.from_node), (e.geometry[-1], e.to_node)):
                n = self.nodes.get(node_id)
                if n is None or n.lat is None or n.lon is None:
                    continue
                gap = haversine_m(end[0], end[1], n.lon, n.lat)
                if gap > GEOMETRY_ENDPOINT_TOLERANCE_M:
                    problems.append(
                        f"{e.id}: geometry 끝점이 노드 {node_id}에서 {gap:.1f}m 떨어져 있음 "
                        f"(허용 {GEOMETRY_ENDPOINT_TOLERANCE_M:.0f}m)")
        return problems

    def outgoing(self, node_id: str) -> list[Edge]:
        """무향 그래프로 취급한다. 역방향 통행 시 slope 부호와 geometry를 뒤집어 돌려준다."""
        out = []
        for e in self.edges.values():
            if e.from_node == node_id:
                out.append(e)
            elif e.to_node == node_id:
                out.append(e.reversed())
        return out
