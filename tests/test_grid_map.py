import json
import re

import pytest

from app.map.grid_comfort import add_comfort_measurements
from app.map.grid_pipeline import build_campus_grid, build_grid
from app.map.grid_visualization import grid_values, save_grid_map
from scripts.test_grid import YONSEI_DEMO_CELL_SIZE_M, yonsei_observations


def map_data(result, path, **kwargs):
    save_grid_map(result, path, **kwargs)
    html = path.read_text(encoding="utf-8")
    match = re.search(r'<script id="grid-data" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(match.group(1)), html


def test_point_and_region_values_are_exported_separately(tmp_path):
    rows = [
        {"id": 5, "latitude": 37.50055, "longitude": 127.00005, "ramp": 1, "ave_vibration": 2, "object": 0},
        {"id": 6, "latitude": 37.50051, "longitude": 127.00009, "ramp": 3, "ave_vibration": 2, "object": 0},
    ]
    result = build_grid(rows, 0.0001, (37.5006, 127), (37.5, 127.0008))
    data, html = map_data(result, tmp_path / "map.html")
    assert len(data["cells"]) == 1
    assert len(data["points"]) == 2
    first, second = data["points"]
    assert first["point_id"] == "P01"
    assert second["point_id"] == "P02"
    assert first["grid_id"] == second["grid_id"]
    assert first["point_weight"] == pytest.approx(1)
    assert second["point_weight"] == pytest.approx(1.6)
    assert first["region_weight"] == second["region_weight"] == pytest.approx(1.3)
    assert [row["id"] for row in data["points"]] == [5, 6]
    assert 'id="point-list"' in html
    assert data["simulated"] is False


def test_unknown_point_weight_is_not_exported_as_zero(tmp_path):
    result = build_grid([{"latitude": 37.38, "longitude": 126.67, "ramp": 2, "ave_vibration": 3}])
    data, html = map_data(result, tmp_path / "map.html")
    assert data["points"][0]["point_weight"] is None
    assert data["points"][0]["region_weight"] is None


def test_raw_point_text_cannot_close_the_json_script(tmp_path):
    label = '</script><script>alert("test")</script>'
    result = build_grid([{"latitude": 37.38, "longitude": 126.67, "surface_label": label}])
    data, html = map_data(result, tmp_path / "map.html")
    assert data["points"][0]["surface_label"] == label
    assert label not in html


def test_yonsei_demo_has_all_points_and_complete_region_weights(tmp_path):
    rows = yonsei_observations()
    result = build_campus_grid(rows, YONSEI_DEMO_CELL_SIZE_M)
    data, html = map_data(result, tmp_path / "yonsei.html")
    assert len(data["points"]) == 24
    assert len(data["cells"]) == 12
    assert all(cell["observation_count"] == 2 and cell["weight"] is not None for cell in data["cells"])
    assert data["lines"][0] == [list(result.map_left_top), list(result.to_geographic(0, result.map_width))]
    assert "L.polygon(cell.corners" in html
    cells = {cell["grid_id"]: cell for cell in data["cells"]}
    for point in data["points"]:
        cell = cells[point["grid_id"]]
        i, j = result.get_grid(point["latitude"], point["longitude"])
        assert (cell["row"], cell["column"]) == (i, j)
        assert cell["corners"] == [list(corner) for corner in result.get_cell_corners(i, j)]
    assert len({point["point_id"] for point in data["points"]}) == 24
    assert data["simulated"] is True


def test_entrances_keep_occupied_cell_or_snap_to_nearest_observed_boundary(tmp_path):
    reference = build_campus_grid([])
    size = reference.size

    def coordinates(row, column):
        return reference.to_geographic(size * row, size * column)

    def point(row, column):
        lat, lon = coordinates(row, column)
        return {"latitude": lat, "longitude": lon}

    def feature(row, column, kind="entrance"):
        lat, lon = coordinates(row, column)
        return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {"kind": kind}}

    result = build_campus_grid([point(1.5, 3.5), point(2.5, 0.5)])
    entrances = {"type": "FeatureCollection", "features": [
        feature(1.25, 3.25), feature(1.5, 2.8), feature(1.5, 2.8, "place"),
    ]}
    data, _ = map_data(result, tmp_path / "map.html", entrances=entrances)
    direct, fallback, place = data["entrances"]
    grid_id = result.grid[(1, 3)]["grid_id"]
    assert direct["target"] == {"grid_id": grid_id, "distance_m": 0, "in_cell": True}
    assert fallback["target"]["grid_id"] == grid_id
    assert fallback["target"]["distance_m"] == pytest.approx(0.2 * size, rel=0.01)
    assert fallback["target"]["in_cell"] is False
    assert place["target"] is None
    empty, _ = map_data(reference, tmp_path / "empty.html", entrances=entrances)
    assert all(entrance["target"] is None for entrance in empty["entrances"])


