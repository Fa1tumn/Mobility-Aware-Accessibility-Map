"""주행 기록에서 경사로 구간의 시작·끝과 휠체어 속도를 뽑는다.

입력은 Rubik의 2초 창 관측(record_time, latitude, longitude, slope_percent)이다.
경사는 진행 방향 기준(+ 오르막)이고, 평지에서도 0이 아니다(자세·장착 편향).

순서
    1. 세션 분리: 기록이 max_gap_s보다 오래 끊기면 다른 주행으로 본다.
    2. 편향 추정: 평지가 대부분이므로 중앙값 근처(±flat_band_pct)만 남겨 중앙값을 다시 구한다.
       g = slope - bias
    3. 경사로 핵심 구간: |g| ≥ on_pct에서 시작해 |g| ≥ off_pct인 동안 이어지는 같은 부호 구간
       (히스테리시스). min_windows보다 짧으면 버리고, merge_gap 이하로 끊긴 같은 부호 구간은 잇는다.
    4. 시작·끝 (gradient): 변화율 dg/dt(%/s)를 구해 핵심 구간 앞뒤 search 창 안에서
         - 경계(edge):  변화율이 가장 큰 곳. 2초 평균은 계단 모양 경사를 기울어진 선으로
                        뭉개는데, 그 선의 가운데(= 변화율 최대 = 고원값의 절반)가 실제 경계다.
                        고원값 절반을 지나는 시각을 선형 보간해 2초보다 촘촘하게 잡는다.
         - 변화 시작(onset): 경계에서 거슬러 올라가며 변화율이 최대값의 onset_frac 아래로
                        떨어지는 시각. 끝 쪽은 같은 방식으로 변화가 끝나는 시각(settle).
       onset~edge 사이는 '전이 구간'으로 표시한다. 간선 경사 프로필을 채울 때 이 구간은
       평지와 고원값 사이를 선형으로 잇고, 대표 경사에는 넣지 않는다.
    5. 길이·속도: GPS 좌표를 시간으로 보간하고 이동 평균(pos_smooth 창)한 뒤 누적 거리를 구해
       경계 시각에서의 거리 차이를 길이로, 길이/시간을 평균 속도로 쓴다.
    6. 같은 장소: 경사로 중간 지점이 same_place_m 안이면 같은 경사로로 묶는다(오르내림 왕복 확인용).

numpy만 쓴다. 그림은 scripts/ramp_segments.py가 matplotlib으로 그린다.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence

import numpy as np

KST = timezone(timedelta(hours=9))
EARTH_R = 6_371_000.0
_NULLS = {"", "null", "none", "nan"}


@dataclass
class Sample:
    t: datetime                      # UTC
    lat: Optional[float]
    lon: Optional[float]
    slope: Optional[float]           # %, 진행 방향 기준 (+ 오르막)


@dataclass
class Params:
    on_pct: float = 3.0              # 핵심 구간 시작 문턱 (편향 보정 후 |g|)
    off_pct: float = 1.5             # 핵심 구간 유지 문턱
    min_windows: int = 3             # 핵심 구간 최소 창 수 (2초 창이면 6초)
    merge_gap: int = 1               # 같은 부호 구간 사이 허용 끊김 (창 수)
    search: int = 3                  # 경계 탐색 범위 (핵심 구간 앞뒤 창 수)
    onset_frac: float = 0.2          # 변화 시작 = 변화율이 최대값의 이 비율 아래로 떨어지는 곳
    max_gap_s: float = 6.0           # 이보다 긴 기록 끊김은 세션 분리
    flat_band_pct: float = 2.0       # 편향 추정 시 평지로 볼 범위
    bias: Optional[float] = None     # 주면 추정하지 않고 이 값 사용
    pos_smooth: int = 5              # 좌표 이동 평균 창 수
    min_speed: float = 0.3           # 이동 중으로 볼 최소 속도 (m/s)
    same_place_m: float = 25.0       # 같은 경사로로 묶는 중간 지점 거리


@dataclass
class Ramp:
    idx: int
    session: int
    direction: str                   # up | down
    slope_pct: float                 # 핵심 구간 중앙값, 편향 보정, 부호 포함
    slope_p90_pct: float             # |g|의 90번째 백분위 (부호 포함)
    start_onset: datetime            # 변화 시작
    start: datetime                  # 시작 경계 (변화율 최대)
    end: datetime                    # 끝 경계
    end_settle: datetime             # 변화 끝
    duration_s: float                # start → end
    onset_s: float                   # start_onset → start
    settle_s: float                  # end → end_settle
    peak_rate_in: float              # 시작 경계의 변화율 (%/s, 부호 포함)
    peak_rate_out: float
    n_windows: int                   # 핵심 구간 창 수
    length_m: Optional[float] = None
    speed_mps: Optional[float] = None
    rise_m: Optional[float] = None   # Σ g/100 · ds (오르막 +)
    start_lat: Optional[float] = None
    start_lon: Optional[float] = None
    end_lat: Optional[float] = None
    end_lon: Optional[float] = None
    place: Optional[int] = None      # 같은 장소 묶음 번호
    gps_points: int = 0              # 경계 사이 실제 GPS 표본 수 (0이면 길이·속도 없음)
    clipped: bool = False            # 세션 처음·끝에 걸려 경계를 못 찾음

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("start_onset", "start", "end", "end_settle"):
            d[k] = getattr(self, k).astimezone(KST).isoformat(timespec="seconds")
        return d


@dataclass
class Analysis:
    params: Params
    bias_pct: float
    n_samples: int
    n_sessions: int
    t: np.ndarray                    # 초, 첫 표본 기준
    t0: datetime
    session: np.ndarray              # 표본별 세션 번호
    slope: np.ndarray                # 원래 값 (NaN 보간 전)
    g: np.ndarray                    # 편향 보정, 세션 안 보간
    rate: np.ndarray                 # dg/dt (%/s)
    phase: list[str]                 # flat | onset | ramp | settle
    dist: np.ndarray                 # 세션별 누적 거리 (m), 좌표 없으면 NaN
    speed: np.ndarray                # 창별 속도 (m/s)
    ramps: list[Ramp] = field(default_factory=list)

    def summary(self) -> dict:
        def stat(mask):
            v = self.speed[mask & np.isfinite(self.speed) & (self.speed >= self.params.min_speed)]
            if v.size == 0:
                return None
            return {"median": round(float(np.median(v)), 2),
                    "p25": round(float(np.percentile(v, 25)), 2),
                    "p75": round(float(np.percentile(v, 75)), 2), "n": int(v.size)}

        phase = np.array(self.phase)
        sign = np.zeros(len(self.g))
        for r in self.ramps:
            i0, i1 = self._span(r)
            sign[i0:i1 + 1] = 1 if r.direction == "up" else -1
        places = {r.place for r in self.ramps if r.place is not None}
        return {
            "bias_pct": round(self.bias_pct, 2),
            "samples": self.n_samples,
            "sessions": self.n_sessions,
            "ramps": len(self.ramps),
            "ramps_up": sum(r.direction == "up" for r in self.ramps),
            "ramps_down": sum(r.direction == "down" for r in self.ramps),
            "places": len(places),
            "speed_flat": stat(phase == "flat"),
            "speed_up": stat((phase == "ramp") & (sign > 0)),
            "speed_down": stat((phase == "ramp") & (sign < 0)),
            "onset_s_median": _round(np.median([r.onset_s for r in self.ramps])) if self.ramps else None,
            "settle_s_median": _round(np.median([r.settle_s for r in self.ramps])) if self.ramps else None,
        }

    def _span(self, r: Ramp) -> tuple[int, int]:
        ts = np.array([(r.start - self.t0).total_seconds(), (r.end - self.t0).total_seconds()])
        i0 = int(np.searchsorted(self.t, ts[0], side="left"))
        i1 = int(np.searchsorted(self.t, ts[1], side="right")) - 1
        return i0, max(i0, i1)


# ---------------------------------------------------------------- 입력

def _num(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return None if (isinstance(v, float) and math.isnan(v)) else float(v)
    s = str(v).strip()
    if s.lower() in _NULLS:
        return None
    return float(s)


def _time(v: str) -> datetime:
    s = str(v).strip().replace(" ", "T", 1)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    elif len(s) > 3 and s[-3] in "+-" and s[-2:].isdigit() and ":" not in s[-6:]:
        s += ":00"                      # Supabase CSV: "+00"
    t = datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _row(r: dict) -> Sample:
    return Sample(t=_time(r["record_time"]), lat=_num(r.get("latitude")),
                  lon=_num(r.get("longitude")), slope=_num(r.get("slope_percent")))


def load_samples(path: str | Path) -> list[Sample]:
    """Supabase에서 내려받은 CSV 또는 JSON(행 목록, 또는 {"observations": [...]})."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = raw if isinstance(raw, list) else raw.get("observations") or raw.get("rows") or []
    else:
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    samples = [_row(r) for r in rows if r.get("record_time")]
    samples.sort(key=lambda s: s.t)
    return samples


