import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

from app.map.campus_grid import load_campus_grid
from app.map.grid_comfort import add_comfort_measurements
from app.map.grid_pipeline import build_campus_grid, build_grid, build_grid_from_env
from app.map.grid_visualization import LABELS, grid_value, save_grid_image, save_grid_map
from app.storage.supabase_reader import ROOT, fetch_observations


YONSEI_DEMO_CELL_SIZE_M = 50
DEFAULT_ENTRANCES = ROOT / "data/campus/entrances.geojson"
DEFAULT_COMFORT = ROOT / "data/campus/comfort.geojson"


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
    targets = [(1, 4), (1, 5), (1, 6), (2, 6), (3, 6), (3, 7), (3, 8),
               (4, 8), (5, 8), (6, 8), (6, 7), (6, 6)]
    reference = load_campus_grid(YONSEI_DEMO_CELL_SIZE_M)
    rows = []
    start = datetime(2026, 10, 16, 3, 0, tzinfo=timezone.utc)
    for index, (i, j) in enumerate(targets):
        for sample in range(2):
            offset = 0.15 + sample * 0.7
            latitude, longitude = reference.to_geographic(
                (i + offset) * reference.size, (j + offset) * reference.size,
            )
            time = start + timedelta(seconds=len(rows) * 5)
            objects = [{"label": "obstacle"}] if index in (5, 9) else []
            rows.append({
                "id": len(rows) + 1,
                "is_simulated": True,
                "latitude": round(latitude, 7),
                "longitude": round(longitude, 7),
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
    parser.add_argument("--entrances", type=Path, help="Entrance GeoJSON (default: campus entrance snapshot for real campus data)")
    parser.add_argument("--comfort", type=Path, help="Scored IMU window GeoJSON (default: campus comfort snapshot for real campus data)")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--field", choices=LABELS, default="weight")
    sizing = parser.add_mutually_exclusive_group()
    sizing.add_argument("--cell-size-m", type=float, help="Target side length of a campus cell in meters")
    sizing.add_argument("--size", type=float, help="Legacy cell size in degrees")
    parser.add_argument("--auto-bounds", action="store_true", help="Use the axis-aligned GRID_* settings or observation bounds")
    args = parser.parse_args()
    if args.auto_bounds and args.yonsei_demo:
        parser.error("--yonsei-demo uses the fixed campus grid.")
    if args.cell_size_m is not None and (args.demo or args.auto_bounds):
        parser.error("--cell-size-m requires the campus grid.")
    if args.output is None:
        args.output = Path("output/grid/yonsei_demo.png" if args.yonsei_demo else "output/grid/grid.png")
    load_dotenv(ROOT / ".env")
    try:
        if args.yonsei_demo:
            rows = yonsei_observations()
            cell_size_m = args.cell_size_m if args.cell_size_m is not None else YONSEI_DEMO_CELL_SIZE_M
            result = build_campus_grid(rows, cell_size_m, args.size)
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
            if args.auto_bounds:
                result = build_grid_from_env(rows, args.size)
            else:
                result = build_campus_grid(rows, args.cell_size_m, args.size)
            title = "Local observations" if args.input or args.sqlite else "Supabase observations"
        fixed_campus = not (args.demo or args.yonsei_demo or args.auto_bounds)
        comfort_source = args.comfort or (DEFAULT_COMFORT if fixed_campus and DEFAULT_COMFORT.is_file() else None)
        comfort = None
        if comfort_source is not None:
            comfort = add_comfort_measurements(result, json.loads(comfort_source.read_text(encoding="utf-8")))
        if args.field == "comfort_cost" and not (comfort and comfort["cell_count"]):
            raise ValueError("No scored comfort windows in the grid. Supply a matching GeoJSON with --comfort.")
        if args.field == "comfort_cost":
            map_title = "Yonsei International Campus" if fixed_campus else title
            image_title = f"{title} - {LABELS[args.field]}"
        else:
            image_title = f"{title} - {args.field}"
            map_title = "Yonsei International Campus - Grid and Simulated Observations" if args.yonsei_demo else image_title
        save_grid_image(result, args.output, image_title, args.field)
        entrance_source = args.entrances
        if entrance_source is None and fixed_campus:
            entrance_source = DEFAULT_ENTRANCES if DEFAULT_ENTRANCES.is_file() else None
        entrances = json.loads(entrance_source.read_text(encoding="utf-8")) if entrance_source else None
        save_grid_map(result, args.output.with_suffix(".html"), map_title, args.field, entrances=entrances, comfort=comfort)
        cells = [{"row": i, "column": j, **result.get_cell_geometry(i, j), **cell} for (i, j), cell in result.grid.items()]
        args.output.with_suffix(".json").write_text(json.dumps(cells, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        args.output.with_name(args.output.stem + "_observations.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    except (ValueError, RuntimeError, KeyError, TypeError, OSError, sqlite3.Error) as error:
        parser.exit(1, f"Grid generation failed: {error}\n")
    mapped = len(result.observations)
    print(f"Mapped observations: {mapped}/{len(rows)}; grid: {result.rows} x {result.columns}")
    if mapped != len(rows):
        print(f"Excluded {len(rows) - mapped} observations with invalid coordinates or outside the campus grid.")
    measured = sum(grid_value(cell, args.field) is not None for cell in result.grid.values())
    print(f"Cells with {args.field}: {measured}")
    if not measured:
        print("This field has no complete measurements. Try --field ramp or --field ave_vibration.")
    if comfort is not None:
        print(f"Comfort map: {comfort['window_count']}/{comfort['source_count']} scored windows in {comfort['cell_count']} grid cells")
    print(f"Image: {args.output}")
    print(f"Cells: {args.output.with_suffix('.json')}")
    print(f"Map: {args.output.with_suffix('.html')}")


if __name__ == "__main__":
    main()
