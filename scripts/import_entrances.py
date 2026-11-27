"""웹앱으로 등록한 출입구를 받아 경로 graph와 건물 파일에 붙인다.

    # Supabase에서 받기 (.env의 SUPABASE_URL, SUPABASE_KEY 사용)
    python -m scripts.import_entrances --graph data/graph/test_area.geojson \
        --out-graph output/route/graph_with_entrances.geojson \
        --out-buildings output/route/buildings_registered.json

    # 저장해 둔 JSON으로 하기
    python -m scripts.import_entrances --input data/campus/entrances_registered.json --graph ...

받은 기록 원본은 --save-raw(기본 data/campus/entrances_registered.json)에 남긴다.
결과 파일은 scripts.route / scripts.building_route의 --graph, --buildings에 그대로 넣는다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.graph.buildings import load_buildings, save_buildings
from app.graph.loader import load_geojson, save_geojson
from app.graph.registered_entrances import MAX_CONNECT_M, attach_entrances

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW = ROOT / "data" / "campus" / "entrances_registered.json"


def fetch_entrances() -> list[dict]:
    from app.storage.supabase_reader import fetch_observations

    os.environ["SUPABASE_TABLE"] = os.environ.get("ENTRANCE_TABLE", "entrances")
    os.environ["SUPABASE_ORDER"] = "recorded_at.asc,id.asc"
    return fetch_observations()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="웹앱 등록 출입구를 graph에 붙이기")
    parser.add_argument("--input", type=Path, help="Supabase 대신 읽을 기록 JSON")
    parser.add_argument("--save-raw", type=Path, default=DEFAULT_RAW, help="받은 기록 원본 저장 위치")
    parser.add_argument("--graph", type=Path, help="붙일 보행로 graph GeoJSON")
    parser.add_argument("--buildings", type=Path, help="기존 건물 파일(있으면 출입구를 추가)")
    parser.add_argument("--out-graph", type=Path, default=ROOT / "output/route/graph_with_entrances.geojson")
    parser.add_argument("--out-buildings", type=Path, default=ROOT / "output/route/buildings_registered.json")
    parser.add_argument("--max-connect-m", type=float, default=MAX_CONNECT_M)
    args = parser.parse_args(argv)
    try:
        if args.input:
            records = json.loads(args.input.read_text(encoding="utf-8"))
        else:
            records = fetch_entrances()
            args.save_raw.parent.mkdir(parents=True, exist_ok=True)
            args.save_raw.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"받은 기록 {len(records)}건 → {args.save_raw}")
        unknown = sum(1 for r in records for k in ("stairs", "ramp", "threshold") if r.get(k, "unknown") == "unknown")
        print(f"출입구 {len(records)}건, 미확인 항목 {unknown}개")
        if not args.graph:
            return 0
        graph = load_geojson(args.graph)
        book = load_buildings(args.buildings, graph) if args.buildings else None
        book, report = attach_entrances(graph, records, book, args.max_connect_m)
        problems = graph.validate()
        if problems:
            raise ValueError("graph 검사 실패: " + "; ".join(problems[:5]))
        args.out_graph.parent.mkdir(parents=True, exist_ok=True)
        args.out_buildings.parent.mkdir(parents=True, exist_ok=True)
        save_geojson(graph, args.out_graph)
        save_buildings(book, args.out_buildings)
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    print(f"붙인 출입구 {len(report.added)}개, 건너뜀 {len(report.skipped)}개")
    for rid, why in report.skipped:
        print(f"  건너뜀 {rid}: {why}")
    print(f"graph → {args.out_graph}")
    print(f"건물 → {args.out_buildings}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
