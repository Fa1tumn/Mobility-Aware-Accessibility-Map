import math


class grid:
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
        self.rows = max(1, math.ceil(round(self.map_length / self.size, 8)))
        self.columns = max(1, math.ceil(round(self.map_width / self.size, 8)))
        if self.rows * self.columns > 250000:
            raise ValueError("Too many cells. Increase GRID_SIZE or reduce the map area.")
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

    def get_cell_bounds(self, i, j):
        north = self.north - i * self.size
        west = self.west + j * self.size
        return {
            "north": north,
            "south": max(self.south, north - self.size),
            "west": west,
            "east": min(self.east, west + self.size),
        }

    def get_grid(self, latitude, longitude):
        latitude, longitude = float(latitude), float(longitude)
        if not math.isfinite(latitude) or not math.isfinite(longitude):
            raise ValueError("Coordinates must be finite numbers.")
        if not self.south <= latitude <= self.north or not self.west <= longitude <= self.east:
            raise ValueError("Latitude and longitude must be within the map boundaries.")
        i = min(int(round((self.north - latitude) / self.size, 8)), self.rows - 1)
        j = min(int(round((longitude - self.west) / self.size, 8)), self.columns - 1)
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
