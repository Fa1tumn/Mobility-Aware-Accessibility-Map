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

오르막·내리막 분리 비용
    프로필에 w_up 또는 w_down이 있으면 w_slope 대신 아래 식을 쓴다.
    경사는 진행 방향 기준이다(역방향 간선은 Graph.outgoing이 부호를 뒤집어 준다).

        오르막 g > 0:  w_up   × (g / 오르막 한도)²
        내리막 g < 0:  w_down × (|g| / 내리막 한도)²

    거리(100m 단위)를 곱해 더한다. 한도에 닿은 경사는 100m당 w_up(또는 w_down)이고,
    경사가 두 배면 비용은 네 배다. 한도가 무한대(제한 없음)면 RAMP_LIMIT_PCT를 기준으로 쓴다.
    미측정 경사는 방향을 모르므로 보수값(UNKNOWN_SLOPE_PROXY_DEG)을 오르막·내리막
    양쪽에 넣어 보고 더 큰 쪽을 쓴다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.graph.geo import deg_to_pct
from app.graph.schema import Edge
from app.profile.definitions import RAMP_LIMIT_PCT, SURFACE_PENALTY, Profile

# 거리 정규화 기준. 100m를 1.0으로 본다.
DISTANCE_UNIT_M = 100.0

# 경사 미측정 구간에 쓰는 보수적 기본값(도).
UNKNOWN_SLOPE_PROXY_DEG = 3.0

# 문턱 미측정 시 가정값(cm). 0으로 두면 미측정이 유리해진다.
UNKNOWN_THRESHOLD_CM = 1.0

# 방향별 경사 비용: 이 이상인 경사를 비용 사유로 표시한다(%).
SLOPE_REASON_PCT = 5.0


@dataclass
class Cost:
    value: float
    reasons: list[str] = field(default_factory=list)   # 부담 요인


def _slope_ref_pct(limit_pct: float) -> float:
    """제곱 비용의 기준 경사(%). 한도가 없으면(무한대) 법규 참고값을 쓴다."""
    return limit_pct if math.isfinite(limit_pct) else RAMP_LIMIT_PCT


def directional_slope_factor(slope_pct: float, profile: Profile) -> float:
    """진행 방향 경사(%) 하나의 비용 계수(100m당). 오르막·내리막을 따로 본다."""
    if slope_pct > 0:
        ratio = slope_pct / _slope_ref_pct(profile.uphill_limit_pct)
        return (profile.w_up or 0.0) * ratio * ratio
    if slope_pct < 0:
        ratio = -slope_pct / _slope_ref_pct(profile.downhill_limit_pct)
        return (profile.w_down or 0.0) * ratio * ratio
    return 0.0


def compute(edge: Edge, profile: Profile) -> Cost:
    d = edge.distance_m / DISTANCE_UNIT_M
    total = profile.w_distance * d
    reasons: list[str] = []

    # --- 경사 (오르막·내리막 분리) ---
    if profile.uses_directional_slope_cost:
        if edge.slope_pct is None:
            # 방향을 모르므로 양쪽 중 더 부담스러운 쪽으로 본다. 0으로 두지 않는다.
            proxy = deg_to_pct(UNKNOWN_SLOPE_PROXY_DEG)
            factor = max(directional_slope_factor(proxy, profile),
                         directional_slope_factor(-proxy, profile))
            reasons.append("경사 미측정")
        else:
            factor = directional_slope_factor(edge.slope_pct, profile)
            if edge.abs_slope_pct >= SLOPE_REASON_PCT:
                direction = "오르막" if edge.slope_pct > 0 else "내리막"
                reasons.append(f"{direction} {edge.abs_slope_pct:.1f}%")
        total += factor * d

    # --- 경사 (방향 구분 없는 선형, 호환용) ---
    elif profile.w_slope:
        s = edge.abs_slope_deg
        if s is None:
            s = UNKNOWN_SLOPE_PROXY_DEG
            reasons.append("경사 미측정")
        ratio = s / max(profile.max_slope_deg, 1e-6)
        total += profile.w_slope * ratio * d
        if edge.slope_deg is not None and abs(edge.slope_deg) >= 3.0:
            reasons.append(f"경사 {edge.slope_pct:+.1f}%")

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
