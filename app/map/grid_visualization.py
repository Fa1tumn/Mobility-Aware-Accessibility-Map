import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.colors import BoundaryNorm, ListedColormap, Normalize

from app.map.grid_comfort import COMFORT_BOUNDS, COMFORT_COLORS
from app.map.grid_navigation import entrance_targets, observed_grid_edges


LABELS = {
    "weight": "Weight",
    "ramp": "Slope (%)",
    "ave_vibration": "Vibration frequency (Hz)",
    "object": "Detected object count",
    "comfort_cost": "Ride comfort cost",
}


def grid_value(cell, field):
    return cell.get("comfort", {}).get("cost") if field == "comfort_cost" else cell[field]


def grid_values(result, field):
    if field not in LABELS:
        raise ValueError("Unknown grid field.")
    values = np.full((result.rows, result.columns), np.nan)
    targets = np.full_like(values, np.nan)
    for (i, j), cell in result.grid.items():
        value = grid_value(cell, field)
        if cell["observation_count"] or (field == "comfort_cost" and value is not None):
            targets[i, j] = 1
        if value is not None:
            values[i, j] = value
    return values, targets


def grid_lines(result):
    rows = [result.row_edge(i) for i in range(result.rows + 1)]
    columns = [result.column_edge(j) for j in range(result.columns + 1)]
    return [
        [result.to_geographic(down, 0), result.to_geographic(down, result.map_width)]
        for down in rows
    ] + [
        [result.to_geographic(0, across), result.to_geographic(result.map_length, across)]
        for across in columns
    ]


def save_grid_image(result, output_path, title="Observation grid", field="weight"):
    values, targets = grid_values(result, field)
    across, down = np.meshgrid(
        [result.column_edge(j) for j in range(result.columns + 1)],
        [result.row_edge(i) for i in range(result.rows + 1)],
    )
    latitudes, longitudes = result.to_geographic(down, across)
    empty = plt.get_cmap("Greys").copy()
    empty.set_bad("#ffffff")
    known = values[np.isfinite(values)]
    low = float(known.min()) if known.size else 0
    high = float(known.max()) if known.size else 1
    if field == "comfort_cost":
        colors = ListedColormap(COMFORT_COLORS)
        scale = BoundaryNorm((0, *COMFORT_BOUNDS, max(high, 1.5) + 0.01), colors.N)
    else:
        colors = plt.get_cmap("YlOrRd").copy()
        scale = Normalize(low, high if high > low else low + 1)
    colors.set_bad((1, 1, 1, 0))
    masked = np.ma.masked_invalid(values)
    masked = np.ma.masked_where(np.isnan(targets), masked)
    fig, axes = plt.subplots(1, 2, figsize=(14, 8))
    axes[0].pcolormesh(longitudes, latitudes, np.ma.masked_invalid(targets), cmap=empty, vmin=0, vmax=1.6)
    axes[1].pcolormesh(longitudes, latitudes, np.ma.masked_invalid(targets), cmap=empty, vmin=0, vmax=1.6)
    image = axes[1].pcolormesh(longitudes, latitudes, masked, cmap=colors, norm=scale)
    lines = np.asarray(grid_lines(result))[:, :, ::-1] if result.rows * result.columns <= 40000 else None
    coverage_title = "Observation coverage" if field == "comfort_cost" else "Target regions / ID"
    for ax, subtitle in zip(axes, (coverage_title, LABELS[field] + " per region")):
        if lines is not None:
            width = 0.8 if result.rows * result.columns <= 400 else 0.2
            ax.add_collection(LineCollection(lines, colors="#707780", linewidths=width))
        ax.set_xlim(result.west, result.east)
        ax.set_ylim(result.south, result.north)
        ax.set_aspect(1 / np.cos(np.radians((result.north + result.south) / 2)))
        ax.ticklabel_format(useOffset=False, style="plain")
        ax.tick_params(axis="x", rotation=30)
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.set_title(subtitle)
    for i, j in result.grid:
        if np.isnan(targets[i, j]):
            continue
        bounds = result.get_cell_bounds(i, j)
        x = (bounds["west"] + bounds["east"]) / 2
        y = (bounds["north"] + bounds["south"]) / 2
        if result.rows <= 25 and result.columns <= 25:
            size = min(10, max(5, 90 / max(result.rows, result.columns)))
            axes[0].text(x, y, str(cell["grid_id"]), ha="center", va="center", color="white", fontsize=size)
            value = "N/A" if np.isnan(values[i, j]) else f"{values[i, j]:.2f}"
            axes[1].text(x, y, value, ha="center", va="center", fontsize=size, bbox={"facecolor": "white", "alpha": 0.7, "edgecolor": "none", "pad": 1})
    fig.colorbar(image, ax=axes[1], label=LABELS[field], fraction=0.045, pad=0.03,
                 ticks=COMFORT_BOUNDS if field == "comfort_cost" else None)
    fig.suptitle(title)
    caption = ("Cost 1.0 is the survey reference. Lower is more comfortable. Grey = no scored IMU windows."
               if field == "comfort_cost" else "White = no observations; grey / N/A = observed, value unknown. One region stores one aggregated value.")
    fig.text(0.5, 0.025, caption, ha="center", fontsize=10)
    fig.subplots_adjust(left=0.07, right=0.95, bottom=0.15, top=0.9, wspace=0.24)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
    return output_path


