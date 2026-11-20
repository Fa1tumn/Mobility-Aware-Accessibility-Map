"""Supabase의 최신 관측일 데이터를 내려받아 격자 지도를 갱신합니다."""

import argparse
import json
import math
import subprocess
import sys

from app.map.grid_pipeline import observation_time
from app.storage.supabase_reader import ROOT, fetch_observations


def has_coordinates(row):
    try:
        latitude = float(row["latitude"])
        longitude = float(row["longitude"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    return (
        math.isfinite(latitude)
        and math.isfinite(longitude)
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    )


def select_latest_day(rows):
    if not rows:
        raise ValueError("조회된 관측 기록이 없습니다.")
    dated = [(row, observation_time(row).date()) for row in rows if row.get("record_time")]
    if not dated:
        raise ValueError("최신 관측일을 선택할 record_time 값이 없습니다.")
    latest_day = max(day for _, day in dated)
    selected = [row for row, day in dated if day == latest_day and has_coordinates(row)]
    if not selected:
        raise ValueError(f"최신 관측일({latest_day}, UTC)에 유효한 좌표가 없습니다.")
    return latest_day, selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sizing = parser.add_mutually_exclusive_group()
    sizing.add_argument("--cell-size-m", type=float, help="캠퍼스 격자 한 변의 목표 길이(m)")
    sizing.add_argument("--size", type=float, help="기존 격자 간격(도)")
    parser.add_argument("--field", choices=["weight", "ramp", "ave_vibration", "object"], default="ave_vibration")
    args = parser.parse_args()
    size_flag = "--size" if args.size is not None else "--cell-size-m"
    size = args.size if args.size is not None else args.cell_size_m
    if size is not None and (not math.isfinite(size) or size <= 0):
        parser.error(f"{size_flag}는 유한한 양수여야 합니다.")
    try:
        rows = fetch_observations()
        latest_day, selected = select_latest_day(rows)
        unmapped = [row for row in rows if not has_coordinates(row)]
        snapshots = {
            "supabase_latest_observations": rows,
            "supabase_latest_day_observations": selected,
            "supabase_unmapped_observations": unmapped,
        }
        data_dir = ROOT / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        for name, records in snapshots.items():
            (data_dir / f"{name}.json").write_text(
                json.dumps(records, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
            )
        print(f"전체 {len(rows)}개 / 좌표 누락·오류 {len(unmapped)}개", flush=True)
        print(f"선택: {latest_day} (UTC), 유효한 좌표 {len(selected)}개", flush=True)
        command = [
            sys.executable, "-m", "scripts.test_grid",
            "--input", str(data_dir / "supabase_latest_day_observations.json"),
            "--field", args.field, "--output", "output/grid/grid.png",
        ]
        if size is not None:
            command.extend((size_flag, str(size)))
        result = subprocess.run(command, cwd=ROOT, check=False)
    except (ValueError, RuntimeError, KeyError, TypeError, OSError) as error:
        parser.exit(1, f"격자 갱신 실패: {error}\n")
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
