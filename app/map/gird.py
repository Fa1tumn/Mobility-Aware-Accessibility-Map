import math


MAX_CELLS = 250_000


class grid:
    boundary_tolerance = 0

    def __init__(self, size, map_right_bottom, map_left_top, observations=None):
        self.size = float(size)
        self.north, self.west = map(float, map_left_top)
        self.south, self.east = map(float, map_right_bottom)
        values = [self.size, self.north, self.south, self.west, self.east]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Grid settings must be finite numbers.")
        if self.size <= 0 or not -90 <= self.south < self.north <= 90:
            raise ValueError("Check grid size and latitude boundaries.")
        if not -180 <= self.west < self.east <= 180:
            raise ValueError("Check longitude boundaries.")
        self.map_left_top = (self.north, self.west)
        self.map_right_bottom = (self.south, self.east)
        self.map_length = self.north - self.south
        self.map_width = self.east - self.west
        self._set_dimensions(observations)

    def _set_dimensions(self, observations):
        if max(self.map_length, self.map_width) / self.size > MAX_CELLS:
            raise ValueError("Too many cells. Increase the cell size or reduce the map area.")
        self.rows = max(1, math.ceil(round(self.map_length / self.size, 8)))
        self.columns = max(1, math.ceil(round(self.map_width / self.size, 8)))
        if self.rows * self.columns > MAX_CELLS:
            raise ValueError("Too many cells. Increase the cell size or reduce the map area.")
        self.observations = [] if observations is None else observations
        self.grid = {}
        self.counts = {}

    def init_grid(self):
        self.grid = {}
        self.counts = {}
        for i in range(self.rows):
            for j in range(self.columns):
                self.grid[(i, j)] = {
                    "grid_id": i * self.columns + j + 1,
                    "record_time": None,
                    "surface_label": None,
                    "surface_confidence": None,
                    "ramp": None,
                    "ave_vibration": None,
                    "object": None,
                    "weight": None,
                    "observation_count": 0,
                }
                self.counts[(i, j)] = {"ramp": 0, "ave_vibration": 0}
        return self.grid

    def row_edge(self, i):
        return min(i * self.size, self.map_length)

    def column_edge(self, j):
        return min(j * self.size, self.map_width)

    def to_geographic(self, down, across):
        return self.north - down, self.west + across

    def to_grid_offsets(self, latitude, longitude):
        return self.north - latitude, longitude - self.west

    def get_cell_corners(self, i, j):
        top, bottom = self.row_edge(i), self.row_edge(i + 1)
        left, right = self.column_edge(j), self.column_edge(j + 1)
        return [self.to_geographic(down, across) for down, across in (
            (top, left), (top, right), (bottom, right), (bottom, left),
        )]

    def get_cell_geometry(self, i, j):
        corners = self.get_cell_corners(i, j)
        latitudes, longitudes = zip(*corners)
        return {
            "north": max(latitudes),
            "south": min(latitudes),
            "west": min(longitudes),
            "east": max(longitudes),
            "corners": corners,
        }

    def get_cell_bounds(self, i, j):
        bounds = self.get_cell_geometry(i, j)
        del bounds["corners"]
        return bounds

    def get_grid(self, latitude, longitude):
        latitude, longitude = float(latitude), float(longitude)
        if not math.isfinite(latitude) or not math.isfinite(longitude):
            raise ValueError("Coordinates must be finite numbers.")
        down, across = self.to_grid_offsets(latitude, longitude)
        tolerance = self.boundary_tolerance
        if not (-tolerance <= down <= self.map_length + tolerance and
                -tolerance <= across <= self.map_width + tolerance):
            raise ValueError("Latitude and longitude must be within the map boundaries.")
        i = min(int(round(down / self.size, 8)), self.rows - 1)
        j = min(int(round(across / self.size, 8)), self.columns - 1)
        return i, j

    def weight_grid(self, i, j, ramp_weight=0.3, vibration_weight=0.3, object_weight=0.3, bias=0.1):
        cell = self.grid[(i, j)]
        if any(cell[field] is None for field in ("ramp", "ave_vibration", "object")):
            return None
        return ramp_weight * cell["ramp"] + vibration_weight * cell["ave_vibration"] + object_weight * cell["object"] + bias

    def insert_grid_observation(self, observation):
        i, j = self.get_grid(observation["latitude"], observation["longitude"])
        numbers = {}
        for field in ("surface_confidence", "ramp", "ave_vibration", "object"):
            value = observation.get(field)
            if value is not None:
                value = float(value)
                if not math.isfinite(value):
                    raise ValueError(f"{field} must be a finite number.")
                if field in ("ave_vibration", "object") and value < 0:
                    raise ValueError(f"{field} cannot be negative.")
                if field == "surface_confidence" and not 0 <= value <= 1:
                    raise ValueError("surface_confidence must be between 0 and 1.")
            numbers[field] = value
        if not self.grid:
            self.init_grid()
        cell = self.grid[(i, j)]
        confidence = numbers["surface_confidence"]
        if observation.get("surface_label") is not None and confidence is not None:
            if cell["surface_confidence"] is None or confidence > cell["surface_confidence"]:
                cell["surface_label"] = observation["surface_label"]
                cell["surface_confidence"] = confidence
        for field in ("ramp", "ave_vibration"):
            value = numbers[field]
            if value is not None:
                count = self.counts[(i, j)][field]
                previous = cell[field] if count else 0
                cell[field] = (previous * count + value) / (count + 1)
                self.counts[(i, j)][field] = count + 1
        if numbers["object"] is not None:
            cell["object"] = numbers["object"]
        if observation.get("record_time") is not None:
            cell["record_time"] = observation["record_time"]
        cell["observation_count"] += 1
        cell["weight"] = self.weight_grid(i, j)
        return self.grid
