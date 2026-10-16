import json
import os
from datetime import datetime, timezone

from app.map.gird import grid


def normalize_observation(observation):
    row = dict(observation)
    if "ramp" not in row:
        row["ramp"] = row.get("slope_percent")
    if "ave_vibration" not in row:
        row["ave_vibration"] = row.get("vibration_frequency_avg_hz")
    if "object" not in row:
        row["object"] = None
        if row.get("objects_supported") in (1, True):
            objects = row.get("objects")
            if isinstance(objects, str):
                objects = json.loads(objects)
            if isinstance(objects, list):
                row["object"] = len(objects)
            elif objects is not None:
                raise ValueError("objects must be a JSON list when objects_supported is 1.")
    return row


def observation_time(observation):
    value = observation.get("record_time")
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    time = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if time.tzinfo is None:
        time = time.replace(tzinfo=timezone.utc)
    return time.astimezone(timezone.utc)


def build_grid(observations, size=0.0001, map_left_top=None, map_right_bottom=None):
    if not observations:
        raise ValueError("No observations. Check the table and its SELECT policy.")
    observations = [normalize_observation(row) for row in observations]
    size = float(size)
    if (map_left_top is None) != (map_right_bottom is None):
        raise ValueError("Provide both map corners or leave both unset.")
    if map_left_top is None:
        latitudes = [float(row["latitude"]) for row in observations]
        longitudes = [float(row["longitude"]) for row in observations]
        map_left_top = (max(latitudes) + size / 2, min(longitudes) - size / 2)
        map_right_bottom = (min(latitudes) - size / 2, max(longitudes) + size / 2)
    result = grid(size, map_right_bottom, map_left_top, observations)
    result.init_grid()
    for row in sorted(observations, key=observation_time):
        result.insert_grid_observation(row)
    return result


def build_grid_from_env(observations, size=None):
    names = ("GRID_NORTH", "GRID_WEST", "GRID_SOUTH", "GRID_EAST")
    bounds = [os.getenv(name, "").strip() for name in names]
    if any(bounds) and not all(bounds):
        raise ValueError("Set all four GRID boundary values, or leave all four empty.")
    left_top = (float(bounds[0]), float(bounds[1])) if all(bounds) else None
    right_bottom = (float(bounds[2]), float(bounds[3])) if all(bounds) else None
    return build_grid(observations, size if size is not None else os.getenv("GRID_SIZE", "0.0001"), left_top, right_bottom)
