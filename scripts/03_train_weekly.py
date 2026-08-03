"""
Step 3 -- Train the weekly projection model.

Does two things:
  1. A quick honest check: train on older seasons, test on the most recent one,
     and compare the model against the recent-form baseline.
  2. Retrain on ALL available seasons and save that model for making
     projections (scripts/05).

    python scripts/03_train_weekly.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src import config, data, evaluate, features, model  # noqa: E402


def main() -> None:
    feat = data.load_df("features", folder=config.PROCESSED_DIR)
    if feat is None:
        print("No feature table found. Run: python scripts/02_build_features.py")
        return

    seasons = sorted(int(s) for s in feat["season"].dropna().unique())
    holdout = seasons[-1]
    print(f"Quick check: train on {seasons[0]}-{holdout - 1}, test on {holdout}\n")

    preds = evaluate.walk_forward_backtest(feat, test_seasons=[holdout])
    summary = evaluate.summarize(preds)
    if not summary.empty:
        print("\nAccuracy (lower MAE = better; positive improvement beats baseline):")
        print(summary.to_string(index=False))

    print("\nRetraining on ALL seasons and saving the model...")
    fitted = model.train_weekly_model(feat)
    path = model.save_model(fitted)
    print(f"  Saved model to: {path}")
    print(f"  Trained on {len(fitted.numeric)} numeric + "
          f"{len(fitted.categorical)} categorical features.")
    print("\nNext: python scripts/04_backtest.py  (or 05_rank_players.py)")


if __name__ == "__main__":
    main()
