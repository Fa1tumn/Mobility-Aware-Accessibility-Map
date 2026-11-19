"""Cost Function — soft preference만 계산한다.

hard constraint는 feasibility.py가 이미 걸렀다고 가정한다.
여기서는 '지나갈 수 있는 구간이 얼마나 부담스러운가'만 본다.

미측정 값 처리 원칙
    slope_deg=None은 '평평하다'가 아니라 '모른다'이다.
    그래서 0으로 취급하지 않는다. 그러면 측정하지 않은 구간이 가장 싸 보여서
    라우팅이 미측정 구간을 선호하게 된다.
    대신 보수적 기본값(UNKNOWN_SLOPE_PROXY_DEG)을 쓴다.

    이번 데모 프로파일은 w_slope=0이라 이 항이 꺼져 있다. 캠퍼스 경사로가
    대부분 -6도 내외로 균일해 변별력이 없기 때문이다. 나중에 켜더라도 위
    버그가 생기지 않도록 로직만 미리 맞춰둔다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.graph.schema import Edge
from app.profile.definitions import Profile, SURFACE_PENALTY

# 거리 정규화 기준. 100m를 1.0으로 본다.
DISTANCE_UNIT_M = 100.0

# 경사 미측정 구간에 쓰는 보수적 기본값(도).
UNKNOWN_SLOPE_PROXY_DEG = 3.0

# 문턱 미측정 시 가정값(cm). 0으로 두면 미측정이 유리해진다.
UNKNOWN_THRESHOLD_CM = 1.0


@dataclass
class Cost:
    value: float
    reasons: list[str] = field(default_factory=list)   # 부담 요인


def compute(edge: Edge, profile: Profile) -> Cost:
    d = edge.distance_m / DISTANCE_UNIT_M
    total = profile.w_distance * d
    reasons: list[str] = []

    # --- 경사 ---
    if profile.w_slope:
        s = edge.abs_slope_deg
        if s is None:
            s = UNKNOWN_SLOPE_PROXY_DEG
            reasons.append("경사 미측정")
        ratio = s / max(profile.max_slope_deg, 1e-6)
        total += profile.w_slope * ratio * d
        if edge.slope_deg is not None and abs(edge.slope_deg) >= 3.0:
            reasons.append(f"경사 {edge.slope_deg:+.1f}도")

    # --- 노면 ---
    if profile.w_surface:
        sp = SURFACE_PENALTY.get(edge.surface, SURFACE_PENALTY["unknown"])
        total += profile.w_surface * sp * d
        if sp >= 0.5:
            reasons.append(f"노면 {edge.surface}")

    # --- 통행폭 ---
    if profile.w_width and edge.width_level == "narrow":
        total += profile.w_width * d
        reasons.append("통행폭 좁음")

    # --- 관측 불확실성 ---
    if profile.w_uncertainty:
        total += profile.w_uncertainty * (1.0 - edge.confidence) * d
        if edge.confidence < 0.5:
            reasons.append(f"신뢰도 {edge.confidence:.2f}")

    # --- 지점 페널티 ---
    if edge.stairs > 0 and profile.p_stairs_per_step:
        total += profile.p_stairs_per_step * edge.stairs
        reasons.append(f"계단 {edge.stairs}단")

    if profile.p_threshold_per_cm:
        th = UNKNOWN_THRESHOLD_CM if edge.threshold_cm is None else edge.threshold_cm
        if th > 0:
            total += profile.p_threshold_per_cm * th
            reasons.append(f"문턱 {th:.1f}cm")

    return Cost(value=total, reasons=reasons)
