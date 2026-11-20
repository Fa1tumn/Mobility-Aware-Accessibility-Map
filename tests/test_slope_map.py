"""여러 날 경사 지도 테스트: 캠퍼스 격자에 합성 기록 두 개를 올린다."""

import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest

from app.analysis.ramp_segments import Params, Sample
from app.analysis.slope_map import RAMP_LIMIT_PCT, Source, build_payload, color_for, save_html
from tests.test_ramp_segments import T0, record

ROOT = Path(__file__).resolve().parents[1]
LAT0, LON0 = 37.3822, 126.6700          # 캠퍼스 격자 안


def campus(samples, dlat=0.0):
    return [Sample(s.t, s.lat - 37.3820 + LAT0 + dlat, LON0, s.slope) for s in samples]


def test_MAP_01_두_기록을_한_격자에():
    a = campus(record([(60.7, 100.7, 6.0)], bias=2.0))
    b = campus(record([(40.0, 60.0, -9.5)], bias=-0.5), dlat=-0.0004)
    b = [Sample(s.t + timedelta(days=1), s.lat, s.lon, s.slope) for s in b]
    p = build_payload([Source("11/19 루프", a), Source("11/20 휠체어", b)])
    assert [d["label"] for d in p["days"]] == ["11/19 루프", "11/20 휠체어"]
    assert p["days"][0]["bias_pct"] == pytest.approx(2.0, abs=0.3)
    assert p["days"][1]["bias_pct"] == pytest.approx(-0.5, abs=0.3)      # 편향은 기록마다 따로
    assert p["outside"] == 0 and len(p["points"]) == len(a) + len(b)
    assert {r["tag"] for r in p["ramps"]} == {"19-1", "20-1"}
    steep = next(r for r in p["ramps"] if r["day"] == 1)
    assert steep["over_limit"] and steep["slope"] < -RAMP_LIMIT_PCT
    assert len(steep["track"]) >= 2


def test_MAP_02_칸은_경사_크기로_평균():
    # 같은 칸을 오르막·내리막으로 지나도 0%가 되지 않는다 (편향 0으로 고정)
    up = campus(record([(0.0, 240.0, 6.0)], n=120, speed=0.0, bias=0.0, noise=0.0))
    down = [Sample(s.t + timedelta(hours=1), s.lat, s.lon, -s.slope) for s in up]
    p = build_payload([Source("a", up, Params(bias=0.0)), Source("b", down, Params(bias=0.0))])
    cell = max(p["cells"], key=lambda c: c["n"])
    assert cell["mean"] == pytest.approx(6.0, abs=0.5) and set(cell["days"]) == {0, 1}


def test_MAP_03_격자_밖과_GPS_없는_점():
    a = campus(record([(60.7, 100.7, 6.0)]))
    a[5] = Sample(a[5].t, None, None, a[5].slope)
    a[6] = Sample(a[6].t, 10.0, 10.0, a[6].slope)                          # 캠퍼스 밖
    p = build_payload([Source("x", a)])
    assert p["outside"] == 1 and len(p["points"]) == len(a) - 2


def test_MAP_04_색():
    assert color_for(None) == "#a8adb4"
    assert color_for(0) == "#f7f4ea" and color_for(20) == "#7c2d12"
    assert color_for(5.0) != color_for(1.0)


def test_MAP_05_HTML에_데이터를_넣음(tmp_path):
    p = build_payload([Source("x", campus(record([(60.7, 100.7, 6.0)])))])
    out = save_html(p, tmp_path / "m.html")
    html = out.read_text(encoding="utf-8")
    assert "__SLOPE_DATA__" not in html
    blob = html.split('id="slope-data" type="application/json">')[1].split("</script>")[0]
    assert json.loads(blob)["ramps"][0]["direction"] == "up"


def test_CLI_MAP_01_명령줄(tmp_path):
    rows = campus(record([(60.7, 100.7, 6.0)]))
    f = tmp_path / "o.csv"
    f.write_text("record_time,latitude,longitude,slope_percent\n" + "\n".join(
        f"{s.t.isoformat()},{s.lat},{s.lon},{s.slope}" for s in rows), encoding="utf-8")
    out = tmp_path / "m.html"
    done = subprocess.run([sys.executable, "-m", "scripts.slope_map", "--input", f"11/20 휠체어={f}",
                           "--out", str(out)], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert out.exists() and "11/20 휠체어" in done.stdout


def test_MAP_06_빈_입력은_오류(tmp_path):
    f = tmp_path / "e.csv"
    f.write_text("record_time,latitude,longitude,slope_percent\n", encoding="utf-8")
    done = subprocess.run([sys.executable, "-m", "scripts.slope_map", "--input", str(f),
                           "--out", str(tmp_path / "m.html")], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 1 and "표본이 없다" in done.stderr
    assert np.isfinite(T0.timestamp())