def save_grid_map(result, output_path, title="Observation grid", field="weight", *, entrances=None, comfort=None):
    comfort_default = field == "comfort_cost"
    if comfort_default:
        field = "ave_vibration"
    values, _ = grid_values(result, field)
    known = values[np.isfinite(values)]
    low = float(known.min()) if known.size else 0
    high = float(known.max()) if known.size else 1
    scale = Normalize(low, high if high > low else low + 1)
    cells = []
    for (i, j), cell in result.grid.items():
        if cell["observation_count"] or cell.get("comfort"):
            color = "#a8adb4" if cell[field] is None else matplotlib.colors.to_hex(plt.get_cmap("YlOrRd")(scale(cell[field])))
            center = result.to_geographic((result.row_edge(i) + result.row_edge(i + 1)) / 2,
                                          (result.column_edge(j) + result.column_edge(j + 1)) / 2)
            cells.append({"row": i, "column": j, "center": center,
                          **result.get_cell_geometry(i, j), **cell, "color": color})
    points = []
    for index, row in enumerate(result.observations):
        i, j = result.get_grid(row["latitude"], row["longitude"])
        measurements = [row.get(name) for name in ("ramp", "ave_vibration", "object")]
        point_weight = None if any(value is None for value in measurements) else sum(0.3 * float(value) for value in measurements) + 0.1
        points.append({
            **row,
            "point_id": f"P{index + 1:02d}",
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "grid_id": result.grid[(i, j)]["grid_id"],
            "point_weight": point_weight,
            "region_weight": result.grid[(i, j)]["weight"],
        })
    payload = {
        "title": title,
        "field": field,
        "label": LABELS[field],
        "north": result.north,
        "south": result.south,
        "west": result.west,
        "east": result.east,
        "size": result.size,
        "rows": result.rows,
        "columns": result.columns,
        "low": low,
        "high": high,
        "lines": grid_lines(result),
        "cells": cells,
        "points": points,
        "simulated": bool(points) and all(row.get("is_simulated") is True for row in result.observations),
    }
    if entrances is not None:
        payload["entrances"] = entrance_targets(result, entrances)
        payload["grid_edges"] = observed_grid_edges(cells)
    if comfort is not None:
        payload["comfort"] = {**comfort, "show_default": comfort_default}
    template = Path(__file__).with_name("grid_map.html").read_text(encoding="utf-8")
    navigation = Path(__file__).with_name("grid_navigation.js").read_text(encoding="utf-8")
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(template.replace("__GRID_NAVIGATION__", navigation).replace("__GRID_DATA__", data), encoding="utf-8")
    return output_path
