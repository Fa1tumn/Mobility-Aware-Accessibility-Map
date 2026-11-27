"""등록한 출입구를 받아 출입구 GeoJSON과 지도 HTML을 만든다.

    python -m scripts.entrance_map                      # Supabase에서 받기 (.env)
    python -m scripts.entrance_map --input data/campus/entrances_registered.json
    python -m scripts.open_grid output/entrances/entrance_map.html --port 8783
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.map.entrance_map import build_collection, save_map

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="출입구 GeoJSON과 지도 만들기")
    parser.add_argument("--input", type=Path, help="Supabase 대신 읽을 기록 JSON")
    parser.add_argument("--save-raw", type=Path, default=ROOT / "data/campus/entrances_registered.json")
    parser.add_argument("--geojson", type=Path, default=ROOT / "data/campus/entrances.geojson")
    parser.add_argument("--html", type=Path, default=ROOT / "output/entrances/entrance_map.html")
    parser.add_argument("--buildings", type=Path, default=ROOT / "web/entrance/buildings.json")
    parser.add_argument("--strict", action="store_true", help="'모름'을 '없음'으로 읽지 않기")
    args = parser.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        url = os.getenv("SUPABASE_URL", "").strip().rstrip("/").removesuffix("/rest/v1")
        photo_base = f"{url}/storage/v1/object/public/entrance-photos" if url else ""
        if args.input:
            records = json.loads(args.input.read_text(encoding="utf-8"))
        else:
            from scripts.import_entrances import fetch_entrances
            records = fetch_entrances()
            args.save_raw.parent.mkdir(parents=True, exist_ok=True)
            args.save_raw.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        collection = build_collection(records, photo_base, args.strict)
        args.geojson.parent.mkdir(parents=True, exist_ok=True)
        args.geojson.write_text(json.dumps(collection, ensure_ascii=False, indent=2), encoding="utf-8")
        buildings = json.loads(args.buildings.read_text(encoding="utf-8"))["buildings"]
        save_map(collection, buildings, args.html, "캠퍼스 출입구 지도")
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    print(f"출입구·장소 {collection['properties']['count']}곳: {collection['properties']['status_counts']}")
    print(f"GeoJSON → {args.geojson}")
    print(f"지도 → {args.html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
