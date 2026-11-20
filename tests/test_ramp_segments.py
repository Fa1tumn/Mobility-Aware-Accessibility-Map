"""경사로 시작·끝(변화율)과 속도 분석 테스트.

합성 기록: 2초 창, 각 창 값은 [t-1, t+1] 구간의 실제 경사 평균(창 평균이 경계를 뭉개는 효과),
평지 편향 +2%, 잡음 0.3%p, 1.0 m/s로 북쪽 직진.
"""

import csv
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from app.analysis.ramp_segments import Params, Sample, analyze, estimate_bias, load_samples, save

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 11, 20, 4, 40, tzinfo=timezone.utc)
LAT0, LON0 = 37.3820, 126.6700


def true_slope(t, ramps):
    s = np.zeros_like(t)
    for a, b, g in ramps:
        s[(t >= a) & (t < b)] = g
    return s


def record(ramps, n=120, dt=2.0, bias=2.0, noise=0.3, speed=1.0, seed=0, stop=None):
    """ramps: [(시작 s, 끝 s, 경사 %)]. stop: (a, b) 구간은 제자리."""
    rng = np.random.default_rng(seed)
    t = np.arange(n) * dt
    fine = np.linspace(-1, 1, 41)
    win = np.array([true_slope(tk + fine, ramps).mean() for tk in t])
    slope = win + bias + rng.normal(0, noise, n)
    v = np.full(n, speed)
    if stop:
        v[(t >= stop[0]) & (t < stop[1])] = 0.0
    dist = np.concatenate([[0.0], np.cumsum(v[:-1] * dt)])
    lat = LAT0 + dist / 111_320.0
    return [Sample(T0 + timedelta(seconds=float(tk)), float(la), LON0, float(sl))
            for tk, la, sl in zip(t, lat, slope)]


def sec(an, when):
    return (when - an.t0).total_seconds()


# ── 편향
def test_RAMP_01_편향은_평지_중앙값():
    v = np.concatenate([np.full(80, 2.0), np.full(20, 8.0), np.full(10, -4.0)])
    assert estimate_bias(v) == pytest.approx(2.0)


# ── 시작·끝
def test_RAMP_02_오르막_경계와_경사_길이_속도():
    an = analyze(record([(60.7, 100.7, 6.0)]))
    assert len(an.ramps) == 1
    r = an.ramps[0]
    assert r.direction == "up"
    assert an.bias_pct == pytest.approx(2.0, abs=0.3)
    assert r.slope_pct == pytest.approx(6.0, abs=0.4)
    assert sec(an, r.start) == pytest.approx(60.7, abs=1.0)        # 2초 창보다 촘촘하게
    assert sec(an, r.end) == pytest.approx(100.7, abs=1.0)
    assert r.length_m == pytest.approx(40.0, abs=3.0)
    assert r.speed_mps == pytest.approx(1.0, abs=0.1)
    assert r.rise_m == pytest.approx(40.0 * 0.06, abs=0.3)
    assert r.start_onset <= r.start and r.end <= r.end_settle
    assert 0 < r.onset_s <= 4 and 0 < r.settle_s <= 4               # 창 평균이 만드는 전이 폭


def test_RAMP_03_내리막은_부호와_변화율이_반대():
    an = analyze(record([(41.0, 75.0, -8.0)]))
    r = an.ramps[0]
    assert r.direction == "down" and r.slope_pct == pytest.approx(-8.0, abs=0.4)
    assert r.peak_rate_in < 0 < r.peak_rate_out                       # 들어갈 때 떨어지고 나올 때 오른다
    assert r.rise_m < 0


def test_RAMP_04_경계는_창_위치와_무관하게_반값_교차():
    # 실제 경계를 창 사이 여러 위치에 두어도 1초 안에서 찾는다
    for offset in (0.0, 0.5, 1.0, 1.5):
        an = analyze(record([(60 + offset, 100 + offset, 6.0)], noise=0.0))
        assert sec(an, an.ramps[0].start) == pytest.approx(60 + offset, abs=0.6)


