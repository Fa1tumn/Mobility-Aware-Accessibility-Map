"""출입구 등록 웹앱(web/entrance)에서 모은 출입구를 경로 graph에 붙인다.

웹앱 기록 한 건 → 출입구 노드 하나(kind="entrance", 위치는 사용자가 맞춘 핀)
               + 가장 가까운 보행로 노드와 잇는 연결 간선 하나
               + 건물 파일(BuildingBook)의 출입구 목록에 추가

계단·문턱·경사로는 연결 간선에 싣는다. 경로 엔진의 통행 판정(feasibility)이
간선 속성을 보기 때문이다.

'모름'은 '없음'으로 바꾸지 않는다. 값은 0으로 두되 간선 confidence를 낮추고
note에 미확인 항목을 적어, 불확실성 비용과 화면 표시에서 드러나게 한다.
'문턱 있음'인데 높이를 재지 않았으면 ASSUMED_THRESHOLD_CM(휠체어 한도 2cm보다 높음)을
쓴다. 잰 값이 들어올 때까지 휠체어 경로에서 그 문을 쓰지 않게 하려는 보수적 가정이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from app.graph.buildings import Building, BuildingBook
from app.graph.geo import haversine_m
from app.graph.schema import Edge, Graph, Node

# 핀에서 이 거리 안의 보행로 노드에만 잇는다(m). 더 멀면 graph에 길을 먼저 그려야 한다.
MAX_CONNECT_M = 25.0

# 문턱은 있는데 높이를 재지 않은 경우의 가정값(cm). 휠체어 한도(2cm)보다 높게 둔다.
ASSUMED_THRESHOLD_CM = 3.0

# 미확인 항목 하나마다 연결 간선 confidence에서 빼는 값
UNKNOWN_PENALTY = 0.25

DOOR_LABEL = {"automatic": "자동문", "button": "버튼식", "push": "미는 문", "pull": "당기는 문",
              "revolving": "회전문", "open": "문 없음", "unknown": "문 종류 모름"}


@dataclass
class AttachReport:
    added: list[str] = field(default_factory=list)                # 붙인 출입구 노드 ID
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (기록 ID, 이유)


def _slug(text: str) -> str:
    s = re.sub(r"\s+", "_", text.strip())
    return re.sub(r"[^0-9A-Za-z_가-힣]", "", s) or "building"


def _short(record_id: str) -> str:
    return "ent_" + str(record_id).replace("-", "")[:10]


def _nearest(graph: Graph, lat: float, lon: float) -> tuple[Optional[str], float]:
    best, best_d = None, float("inf")
    for node in graph.nodes.values():
        if node.lat is None or node.lon is None or node.kind == "entrance" and node.id.startswith("ent_"):
            continue
        d = haversine_m(lon, lat, node.lon, node.lat)
        if d < best_d:
            best, best_d = node.id, d
    return best, best_d


def connector_edge(record: dict, node_id: str, target: Node, distance_m: float) -> Edge:
    """기록 한 건을 출입구 노드 → 보행로 노드 연결 간선으로 바꾼다."""
    unknown = []

    stairs = record.get("stairs", "unknown")
    if stairs == "yes":
        count = record.get("stairs_count")
        stairs_n = int(count) if isinstance(count, (int, float)) and count > 0 else 1
        if not (isinstance(count, (int, float)) and count > 0):
            unknown.append("계단 단수")
    else:
        stairs_n = 0
        if stairs != "no":
            unknown.append("계단")

    threshold = record.get("threshold", "unknown")
    if threshold == "yes":
        cm = record.get("threshold_cm")
        if isinstance(cm, (int, float)) and cm >= 0:
            threshold_cm = float(cm)
        else:
            threshold_cm = ASSUMED_THRESHOLD_CM
            unknown.append("문턱 높이")
    else:
        threshold_cm = 0.0
        if threshold != "no":
            unknown.append("문턱")

    ramp = record.get("ramp") == "yes"
    if record.get("ramp", "unknown") == "unknown":
        unknown.append("경사로")

    door = DOOR_LABEL.get(record.get("door_type", "unknown"), "문 종류 모름")
    note = f"웹앱 등록 · {door}"
    if unknown:
        note += " · 미확인: " + ", ".join(unknown)
    return Edge(
        id=node_id,
        from_node=node_id,
        to_node=target.id,
        distance_m=round(max(distance_m, 0.5), 1),
        stairs=stairs_n,
        ramp=ramp,
        threshold_cm=threshold_cm,
        geometry=[[record["pin_lon"], record["pin_lat"]], [target.lon, target.lat]],
        source="survey",
        confidence=max(0.1, 1.0 - UNKNOWN_PENALTY * len(unknown)),
        verified_at=(record.get("recorded_at") or "")[:10] or None,
        note=note,
    )


def attach_entrances(graph: Graph, records: Iterable[dict], book: Optional[BuildingBook] = None,
                     max_connect_m: float = MAX_CONNECT_M) -> tuple[BuildingBook, AttachReport]:
    """기록들을 graph에 붙이고 건물 목록을 돌려준다. graph는 제자리에서 바뀐다."""
    book = book if book is not None else BuildingBook()
    report = AttachReport()
    for record in records:
        rid = str(record.get("id") or "")
        try:
            lat, lon = float(record["pin_lat"]), float(record["pin_lon"])
        except (KeyError, TypeError, ValueError):
            report.skipped.append((rid, "핀 좌표 없음"))
            continue
        node_id = _short(rid)
        if node_id in graph.nodes:
            report.skipped.append((rid, "이미 붙어 있음"))
            continue
        target_id, distance = _nearest(graph, lat, lon)
        if target_id is None or distance > max_connect_m:
            report.skipped.append((rid, f"가까운 보행로 노드 없음 ({distance:.0f}m > {max_connect_m:.0f}m)"
                                   if target_id else "graph에 좌표 있는 노드 없음"))
            continue
        building_name = (record.get("building_name") or "").strip() or "이름 없는 건물"
        entrance_name = (record.get("entrance_name") or "").strip()
        graph.add_node(Node(id=node_id, name=f"{building_name} {entrance_name}".strip(),
                            lat=lat, lon=lon, kind="entrance"))
        graph.add_edge(connector_edge(record, node_id, graph.nodes[target_id], distance))
        bid = record.get("building_id") or _slug(building_name)
        if bid not in book.buildings:
            book.buildings[bid] = Building(id=bid, name=building_name, entrances=[])
        book.buildings[bid].entrances.append(node_id)
        report.added.append(node_id)
    for b in book:
        if b.point is None and b.entrances:
            pts = [(graph.nodes[n].lon, graph.nodes[n].lat) for n in b.entrances]
            b.point = [sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)]
    return book, report
