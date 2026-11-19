"""이벤트 재탐색 시나리오 재생.

시나리오 JSON의 단계를 시간 순서대로 돌리며, 단계마다 이벤트를 넣거나 해제하고
현재 위치에서 재탐색 판단(app.nav.reroute)을 출력한다.

    python -m scripts.event_demo data/events/demo_mini.json
    python -m scripts.event_demo data/events/demo_mini.json --profile wheelchair
    python -m scripts.event_demo data/events/demo_mini.json --out-dir output/route/demo

--out-dir을 주면 단계마다 그 시점의 경로를 step_NN.geojson으로 저장한다(웹 화면 재생용).

시나리오 형식
    {"graph": "...geojson", "profile": "default", "start": "A", "goal": "D",
     "depart": "2026-11-21T10:00:00",
     "steps": [{"at": "...", "position": "A",
                "add": [{"type": "construction", "edge_id": "BD", "until": "...", "note": ""}],
                "clear": ["E001"]}, ...]}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.events.model import parse_time
from app.events.overlay import EventOverlay
from app.events.store import EventStore
from app.graph.loader import load_geojson
from app.nav.reroute import check_reroute
from app.profile.definitions import get
from app.routing.dijkstra import find_route
from app.routing.geojson import route_to_geojson

ROOT = Path(__file__).resolve().parents[1]
ACTION_TEXT = {"keep": "유지", "reroute": "재탐색", "no_route": "경로 없음", "arrived": "도착"}


def _path_text(route) -> str:
    return f"{' → '.join(route.node_path)} ({route.total_distance_m:.0f}m)"


def run_scenario(path: Path, profile_name: str | None = None, out_dir: Path | None = None) -> list[dict]:
    sc = json.loads(Path(path).read_text(encoding="utf-8"))
    graph_path = Path(sc["graph"])
    graph = load_geojson(graph_path if graph_path.is_absolute() else ROOT / graph_path)
    profile = get(profile_name or sc.get("profile", "default"))
    store = EventStore(load=False)
    depart = parse_time(sc["depart"])

    route = find_route(graph, sc["start"], sc["goal"], profile, depart,
                       events=EventOverlay.from_store(store, depart))
    log = [{"at": depart, "position": sc["start"], "action": "depart" if route.found else "no_route",
            "route": route, "reasons": route.blocked if not route.found else [], "added": []}]
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    for n, step in enumerate(sc["steps"], start=1):
        if not route.found:
            break
        now = parse_time(step["at"])
        added = []
        for spec in step.get("add", []):
            ev = store.add(spec["type"], spec["edge_id"], now, until=parse_time(spec.get("until")),
                           minutes=spec.get("minutes"), note=spec.get("note", ""), graph=graph)
            added.append(ev)
        for event_id in step.get("clear", []):
            store.clear(event_id, now)
        overlay = EventOverlay.from_store(store, now)
        decision = check_reroute(route, step["position"], graph, profile, overlay, now)
        route = decision.route
        log.append({"at": now, "position": step["position"], "action": decision.action,
                    "route": route, "reasons": decision.reasons,
                    "added": [overlay.describe(ev) + f" @ {ev.edge_id}" for ev in added]})
        if out_dir:
            fc = route_to_geojson(graph, route, profile, step["position"], sc["goal"], now, overlay)
            fc["properties"]["action"] = decision.action
            fc["properties"]["decision_reasons"] = decision.reasons
            (out_dir / f"step_{n:02d}.geojson").write_text(
                json.dumps(fc, ensure_ascii=False, indent=2), encoding="utf-8")
        if decision.action in ("arrived", "no_route"):
            break
    return log


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="이벤트 재탐색 시나리오 재생")
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--profile", help="시나리오의 프로필 대신 사용")
    parser.add_argument("--out-dir", type=Path, help="단계별 경로 GeoJSON 저장 폴더")
    args = parser.parse_args(argv)
    try:
        log = run_scenario(args.scenario, args.profile, args.out_dir)
    except (OSError, ValueError, KeyError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    for item in log:
        t = item["at"].strftime("%H:%M:%S")
        for text in item["added"]:
            print(f"{t}  [{item['position']}] 이벤트 추가: {text}")
        if item["action"] == "depart":
            print(f"{t}  [{item['position']}] 출발: {_path_text(item['route'])}")
            continue
        head = ACTION_TEXT[item["action"]]
        body = "" if item["action"] in ("arrived", "no_route") else f": {_path_text(item['route'])}"
        print(f"{t}  [{item['position']}] {head}{body}")
        for reason in item["reasons"]:
            print(f"{'':10}· {reason}")
    return 0 if log[-1]["action"] != "no_route" else 2


if __name__ == "__main__":
    raise SystemExit(main())