def test_RAMP_05_왕복과_같은_장소():
    # 같은 경사로를 내려갔다가 좌표를 되짚어 올라온다
    samples = record([(40.0, 80.0, -6.0)], n=60)
    back = [Sample(s.t + timedelta(seconds=120), s.lat, s.lon, 4.0 - (s.slope - 2.0))
            for s in reversed(samples)]
    back = [Sample(T0 + timedelta(seconds=120 + 2 * i), b.lat, b.lon, b.slope) for i, b in enumerate(back)]
    an = analyze(samples + back, Params(bias=2.0))
    assert [r.direction for r in an.ramps] == ["down", "up"]
    assert an.ramps[0].place == an.ramps[1].place
    assert an.summary()["places"] == 1


# ── 걸러내기
def test_RAMP_06_짧은_튐과_정지_중_흔들림은_버림():
    samples = record([(60.0, 61.5, 7.0)])                              # 창 하나짜리 튐 (턱 넘기 등)
    assert analyze(samples).ramps == []
    still = record([(60.0, 72.0, 7.0)], stop=(50.0, 90.0))             # 서 있는 동안 12초 기울어짐
    assert analyze(still).ramps == []


def test_RAMP_07_한_창_끊김은_이어_붙임():
    samples = record([(40.0, 60.0, 6.0), (62.0, 84.0, 6.0)], noise=0.0)
    an = analyze(samples)
    assert len(an.ramps) == 1 and an.ramps[0].duration_s == pytest.approx(44.0, abs=2.0)


def test_RAMP_08_기록이_끊기면_세션을_나눔():
    a = record([(40.0, 80.0, 6.0)], n=60)
    b = [Sample(s.t + timedelta(seconds=300), s.lat + 0.01, s.lon, s.slope) for s in a]
    an = analyze(a + b)
    assert an.n_sessions == 2
    assert [r.session for r in an.ramps] == [0, 1]


def test_RAMP_09_단계_표시():
    an = analyze(record([(60.7, 100.7, 6.0)]))
    phases = set(an.phase)
    assert {"flat", "ramp"} <= phases
    assert an.phase[0] == "flat" and an.phase[45] == "ramp"


# ── 입력·출력
def test_RAMP_10_Supabase_CSV와_JSON을_읽음(tmp_path):
    rows = [
        {"record_time": "2026-11-20 04:41:24.453807+00", "latitude": "37.38", "longitude": "126.67", "slope_percent": "2.1"},
        {"record_time": "2026-11-20 04:41:26.453807+00", "latitude": "null", "longitude": "null", "slope_percent": "null"},
    ]
    p = tmp_path / "o.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    s = load_samples(p)
    assert s[0].t == datetime(2026, 11, 20, 4, 41, 24, 453807, tzinfo=timezone.utc)
    assert s[1].lat is None and s[1].slope is None
    j = tmp_path / "o.json"
    j.write_text(json.dumps([{**rows[0], "record_time": "2026-11-20T04:41:24.453807+00:00",
                              "latitude": 37.38, "slope_percent": None}]), encoding="utf-8")
    assert load_samples(j)[0].slope is None


def test_RAMP_11_결과_파일(tmp_path):
    an = analyze(record([(60.7, 100.7, 6.0)]))
    paths = save(an, tmp_path)
    data = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert data["summary"]["ramps"] == 1 and data["ramps"][0]["direction"] == "up"
    assert data["ramps"][0]["start"].endswith("+09:00")
    assert paths["windows"].read_text(encoding="utf-8").count("\n") == an.n_samples + 1


def test_CLI_RAMP_01_명령줄(tmp_path):
    an_rows = record([(60.7, 100.7, 6.0)])
    p = tmp_path / "o.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["record_time", "latitude", "longitude", "slope_percent"])
        for s in an_rows:
            w.writerow([s.t.isoformat(), s.lat, s.lon, s.slope])
    out = tmp_path / "out"
    done = subprocess.run([sys.executable, "-m", "scripts.ramp_segments", "--input", str(p),
                           "--out-dir", str(out)], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert "오르막" in done.stdout and (out / "ramps.csv").exists()
