"""출입구 등록 웹앱(web/entrance)에서 모은 출입구를 경로 graph에 붙인다.

원칙
    0. 팀 결정(2026-11-27): 현장 등록에서 '모름'은 대부분 '없음'을 뜻한다. 그래서 기본 규칙은
       계단·문턱·경사로의 '모름'을 '없음'으로 읽는다(ASSUME_UNKNOWN_AS_NO). 원본 기록은 바꾸지 않고,
       어떤 값을 가정했는지 assumed에 남긴다. strict=True면 이 규칙을 끈다.
       '있음'인데 계단 단수·문턱 높이를 안 잰 경우는 가정하지 않는다(값을 지어낼 수 없음).
    1. 미확인은 미확인으로 둔다. '모름'을 0으로 바꾸거나, 재지 않은 계단 단수·문턱 높이를
       가정값으로 채우지 않는다. 경로 엔진의 간선은 계단 수와 문턱 높이에 빈 값을 둘 수 없으므로,
       하나라도 미확인인 출입구는 graph에 넣지 않고 '현장 보완 필요'로 남긴다.
    2. 보행로 연결은 사람이 확인한 뒤에만 만든다. 핀 주변 보행로 노드는 '후보'로만 내보내고,
       연결 확인 파일(links)에 적힌 노드와만 잇는다.

출입구 하나의 상태
    needs_survey  계단·문턱·경사로 중 미확인이 있다 (또는 '있음'인데 단수·높이를 안 쟀다)
    needs_link    값은 다 있는데 연결할 보행로를 아직 확인하지 않았다
    attached      graph에 출입구 노드와 연결 간선을 넣었다
    place         출입구가 아닌 장소(메모가 "[장소]"로 시작). graph에 넣지 않는다
    invalid       핀 좌표가 없거나, 확인한 노드가 graph에 없다
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from app.graph.buildings import Building, BuildingBook
from app.graph.geo import haversine_m
from app.graph.schema import Edge, Graph, Node

# 핀에서 이 거리 안의 보행로 노드를 연결 후보로 보여준다(m).
CANDIDATE_RADIUS_M = 25.0
MAX_CANDIDATES = 3

PLACE_TAG = "[장소]"

# '모름'을 '없음'으로 읽는 기본 규칙 (팀 결정)
ASSUME_UNKNOWN_AS_NO = True
ASSUMABLE = (("stairs", "계단"), ("threshold", "문턱"), ("ramp", "경사로"))


def apply_unknown_policy(record: dict, strict: bool = not ASSUME_UNKNOWN_AS_NO) -> tuple[dict, list[str]]:
    """'모름'을 '없음'으로 읽은 사본과 가정한 항목 목록. 원본 record는 바꾸지 않는다."""
    if strict:
        return record, []
    out, assumed = dict(record), []
    for key, label in ASSUMABLE:
        if out.get(key, "unknown") == "unknown":
            out[key] = "no"
            assumed.append(label)
    return out, assumed


def is_place(record: dict) -> bool:
    return (record.get("note") or "").startswith(PLACE_TAG)


DOOR_LABEL = {"automatic": "자동문", "button": "버튼식", "push": "미는 문", "pull": "당기는 문",
              "revolving": "회전문", "open": "문 없음", "unknown": "문 종류 모름"}


@dataclass
class EntranceReview:
    record_id: str
    node_id: str
    building: str
    entrance: str
    status: str
    missing: list[str] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)   # [{"node_id", "name", "distance_m"}]
    link: Optional[str] = None
    reason: str = ""
    assumed: list[str] = field(default_factory=list)   # '모름'을 '없음'으로 읽은 항목

    def to_dict(self) -> dict:
        return {"record_id": self.record_id, "node_id": self.node_id, "building": self.building,
                "entrance": self.entrance, "status": self.status, "missing": self.missing,
                "candidates": self.candidates, "link": self.link, "reason": self.reason,
                "assumed": self.assumed}


def node_id_for(record_id: str) -> str:
    return "ent_" + str(record_id).replace("-", "")[:10]


def _slug(text: str) -> str:
    s = re.sub(r"\s+", "_", text.strip())
    return re.sub(r"[^0-9A-Za-z_가-힣]", "", s) or "building"


def missing_items(record: dict) -> list[str]:
    """경로 판정에 필요한데 확인되지 않은 항목."""
    missing = []
    stairs = record.get("stairs", "unknown")
    count = record.get("stairs_count")
    if stairs == "unknown":
        missing.append("계단")
    elif stairs == "yes" and not (isinstance(count, (int, float)) and count > 0):
        missing.append("계단 단수")
    threshold = record.get("threshold", "unknown")
    cm = record.get("threshold_cm")
    if threshold == "unknown":
        missing.append("문턱")
    elif threshold == "yes" and not (isinstance(cm, (int, float)) and cm > 0):
        missing.append("문턱 높이")
    if record.get("ramp", "unknown") == "unknown":
        missing.append("경사로")
    return missing


def candidates_for(graph: Graph, lat: float, lon: float,
                   radius_m: float = CANDIDATE_RADIUS_M, limit: int = MAX_CANDIDATES) -> list[dict]:
    """핀 주변 보행로 노드(등록 출입구 노드 제외)를 가까운 순으로."""
    found = []
    for node in graph.nodes.values():
        if node.lat is None or node.lon is None or node.id.startswith("ent_"):
            continue
        d = haversine_m(lon, lat, node.lon, node.lat)
        if d <= radius_m:
            found.append({"node_id": node.id, "name": node.name, "distance_m": round(d, 1)})
    return sorted(found, key=lambda c: c["distance_m"])[:limit]


def connector_edge(record: dict, node_id: str, target: Node) -> Edge:
    """값이 모두 확인된 기록을 출입구 노드 → 확인된 보행로 노드 간선으로 바꾼다."""
    lat, lon = float(record["pin_lat"]), float(record["pin_lon"])
    door = DOOR_LABEL.get(record.get("door_type", "unknown"), "문 종류 모름")
    return Edge(
        id=node_id,
        from_node=node_id,
        to_node=target.id,
        distance_m=round(max(haversine_m(lon, lat, target.lon, target.lat), 0.5), 1),
        stairs=int(record["stairs_count"]) if record["stairs"] == "yes" else 0,
        ramp=record["ramp"] == "yes",
        threshold_cm=float(record["threshold_cm"]) if record["threshold"] == "yes" else 0.0,
        geometry=[[lon, lat], [target.lon, target.lat]],
        source="survey",
        verified_at=(record.get("recorded_at") or "")[:10] or None,
        note=f"웹앱 등록 · {door}" + (f" · 가정(모름→없음): {', '.join(assumed)}" if (assumed := record.get("_assumed")) else ""),
    )


def attach_entrances(graph: Graph, records: Iterable[dict], links: Optional[dict[str, str]] = None,
                     book: Optional[BuildingBook] = None,
                     radius_m: float = CANDIDATE_RADIUS_M,
                     strict: bool = not ASSUME_UNKNOWN_AS_NO) -> tuple[BuildingBook, list[EntranceReview]]:
    """확인이 끝난 기록만 graph에 붙인다. graph는 제자리에서 바뀐다.

    links: {기록 ID 또는 출입구 노드 ID: 확인한 보행로 노드 ID}
    돌려주는 리뷰 목록에는 모든 기록의 상태, 미확인 항목, 연결 후보가 들어 있다.
    """
    links = links or {}
    book = book if book is not None else BuildingBook()
    reviews = []
    for record in records:
        rid = str(record.get("id") or "")
        node_id = node_id_for(rid)
        building = (record.get("building_name") or "").strip() or "이름 없는 건물"
        entrance = (record.get("entrance_name") or "").strip()
        review = EntranceReview(rid, node_id, building, entrance, status="invalid")
        reviews.append(review)
        try:
            lat, lon = float(record["pin_lat"]), float(record["pin_lon"])
        except (KeyError, TypeError, ValueError):
            review.reason = "핀 좌표 없음"
            continue
        review.candidates = candidates_for(graph, lat, lon, radius_m)
        if is_place(record):
            review.status = "place"
            review.reason = "출입구가 아닌 장소"
            continue
        record, review.assumed = apply_unknown_policy(record, strict)
        record["_assumed"] = review.assumed
        review.missing = missing_items(record)
        review.link = links.get(rid) or links.get(node_id)
        if review.missing:
            review.status = "needs_survey"
            continue
        if not review.link:
            review.status = "needs_link"
            review.reason = "연결할 보행로 미확인" if review.candidates else f"{radius_m:.0f}m 안에 보행로 노드 없음"
            continue
        target = graph.nodes.get(review.link)
        if target is None or target.lat is None or target.lon is None:
            review.reason = f"확인한 노드 '{review.link}'가 graph에 없거나 좌표가 없음"
            continue
        if node_id in graph.nodes:
            review.status = "attached"
            review.reason = "이미 붙어 있음"
            continue
        graph.add_node(Node(id=node_id, name=f"{building} {entrance}".strip(), lat=lat, lon=lon, kind="entrance"))
        graph.add_edge(connector_edge(record, node_id, target))
        bid = record.get("building_id") or _slug(building)
        if bid not in book.buildings:
            book.buildings[bid] = Building(id=bid, name=building, entrances=[])
        book.buildings[bid].entrances.append(node_id)
        review.status = "attached"
    for b in book:
        if b.point is None and b.entrances:
            pts = [(graph.nodes[n].lon, graph.nodes[n].lat) for n in b.entrances if n in graph.nodes]
            if pts:
                b.point = [sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)]
    return book, reviews
