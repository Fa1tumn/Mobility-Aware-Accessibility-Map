import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import Normalize


LABELS = {
    "weight": "Weight",
    "ramp": "Slope (%)",
    "ave_vibration": "Vibration frequency (Hz)",
    "object": "Detected object count",
}


def grid_values(result, field):
    if field not in LABELS:
        raise ValueError("Unknown grid field.")
    values = np.full((result.rows, result.columns), np.nan)
    targets = np.full_like(values, np.nan)
    for (i, j), cell in result.grid.items():
        if cell["observation_count"]:
            targets[i, j] = 1
        if cell[field] is not None:
            values[i, j] = cell[field]
    return values, targets


def save_grid_image(result, output_path, title="Observation grid", field="weight"):
    values, targets = grid_values(result, field)
    latitudes = np.maximum(result.north - np.arange(result.rows + 1) * result.size, result.south)
    longitudes = np.minimum(result.west + np.arange(result.columns + 1) * result.size, result.east)
    empty = plt.get_cmap("Greys").copy()
    empty.set_bad("#ffffff")
    colors = plt.get_cmap("YlOrRd").copy()
    colors.set_bad((1, 1, 1, 0))
    known = values[np.isfinite(values)]
    low = float(known.min()) if known.size else 0
    high = float(known.max()) if known.size else 1
    scale = Normalize(low, high if high > low else low + 1)
    masked = np.ma.masked_invalid(values)
    masked = np.ma.masked_where(np.isnan(targets), masked)
    fig, axes = plt.subplots(1, 2, figsize=(14, 8))
    axes[0].pcolormesh(longitudes, latitudes, np.ma.masked_invalid(targets), cmap=empty, vmin=0, vmax=1.6)
    axes[1].pcolormesh(longitudes, latitudes, np.ma.masked_invalid(targets), cmap=empty, vmin=0, vmax=1.6)
    image = axes[1].pcolormesh(longitudes, latitudes, masked, cmap=colors, norm=scale)
    for ax, subtitle in zip(axes, ("Target regions / ID", LABELS[field] + " per region")):
        if result.rows * result.columns <= 40000:
            width = 0.8 if result.rows * result.columns <= 400 else 0.2
            ax.vlines(longitudes, result.south, result.north, color="#707780", linewidth=width)
            ax.hlines(latitudes, result.west, result.east, color="#707780", linewidth=width)
        ax.set_xlim(result.west, result.east)
        ax.set_ylim(result.south, result.north)
        ax.set_aspect(1 / np.cos(np.radians((result.north + result.south) / 2)))
        ax.ticklabel_format(useOffset=False, style="plain")
        ax.tick_params(axis="x", rotation=30)
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.set_title(subtitle)
    for (i, j), cell in result.grid.items():
        if not cell["observation_count"]:
            continue
        bounds = result.get_cell_bounds(i, j)
        x = (bounds["west"] + bounds["east"]) / 2
        y = (bounds["north"] + bounds["south"]) / 2
        if result.rows <= 25 and result.columns <= 25:
            size = min(10, max(5, 90 / max(result.rows, result.columns)))
            axes[0].text(x, y, str(cell["grid_id"]), ha="center", va="center", color="white", fontsize=size)
            value = "N/A" if cell[field] is None else f"{cell[field]:.2f}"
            axes[1].text(x, y, value, ha="center", va="center", fontsize=size, bbox={"facecolor": "white", "alpha": 0.7, "edgecolor": "none", "pad": 1})
    fig.colorbar(image, ax=axes[1], label=LABELS[field], fraction=0.045, pad=0.03)
    fig.suptitle(title)
    fig.text(0.5, 0.025, "White = no observations; grey / N/A = observed, value unknown. One region stores one aggregated value.", ha="center", fontsize=10)
    fig.subplots_adjust(left=0.07, right=0.95, bottom=0.15, top=0.9, wspace=0.24)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
    return output_path


def save_grid_map(result, output_path, title="Observation grid", field="weight"):
    values, targets = grid_values(result, field)
    known = values[np.isfinite(values)]
    low = float(known.min()) if known.size else 0
    high = float(known.max()) if known.size else 1
    scale = Normalize(low, high if high > low else low + 1)
    cells = []
    for (i, j), cell in result.grid.items():
        if cell["observation_count"]:
            color = "#a8adb4" if cell[field] is None else matplotlib.colors.to_hex(plt.get_cmap("YlOrRd")(scale(cell[field])))
            cells.append({"row": i, "column": j, **result.get_cell_bounds(i, j), **cell, "color": color})
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
        "cells": cells,
        "points": points,
        "simulated": all(row.get("is_simulated") is True for row in result.observations),
    }
    template = Path(__file__).with_name("grid_map.html").read_text(encoding="utf-8")
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(template.replace("__GRID_DATA__", data), encoding="utf-8")
    return output_path
