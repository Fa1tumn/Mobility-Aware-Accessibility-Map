"""RUBIK Pi의 IMU 창별 편안함 비용을 격자에서 집계한다."""

import math
from bisect import bisect_right
from collections import defaultdict
from statistics import median


# RUBIK Pi PR #7의 block_comfort_map.html과 같은 경계와 색상.
COMFORT_BOUNDS = (0.85, 1.0, 1.15, 1.4)
COMFORT_COLORS = ("#1a9850", "#91cf60", "#fee08b", "#fc8d59", "#d73027")
COMFORT_LEGEND = ("< 0.85 · Comfortable", "0.85–<1.00", "1.00–<1.15",
                  "1.15–<1.40 · Uncomfortable", "≥ 1.40")


def comfort_color(cost):
    return COMFORT_COLORS[bisect_right(COMFORT_BOUNDS, cost)]


def add_comfort_measurements(result, collection):
    if collection.get("type") != "FeatureCollection":
        raise ValueError("Comfort GeoJSON must be a FeatureCollection of scored IMU windows.")
    windows = defaultdict(list)
    for feature in collection["features"]:
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Point":
            continue
        props = feature.get("properties") or {}
        values = [props.get(key) for key in ("comfort_cost", "vertical_rms_mps2", "shocks_per_10m")]
        if not all(isinstance(value, (int, float)) and math.isfinite(value) and value >= 0 for value in values):
            continue
        try:
            lon, lat = geometry["coordinates"][:2]
            position = result.get_grid(lat, lon)
        except (KeyError, TypeError, ValueError):
            continue
        windows[position].append(values)

    for position, samples in windows.items():
        cost, rms, shocks = map(median, zip(*samples))
        result.grid[position]["comfort"] = {
            "cost": cost,
            "vertical_rms_mps2": rms,
            "shocks_per_10m": shocks,
            "window_count": len(samples),
            "color": comfort_color(cost),
        }
    return {
        "cell_count": len(windows),
        "window_count": sum(map(len, windows.values())),
        "source_count": len(collection["features"]),
        "survey_date": (collection.get("properties") or {}).get("survey_date"),
        "legend": list(zip(COMFORT_COLORS, COMFORT_LEGEND)),
    }