# ---------------------------------------------------------------- 계산 도구

def estimate_bias(slope: np.ndarray, band: float = 2.0, rounds: int = 3) -> float:
    v = slope[np.isfinite(slope)]
    if v.size == 0:
        return 0.0
    b = float(np.median(v))
    for _ in range(rounds):
        near = v[np.abs(v - b) < band]
        if near.size == 0:
            break
        b = float(np.median(near))
    return b


def _fill(t: np.ndarray, y: np.ndarray) -> np.ndarray:
    ok = np.isfinite(y)
    if ok.sum() == 0:
        return y.copy()
    if ok.sum() == 1:
        return np.full_like(y, y[ok][0])
    return np.interp(t, t[ok], y[ok])


def _moving_mean(y: np.ndarray, n: int) -> np.ndarray:
    if n <= 1 or y.size < 2:
        return y.copy()
    k = min(n, y.size)
    pad = k // 2
    yp = np.pad(y, (pad, k - 1 - pad), mode="edge")
    return np.convolve(yp, np.ones(k) / k, mode="valid")


def _haversine(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.sqrt(a))


def _cross(t: np.ndarray, y: np.ndarray, k: int, level: float) -> float:
    """y[k]와 y[k+1] 사이에서 level을 지나는 시각 (선형 보간)."""
    y0, y1 = y[k], y[k + 1]
    if y1 == y0:
        return float(t[k])
    a = (level - y0) / (y1 - y0)
    return float(t[k] + min(max(a, 0.0), 1.0) * (t[k + 1] - t[k]))


