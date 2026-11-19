"""Mobility Profile 정의.

중요: 이것은 '장애 유형'이 아니라 '이동 환경에 대한 제약과 선호의 집합'이다.
특정 신체 조건을 가진 사람이 무엇을 선호하는지 시스템이 임의로 단정하지 않는다.
아래 3종은 데모용 프리셋이며, 사용자가 값을 직접 조정할 수 있는 구조로 둔다.

단위: 데이터와 화면은 경사율(%)을 쓴다. max_slope_deg는 내부 비교용 각도이며,
경사율로 정할 때는 pct_to_deg()로 변환한다. max_slope_pct 속성으로 %를 읽을 수 있다.

법규 기준값(아래 상수), 사용자 능력, 프로필 한도는 서로 다른 설정이다.
프리셋은 법규 기준을 시작값으로 쓴 데모용 값이며 사용자가 바꿀 수 있다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from app.graph.geo import deg_to_pct, pct_to_deg

# 법규 참고 기준(경사로 기울기 1/12). 프로필 한도를 정할 때 참고값으로만 쓴다.
RAMP_LIMIT_PCT = 100.0 / 12.0       # 8.33%


def _validate_limit_pct(name: str, value: float | None) -> None:
    """방향별 경사 한도(%). None(미지정)이거나 유한한 양수여야 한다."""
    if value is None:
        return
    if not (math.isfinite(value) and value > 0.0):
        raise ValueError(f"{name}는 0보다 큰 유한한 값이어야 한다 ({value!r})")


def _validate_weight(name: str, value: float | None) -> None:
    """방향별 경사 가중치. None(미지정)이거나 0 이상의 유한한 값이어야 한다."""
    if value is None:
        return
    if not (math.isfinite(value) and value >= 0.0):
        raise ValueError(f"{name}는 0 이상의 유한한 값이어야 한다 ({value!r})")


@dataclass(frozen=True)
class Profile:
    name: str

    # --- Hard constraint: 위반하면 통행 불가(INF) ---
    stairs_allowed: bool = True
    max_threshold_cm: float = 100.0
    max_slope_deg: float = 90.0          # 방향 구분 없는 단일 한도(호환용)
    # 오르막/내리막 별도 한도(%). None이면 max_slope_deg를 양방향에 적용한다.
    max_up_pct: float | None = None
    max_down_pct: float | None = None
    min_width_level: str = "narrow"      # narrow < normal < wide

    # --- 가중치: 클수록 그 요소를 더 회피 ---
    w_distance: float = 1.0
    w_slope: float = 0.0                 # 방향 구분 없는 선형 경사비용(호환용)
    # 오르막/내리막 별도 가중치(제곱 비용). 둘 중 하나라도 지정되면 w_slope 대신 쓴다.
    w_up: float | None = None
    w_down: float | None = None
    w_surface: float = 0.0
    w_width: float = 0.0
    w_uncertainty: float = 0.0

    # --- 지점 페널티 (구간당 가산) ---
    p_stairs_per_step: float = 0.0       # 계단 1단당
    p_threshold_per_cm: float = 0.0      # 문턱 1cm당

    def __post_init__(self) -> None:
        # 방향별 경사 한도는 유한한 양수만 허용(0·음수·NaN 거부).
        _validate_limit_pct("max_up_pct", self.max_up_pct)
        _validate_limit_pct("max_down_pct", self.max_down_pct)
        # 방향별 가중치는 0 이상(음수·NaN·무한대 거부).
        _validate_weight("w_up", self.w_up)
        _validate_weight("w_down", self.w_down)

    def with_overrides(self, **kw) -> "Profile":
        """사용자가 값을 바꾼 프로파일을 만든다. max_slope_pct로 경사 한도를 줄 수 있다.

        max_up_pct / max_down_pct는 그대로 받는다(방향별 한도). 방향 한도가
        없으면 uphill_limit_pct / downhill_limit_pct가 max_slope_pct로 폴백한다.
        """
        if "max_slope_pct" in kw:
            kw["max_slope_deg"] = pct_to_deg(kw.pop("max_slope_pct"))
        return replace(self, **kw)

    @property
    def max_slope_pct(self) -> float:
        """방향 구분 없는 경사 한도(%). 90°(제한 없음)는 무한대로 본다."""
        if self.max_slope_deg >= 90.0:
            return float("inf")
        return deg_to_pct(self.max_slope_deg)

    @property
    def uphill_limit_pct(self) -> float:
        """오르막 한도(%). max_up_pct가 없으면 방향 구분 없는 한도로 폴백한다."""
        return self.max_up_pct if self.max_up_pct is not None else self.max_slope_pct

    @property
    def downhill_limit_pct(self) -> float:
        """내리막 한도(%). max_down_pct가 없으면 방향 구분 없는 한도로 폴백한다."""
        return self.max_down_pct if self.max_down_pct is not None else self.max_slope_pct

    @property
    def uses_directional_slope_cost(self) -> bool:
        """오르막/내리막 분리 비용을 쓰는지. w_up·w_down 중 하나라도 지정되면 True."""
        return self.w_up is not None or self.w_down is not None


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
    # 9월 값 유지: 8°는 약 14.1%로, 경사로 기준 1/12(8.33%)보다 느슨하다.
    # 9월 답사에서 캠퍼스 경사로가 약 -6°(약 10.5%)로 기록돼 1/12를 적용하면
    # 데모 graph의 휠체어 경로가 모두 막힌다. 한도는 팀이 정할 값이므로 바꾸지 않고,
    # with_overrides(max_slope_pct=RAMP_LIMIT_PCT)처럼 설정으로 조정한다.
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
