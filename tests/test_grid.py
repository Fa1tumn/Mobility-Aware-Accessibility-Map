import math

import pytest

from app.map.gird import grid
from app.map.grid_pipeline import build_grid, normalize_observation


def observation(**values):
    row = {"latitude": 37.50055, "longitude": 127.00005, "ramp": 1, "ave_vibration": 2, "object": 0}
    row.update(values)
    return row


def test_boundaries_and_partial_cells():
    result = grid(0.0001, (37.5, 127.00025), (37.50025, 127.0))
    assert (result.rows, result.columns) == (3, 3)
    assert result.get_grid(37.50025, 127.0) == (0, 0)
    assert result.get_grid(37.5, 127.00025) == (2, 2)
    assert result.get_grid(37.50015, 127.0001) == (1, 1)
    with pytest.raises(ValueError):
        result.get_grid(37.50026, 127.0)


def test_multiple_observations_use_mean_and_highest_confidence():
    rows = [
        observation(ramp=1, ave_vibration=2, surface_label="road", surface_confidence=0.9),
        observation(ramp=3, ave_vibration=4, surface_label="sidewalk", surface_confidence=0.8),
        observation(ramp=8, ave_vibration=9, object=2),
    ]
    result = build_grid(rows)
    cell = result.grid[(0, 0)]
    assert cell["ramp"] == 4
    assert cell["ave_vibration"] == 5
    assert cell["surface_label"] == "road"
    assert cell["weight"] == pytest.approx(3.4)
    assert cell["observation_count"] == 3


def test_null_values_do_not_erase_measurements():
    result = build_grid([observation(), observation(ramp=None, ave_vibration=None, object=None)])
    cell = result.grid[(0, 0)]
    assert cell["ramp"] == 1
    assert cell["ave_vibration"] == 2
    assert cell["object"] == 0
    assert cell["weight"] == pytest.approx(1)


def test_incomplete_and_empty_cells_have_no_weight():
    result = build_grid([observation(ave_vibration=None)], 0.0001, (37.5006, 127), (37.5, 127.0008))
    assert result.grid[(0, 0)]["weight"] is None
    assert result.grid[(0, 1)]["weight"] is None
    assert result.grid[(0, 1)]["observation_count"] == 0


def test_latest_object_uses_timestamp_with_timezone():
    older = observation(record_time="2026-10-16T08:00:00+09:00", object=3)
    newer = observation(record_time="2026-10-16T00:00:00Z", object=0)
    result = build_grid([newer, older])
    assert result.grid[(0, 0)]["object"] == 0
    assert result.grid[(0, 0)]["record_time"] == newer["record_time"]


@pytest.mark.parametrize("size", [0, -1, math.nan, math.inf])
def test_invalid_grid_size(size):
    with pytest.raises(ValueError):
        build_grid([observation()], size)


@pytest.mark.parametrize("values", [{"latitude": math.nan}, {"ave_vibration": math.inf}, {"object": -1}])
def test_invalid_measurements(values):
    with pytest.raises(ValueError):
        build_grid([observation(**values)])


def test_empty_data_is_reported():
    with pytest.raises(ValueError, match="No observations"):
        build_grid([])


def test_database_fields_and_unsupported_objects():
    row = {
        "latitude": 37.502789,
        "longitude": 126.9905,
        "slope_percent": -9.5,
        "vibration_frequency_avg_hz": 15,
        "objects_supported": 0,
        "objects": None,
    }
    result = build_grid([row])
    cell = result.grid[(0, 0)]
    assert cell["ramp"] == -9.5
    assert cell["ave_vibration"] == 15
    assert cell["object"] is None
    assert cell["weight"] is None
    assert "ramp" not in row


@pytest.mark.parametrize("objects,expected", [('[]', 0), ('[{"label":"person"}]', 1), ([{}, {}], 2), (None, None)])
def test_supported_object_counts(objects, expected):
    row = normalize_observation({"objects_supported": 1, "objects": objects})
    assert row["object"] == expected


def test_unsupported_objects_are_not_used():
    row = normalize_observation({"objects_supported": 0, "objects": '[{"label":"person"}]'})
    assert row["object"] is None


def test_region_ids_and_clipped_boundaries():
    result = grid(0.0001, (37.5, 127.00025), (37.50025, 127.0))
    result.init_grid()
    assert [cell["grid_id"] for cell in result.grid.values()] == list(range(1, 10))
    bounds = result.get_cell_bounds(2, 2)
    assert bounds["south"] == 37.5
    assert bounds["east"] == 127.00025
    assert bounds["north"] == pytest.approx(37.50005)
    assert bounds["west"] == pytest.approx(127.0002)


def test_observations_in_one_region_share_one_weight():
    rows = [
        observation(latitude=37.50055, longitude=127.00005, ramp=1),
        observation(latitude=37.50051, longitude=127.00009, ramp=3),
        observation(latitude=37.50055, longitude=127.00015, ramp=5),
    ]
    result = build_grid(rows, 0.0001, (37.5006, 127), (37.5, 127.0008))
    assert result.grid[(0, 0)]["observation_count"] == 2
    assert result.grid[(0, 0)]["ramp"] == 2
    assert result.grid[(0, 0)]["weight"] == pytest.approx(1.3)
    assert result.grid[(0, 1)]["observation_count"] == 1
    assert result.grid[(0, 1)]["weight"] == pytest.approx(2.2)


def test_size_override_merges_regions(monkeypatch):
    from app.map.grid_pipeline import build_grid_from_env

    bounds = {"GRID_NORTH": "37.5006", "GRID_WEST": "127", "GRID_SOUTH": "37.5", "GRID_EAST": "127.0002"}
    for name, value in bounds.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("GRID_SIZE", "0.0001")
    rows = [observation(longitude=127.00005), observation(longitude=127.00015)]
    original = build_grid_from_env(rows)
    larger = build_grid_from_env(rows, 0.001)
    assert original.columns == 2
    assert larger.columns == 1
    assert larger.size == 0.001
    assert larger.grid[(0, 0)]["observation_count"] == 2
