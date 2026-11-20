"""건물 간 경로: 출발·도착 건물과 프로필, 시각을 받아 출입구까지 포함한 경로를 낸다.

    python -m scripts.building_route --graph tests/fixtures/routing_buildings.geojson \
        --buildings tests/fixtures/buildings_mini.json --schedule tests/fixtures/schedule_buildings.json \
        --from student_hall --to library --profile wheelchair --when 2026-11-20T19:00

    python -m scripts.building_route --graph ... --buildings ... --list      # 건물 목록

--profile all이면 프로필마다 출력한다. --out을 주면 추천 경로를 GeoJSON으로 저장하고
(프로필이 여럿이면 파일 이름 뒤에 _<profile>), 요약에 출발·도착 건물과 출입구,
쓸 수 없는 출입구 이유를 넣는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from app.events.overlay import EventOverlay
from app.events.store import EventStore
from app.graph.buildings import load_buildings
from app.graph.loader import load_geojson
from app.graph.schema import SchemaError
from app.profile.definitions import PRESETS, get
from app.routing.buildings import building_route, format_building_route
from app.routing.geojson import route_to_geojson
from app.schedule.resolver import ScheduleBook


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="건물 간 경로")
    p.add_argument("--graph", type=Path, required=True)
    p.add_argument("--buildings", type=Path, required=True)
    p.add_argument("--list", action="store_true", help="건물 목록만 출력")
    p.add_argument("--from", dest="origin", help="출발 건물 ID")
    p.add_argument("--to", dest="dest", help="도착 건물 ID")
    p.add_argument("--profile", default="wheelchair", help=f"{', '.join(sorted(PRESETS))} 또는 all")
    p.add_argument("--when", help="기준 시각 (예: 2026-11-20T19:00). 출입구 운영 시간·이벤트에 사용")
    p.add_argument("--schedule", type=Path, help="출입구 운영 시간 JSON")
    p.add_argument("--events", type=Path, help="수동 이벤트 파일")
    p.add_argument("--out", type=Path, help="추천 경로 GeoJSON")
    args = p.parse_args(argv)
    if not args.list and not (args.origin and args.dest):
        p.error("--from과 --to를 지정하거나 --list를 쓰세요")
    if args.profile != "all" and args.profile not in PRESETS:
        p.error(f"알 수 없는 프로필: {args.profile}")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        graph = load_geojson(args.graph)
        buildings = load_buildings(args.buildings, graph)
        schedule = ScheduleBook.load(args.schedule) if args.schedule else None
        when = datetime.fromisoformat(args.when) if args.when else None
        events = None
        if args.events:
            events = EventOverlay.from_store(EventStore(args.events),
                                             when or datetime.now().replace(microsecond=0))
    except (OSError, ValueError, SchemaError, json.JSONDecodeError) as error:
        print(f"입력 오류: {error}", file=sys.stderr)
        return 1

    if args.list:
        for b in buildings:
            names = ", ".join(f"{n}({graph.nodes[n].name or n})" for n in b.entrances)
            print(f"{b.id:<16}{b.name:<16}출입구 {names}")
        return 0

    profiles = list(PRESETS.values()) if args.profile == "all" else [get(args.profile)]
    exit_code = 0
    for profile in profiles:
        try:
            br = building_route(graph, buildings, args.origin, args.dest, profile, when, schedule, events)
        except (KeyError, ValueError) as error:
            print(f"입력 오류: {error}", file=sys.stderr)
            return 1
        print(format_building_route(graph, br))
        rec = br.recommended
        if rec is None:
            exit_code = 2
        if args.out:
            if rec is not None:
                fc = route_to_geojson(graph, rec.result, profile, rec.from_entrance, rec.to_entrance, when, events)
            else:
                fc = {"type": "FeatureCollection", "features": [],
                      "properties": {"profile": profile.name, "found": False, "blocked": br.blocked}}
            fc["properties"].update({
                "origin_building": br.origin.id, "dest_building": br.dest.id,
                "from_entrance": rec.from_entrance if rec else None,
                "to_entrance": rec.to_entrance if rec else None,
                "why": rec.why if rec else [],
                "entrance_notes": br.entrance_notes,
            })
            out = args.out
            if len(profiles) > 1:
                out = out.with_name(f"{out.stem}_{profile.name}{out.suffix or '.geojson'}")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(fc, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  저장: {out}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
