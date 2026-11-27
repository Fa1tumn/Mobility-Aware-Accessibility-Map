"""출입구 지도 데이터: 미확인은 비워 두고, 장소는 출입구와 구분한다."""

import json
import re

from app.map.entrance_map import build_collection, save_map


def rec(rid, **kw):
    row = {"id": rid, "pin_lat": 37.38, "pin_lon": 126.67, "building_id": "b1", "building_name": "진리관 C",
           "entrance_name": "정문", "stairs": "no", "ramp": "no", "threshold": "no", "door_type": "pull",
           "photo_path": "2026-11-27/x.jpg", "gps_lat": 37.38001, "gps_lon": 126.67, "gps_accuracy_m": 4.0}
    row.update(kw)
    return row


def test_status_and_unknown_kept_empty():
    fc = build_collection([rec("a"), rec("b", stairs="yes", threshold="unknown"),
                           rec("c", note="[장소] 셔틀버스 정류장")], "https://x/storage/v1/object/public/entrance-photos")
    props = {f["properties"]["id"]: f["properties"] for f in fc["features"]}
    assert props["a"]["status"] == "complete"
    # 계단이 있으면 휠체어 추천에서 빠지므로 단수 미측정은 조사 필요가 아닌 '측정 불필요'로 둔다
    assert props["b"]["status"] == "complete"
    assert props["b"]["missing"] == [] and props["b"]["unmeasured"] == ["계단 단수"]
    assert props["b"]["stairs"] == {"state": "yes", "amount": None}
    assert props["b"]["threshold_cm"] == {"state": "no", "amount": 0, "assumed": True}
    assert props["b"]["assumed"] == ["문턱"] and props["b"]["recorded_as"]["threshold"] == "unknown"
    assert props["a"]["threshold_cm"] == {"state": "no", "amount": 0}
    assert props["c"]["kind"] == "place" and props["c"]["status"] == "place"
    assert props["a"]["photo_url"].endswith("/entrance-photos/2026-11-27/x.jpg")
    assert fc["properties"]["status_counts"] == {"complete": 2, "place": 1}


def test_map_html_embeds_data_safely(tmp_path):
    fc = build_collection([rec("a", note="</script><script>alert(1)</script>")])
    out = save_map(fc, [{"id": "b1", "name": "진리관 C", "named": True, "point": [126.67, 37.38],
                         "outline": [[126.67, 37.38], [126.6701, 37.38], [126.6701, 37.3801]]}], tmp_path / "m.html", "t")
    html = out.read_text(encoding="utf-8")
    assert "__ENTRANCE_DATA__" not in html and "</script><script>alert" not in html
    data = json.loads(re.search(r'<script id="entrance-data" type="application/json">(.*?)</script>', html, re.S).group(1))
    assert data["entrances"]["features"][0]["properties"]["note"].startswith("</script>")


def test_strict_mode_keeps_unknown():
    fc = build_collection([rec("b", threshold="unknown")], strict=True)
    p = fc["features"][0]["properties"]
    assert p["status"] == "needs_survey" and p["threshold_cm"] == {"state": "unknown", "amount": None}
    assert p["assumed"] == []


def test_wheelchair_exclusion_rules():
    fc = build_collection([
        rec("ok"),
        rec("st", stairs="yes", stairs_count=2),
        rec("th", threshold="yes"),                                   # 높이 미측정
        rec("room", entrance_name="자유관A 계단실 출입구"),
    ])
    p = {f["properties"]["id"]: f["properties"] for f in fc["features"]}
    assert p["ok"]["wheelchair"] == {"recommended": True, "reasons": []}
    assert p["st"]["wheelchair"]["reasons"] == ["계단 2단"]
    assert p["th"]["wheelchair"]["reasons"] == ["문턱 있음"]
    assert p["th"]["status"] == "complete" and p["th"]["unmeasured"] == ["문턱 높이"]
    assert p["th"]["threshold_cm"]["amount"] is None                   # 높이를 지어내지 않음
    assert p["room"]["wheelchair"]["reasons"] == ["계단실 출입구"]
    assert fc["properties"]["wheelchair_excluded"] == 3
