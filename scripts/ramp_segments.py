"""경사로 구간 분석: 시작·끝(변화율 기준)과 휠체어 속도.

    python -m scripts.ramp_segments --input observations_2026-11-20.csv --out-dir output/ramps/2026-11-20 --plot

Supabase에서 내려받은 CSV/JSON을 그대로 받는다. 결과:
    ramps.json   파라미터, 요약(편향, 속도 중앙값), 경사로별 값
    ramps.csv    경사로별 값 (스프레드시트용)
    windows.csv  2초 창별 편향 보정 경사, 변화율, 단계(flat/onset/ramp/settle), 거리, 속도
    timeline.png 전체 경사와 찾은 구간 (--plot)
    ramp_<n>.png 경사로 하나의 경사·변화율과 시작·끝 표시 (--plot)

방법은 app/analysis/ramp_segments.py 첫머리에 적었다.
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

from app.analysis.ramp_segments import KST, Analysis, Params, analyze, format_table, load_samples, save


def parse_args(argv=None) -> argparse.Namespace:
    d = Params()
    p = argparse.ArgumentParser(description="경사로 시작·끝과 휠체어 속도 분석")
    p.add_argument("--input", type=Path, required=True, help="Supabase 관측 CSV 또는 JSON")
    p.add_argument("--out-dir", type=Path, help="결과 저장 폴더")
    p.add_argument("--plot", action="store_true", help="그림 저장 (--out-dir 필요)")
    p.add_argument("--bias", type=float, help="편향(%%)을 직접 지정. 없으면 평지에서 추정")
    p.add_argument("--on", type=float, default=d.on_pct, help="핵심 구간 시작 문턱 %%")
    p.add_argument("--off", type=float, default=d.off_pct, help="핵심 구간 유지 문턱 %%")
    p.add_argument("--min-windows", type=int, default=d.min_windows)
    p.add_argument("--onset-frac", type=float, default=d.onset_frac,
                   help="변화 시작 = 변화율이 최대값의 이 비율 아래로 떨어지는 곳")
    p.add_argument("--from", dest="start", help="이 시각(KST, HH:MM) 이후만")
    p.add_argument("--to", dest="end", help="이 시각(KST, HH:MM) 이전만")
    args = p.parse_args(argv)
    if args.plot and not args.out_dir:
        p.error("--plot에는 --out-dir가 필요합니다")
    return args


def _clip(samples, start: str | None, end: str | None):
    if not (start or end):
        return samples

    def ok(s):
        hm = s.t.astimezone(KST).strftime("%H:%M")
        return (not start or hm >= start) and (not end or hm < end)
    return [s for s in samples if ok(s)]


def plot(an: Analysis, out: Path) -> list[Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    for name in ("Noto Sans CJK KR", "Noto Sans KR", "AppleGothic", "Malgun Gothic", "NanumGothic"):
        if any(name in f.name for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = name
            break
    plt.rcParams["axes.unicode_minus"] = False
    up, down, ink = "#C2551F", "#2457B8", "#16202E"
    times = [an.t0 + timedelta(seconds=float(x)) for x in an.t]
    tk = [t.astimezone(KST).replace(tzinfo=None) for t in times]
    paths = []

    fig, ax = plt.subplots(figsize=(14, 4.2), dpi=150)
    ax.plot(tk, an.g, color=ink, lw=1)
    ax.axhline(0, color="#999", lw=0.8)
    for r in an.ramps:
        c = up if r.direction == "up" else down
        a = r.start.astimezone(KST).replace(tzinfo=None)
        b = r.end.astimezone(KST).replace(tzinfo=None)
        ax.axvspan(a, b, color=c, alpha=0.15, lw=0)
        ax.text(a, 11.2, str(r.idx), fontsize=8, color=c)
    ax.set_ylim(-12, 12)
    import matplotlib.dates as mdates
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.set_ylabel("편향 보정 경사 (%)  + 오르막")
    ax.set_title(f"찾은 경사로 {len(an.ramps)}개 · 편향 {an.bias_pct:+.2f}% 보정", loc="left")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    p = out / "timeline.png"
    fig.savefig(p)
    plt.close(fig)
    paths.append(p)

    for r in an.ramps:
        c = up if r.direction == "up" else down
        t_a = (r.start_onset - an.t0).total_seconds() - 12
        t_b = (r.end_settle - an.t0).total_seconds() + 12
        m = (an.t >= t_a) & (an.t <= t_b)
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(8, 5), dpi=150, sharex=True,
                                     gridspec_kw={"height_ratios": [3, 2]})
        x = an.t[m] - (r.start - an.t0).total_seconds()
        a1.plot(x, an.g[m], "o-", color=ink, ms=3, lw=1)
        a2.plot(x, an.rate[m], "o-", color=c, ms=3, lw=1)
        for ax_ in (a1, a2):
            for key, ls in (("start_onset", ":"), ("start", "-"), ("end", "-"), ("end_settle", ":")):
                xv = (getattr(r, key) - r.start).total_seconds()
                ax_.axvline(xv, color=c, ls=ls, lw=1)
            ax_.axhline(0, color="#999", lw=0.6)
            for s in ("top", "right"):
                ax_.spines[s].set_visible(False)
        a1.axhline(r.slope_pct, color=c, lw=0.8, ls="--")
        a1.set_ylabel("경사 %")
        a2.set_ylabel("변화율 %/s")
        a2.set_xlabel("시작 경계 기준 시간 (s)   실선 = 경계(변화율 최대), 점선 = 변화 시작·끝")
        dirn = "오르막" if r.direction == "up" else "내리막"
        a1.set_title(f"#{r.idx} {dirn} {r.slope_pct:+.1f}% · {r.duration_s:.0f}s"
                     + (f" · {r.length_m:.0f}m · {r.speed_mps:.2f} m/s" if r.length_m is not None else ""),
                     loc="left")
        fig.tight_layout()
        p = out / f"ramp_{r.idx:02d}.png"
        fig.savefig(p)
        plt.close(fig)
        paths.append(p)
    return paths


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        samples = _clip(load_samples(args.input), args.start, args.end)
        params = Params(on_pct=args.on, off_pct=args.off, min_windows=args.min_windows,
                        onset_frac=args.onset_frac, bias=args.bias)
        an = analyze(samples, params)
    except (OSError, ValueError, KeyError) as error:
        print(f"입력 오류: {error}", file=sys.stderr)
        return 1
    print(format_table(an))
    if args.out_dir:
        paths = save(an, args.out_dir)
        if args.plot:
            plot(an, args.out_dir)
        print(f"저장: {args.out_dir} ({', '.join(p.name for p in paths.values())})")
    return 0 if an.ramps else 2


if __name__ == "__main__":
    raise SystemExit(main())
