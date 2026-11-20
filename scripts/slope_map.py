"""여러 날의 Supabase 기록을 경사 지도 HTML 한 장으로 합친다.

    python -m scripts.slope_map \
        --input "11/19 루프=observations_2026-11-19.csv" \
        --input "11/20 휠체어=observations_2026-11-20.csv" \
        --out output/slope/slope-map.html

    python -m scripts.open_grid output/slope/slope-map.html     # 배경 지도까지 보려면 HTTP로

--input은 "이름=파일" 또는 파일만. 파일은 Supabase CSV/JSON. 편향은 파일마다 따로 추정한다.
격자는 config/campus_grid.json의 캠퍼스 정사각형 격자, 경사로 구간은 app/analysis/ramp_segments.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.analysis.ramp_segments import load_samples
from app.analysis.slope_map import Source, build_payload, save_html


def parse_input(text: str) -> tuple[str, Path]:
    if "=" in text:
        label, path = text.split("=", 1)
        return label.strip(), Path(path.strip())
    p = Path(text)
    return p.stem, p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="여러 날 경사 지도")
    ap.add_argument("--input", action="append", required=True, help='"이름=파일" (여러 번)')
    ap.add_argument("--out", type=Path, default=Path("output/slope/slope-map.html"))
    ap.add_argument("--cell-size-m", type=float, default=None, help="격자 한 변 (기본 10m)")
    ap.add_argument("--title")
    args = ap.parse_args(argv)
    try:
        sources = []
        for item in args.input:
            label, path = parse_input(item)
            samples = load_samples(path)
            if not samples:
                raise ValueError(f"{path}: 표본이 없다")
            sources.append(Source(label, samples))
        payload = build_payload(sources, args.cell_size_m, args.title)
    except (OSError, ValueError, KeyError) as error:
        print(f"입력 오류: {error}", file=sys.stderr)
        return 1
    out = save_html(payload, args.out)
    for d in payload["days"]:
        print(f"{d['label']}: 2초 창 {d['samples']}개, 편향 {d['bias_pct']:+.2f}%, 경사로 {d['ramps']}구간/{d['places']}곳")
    print(f"칸 {len(payload['cells'])}개, 점 {len(payload['points'])}개, 격자 밖 {payload['outside']}개")
    print(f"저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
