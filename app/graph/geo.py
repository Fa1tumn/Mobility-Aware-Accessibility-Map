"""좌표·경사 단위 변환 유틸.

경사는 `%`를 기본 단위로 쓴다(IMU의 slope_percent와 같은 단위).
각도가 필요한 기존 엔진과 만나는 곳에서만 이 함수로 변환한다.
좌표는 GeoJSON 순서인 [경도, 위도]를 따른다.
"""

from __future__ import annotations

import math
from typing import Sequence

EARTH_RADIUS_M = 6_371_000.0


def pct_to_deg(pct: float) -> float:
    """경사율(%) → 경사각(도). 10% ≈ 5.71°."""
    return math.degrees(math.atan(pct / 100.0))


def deg_to_pct(deg: float) -> float:
    """경사각(도) → 경사율(%)."""
    return math.tan(math.radians(deg)) * 100.0


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """두 좌표 사이의 지표면 거리(m)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def polyline_length_m(coords: Sequence[Sequence[float]]) -> float:
    """[[lon, lat], ...] 선의 길이(m)."""
    return sum(haversine_m(a[0], a[1], b[0], b[1]) for a, b in zip(coords, coords[1:]))
