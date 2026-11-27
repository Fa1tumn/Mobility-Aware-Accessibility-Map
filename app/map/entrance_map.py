"""등록한 출입구를 캠퍼스 지도 데이터로 정리한다.

    기록(Supabase entrances) + 건물 목록(web/entrance/buildings.json)
        → 출입구 GeoJSON (data/campus/entrances.geojson): 경로·네비게이션이 읽는 출입구 위치와 상태
        → 지도 HTML (output/entrances/entrance_map.html): 건물 윤곽, 출입구 점, 사진 팝업

출입구마다 상태를 하나 붙인다.
    complete      계단·문턱·경사로 값이 모두 있다 (있음이면 단수·높이까지)
    needs_survey  값을 지어낼 수 없는 항목이 있다('있음'인데 단수·높이 미입력, strict면 '모름'도)
    place         출입구가 아닌 장소 (메모가 "[장소]"로 시작)
팀 결정에 따라 '모름'은 '없음'으로 읽고(assumed에 기록, 원본은 그대로), 잰 적 없는 숫자는 채우지 않는다.

휠체어 사용자 접근 불편 (팀 결정 2026-11-27)
    계단 있음 · 문턱 있음(높이와 상관없이) · 이름/메모에 '계단실' → wheelchair.recommended = False
    단, 경사로가 있으면 계단·문턱을 피해 갈 수 있으므로 불편으로 보지 않는다.
    이 경우 계단 단수·문턱 높이를 안 쟀어도 휠체어 판정에는 충분하므로 needs_survey로 보지 않고,
    잰 적 없는 값은 unmeasured에 남긴다(amount는 null).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from app.graph.registered_entrances import apply_unknown_policy, is_place, missing_items

TEMPLATE = Path(__file__).with_name("entrance_map.html")
DOOR_LABEL = {"automatic": "자동문", "button": "버튼식", "push": "미는 문", "pull": "당기는 문",
              "revolving": "회전문", "open": "문 없음", "unknown": "모름"}


AMOUNT_ONLY = {"계단 단수", "문턱 높이"}


def wheelchair_assessment(record: dict) -> dict:
    reasons = []
    if record.get("stairs") == "yes":
        n = record.get("stairs_count")
        reasons.append(f"계단 {n}단" if isinstance(n, (int, float)) and n > 0 else "계단 있음")
    if record.get("threshold") == "yes":
        cm = record.get("threshold_cm")
        reasons.append(f"문턱 {cm:g}cm" if isinstance(cm, (int, float)) and cm > 0 else "문턱 있음")
    text = f"{record.get('entrance_name') or ''} {record.get('note') or ''}"
    if "계단실" in text:
        reasons.append("계단실 출입구")
    if record.get("ramp") == "yes":
        reasons = []                  # 경사로로 우회 가능
    return {"recommended": not reasons, "reasons": reasons}


def entrance_status(record: dict) -> tuple[str, list[str], list[str]]:
    """(상태, 미확인 항목, 잰 적 없지만 판정에는 충분한 항목)."""
    if is_place(record):
        return "place", [], []
    missing = missing_items(record)
    excluded = not wheelchair_assessment(record)["recommended"]
    unmeasured = [m for m in missing if excluded and m in AMOUNT_ONLY]
    missing = [m for m in missing if m not in unmeasured]
    return ("needs_survey" if missing else "complete"), missing, unmeasured


def _value(record: dict, key: str, amount_key: str, assumed: list[str], label: str):
    v = _raw_value(record, key, amount_key)
    if label in assumed:
        v["assumed"] = True
    return v


def _raw_value(record: dict, key: str, amount_key: str):
    """있음/없음/모름을 그대로 두고, 있음이면 잰 값을 붙인다. 모름은 None."""
    state = record.get(key, "unknown")
    if state == "no":
        return {"state": "no", "amount": 0}
    if state == "yes":
        amount = record.get(amount_key)
        return {"state": "yes", "amount": amount if isinstance(amount, (int, float)) and amount > 0 else None}
    return {"state": "unknown", "amount": None}


def to_feature(record: dict, photo_base: str = "", strict: bool = False) -> dict:
    original = record
    record, assumed = apply_unknown_policy(record, strict or is_place(record))
    status, missing, unmeasured = entrance_status(record)
    photo = record.get("photo_path")
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [record["pin_lon"], record["pin_lat"]]},
        "properties": {
            "id": record["id"],
            "kind": "place" if status == "place" else "entrance",
            "status": status,
            "missing": missing,
            "unmeasured": unmeasured,
            "wheelchair": None if status == "place" else wheelchair_assessment(record),
            "building_id": record.get("building_id"),
            "building_name": record.get("building_name"),
            "entrance_name": record.get("entrance_name"),
            "assumed": assumed,
            "recorded_as": {k: original.get(k, "unknown") for k in ("stairs", "threshold", "ramp")},
            "stairs": _value(record, "stairs", "stairs_count", assumed, "계단"),
            "threshold_cm": _value(record, "threshold", "threshold_cm", assumed, "문턱"),
            "ramp": record.get("ramp", "unknown"),
            "door_type": record.get("door_type", "unknown"),
            "opening_hours": record.get("opening_hours"),
            "note": record.get("note"),
            "photo_url": f"{photo_base.rstrip('/')}/{photo}" if photo and photo_base else photo,
            "gps": None if record.get("gps_lat") is None else {
                "lat": record["gps_lat"], "lon": record["gps_lon"], "accuracy_m": record.get("gps_accuracy_m")},
            "pin_moved_m": record.get("pin_moved_m"),
            "recorded_at": record.get("recorded_at"),
            "recorder": record.get("recorder"),
        },
    }


def build_collection(records: list[dict], photo_base: str = "", strict: bool = False) -> dict:
    features = [to_feature(r, photo_base, strict) for r in records
                if isinstance(r.get("pin_lat"), (int, float)) and isinstance(r.get("pin_lon"), (int, float))]
    counts = Counter(f["properties"]["status"] for f in features)
    excluded = sum(1 for f in features if f["properties"]["wheelchair"] and not f["properties"]["wheelchair"]["recommended"])
    return {
        "type": "FeatureCollection",
        "properties": {"count": len(features), "status_counts": dict(counts),
                       "wheelchair_excluded": excluded,
                       "assumed_unknown_as_no": not strict,
                       "assumed_features": sum(bool(f["properties"]["assumed"]) for f in features),
                       "note": ("'모름'은 '없음'으로 읽음(팀 결정). 해당 값에 assumed=true, 원래 입력은 recorded_as. "
                                "'있음'인데 잰 값이 없으면 amount=null로 비워 둔다.") if not strict else
                               "미확인 값은 비워 둔다(state=unknown, amount=null)."},
        "features": features,
    }


def save_map(collection: dict, buildings: list[dict], path: Path, title: str) -> Path:
    payload = {"title": title, "entrances": collection, "buildings": buildings, "door_label": DOOR_LABEL}
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE.read_text(encoding="utf-8").replace("__ENTRANCE_DATA__", data), encoding="utf-8")
    return path
