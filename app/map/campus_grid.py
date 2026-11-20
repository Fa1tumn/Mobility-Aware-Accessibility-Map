import json
import math
from pathlib import Path

from app.map.gird import MAX_CELLS, grid


CAMPUS_CONFIG = Path(__file__).resolve().parents[2] / "config" / "campus_grid.json"
DEFAULT_CELL_SIZE_M = 10.0


def meters_per_degree(latitude):
    angle = math.radians(latitude)
    axis = 6378137.0
    eccentricity_squared = 0.00669437999014
    radius_factor = 1 - eccentricity_squared * math.sin(angle) ** 2
    north = math.radians(axis * (1 - eccentricity_squared) / radius_factor ** 1.5)
    east = math.radians(axis * math.cos(angle) / math.sqrt(radius_factor))
    return north, east


class CampusGrid(grid):
    boundary_tolerance = 1e-8

    def __init__(self, top_left, top_right, depth_m, cell_size_m):
        self.origin_latitude, self.origin_longitude = map(float, top_left)
        self.map_left_top = (self.origin_latitude, self.origin_longitude)
        right_latitude, right_longitude = map(float, top_right)
        if not (-90 < self.origin_latitude < 90 and -90 < right_latitude < 90
                and -180 <= self.origin_longitude < right_longitude <= 180):
            raise ValueError("Campus top corners must be valid coordinates ordered from west to east.")
        depth_m, cell_size_m = float(depth_m), float(cell_size_m)
        if not all(math.isfinite(value) and value > 0 for value in (depth_m, cell_size_m)):
            raise ValueError("Campus depth and cell size must be positive and finite.")

        self.latitude_scale, self.longitude_scale = meters_per_degree(self.origin_latitude)
        east = (right_longitude - self.origin_longitude) * self.longitude_scale
        north = (right_latitude - self.origin_latitude) * self.latitude_scale
        self.map_width = math.hypot(east, north)
        self.across_east, self.across_north = east / self.map_width, north / self.map_width

        if self.map_width / cell_size_m > MAX_CELLS:
            raise ValueError("Too many cells. Increase the cell size or reduce the map area.")
        columns = max(1, math.ceil(round(self.map_width / cell_size_m, 8)))
        self.size = self.map_width / columns
        if depth_m / self.size > MAX_CELLS:
            raise ValueError("Too many cells. Increase the cell size or reduce the map area.")
        self.map_length = max(1, math.ceil(round(depth_m / self.size, 8))) * self.size
        self._set_dimensions(observations=None)

        self.map_right_bottom = self.to_geographic(self.map_length, self.map_width)
        corners = [self.to_geographic(down, across)
                   for down in (0, self.map_length) for across in (0, self.map_width)]
        latitudes, longitudes = zip(*corners)
        self.north, self.south = max(latitudes), min(latitudes)
        self.west, self.east = min(longitudes), max(longitudes)

    def to_geographic(self, down, across):
        north = across * self.across_north - down * self.across_east
        east = across * self.across_east + down * self.across_north
        return (self.origin_latitude + north / self.latitude_scale,
                self.origin_longitude + east / self.longitude_scale)

    def to_grid_offsets(self, latitude, longitude):
        north = (latitude - self.origin_latitude) * self.latitude_scale
        east = (longitude - self.origin_longitude) * self.longitude_scale
        down = east * self.across_north - north * self.across_east
        across = east * self.across_east + north * self.across_north
        return down, across


def load_campus_grid(cell_size_m=None, size_degrees=None):
    settings = json.loads(CAMPUS_CONFIG.read_text(encoding="utf-8"))
    if size_degrees is not None:
        latitude_scale, _ = meters_per_degree(settings["top_left"][0])
        cell_size_m = size_degrees * latitude_scale
    if cell_size_m is None:
        cell_size_m = DEFAULT_CELL_SIZE_M
    return CampusGrid(settings["top_left"], settings["top_right"], settings["depth_m"], cell_size_m)
