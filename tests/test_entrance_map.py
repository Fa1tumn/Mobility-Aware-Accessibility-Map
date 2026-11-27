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
    assert props["b"]["status"] == "needs_survey"
    assert props["b"]["missing"] == ["계단 단수", "문턱"]
    assert props["b"]["stairs"] == {"state": "yes", "amount": None}
    assert props["b"]["threshold_cm"] == {"state": "unknown", "amount": None}
    assert props["a"]["threshold_cm"] == {"state": "no", "amount": 0}
    assert props["c"]["kind"] == "place" and props["c"]["status"] == "place"
    assert props["a"]["photo_url"].endswith("/entrance-photos/2026-11-27/x.jpg")
    assert fc["properties"]["status_counts"] == {"complete": 1, "needs_survey": 1, "place": 1}


def test_map_html_embeds_data_safely(tmp_path):
    fc = build_collection([rec("a", note="</script><script>alert(1)</script>")])
    out = save_map(fc, [{"id": "b1", "name": "진리관 C", "named": True, "point": [126.67, 37.38],
                         "outline": [[126.67, 37.38], [126.6701, 37.38], [126.6701, 37.3801]]}], tmp_path / "m.html", "t")
    html = out.read_text(encoding="utf-8")
    assert "__ENTRANCE_DATA__" not in html and "</script><script>alert" not in html
    data = json.loads(re.search(r'<script id="entrance-data" type="application/json">(.*?)</script>', html, re.S).group(1))
    assert data["entrances"]["features"][0]["properties"]["note"].startswith("</script>")
