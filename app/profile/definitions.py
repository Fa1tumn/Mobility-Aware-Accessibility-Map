"""Mobility Profile 정의.

중요: 이것은 '장애 유형'이 아니라 '이동 환경에 대한 제약과 선호의 집합'이다.
특정 신체 조건을 가진 사람이 무엇을 선호하는지 시스템이 임의로 단정하지 않는다.
아래 3종은 데모용 프리셋이며, 사용자가 값을 직접 조정할 수 있는 구조로 둔다.

단위: max_slope_deg는 도(degree). Edge.slope_deg와 같은 단위여야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Profile:
    name: str

    # --- Hard constraint: 위반하면 통행 불가(INF) ---
    stairs_allowed: bool = True
    max_threshold_cm: float = 100.0
    max_slope_deg: float = 90.0
    min_width_level: str = "narrow"      # narrow < normal < wide

    # --- 가중치: 클수록 그 요소를 더 회피 ---
    w_distance: float = 1.0
    w_slope: float = 0.0
    w_surface: float = 0.0
    w_width: float = 0.0
    w_uncertainty: float = 0.0

    # --- 지점 페널티 (구간당 가산) ---
    p_stairs_per_step: float = 0.0       # 계단 1단당
    p_threshold_per_cm: float = 0.0      # 문턱 1cm당

    def with_overrides(self, **kw) -> "Profile":
        """사용자가 값을 바꾼 프로파일을 만든다."""
        return replace(self, **kw)


WIDTH_RANK = {"narrow": 0, "normal": 1, "wide": 2, "unknown": 1}

# 노면이 통행에 주는 부담 (0~1)
SURFACE_PENALTY = {
    "unknown": 0.3,      # 모르면 중간값. 낙관하지 않는다
    "asphalt": 0.0,
    "concrete": 0.0,
    "tile": 0.1,
    "block": 0.2,
    "tactile": 0.3,
    "damaged": 1.0,
}


# ---------------------------------------------------------------- 프리셋

DEFAULT = Profile(
    name="default",
    stairs_allowed=True,
    w_distance=1.0,
    w_slope=0.0,      # 캠퍼스 경사로가 균일해 변별력 없음
    p_stairs_per_step=0.02,
)

WHEELCHAIR = Profile(
    name="wheelchair",
    stairs_allowed=False,          # 계단은 통행 불가
    max_threshold_cm=2.0,          # 편의증진법 기준 참고값
    max_slope_deg=8.0,
    min_width_level="normal",
    w_distance=1.0,
    w_slope=0.0,      # max_slope_deg는 feasibility에서 hard constraint로 유지
    w_surface=2.0,
    w_width=1.0,
    w_uncertainty=1.0,
    p_threshold_per_cm=2.0,
)

LUGGAGE = Profile(
    name="luggage",                # 캐리어. 계단 가능하지만 매우 불편
    stairs_allowed=True,
    max_threshold_cm=10.0,
    w_distance=1.0,
    w_slope=0.0,
    w_surface=1.5,
    w_uncertainty=0.3,
    p_stairs_per_step=0.5,         # 단수에 비례해 크게 가산
    p_threshold_per_cm=0.3,
)

PRESETS: dict[str, Profile] = {
    p.name: p for p in (DEFAULT, WHEELCHAIR, LUGGAGE)
}


def get(name: str) -> Profile:
    if name not in PRESETS:
        raise KeyError(f"알 수 없는 프로파일 '{name}'. 사용 가능: {sorted(PRESETS)}")
    return PRESETS[name]
