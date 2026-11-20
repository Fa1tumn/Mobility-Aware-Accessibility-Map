"""건물 정의: 건물 하나에 출입구 노드 여러 개.

graph GeoJSON은 보행로 연결 구조만 담고, 건물은 별도 파일에 둔다
(GeoJSON 로더는 정의되지 않은 속성을 거부한다).

    {"buildings": [
        {"id": "library", "name": "언더우드기념도서관",
         "entrances": ["L1", "L2", "L3"],          ← graph의 노드 ID
         "point": [126.67, 37.38],                  ← 선택. 없으면 출입구 좌표 평균
         "outline": [[lon, lat], ...],              ← 선택. 지도에 그릴 윤곽
         "note": ""}
    ]}

출입구 운영 시간은 여기 두지 않는다. 출입구로 들어가는 간선의 entrance_id가
운영 시간 파일(app/schedule)을 가리킨다. 같은 정보를 두 곳에 적지 않기 위해서다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from app.graph.schema import Graph, SchemaError

ALLOWED = {"id", "name", "entrances", "point", "outline", "note"}


@dataclass
class Building:
    id: str
    name: str
    entrances: list[str]
    point: Optional[list[float]] = None          # [lon, lat]
    outline: Optional[list[list[float]]] = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "name": self.name, "entrances": list(self.entrances)}
        if self.point is not None:
            out["point"] = self.point
        if self.outline is not None:
            out["outline"] = self.outline
        if self.note:
            out["note"] = self.note
        return out


@dataclass
class BuildingBook:
    buildings: dict[str, Building] = field(default_factory=dict)

    def __getitem__(self, building_id: str) -> Building:
        if building_id not in self.buildings:
            raise KeyError(f"알 수 없는 건물 '{building_id}'. 사용 가능: {sorted(self.buildings)}")
        return self.buildings[building_id]

    def __iter__(self):
        return iter(self.buildings.values())

    def __len__(self) -> int:
        return len(self.buildings)

    def building_of(self, node_id: str) -> Optional[Building]:
        return next((b for b in self.buildings.values() if node_id in b.entrances), None)


def _centroid(graph: Graph, entrances: list[str]) -> Optional[list[float]]:
    pts = [(graph.nodes[n].lon, graph.nodes[n].lat) for n in entrances
           if graph.nodes[n].lon is not None and graph.nodes[n].lat is not None]
    if not pts:
        return None
    return [sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)]


def load_buildings(path: str | Path, graph: Graph) -> BuildingBook:
    """건물 파일을 읽고 graph와 맞는지 검사한다. 문제가 있으면 SchemaError."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    book = BuildingBook()
    owner: dict[str, str] = {}
    for i, row in enumerate(raw.get("buildings", [])):
        unknown = set(row) - ALLOWED
        if unknown:
            raise SchemaError(f"건물 {i}: 정의되지 않은 속성 {sorted(unknown)}")
        bid = row.get("id")
        if not bid:
            raise SchemaError(f"건물 {i}: id가 없다")
        if bid in book.buildings:
            raise SchemaError(f"건물 ID 중복: {bid}")
        entrances = list(row.get("entrances") or [])
        if not entrances:
            raise SchemaError(f"{bid}: 출입구가 하나 이상 있어야 한다")
        if len(set(entrances)) != len(entrances):
            raise SchemaError(f"{bid}: 같은 출입구가 두 번 적혀 있다")
        for node_id in entrances:
            if node_id not in graph.nodes:
                raise SchemaError(f"{bid}: 출입구 노드 '{node_id}'가 graph에 없다")
            if node_id in owner:
                raise SchemaError(f"출입구 '{node_id}'가 두 건물({owner[node_id]}, {bid})에 겹친다")
            owner[node_id] = bid
        point = row.get("point")
        if point is not None and (len(point) != 2 or not all(isinstance(v, (int, float)) for v in point)):
            raise SchemaError(f"{bid}: point는 [경도, 위도]")
        book.buildings[bid] = Building(
            id=bid, name=row.get("name", bid), entrances=entrances,
            point=point if point is not None else _centroid(graph, entrances),
            outline=row.get("outline"), note=row.get("note", ""))
    if not book.buildings:
        raise SchemaError("건물이 하나도 없다")
    return book


def save_buildings(book: BuildingBook, path: str | Path) -> None:
    data = {"buildings": [b.to_dict() for b in book]}
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
