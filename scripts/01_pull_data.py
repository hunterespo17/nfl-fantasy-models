"""
Step 1 -- Download the raw data.

Pulls weekly player stats, schedules, snap counts, and (if available) expected
fantasy points from nflverse, and caches them in data/raw/. The first run
downloads; later runs load instantly from the cache.

    python scripts/01_pull_data.py            # use the cache if present
    python scripts/01_pull_data.py --refresh  # force a fresh download
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src import config, data  # noqa: E402


def main() -> None:
    refresh = "--refresh" in sys.argv
    print(f"Pulling nflverse data for seasons {config.SEASONS[0]}-{config.SEASONS[-1]} "
          f"(refresh={refresh})...\n")

    datasets = data.pull_all(config.SEASONS, refresh=refresh)

    print("\nDownloaded / loaded:")
    for name, df in datasets.items():
        print(f"  {name:<22} {df.shape[0]:>8,} rows x {df.shape[1]:>3} cols")

    # Show a peek at the most important table so you know what you're working with.
    weekly = datasets["player_weekly_stats"]
    print("\nSample columns in player_weekly_stats:")
    print("  " + ", ".join(list(weekly.columns)[:25]))
    print(f"\nCached in: {config.RAW_DIR}")
    print("\nNext: python scripts/02_build_features.py")


if __name__ == "__main__":
    main()
