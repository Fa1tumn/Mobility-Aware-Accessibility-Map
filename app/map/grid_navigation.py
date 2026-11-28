"""캠퍼스 격자 지도에 표시할 출입구와 인접 격자 경로를 구성한다."""

from app.graph.geo import haversine_m
from app.profile.definitions import SURFACE_PENALTY, WHEELCHAIR


SURFACE_ALIASES = {"blocks": "block", "cement": "concrete"}
ENTRANCE_MAP_FIELDS = ("id", "kind", "building_name", "entrance_name", "wheelchair",
                       "stairs", "threshold_cm", "ramp", "opening_hours", "note", "photo_url")


def entrance_targets(result, collection):
    occupied = [(i, j, cell["grid_id"]) for (i, j), cell in result.grid.items()
                if cell["observation_count"]]
    targets = []
    for feature in collection["features"]:
        props = feature["properties"]
        geometry = feature.get("geometry") or {}
        if props.get("kind") not in ("place", "entrance") or geometry.get("type") != "Point":
            continue
        coordinates = geometry.get("coordinates") or []
        if len(coordinates) < 2:
            continue
        lon, lat = coordinates[:2]
        if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        target = None
        if props["kind"] == "entrance" and occupied:
            target = nearest_occupied_cell(result, occupied, lat, lon)
        details = {key: props[key] for key in ENTRANCE_MAP_FIELDS if key in props}
        targets.append({"lat": lat, "lon": lon, "properties": details, "target": target})
    return targets


def nearest_occupied_cell(result, occupied, lat, lon):
    try:
        position = result.get_grid(lat, lon)
    except ValueError:
        position = None
    if position is not None:
        cell = result.grid[position]
        if cell["observation_count"]:
            return {"grid_id": cell["grid_id"], "distance_m": 0, "in_cell": True}

    down, across = result.to_grid_offsets(lat, lon)

    def distance(candidate):
        i, j, grid_id = candidate
        nearest = result.to_geographic(
            min(max(down, result.row_edge(i)), result.row_edge(i + 1)),
            min(max(across, result.column_edge(j)), result.column_edge(j + 1)),
        )
        return haversine_m(lon, lat, nearest[1], nearest[0]), grid_id

    distance_m, grid_id = min(map(distance, occupied))
    return {"grid_id": grid_id, "distance_m": distance_m, "in_cell": False}


def surface_penalty(cell):
    label = cell.get("surface_label")
    unknown = SURFACE_PENALTY["unknown"]
    penalty = SURFACE_PENALTY.get(SURFACE_ALIASES.get(label, label), unknown)
    confidence = float(cell.get("surface_confidence") or 0)
    return unknown + confidence * (penalty - unknown)


def observed_grid_edges(cells):
    """변이나 꼭짓점을 맞댄 관측 격자의 중심을 연결한다."""
    observed = {(cell["row"], cell["column"]): cell for cell in cells if cell["observation_count"]}
    penalties = {position: surface_penalty(cell) for position, cell in observed.items()}
    edges = []
    for (row, col), cell in observed.items():
        lat, lon = cell["center"]
        # 다른 끝점에서도 같은 간선을 만들지 않도록 오른쪽과 다음 행만 확인한다.
        for dy, dx in ((0, 1), (1, -1), (1, 0), (1, 1)):
            neighbor_pos = (row + dy, col + dx)
            neighbor = observed.get(neighbor_pos)
            if neighbor is None:
                continue
            other_lat, other_lon = neighbor["center"]
            distance = haversine_m(lon, lat, other_lon, other_lat)
            penalty = distance * WHEELCHAIR.w_surface * (penalties[(row, col)] + penalties[neighbor_pos]) / 2
            edges.append([cell["grid_id"], neighbor["grid_id"], distance, penalty])
    return edges
