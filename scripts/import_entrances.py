"""웹앱으로 등록한 출입구를 받아 검토 목록을 만들고, 확인이 끝난 것만 graph에 붙인다.

    # 1) 받기 + 검토 목록 (Supabase는 .env의 SUPABASE_URL, SUPABASE_KEY 사용)
    python -m scripts.import_entrances --graph data/graph/test_area.geojson

    # 2) 검토 목록(output/route/entrance_review.json)의 후보를 현장·지도에서 확인하고
    #    data/campus/entrance_links.json에 적는다: {"links": {"<record_id>": "<보행로 노드 ID>"}}

    # 3) 다시 실행하면 값이 다 있고 연결이 확인된 출입구만 graph와 건물 파일에 들어간다
    python -m scripts.import_entrances --graph data/graph/test_area.geojson

미확인 항목은 0이나 가정값으로 채우지 않는다. 그런 출입구는 graph에 넣지 않고
검토 목록에 needs_survey로 남는다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from app.graph.buildings import load_buildings, save_buildings
from app.graph.loader import load_geojson, save_geojson
from app.graph.registered_entrances import CANDIDATE_RADIUS_M, attach_entrances, missing_items

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW = ROOT / "data" / "campus" / "entrances_registered.json"
DEFAULT_LINKS = ROOT / "data" / "campus" / "entrance_links.json"
STATUS_TEXT = {"needs_survey": "현장 보완 필요", "needs_link": "연결 확인 필요", "attached": "graph에 연결됨",
               "place": "장소(출입구 아님)", "invalid": "오류"}


def fetch_entrances() -> list[dict]:
    from app.storage.supabase_reader import fetch_observations

    os.environ["SUPABASE_TABLE"] = os.environ.get("ENTRANCE_TABLE", "entrances")
    os.environ["SUPABASE_ORDER"] = "recorded_at.asc,id.asc"
    return fetch_observations()


def load_links(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    links = data.get("links", {})
    if not isinstance(links, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in links.items()):
        raise ValueError(f"{path}: links는 {{기록 ID: 노드 ID}} 형식이어야 한다")
    return links


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="웹앱 등록 출입구 검토와 graph 연결")
    parser.add_argument("--input", type=Path, help="Supabase 대신 읽을 기록 JSON")
    parser.add_argument("--save-raw", type=Path, default=DEFAULT_RAW, help="받은 기록 원본 저장 위치")
    parser.add_argument("--graph", type=Path, help="보행로 graph GeoJSON (없으면 미확인 항목만 점검)")
    parser.add_argument("--links", type=Path, default=DEFAULT_LINKS, help="연결 확인 파일")
    parser.add_argument("--buildings", type=Path, help="기존 건물 파일(있으면 출입구를 추가)")
    parser.add_argument("--review", type=Path, default=ROOT / "output/route/entrance_review.json")
    parser.add_argument("--out-graph", type=Path, default=ROOT / "output/route/graph_with_entrances.geojson")
    parser.add_argument("--out-buildings", type=Path, default=ROOT / "output/route/buildings_registered.json")
    parser.add_argument("--radius-m", type=float, default=CANDIDATE_RADIUS_M)
    args = parser.parse_args(argv)
    try:
        if args.input:
            records = json.loads(args.input.read_text(encoding="utf-8"))
        else:
            records = fetch_entrances()
            args.save_raw.parent.mkdir(parents=True, exist_ok=True)
            args.save_raw.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"받은 기록 {len(records)}건 → {args.save_raw}")
        if not args.graph:
            for r in records:
                miss = missing_items(r)
                print(f"- {r.get('building_name')} {r.get('entrance_name') or ''}: "
                      f"{'미확인 ' + ', '.join(miss) if miss else '값 확인됨'} ({r.get('id')})")
            return 0
        graph = load_geojson(args.graph)
        book = load_buildings(args.buildings, graph) if args.buildings else None
        book, reviews = attach_entrances(graph, records, load_links(args.links), book, args.radius_m)
        problems = graph.validate()
        if problems:
            raise ValueError("graph 검사 실패: " + "; ".join(problems[:5]))
        args.review.parent.mkdir(parents=True, exist_ok=True)
        args.review.write_text(json.dumps([r.to_dict() for r in reviews], ensure_ascii=False, indent=2), encoding="utf-8")
        attached = [r for r in reviews if r.status == "attached"]
        if attached:
            args.out_graph.parent.mkdir(parents=True, exist_ok=True)
            save_geojson(graph, args.out_graph)
            save_buildings(book, args.out_buildings)
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    counts = Counter(r.status for r in reviews)
    print("상태: " + ", ".join(f"{STATUS_TEXT[k]} {v}건" for k, v in counts.items()))
    for r in reviews:
        head = f"- [{STATUS_TEXT[r.status]}] {r.building} {r.entrance}".rstrip() + f" ({r.record_id})"
        print(head)
        if r.missing:
            print(f"    미확인: {', '.join(r.missing)}")
        if r.status != "attached" and r.candidates:
            print("    연결 후보: " + ", ".join(f"{c['node_id']} {c['distance_m']}m" for c in r.candidates))
        if r.reason:
            print(f"    {r.reason}")
    print(f"검토 목록 → {args.review}")
    if attached:
        print(f"graph → {args.out_graph}\n건물 → {args.out_buildings}")
    else:
        print("graph에 붙인 출입구가 없어 graph·건물 파일은 만들지 않았습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
