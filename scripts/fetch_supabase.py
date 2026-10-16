import argparse
import json
from pathlib import Path

from app.storage.supabase_reader import fetch_observations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/observations.json")
    args = parser.parse_args()
    try:
        rows = fetch_observations()
    except (ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(rows)} observations to {output}")
    if not rows:
        print("No visible rows. Check whether the table is empty or the SELECT policy hides them.")


if __name__ == "__main__":
    main()
