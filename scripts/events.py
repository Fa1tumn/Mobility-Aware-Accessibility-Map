"""수동 이벤트 입력·조회·해제.

    python -m scripts.events types
    python -m scripts.events add --type construction --edge BD --until 2026-11-21T18:00 \
        --graph data/graph/test_area.geojson --note "보수 공사"
    python -m scripts.events add --type parked_vehicle --edge EC        # 유효시간은 종류 기본값
    python -m scripts.events list            # 지금 활성인 것만 (--all: 전부)
    python -m scripts.events clear E001

저장 위치 기본값은 data/events/events.json(--store로 변경). 시각은 한국 시간이며,
--now로 기준 시각을 바꿀 수 있다(시연·테스트용).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from app.events.model import parse_time
from app.events.store import DEFAULT_STORE_PATH, EventStore
from app.graph.loader import load_geojson


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="수동 이벤트 관리")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH, help="이벤트 저장 파일")
    parser.add_argument("--now", help="기준 시각 (예: 2026-11-21T10:00). 기본은 현재 시각")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("types", help="이벤트 종류와 기본값")

    add = sub.add_parser("add", help="이벤트 추가")
    add.add_argument("--type", required=True)
    add.add_argument("--edge", required=True, help="간선 ID (graph 파일의 id)")
    end = add.add_mutually_exclusive_group()
    end.add_argument("--until", help="종료 시각")
    end.add_argument("--minutes", type=float, help="지금부터 유효한 시간(분)")
    add.add_argument("--note", default="")
    add.add_argument("--graph", type=Path, help="간선 ID 확인용 graph")

    ls = sub.add_parser("list", help="이벤트 목록")
    ls.add_argument("--all", action="store_true", help="만료·해제된 것도 표시")

    clear = sub.add_parser("clear", help="이벤트 해제")
    clear.add_argument("event_id")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    now = parse_time(args.now) if args.now else datetime.now().replace(microsecond=0)
    try:
        store = EventStore(args.store)
        if args.command == "types":
            for t in store.types.values():
                ttl = "직접 지정" if t.ttl_min is None else f"{t.ttl_min:g}분"
                parts = ["기록만"] if t.record_only else []
                if t.block:
                    parts.append("차단 " + ",".join(t.block))
                if t.penalty:
                    parts.append("비용 " + ", ".join(f"{k}={v:g}" for k, v in t.penalty.items()))
                print(f"{t.name:<16}{t.label:<12}유효 {ttl:<8}{' · '.join(parts)}")
            return 0
        if args.command == "add":
            graph = load_geojson(args.graph) if args.graph else None
            ev = store.add(args.type, args.edge, now, until=parse_time(args.until),
                           minutes=args.minutes, note=args.note, graph=graph)
            store.save()
            until = f"{ev.expires_at:%Y-%m-%d %H:%M}까지" if ev.expires_at else "해제할 때까지"
            print(f"추가: {ev.event_id} {store.types[ev.type].label} @ {ev.edge_id} ({until})")
            return 0
        if args.command == "list":
            shown = 0
            for ev in store.events:
                state = ev.state_at(now)
                if not args.all and state != "active":
                    continue
                until = f"{ev.expires_at:%m-%d %H:%M}" if ev.expires_at else "-"
                print(f"{ev.event_id}  {state:<8}{store.types[ev.type].label:<12}"
                      f"{ev.edge_id:<10}~{until:<12}{ev.note}")
                shown += 1
            if not shown:
                print("이벤트 없음")
            return 0
        if args.command == "clear":
            ev = store.clear(args.event_id, now)
            store.save()
            print(f"해제: {ev.event_id}")
            return 0
    except (ValueError, KeyError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