def _runs(g: np.ndarray, p: Params) -> list[tuple[int, int, int]]:
    """세션 하나 안의 핵심 구간 (시작, 끝, 부호)."""
    runs: list[list[int]] = []
    i, n = 0, len(g)
    while i < n:
        if abs(g[i]) >= p.on_pct:
            s = 1 if g[i] > 0 else -1
            j = i
            while j + 1 < n and s * g[j + 1] >= p.off_pct:
                j += 1
            runs.append([i, j, s])
            i = j + 1
        else:
            i += 1
    merged: list[list[int]] = []
    for r in runs:
        if merged and merged[-1][2] == r[2] and r[0] - merged[-1][1] - 1 <= p.merge_gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [(a, b, s) for a, b, s in merged if b - a + 1 >= p.min_windows]


# ---------------------------------------------------------------- 분석

def analyze(samples: Sequence[Sample], params: Optional[Params] = None) -> Analysis:
    p = params or Params()
    if not samples:
        raise ValueError("표본이 없다")
    t0 = samples[0].t
    t = np.array([(s.t - t0).total_seconds() for s in samples])
    slope = np.array([np.nan if s.slope is None else s.slope for s in samples], dtype=float)
    lat = np.array([np.nan if s.lat is None else s.lat for s in samples], dtype=float)
    lon = np.array([np.nan if s.lon is None else s.lon for s in samples], dtype=float)

    session = np.zeros(len(t), dtype=int)
    if len(t) > 1:
        session[1:] = np.cumsum(np.diff(t) > p.max_gap_s)

    bias = p.bias if p.bias is not None else estimate_bias(slope, p.flat_band_pct)
    g = np.full(len(t), np.nan)
    rate = np.full(len(t), np.nan)
    dist = np.full(len(t), np.nan)
    speed = np.full(len(t), np.nan)
    phase = ["flat"] * len(t)
    ramps: list[Ramp] = []
    plat = np.full(len(t), np.nan)
    plon = np.full(len(t), np.nan)

    for sid in range(int(session.max()) + 1):
        idx = np.flatnonzero(session == sid)
        ts = t[idx]
        gs = _fill(ts, slope[idx]) - bias
        g[idx] = gs
        rs = np.gradient(gs, ts) if len(idx) > 1 else np.zeros(len(idx))
        rate[idx] = rs

        # 좌표: 시간 보간 → 이동 평균 → 누적 거리
        ok = np.isfinite(lat[idx]) & np.isfinite(lon[idx])
        if ok.sum() >= 2:
            la = _moving_mean(_fill(ts, lat[idx]), p.pos_smooth)
            lo = _moving_mean(_fill(ts, lon[idx]), p.pos_smooth)
            plat[idx], plon[idx] = la, lo
            step = np.concatenate([[0.0], _haversine(la[:-1], lo[:-1], la[1:], lo[1:])])
            ds = np.cumsum(step)
            dist[idx] = ds
            dt = np.gradient(ts) if len(idx) > 1 else np.ones(1)
            speed[idx] = np.gradient(ds) / np.where(dt > 0, dt, np.nan)

        for a, b, s in _runs(gs, p):
            ramps.append(_edges(sid, idx, ts, gs, rs, a, b, s, p, t0, phase,
                                dist, plat, plon, ok))

    # 정지 중 흔들림: 좌표가 있는데 거의 움직이지 않았으면 경사로가 아니다
    still = [r for r in ramps if r.speed_mps is not None and r.speed_mps < p.min_speed]
    for r in still:
        for k in range(len(t)):
            if r.start_onset <= t0 + timedelta(seconds=float(t[k])) <= r.end_settle:
                phase[k] = "flat"
    ramps = [r for r in ramps if r not in still]
    for i, r in enumerate(ramps, 1):
        r.idx = i
    _places(ramps, p.same_place_m)
    return Analysis(params=p, bias_pct=bias, n_samples=len(t), n_sessions=int(session.max()) + 1,
                    t=t, t0=t0, session=session, slope=slope, g=g, rate=rate, phase=phase,
                    dist=dist, speed=speed, ramps=ramps)


