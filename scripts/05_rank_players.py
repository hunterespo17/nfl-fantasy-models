"""
Step 5 -- Build season/draft rankings.

Produces a ranked, tiered draft board with value-over-replacement (VOR).

To keep this runnable end-to-end today, the projection here is a simple,
honest starting point: each player's fantasy points per game from the most
recent completed season. The ROADMAP explains how to upgrade this to true
model-based, regressed-to-the-mean projections (the more accurate approach).

    python scripts/05_rank_players.py
    python scripts/05_rank_players.py --season 2024
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from src import config, data, rankings  # noqa: E402

MIN_GAMES = 4  # ignore players with tiny samples when projecting from history


def naive_projection(feat: pd.DataFrame, season: int) -> pd.DataFrame:
    """Project points-per-game from a player's most-recent-season average."""
    season_rows = feat[feat["season"] == season]
    if season_rows.empty:
        raise SystemExit(f"No data for season {season}. Try a different --season.")

    grouped = (
        season_rows.groupby(["player_id", "player_name", "position"], dropna=True)
        .agg(proj_ppg=("fantasy_points", "mean"), games=("fantasy_points", "size"))
        .reset_index()
    )
    grouped = grouped[grouped["games"] >= MIN_GAMES]
    grouped["proj_games"] = config.LEAGUE.get("games_per_season", 17)
    return grouped


def main() -> None:
    feat = data.load_df("features", folder=config.PROCESSED_DIR)
    if feat is None:
        print("No feature table found. Run: python scripts/02_build_features.py")
        return

    season = config.CURRENT_SEASON
    if "--season" in sys.argv:
        season = int(sys.argv[sys.argv.index("--season") + 1])

    print(f"Projecting from {season} per-game production (naive baseline projection)\n")
    proj = naive_projection(feat, season)
    board = rankings.build_rankings(proj)

    out_path = data.save_df(board, "draft_rankings", folder=config.OUTPUT_DIR)

    print("Top 30 overall (by value over replacement):")
    print(board.head(30).to_string(index=False))

    print("\nTop 8 at each position:")
    for pos in config.FANTASY_POSITIONS:
        top = board[board["position"] == pos].head(8)
        print(f"\n  {pos}")
        print(top[["overall_rank", "position_rank", "tier", "player_name",
                   "proj_points_total", "vor"]].to_string(index=False))

    print(f"\nSaved full draft board to: {out_path}")
    print("\nThat's the whole pipeline! See ROADMAP.md for what to improve next.")


if __name__ == "__main__":
    main()
