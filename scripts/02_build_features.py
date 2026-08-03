"""
Step 2 -- Build the modeling table (features).

Loads the cached raw data, engineers leak-free features (recent form, usage,
opponent strength, home/away, ...), and saves the result to data/processed/.

    python scripts/02_build_features.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src import config, data, features  # noqa: E402


def main() -> None:
    weekly = data.load_df("player_weekly_stats")
    if weekly is None:
        print("No cached data found. Run: python scripts/01_pull_data.py")
        return

    schedules = data.load_df("schedules")
    snaps = data.load_df("snap_counts")

    print(f"Building features from {len(weekly):,} weekly rows...")
    feat = features.build_features(
        weekly, schedules=schedules, snaps=snaps, scoring_rules=config.SCORING
    )

    numeric, categorical = features.feature_columns(feat)
    path = data.save_df(feat, "features", folder=config.PROCESSED_DIR)

    print(f"\nBuilt {len(feat):,} player-game rows.")
    print(f"Feature columns ({len(numeric)} numeric + {len(categorical)} categorical):")
    print("  numeric:     " + ", ".join(numeric))
    print("  categorical: " + ", ".join(categorical))
    print(f"\nSaved to: {path}")
    print("\nNext: python scripts/03_train_weekly.py")


if __name__ == "__main__":
    main()