def _edges(sid, idx, ts, gs, rs, a, b, s, p: Params, t0, phase, dist, plat, plon, gps_ok) -> Ramp:
    n = len(ts)
    y = s * gs                      # 경사로 쪽이 +가 되도록
    dy = s * rs
    plateau = float(np.median(y[a:b + 1]))
    half = plateau / 2
    clipped = False

    # 시작 경계: a 앞뒤 search 창에서 변화율 최대, 그 근처의 반값 교차
    lo, hi = max(0, a - p.search), min(n - 1, a + p.search)
    m_in = lo + int(np.argmax(dy[lo:hi + 1]))
    ks = [k for k in range(lo, min(hi, n - 2) + 1) if y[k] < half <= y[k + 1]]
    if ks:
        k = min(ks, key=lambda k: abs(k + 0.5 - m_in))
        t_start = _cross(ts, y, k, half)
    else:
        t_start, clipped = float(ts[a]), True
    peak_in = float(dy[m_in])
    j = m_in
    while j - 1 >= max(0, lo - p.search) and dy[j - 1] >= p.onset_frac * peak_in and peak_in > 0:
        j -= 1
    t_onset = _cross(ts, dy, j - 1, p.onset_frac * peak_in) if j - 1 >= 0 and peak_in > 0 else float(ts[j])
    t_onset = min(t_onset, t_start)

    # 끝 경계: b 앞뒤에서 변화율 최소(가장 크게 떨어짐)
    lo2, hi2 = max(0, b - p.search), min(n - 1, b + p.search)
    m_out = lo2 + int(np.argmin(dy[lo2:hi2 + 1]))
    ke = [k for k in range(lo2, min(hi2, n - 2) + 1) if y[k] >= half > y[k + 1]]
    if ke:
        k = min(ke, key=lambda k: abs(k + 0.5 - m_out))
        t_end = _cross(ts, y, k, half)
    else:
        t_end, clipped = float(ts[b]), True
    peak_out = float(dy[m_out])
    j = m_out
    while j + 1 <= min(n - 1, hi2 + p.search) and dy[j + 1] <= p.onset_frac * peak_out and peak_out < 0:
        j += 1
    t_settle = _cross(ts, dy, j, p.onset_frac * peak_out) if j + 1 < n and peak_out < 0 else float(ts[j])
    t_settle = max(t_settle, t_end)

    # 표본별 단계 표시
    for k in range(n):
        tk = ts[k]
        if t_onset <= tk < t_start:
            phase[idx[k]] = "onset"
        elif t_start <= tk <= t_end:
            phase[idx[k]] = "ramp"
        elif t_end < tk <= t_settle:
            phase[idx[k]] = "settle"

    core = y[a:b + 1]
    r = Ramp(
        idx=0, session=sid, direction="up" if s > 0 else "down",
        slope_pct=round(s * plateau, 2),
        slope_p90_pct=round(s * float(np.percentile(core, 90)), 2),
        start_onset=t0 + timedelta(seconds=t_onset), start=t0 + timedelta(seconds=t_start),
        end=t0 + timedelta(seconds=t_end), end_settle=t0 + timedelta(seconds=t_settle),
        duration_s=round(t_end - t_start, 1), onset_s=round(t_start - t_onset, 1),
        settle_s=round(t_settle - t_end, 1),
        peak_rate_in=round(s * peak_in, 2), peak_rate_out=round(s * peak_out, 2),
        n_windows=b - a + 1, clipped=clipped,
    )

    d = dist[idx]
    r.gps_points = int(np.sum(gps_ok & (ts >= t_start) & (ts <= t_end)))
    if np.isfinite(d).all() and r.gps_points > 0:
        d0, d1 = np.interp([t_start, t_end], ts, d)
        r.length_m = round(float(d1 - d0), 1)
        r.speed_mps = round(r.length_m / r.duration_s, 2) if r.duration_s > 0 else None
        tt = np.linspace(t_start, t_end, max(2, int((t_end - t_start) / 0.5) + 1))
        dd = np.interp(tt, ts, d)
        gg = np.interp(tt, ts, gs)
        r.rise_m = round(float(np.sum((gg[:-1] + gg[1:]) / 2 / 100 * np.diff(dd))), 2)
        la, lo_ = plat[idx], plon[idx]
        r.start_lat, r.start_lon = (round(float(np.interp(t_start, ts, la)), 7),
                                    round(float(np.interp(t_start, ts, lo_)), 7))
        r.end_lat, r.end_lon = (round(float(np.interp(t_end, ts, la)), 7),
                                round(float(np.interp(t_end, ts, lo_)), 7))
    return r


