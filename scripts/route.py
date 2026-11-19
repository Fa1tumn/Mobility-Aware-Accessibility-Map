"""출발·도착·프로필을 받아 경로를 계산하고 GeoJSON으로 저장한다.

    python -m scripts.route --graph data/graph/test_area.geojson \
        --from N1 --to N6 --profile wheelchair --out output/route/route.geojson

    # 모든 프로필 비교 (파일은 route_<profile>.geojson으로 저장)
    python -m scripts.route --graph data/graph/test_area.geojson \
        --from N1 --to N6 --profile all --out output/route/route.geojson

    # 추천·최단·대안 경로와 선택 이유
    python -m scripts.route --graph data/graph/test_area.geojson \
        --from N1 --to N6 --profile wheelchair --explain

좌표가 없는 9월 형식은 --nodes/--edges로 읽는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from app.graph.loader import load_geojson, load_graph
from app.graph.schema import SchemaError
from app.profile.definitions import PRESETS, get
from app.routing.alternatives import format_options, route_options
from app.routing.dijkstra import find_route
from app.routing.geojson import route_to_geojson
from app.schedule.resolver import ScheduleBook


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="프로필별 경로 계산")
    source = parser.add_argument_group("graph")
    source.add_argument("--graph", type=Path, help="좌표가 있는 GeoJSON graph")
    source.add_argument("--nodes", type=Path, help="9월 형식 nodes.json")
    source.add_argument("--edges", type=Path, help="9월 형식 edges.json")
    parser.add_argument("--from", dest="start", required=True, help="출발 노드 ID")
    parser.add_argument("--to", dest="goal", required=True, help="도착 노드 ID")
    parser.add_argument("--profile", default="wheelchair",
                        help=f"{', '.join(sorted(PRESETS))} 또는 all")
    parser.add_argument("--when", help="기준 시각 (예: 2026-11-21T10:00). 출입구 개방 시간에 사용")
    parser.add_argument("--schedule", type=Path, help="출입구 개방 시간 JSON")
    parser.add_argument("--out", type=Path, help="결과 GeoJSON 경로")
    parser.add_argument("--explain", action="store_true",
                        help="추천·최단·대안 경로와 선택 이유를 함께 출력")
    args = parser.parse_args(argv)
    if bool(args.graph) == bool(args.nodes or args.edges):
        parser.error("--graph 하나만, 또는 --nodes와 --edges를 함께 지정하세요")
    if (args.nodes is None) != (args.edges is None):
        parser.error("--nodes와 --edges는 함께 지정해야 합니다")
    if args.profile != "all" and args.profile not in PRESETS:
        parser.error(f"알 수 없는 프로필: {args.profile}")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        graph = load_geojson(args.graph) if args.graph else load_graph(args.nodes, args.edges)
    except (OSError, SchemaError, json.JSONDecodeError) as error:
        print(f"graph 오류: {error}", file=sys.stderr)
        return 1
    when = datetime.fromisoformat(args.when) if args.when else None
    schedule = ScheduleBook.load(args.schedule) if args.schedule else None
    profiles = list(PRESETS.values()) if args.profile == "all" else [get(args.profile)]

    exit_code = 0
    for profile in profiles:
        try:
            result = find_route(graph, args.start, args.goal, profile, when, schedule)
        except KeyError as error:
            print(f"입력 오류: {error}", file=sys.stderr)
            return 1
        collection = route_to_geojson(graph, result, profile, args.start, args.goal, when)
        summary = collection["properties"]
        if args.explain:
            options = route_options(graph, args.start, args.goal, profile, when, schedule)
            print(format_options(options, profile.name))
        else:
            print(f"[{profile.name}] {result.summary()}")
            if result.found:
                print(f"  최대 오르막 {summary['max_uphill_pct']:.1f}% · "
                      f"최대 내리막 {summary['max_downhill_pct']:.1f}% · "
                      f"경사 미측정 {summary['unknown_slope_m']:.0f}m")
                for reason in result.reasons[:5]:
                    print(f"  · {reason}")
        if not result.found:
            exit_code = 2
        if args.out:
            out = args.out
            if len(profiles) > 1:
                out = out.with_name(f"{out.stem}_{profile.name}{out.suffix or '.geojson'}")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(collection, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  저장: {out}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
