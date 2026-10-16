import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

from app.map.grid_pipeline import build_grid, build_grid_from_env
from app.map.grid_visualization import save_grid_image, save_grid_map
from app.storage.supabase_reader import ROOT, fetch_observations


def demo_observations():
    rows = []
    targets = {(0, j) for j in range(8)}
    targets.update((i, 2) for i in range(1, 6))
    targets.update((i, 6) for i in range(1, 6))
    targets.update((5, j) for j in range(3, 6))
    for i in range(6):
        for j in range(8):
            if (i, j) not in targets:
                continue
            for k in range(2):
                rows.append({
                    "id": len(rows) + 1,
                    "is_simulated": True,
                    "latitude": 37.5006 - (i + 0.5) * 0.0001,
                    "longitude": 127.0 + (j + 0.5) * 0.0001,
                    "record_time": f"2026-10-16T00:00:0{k}Z",
                    "surface_label": "sidewalk",
                    "surface_confidence": 0.85 + k * 0.05,
                    "ramp": 0.1 * i,
                    "ave_vibration": 0.1 * j + k * 0.02,
                    "object": 2 if (i, j) in ((3, 2), (4, 2)) else 0,
                })
    return rows


def yonsei_observations():
    targets = [(4, 5), (4, 6), (4, 7), (5, 7), (6, 7), (6, 8), (6, 9), (7, 9), (8, 9), (9, 9), (9, 8), (9, 7)]
    rows = []
    start = datetime(2026, 10, 16, 3, 0, tzinfo=timezone.utc)
    for index, (i, j) in enumerate(targets):
        for sample in range(2):
            offset = 0.15 + sample * 0.7
            time = start + timedelta(seconds=len(rows) * 5)
            objects = [{"label": "obstacle"}] if index in (5, 9) else []
            rows.append({
                "id": len(rows) + 1,
                "is_simulated": True,
                "latitude": round(37.385 - (i + offset) * 0.0005, 7),
                "longitude": round(126.668 + (j + offset) * 0.0005, 7),
                "record_time": time.isoformat().replace("+00:00", "Z"),
                "surface_label": "cement" if index % 3 else "urethane",
                "surface_confidence": round(0.85 + sample * 0.05, 2),
                "slope_percent": round(0.3 + index * 0.4 + sample * 0.2, 2),
                "vibration_frequency_avg_hz": round(2 + index * 0.5 + sample * 0.3, 2),
                "objects_supported": 1,
                "objects": objects,
            })
    return rows


def main():
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--demo", action="store_true")
    source.add_argument("--yonsei-demo", action="store_true")
    source.add_argument("--input", type=Path)
    source.add_argument("--sqlite", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--field", choices=["weight", "ramp", "ave_vibration", "object"], default="weight")
    parser.add_argument("--size", type=float)
    args = parser.parse_args()
    if args.output is None:
        args.output = Path("output/grid/yonsei_demo.png" if args.yonsei_demo else "output/grid/grid.png")
    load_dotenv(ROOT / ".env")
    try:
        if args.yonsei_demo:
            rows = yonsei_observations()
            result = build_grid(rows, args.size if args.size is not None else 0.0005, (37.385, 126.668), (37.378, 126.677))
            title = "Yonsei International Campus - SIMULATED observations"
        elif args.demo:
            rows = demo_observations()
            result = build_grid(rows, args.size if args.size is not None else 0.0001, (37.5006, 127.0), (37.5, 127.0008))
            title = "DEMO observations"
        else:
            if args.sqlite:
                database_url = args.sqlite.resolve().as_uri() + "?mode=ro"
                connection = sqlite3.connect(database_url, uri=True)
                try:
                    connection.row_factory = sqlite3.Row
                    rows = [dict(row) for row in connection.execute("SELECT * FROM observations ORDER BY record_time, id")]
                finally:
                    connection.close()
            elif args.input:
                rows = json.loads(args.input.read_text(encoding="utf-8"))
            else:
                rows = fetch_observations()
            result = build_grid_from_env(rows, args.size)
            title = "Local observations" if args.input or args.sqlite else "Supabase observations"
        save_grid_image(result, args.output, f"{title} - {args.field}", args.field)
        map_title = "Yonsei International Campus - Grid and Simulated Observations" if args.yonsei_demo else f"{title} - {args.field}"
        save_grid_map(result, args.output.with_suffix(".html"), map_title, args.field)
        cells = [{"row": i, "column": j, **result.get_cell_bounds(i, j), **cell} for (i, j), cell in result.grid.items()]
        args.output.with_suffix(".json").write_text(json.dumps(cells, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        args.output.with_name(args.output.stem + "_observations.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    except (ValueError, RuntimeError, KeyError, TypeError, OSError, sqlite3.Error) as error:
        parser.exit(1, f"Grid generation failed: {error}\n")
    print(f"Observations: {len(rows)}; grid: {result.rows} x {result.columns}")
    measured = sum(cell[args.field] is not None for cell in result.grid.values())
    print(f"Cells with {args.field}: {measured}")
    if not measured:
        print("This field has no complete measurements. Try --field ramp or --field ave_vibration.")
    print(f"Image: {args.output}")
    print(f"Cells: {args.output.with_suffix('.json')}")
    print(f"Map: {args.output.with_suffix('.html')}")


if __name__ == "__main__":
    main()
