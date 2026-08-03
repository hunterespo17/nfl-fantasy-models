"""
Self-test -- verify the whole pipeline works, using SYNTHETIC data.

This does NOT download anything. It fabricates a few seasons of fake NFL box
scores, then runs scoring -> features -> training -> backtest -> rankings and
checks each step. Two uses:

  * It's how the project's logic is verified without needing nflverse access.
  * After you install the requirements, running it confirms pandas / sklearn
    are working on your machine before you download real data.

    python scripts/run_selftest.py
"""
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src import config, evaluate, features, model, rankings, scoring  # noqa: E402

RNG = np.random.default_rng(config.RANDOM_SEED)
TEAMS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH", "III", "JJJ"]
SEASONS = [2021, 2022, 2023, 2024]
WEEKS = list(range(1, 15))


def _make_schedule() -> tuple[pd.DataFrame, dict]:
    """Build a coherent schedule and a (season, week, team) -> (opp, is_home) map."""
    rows, mapping = [], {}
    for season in SEASONS:
        for week in WEEKS:
            order = list(TEAMS)
            RNG.shuffle(order)
            for i in range(0, len(order), 2):
                home, away = order[i], order[i + 1]
                rows.append({"season": season, "week": week,
                             "home_team": home, "away_team": away})
                mapping[(season, week, home)] = (away, 1)
                mapping[(season, week, away)] = (home, 0)
    return pd.DataFrame(rows), mapping


def _pois(lam: float) -> int:
    """Poisson draw with the rate clamped to be non-negative (synthetic only)."""
    return int(RNG.poisson(max(0.05, lam)))


def _make_weekly(mapping: dict) -> pd.DataFrame:
    """Fabricate weekly box scores with a per-player skill level + noise."""
    positions = (["QB"] * 8) + (["RB"] * 14) + (["WR"] * 16) + (["TE"] * 8)
    players = []
    for idx, pos in enumerate(positions):
        players.append({
            "player_id": f"P{idx:03d}",
            "player_display_name": f"Player {idx:03d}",
            "position": pos,
            "team": TEAMS[idx % len(TEAMS)],
            "skill": float(RNG.normal(0, 1)),  # latent ability
        })

    rows = []
    for p in players:
        for season in SEASONS:
            for week in WEEKS:
                opp, is_home = mapping[(season, week, p["team"])]
                s = p["skill"]
                noise = RNG.normal(0, 1)
                row = {
                    "player_id": p["player_id"],
                    "player_display_name": p["player_display_name"],
                    "position": p["position"],
                    "recent_team": p["team"],
                    "opponent_team": opp,
                    "season": season,
                    "week": week,
                    "season_type": "REG",
                }
                if p["position"] == "QB":
                    row["passing_yards"] = max(0, 240 + 40 * s + 45 * noise)
                    row["passing_tds"] = _pois(1.6 + 0.5 * s)
                    row["interceptions"] = _pois(0.7)
                    row["rushing_yards"] = max(0, 12 + 8 * noise)
                    row["carries"] = _pois(3)
                    row["rushing_tds"] = _pois(0.1)
                else:
                    targets = _pois(5 + 2 * s) if p["position"] != "RB" else _pois(2)
                    carries = _pois(12 + 3 * s) if p["position"] == "RB" else _pois(0.3)
                    rec = min(targets, _pois(3 + 1.5 * s))
                    row["targets"] = targets
                    row["receptions"] = rec
                    row["receiving_yards"] = max(0, 11 * rec + 6 * noise)
                    row["receiving_tds"] = _pois(0.4 + 0.15 * s)
                    row["carries"] = carries
                    row["rushing_yards"] = max(0, 4.3 * carries + 5 * noise)
                    row["rushing_tds"] = _pois(0.25 if p["position"] == "RB" else 0.02)
                row["fumbles_lost"] = _pois(0.05)
                rows.append(row)
    return pd.DataFrame(rows)


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    if not condition:
        raise AssertionError(label)


def main() -> None:
    print("Self-test: building synthetic data...")
    schedules, mapping = _make_schedule()
    weekly = _make_weekly(mapping)
    check(f"weekly rows generated ({len(weekly):,})", len(weekly) > 1000)

    print("\nScoring...")
    pts = scoring.compute_fantasy_points(weekly)
    check("fantasy points are finite and mostly positive", np.isfinite(pts).all() and pts.mean() > 0)

    print("\nFeature engineering...")
    feat = features.build_features(weekly, schedules=schedules, scoring_rules=config.SCORING)
    numeric, categorical = features.feature_columns(feat)
    check(f"feature table built ({len(feat):,} rows)", len(feat) > 1000)
    check(f"has numeric features ({len(numeric)})", len(numeric) >= 10)
    check("has 'position' as a categorical feature", "position" in categorical)

    # No-leakage sanity: each player's FIRST career game must have no rolling history.
    first_games = feat.sort_values(["player_id", "season", "week"]).groupby("player_id").head(1)
    check("first career game has empty recent-form feature (no leakage)",
          first_games["fantasy_points_roll3"].isna().all())
    check("home/away merged from schedule", feat["is_home"].notna().mean() > 0.9)
    check("opponent-strength feature exists", "opp_points_allowed_to_pos" in feat.columns)

    print("\nBacktesting (train past -> predict future)...")
    preds = evaluate.walk_forward_backtest(feat, test_seasons=[2023, 2024])
    summary = evaluate.summarize(preds)
    check("backtest produced predictions", not preds.empty)
    check("metrics are finite", np.isfinite(summary.loc[summary['group'] == 'ALL', 'model_mae']).all())
    print("\n" + summary.to_string(index=False))

    print("\nTraining + save/load round-trip...")
    fitted = model.train_weekly_model(feat)
    path = model.save_model(fitted)
    reloaded = model.load_model(path)
    p1 = fitted.predict(feat.head(50))
    p2 = reloaded.predict(feat.head(50))
    check("model trains and predicts", len(p1) == 50 and np.isfinite(p1).all())
    check("saved model reloads identically", np.allclose(p1, p2))

    print("\nDraft rankings...")
    proj = (
        feat[feat["season"] == 2024]
        .groupby(["player_id", "player_name", "position"])
        .agg(proj_ppg=("fantasy_points", "mean"))
        .reset_index()
    )
    board = rankings.build_rankings(proj)
    check("rankings produced", len(board) > 20)
    check("has overall_rank, vor, tier", {"overall_rank", "vor", "tier"} <= set(board.columns))
    check("overall rank #1 has the highest VOR", board.iloc[0]["vor"] == board["vor"].max())
    print("\nTop 10 of the synthetic draft board:")
    print(board.head(10).to_string(index=False))

    print("\n" + "=" * 60)
    print("ALL CHECKS PASSED -- the pipeline logic works end to end.")
    print("=" * 60)


if __name__ == "__main__":
    main()
