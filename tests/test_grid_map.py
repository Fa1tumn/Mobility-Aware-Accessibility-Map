import json
import re

import pytest

from app.map.grid_pipeline import build_campus_grid, build_grid
from app.map.grid_visualization import save_grid_map
from scripts.test_grid import YONSEI_DEMO_CELL_SIZE_M, yonsei_observations


def map_data(result, path):
    save_grid_map(result, path)
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
