from unittest.mock import patch

import pytest

from scripts.refresh_grid import has_coordinates, main, select_latest_day


@pytest.mark.parametrize("latitude,longitude", [(None, 126.67), (37.38, None), ("", 126.67), (float("nan"), 126.67), (37.38, float("inf")), (91, 126.67)])
def test_missing_or_invalid_coordinates_are_excluded(latitude, longitude):
    assert not has_coordinates({"latitude": latitude, "longitude": longitude})


def test_latest_day_excludes_old_and_unlocated_records():
    older = {"record_time": "2026-11-04T23:00:00Z", "latitude": 37.38, "longitude": 126.67}
    latest = {**older, "record_time": "2026-11-05T00:00:00Z"}
    missing = {**latest, "latitude": None}
    day, selected = select_latest_day([older, latest, missing])
    assert str(day) == "2026-11-05"
    assert selected == [latest]


def test_newest_day_without_coordinates_does_not_reuse_old_data():
    rows = [
        {"record_time": "2026-11-04T00:00:00Z", "latitude": 37.38, "longitude": 126.67},
        {"record_time": "2026-11-05T00:00:00Z", "latitude": None, "longitude": None},
    ]
    with pytest.raises(ValueError, match="2026-11-05"):
        select_latest_day(rows)


def test_fetch_failure_does_not_run_generator(monkeypatch):
    monkeypatch.setattr("sys.argv", ["refresh_grid"])
    with patch("scripts.refresh_grid.fetch_observations", side_effect=RuntimeError("offline")), patch("scripts.refresh_grid.subprocess.run") as run:
        with pytest.raises(SystemExit) as error:
            main()
        assert error.value.code == 1
        run.assert_not_called()