def test_grid_routes_use_observed_neighbors_and_aggregate_surface(tmp_path):
    reference = build_campus_grid([])

    def point(row, col, surface, confidence=1):
        lat, lon = reference.to_geographic((row + 0.5) * reference.size, (col + 0.5) * reference.size)
        return {"latitude": lat, "longitude": lon, "surface_label": surface, "surface_confidence": confidence}

    points = [point(0, 0, "asphalt"), point(0, 1, "asphalt"), point(0, 1, "blocks", 0.8),
              point(1, 1, "blocks"), point(1, 2, "blocks"), point(3, 4, "blocks")]
    result = build_campus_grid(points)
    data, _ = map_data(result, tmp_path / "map.html", entrances={"features": []})
    positions = {cell["grid_id"]: (cell["row"], cell["column"]) for cell in data["cells"]}
    edges = {(positions[a], positions[b]): (distance, penalty) for a, b, distance, penalty in data["grid_edges"]}
    assert len(edges) == 5
    horizontal = edges[(0, 0), (0, 1)]
    diagonal = edges[(0, 0), (1, 1)]
    assert horizontal[0] == pytest.approx(reference.size, rel=0.01)
    assert horizontal[1] == 0
    assert diagonal[0] == pytest.approx(reference.size * 2 ** 0.5, rel=0.01)
    assert diagonal[1] > 0
    assert ((0, 1), (1, 2)) in edges
    assert all((3, 4) not in pair for pair in edges)


def test_comfort_layer_uses_window_medians_and_pr_boundaries(tmp_path):
    reference = build_campus_grid([])
    size = reference.size
    base_lat, base_lon = reference.to_geographic(0.5 * size, 0.5 * size)
    result = build_campus_grid([{"latitude": base_lat, "longitude": base_lon}])

    def feature(row, col, cost, rms, shocks):
        lat, lon = reference.to_geographic(row * size, col * size)
        return {"geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {"comfort_cost": cost, "vertical_rms_mps2": rms, "shocks_per_10m": shocks}}

    info = add_comfort_measurements(result, {"type": "FeatureCollection", "features": [
        feature(1.2, 0.2, 0.85, 1, 0), feature(1.3, 0.3, 1.15, 3, 4),
        feature(2.2, 0.2, 1.4, 2, 4), feature(-5, 0, 1, 2, 4),
        feature(3.2, 0.2, None, 2, 4),
    ]})
    data, _ = map_data(result, tmp_path / "comfort.html", field="comfort_cost", comfort=info, entrances={"features": []})
    assert data["comfort"]["show_default"] is True
    assert (info["window_count"], info["source_count"]) == (3, 5)
    base, middle, highest = data["cells"]
    assert "comfort" not in base
    assert middle["observation_count"] == 0
    assert middle["comfort"] == {"cost": 1, "vertical_rms_mps2": 2, "shocks_per_10m": 2,
                                  "window_count": 2, "color": "#fee08b"}
    assert highest["comfort"]["color"] == "#d73027"
    values, targets = grid_values(result, "comfort_cost")
    assert values[1, 0] == 1 and targets[1, 0] == 1
    assert data["grid_edges"] == []
