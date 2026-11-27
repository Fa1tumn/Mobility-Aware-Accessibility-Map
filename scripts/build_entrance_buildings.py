"""출입구 등록 웹앱에서 고를 건물 목록을 만든다.

OpenStreetMap에서 받은 건물 윤곽(Overpass `out geom` JSON) 중 캠퍼스 사각형
(config/campus_grid.json) 안이나 가장자리 MARGIN_M 안에 중심이 있는 건물을 골라
web/entrance/buildings.json에 저장한다. 이름이 숫자뿐인 건물(캠퍼스 밖 아파트 동 번호)은 뺀다.
OSM에 이름이 없는 건물은 web/entrance/building_names.json({"<way id>": "이름"})으로 이름을 붙인다.

    curl --data-urlencode 'data=[out:json];way["building"](37.3768,126.6648,37.3868,126.6780);out geom tags;' \
        https://overpass-api.de/api/interpreter -o osm_buildings.json
    python -m scripts.build_entrance_buildings osm_buildings.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.map.campus_grid import load_campus_grid

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "web" / "entrance" / "buildings.json"
DEFAULT_NAMES = ROOT / "web" / "entrance" / "building_names.json"

# 캠퍼스 사각형 가장자리 밖으로 이 거리 안의 건물도 넣는다(m). 경계에 걸친 캠퍼스 건물용.
MARGIN_M = 60.0


def inside_campus(campus, lat: float, lon: float, margin_m: float = 0.0) -> bool:
    down, across = campus.to_grid_offsets(lat, lon)
    return (-margin_m <= down <= campus.map_length + margin_m
            and -margin_m <= across <= campus.map_width + margin_m)


def convert(osm: dict, campus, names: dict | None = None, margin_m: float = MARGIN_M) -> list[dict]:
    names = names or {}
    buildings = []
    for way in osm.get("elements", []):
        if way.get("type") != "way" or not way.get("geometry"):
            continue
        outline = [[round(p["lon"], 7), round(p["lat"], 7)] for p in way["geometry"]]
        lon = sum(p[0] for p in outline) / len(outline)
        lat = sum(p[1] for p in outline) / len(outline)
        if not inside_campus(campus, lat, lon, margin_m):
            continue
        tags = way.get("tags", {})
        name = names.get(str(way["id"])) or tags.get("name:ko") or tags.get("name") or ""
        if name.isdigit():
            continue
        buildings.append({
            "id": f"osm_way_{way['id']}",
            "name": name or f"이름 없는 건물 ({way['id']})",
            "named": bool(name),
            "point": [round(lon, 7), round(lat, 7)],
            "outline": outline,
        })
    buildings.sort(key=lambda b: (not b["named"], b["name"]))
    return buildings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="웹앱용 캠퍼스 건물 목록 생성")
    parser.add_argument("osm_json", type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--names", type=Path, default=DEFAULT_NAMES, help="OSM에 이름 없는 건물의 이름")
    parser.add_argument("--margin-m", type=float, default=MARGIN_M)
    args = parser.parse_args(argv)
    osm = json.loads(args.osm_json.read_text(encoding="utf-8"))
    names = json.loads(args.names.read_text(encoding="utf-8")).get("names", {}) if args.names.is_file() else {}
    buildings = convert(osm, load_campus_grid(), names, args.margin_m)
    payload = {
        "source": "OpenStreetMap contributors (ODbL), building ways in/near config/campus_grid.json",
        "buildings": buildings,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    named = sum(b["named"] for b in buildings)
    print(f"건물 {len(buildings)}개 (이름 있음 {named}개) → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