def _places(ramps: list[Ramp], radius: float) -> None:
    pts = [((r.start_lat + r.end_lat) / 2, (r.start_lon + r.end_lon) / 2)
           if r.start_lat is not None else None for r in ramps]
    parent = list(range(len(ramps)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(ramps)):
        for j in range(i + 1, len(ramps)):
            if pts[i] and pts[j] and _haversine(*pts[i], *pts[j]) <= radius:
                parent[find(j)] = find(i)
    labels: dict[int, int] = {}
    for i, r in enumerate(ramps):
        if pts[i] is None:
            continue
        root = find(i)
        labels.setdefault(root, len(labels) + 1)
        r.place = labels[root]


def _round(v, nd=1):
    return None if v is None or not np.isfinite(v) else round(float(v), nd)


# ---------------------------------------------------------------- 출력

def format_table(an: Analysis) -> str:
    head = (f"편향 {an.bias_pct:+.2f}%  표본 {an.n_samples}개  세션 {an.n_sessions}개  "
            f"경사로 구간 {len(an.ramps)}개")
    lines = [head,
             f"{'#':>2} {'장소':>3} {'방향':<4} {'경사%':>6} {'시작(KST)':>9} {'끝':>8} "
             f"{'시간s':>5} {'길이m':>6} {'속도m/s':>7} {'높이m':>6} {'전이s':>9}"]
    for r in an.ramps:
        lines.append(
            f"{r.idx:>2} {r.place or '-':>3} {'오르막' if r.direction == 'up' else '내리막':<4} "
            f"{r.slope_pct:>+6.1f} {r.start.astimezone(KST):%H:%M:%S} {r.end.astimezone(KST):%H:%M:%S} "
            f"{r.duration_s:>5.1f} {_fmt(r.length_m):>6} {_fmt(r.speed_mps, 2):>7} {_fmt(r.rise_m, 2):>6} "
            f"{r.onset_s:>4.1f}/{r.settle_s:<4.1f}" + ("  (경계 잘림)" if r.clipped else "")
            + ("  (GPS 없음)" if r.gps_points == 0 else ""))
    s = an.summary()

    def sp(k):
        v = s[k]
        return "없음" if v is None else f"{v['median']:.2f} m/s (IQR {v['p25']:.2f}–{v['p75']:.2f}, n={v['n']})"
    lines += [f"속도 중앙값  평지 {sp('speed_flat')}", f"            오르막 {sp('speed_up')}",
              f"            내리막 {sp('speed_down')}",
              f"같은 장소로 묶인 경사로 {s['places']}곳"]
    return "\n".join(lines)


def _fmt(v, nd=1):
    return "-" if v is None else f"{v:.{nd}f}"


def windows_rows(an: Analysis) -> Iterable[dict]:
    for i in range(an.n_samples):
        yield {
            "time_kst": (an.t0 + timedelta(seconds=float(an.t[i]))).astimezone(KST).isoformat(timespec="seconds"),
            "t_s": round(float(an.t[i]), 2), "session": int(an.session[i]),
            "slope_raw": _round(an.slope[i], 3), "g": _round(an.g[i], 3), "rate": _round(an.rate[i], 3),
            "phase": an.phase[i], "dist_m": _round(an.dist[i], 1), "speed_mps": _round(an.speed[i], 2),
        }


def save(an: Analysis, out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {"json": out / "ramps.json", "csv": out / "ramps.csv", "windows": out / "windows.csv"}
    paths["json"].write_text(json.dumps({
        "params": asdict(an.params), "summary": an.summary(),
        "ramps": [r.to_dict() for r in an.ramps]}, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = [r.to_dict() for r in an.ramps]
    with paths["csv"].open("w", encoding="utf-8", newline="") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    with paths["windows"].open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(next(windows_rows(an))))
        w.writeheader()
        w.writerows(windows_rows(an))
    return paths
