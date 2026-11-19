"""Hero 데모: 프로파일과 시각에 따라 경로가 달라지는 것을 보인다.

    python -m scripts.demo_route
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.graph.loader import load_graph
from app.routing.compare import compare_profiles, format_table, routes_differ
from app.schedule.resolver import ScheduleBook

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    g = load_graph(ROOT / "data/routing_demo/nodes.json", ROOT / "data/routing_demo/edges.json")
    book = ScheduleBook.load(ROOT / "data/routing_demo/entrances.json")

    print(f"노드 {len(g.nodes)}개, 간선 {len(g.edges)}개\n")

    for label, when in [("주간 (월 10:00)", datetime(2026, 9, 28, 10, 0)),
                        ("야간 (월 20:00)", datetime(2026, 9, 28, 20, 0))]:
        print("=" * 58)
        print(f"  {label}")
        print("=" * 58)
        rows = compare_profiles(g, "N1", "N6", when=when, schedule=book)
        print(format_table(rows, when))
        print(f"  프로파일에 따라 경로가 갈리는가: "
              f"{'YES' if routes_differ(rows) else 'NO'}\n")


if __name__ == "__main__":
    main()
