"""두 경로의 차이를 사용자에게 보여줄 문장으로 바꾼다.

비용 값(1.46 같은)은 사용자에게 의미가 없다. 대신 요약값 차이만으로 말한다.
    "60m 더 걸음", "오르막 15.0% 1곳 회피", "경사 미측정 40m 포함"
"""

from __future__ import annotations

from app.routing.metrics import RouteMetrics, SteepSegment

# 이보다 작은 차이는 말하지 않는다(GPS·graph 오차 수준).
DISTANCE_EPS_M = 5.0


def _pct_text(segments: list[SteepSegment]) -> str:
    if len(segments) == 1:
        return f"{abs(segments[0].slope_pct):.1f}%"
    return f"최대 {max(abs(s.slope_pct) for s in segments):.1f}%"


def explain(chosen: RouteMetrics, other: RouteMetrics) -> list[str]:
    """chosen 경로가 other 경로와 무엇이 다른지. chosen 입장에서 쓴다."""
    out: list[str] = []

    d = chosen.distance_m - other.distance_m
    if d >= DISTANCE_EPS_M:
        out.append(f"{d:.0f}m 더 걸음")
    elif d <= -DISTANCE_EPS_M:
        out.append(f"{-d:.0f}m 더 짧음")

    mine = {s.edge for s in chosen.steep}
    theirs = {s.edge for s in other.steep}
    for direction in ("오르막", "내리막"):
        avoided = [s for s in other.steep if s.direction == direction and s.edge not in mine]
        added = [s for s in chosen.steep if s.direction == direction and s.edge not in theirs]
        if avoided:
            out.append(f"{direction} {_pct_text(avoided)} {len(avoided)}곳 회피")
        if added:
            out.append(f"{direction} {_pct_text(added)} {len(added)}곳 지남")

    s = other.stairs - chosen.stairs
    if s > 0:
        out.append(f"계단 {s}단 회피")
    elif s < 0:
        out.append(f"계단 {-s}단 지남")

    u = chosen.unknown_slope_m - other.unknown_slope_m
    if u >= DISTANCE_EPS_M:
        out.append(f"경사 미측정 {u:.0f}m 포함")
    elif u <= -DISTANCE_EPS_M:
        out.append(f"경사 미측정 {-u:.0f}m 적음")

    mine_ev = {i for i, _ in chosen.events}
    theirs_ev = {i for i, _ in other.events}
    for event_id, label in other.events:
        if event_id not in mine_ev:
            out.append(f"{label} 구간 회피 ({event_id})")
    for event_id, label in chosen.events:
        if event_id not in theirs_ev:
            out.append(f"{label} 구간 지남 ({event_id})")
    return out
