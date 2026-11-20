"""여러 날의 주행 기록을 한 장의 경사 지도(HTML)로 합친다.

    격자: config/campus_grid.json의 캠퍼스 방향 정사각형 격자 (app/map/campus_grid.py)
    칸 값: 편향을 뺀 경사의 크기 |g| 평균과 최댓값. 같은 경사로를 오르고 내리면 부호가 반대라서
          부호 있는 값으로 평균하면 경사로가 0%처럼 보이기 때문이다.
    점:   2초 창 하나. 편향 보정 경사 g(+ 오르막)로 색을 칠한다.
    경사로: app/analysis/ramp_segments.py가 찾은 구간. 시작~끝 경계 사이 GPS 궤적을 선으로 그린다.

편향은 기록(날)마다 따로 추정한다. 장착 자세와 사람이 다르면 편향도 다르다.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from app.analysis.ramp_segments import KST, Analysis, Params, Sample, analyze

TEMPLATE = Path(__file__).with_name("slope_map.html")
RAMP_LIMIT_PCT = 100.0 / 12.0
# 경사 크기 색 (0 → 10%+). 1/12(8.33%)를 넘으면 가장 진한 색
STOPS = [(0.0, "#f7f4ea"), (2.0, "#fde3a7"), (4.0, "#fbb169"), (6.0, "#f07f3c"), (8.33, "#c2410c"), (10.0, "#7c2d12")]


@dataclass
class Source:
    label: str                 # 화면에 보일 이름 (예: 11/20 휠체어)
    samples: Sequence[Sample]
    params: Optional[Params] = None


def _hex(c: str) -> tuple[int, int, int]:
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def color_for(value: Optional[float]) -> str:
    if value is None or not math.isfinite(value):
        return "#a8adb4"
    v = max(0.0, value)
    for (a, ca), (b, cb) in zip(STOPS, STOPS[1:]):
        if v <= b:
            f = (v - a) / (b - a) if b > a else 0.0
            ra, ga, ba = _hex(ca)
            rb, gb, bb = _hex(cb)
            return "#%02x%02x%02x" % (round(ra + (rb - ra) * f), round(ga + (gb - ga) * f), round(ba + (bb - ba) * f))
    return STOPS[-1][1]


def _f(v, nd=2):
    return None if v is None or not np.isfinite(v) else round(float(v), nd)


def _ramp_track(an: Analysis, r) -> list[list[float]]:
    t0, t1 = (r.start - an.t0).total_seconds(), (r.end - an.t0).total_seconds()
    idx = np.flatnonzero(an.session == r.session)
    ts, la, lo = an.t[idx], an.lat[idx], an.lon[idx]
    if not np.isfinite(la).any():
        return []
    inner = [(float(a), float(b)) for t, a, b in zip(ts, la, lo) if t0 < t < t1 and np.isfinite(a)]
    ends = [(float(np.interp(t0, ts, la)), float(np.interp(t0, ts, lo))),
            (float(np.interp(t1, ts, la)), float(np.interp(t1, ts, lo)))]
    return [[round(a, 7), round(b, 7)] for a, b in [ends[0], *inner, ends[1]]]


def build_payload(sources: Sequence[Source], cell_size_m: Optional[float] = None, title: Optional[str] = None) -> dict:
    from app.map.campus_grid import load_campus_grid

    grid = load_campus_grid(cell_size_m)
    cells: dict[tuple[int, int], dict] = {}
    days, points, ramps = [], [], []
    outside = 0
    for d, src in enumerate(sources):
        an = analyze(src.samples, src.params)
        s = an.summary()
        days.append({"id": d, "label": src.label, "bias_pct": s["bias_pct"], "samples": s["samples"],
                     "ramps": 0, "places": s["places"],
                     "speed_flat": (s["speed_flat"] or {}).get("median"),
                     "start": src.samples[0].t.astimezone(KST).strftime("%m/%d %H:%M"),
                     "end": src.samples[-1].t.astimezone(KST).strftime("%H:%M")})
        for k, smp in enumerate(src.samples):
            if smp.lat is None or smp.lon is None or not np.isfinite(an.g[k]):
                continue
            try:
                i, j = grid.get_grid(smp.lat, smp.lon)
            except (KeyError, TypeError, ValueError, OverflowError):
                outside += 1
                continue
            g = float(an.g[k])
            c = cells.setdefault((i, j), {"sum": 0.0, "max": 0.0, "n": 0, "days": set()})
            c["sum"] += abs(g)
            c["max"] = max(c["max"], abs(g))
            c["n"] += 1
            c["days"].add(d)
            points.append({"day": d, "lat": round(smp.lat, 7), "lon": round(smp.lon, 7), "g": round(g, 2),
                           "raw": _f(smp.slope), "phase": an.phase[k],
                           "time": smp.t.astimezone(KST).strftime("%H:%M:%S"),
                           "grid_id": i * grid.columns + j + 1})
        tag = src.label.split()[0].split("/")[-1] if src.label.strip() else str(d + 1)
        for r in an.ramps:
            track = _ramp_track(an, r) if r.gps_points > 0 else []
            if not track:
                continue                      # GPS 없는 구간은 지도에 올릴 수 없다
            days[-1]["ramps"] += 1
            ramps.append({"day": d, "idx": r.idx, "tag": f"{tag}-{r.idx}", "place": r.place, "direction": r.direction,
                          "slope": r.slope_pct, "length": r.length_m, "duration": r.duration_s,
                          "speed": r.speed_mps, "rise": r.rise_m,
                          "start": r.start.astimezone(KST).strftime("%H:%M:%S"),
                          "end": r.end.astimezone(KST).strftime("%H:%M:%S"),
                          "over_limit": abs(r.slope_pct) > RAMP_LIMIT_PCT, "track": track})

    out_cells = []
    for (i, j), c in sorted(cells.items()):
        geo = grid.get_cell_geometry(i, j)
        mean = c["sum"] / c["n"]
        out_cells.append({"grid_id": i * grid.columns + j + 1, "corners": [[round(a, 7), round(b, 7)] for a, b in geo["corners"]],
                          "mean": round(mean, 2), "max": round(c["max"], 2), "n": c["n"],
                          "days": sorted(c["days"]), "color": color_for(mean)})
    lats = [p["lat"] for p in points] or [grid.south, grid.north]
    lons = [p["lon"] for p in points] or [grid.west, grid.east]
    return {
        "title": title or "경사 지도 · " + " + ".join(s.label for s in sources),
        "cell_size_m": round(grid.size, 2), "rows": grid.rows, "columns": grid.columns,
        "bounds": [[min(lats), min(lons)], [max(lats), max(lons)]],
        "campus": [[round(a, 7), round(b, 7)] for a, b in (grid.to_geographic(0, 0), grid.to_geographic(0, grid.map_width),
                                                            grid.to_geographic(grid.map_length, grid.map_width),
                                                            grid.to_geographic(grid.map_length, 0))],
        "limit_pct": round(RAMP_LIMIT_PCT, 2), "stops": STOPS, "outside": outside,
        "days": days, "cells": out_cells, "points": points, "ramps": ramps,
    }


def save_html(payload: dict, path: str | Path) -> Path:
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE.read_text(encoding="utf-8").replace("__SLOPE_DATA__", data), encoding="utf-8")
    return path
