"""프로파일별 경로 비교표.

발표의 Hero 화면이 이 함수의 출력이다.
"프로파일을 바꾸면 경로가 바뀐다"를 표 한 장으로 보인다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from app.graph.schema import Graph
from app.profile.definitions import Profile, PRESETS
from app.routing.dijkstra import find_route
from app.schedule.resolver import ScheduleBook


def compare_profiles(
    graph: Graph,
    start: str,
    goal: str,
    profiles: Optional[Iterable[Profile]] = None,
    when: Optional[datetime] = None,
    schedule: Optional[ScheduleBook] = None,
) -> list[dict]:
    profiles = list(profiles) if profiles else list(PRESETS.values())
    rows = []
    for p in profiles:
        r = find_route(graph, start, goal, p, when, schedule)
        rows.append({
            "profile": p.name,
            "found": r.found,
            "path": " → ".join(r.node_path) if r.found else "-",
            "distance_m": round(r.total_distance_m, 1) if r.found else None,
            "cost": round(r.total_cost, 2) if r.found else None,
            "reasons": r.reasons if r.found else r.blocked,
        })
    return rows


def format_table(rows: list[dict], when: Optional[datetime] = None) -> str:
    head = f"기준 시각: {when:%Y-%m-%d (%a) %H:%M}\n" if when else ""
    head += f"{'프로파일':<12}{'경로':<28}{'거리':>8}{'비용':>8}\n"
    head += "-" * 58 + "\n"
    body = ""
    for r in rows:
        if r["found"]:
            body += (f"{r['profile']:<12}{r['path']:<28}"
                     f"{r['distance_m']:>7.0f}m{r['cost']:>8.2f}\n")
        else:
            body += f"{r['profile']:<12}{'통행 가능 경로 없음':<28}{'-':>8}{'-':>8}\n"
        for why in r["reasons"][:3]:
            body += f"{'':<12}  · {why}\n"
    return head + body


def routes_differ(rows: list[dict]) -> bool:
    """프로파일에 따라 경로가 실제로 갈리는가. Hero 데모의 합격 조건."""
    paths = {r["path"] for r in rows}
    return len(paths) > 1
