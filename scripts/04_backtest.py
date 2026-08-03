"""
Step 4 -- Backtest across multiple seasons.

Walk-forward evaluation over the most recent seasons: for each one, train only
on earlier seasons and predict it. Prints an accuracy table (model vs baseline)
and saves a calibration chart so you can see where the model is over/under.

    python scripts/04_backtest.py
    python scripts/04_backtest.py 2023 2024 2025   # choose the test seasons
"""
import pathlib
import sys

import matplotlib

matplotlib.use("Agg")  # write charts to file without needing a display
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src import config, data, evaluate  # noqa: E402


def _calibration_chart(preds: pd.DataFrame, path: pathlib.Path) -> None:
    """Bin predictions into deciles; plot mean predicted vs mean actual."""
    d = preds.dropna(subset=["model_pred", "actual"]).copy()
    if d.empty:
        return
    d["bin"] = pd.qcut(d["model_pred"], q=10, duplicates="drop")
    grouped = d.groupby("bin", observed=True).agg(
        pred=("model_pred", "mean"), actual=("actual", "mean")
    )
    lim = float(max(grouped["pred"].max(), grouped["actual"].max())) * 1.1

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot([0, lim], [0, lim], "--", color="gray", label="perfect")
    ax.plot(grouped["pred"], grouped["actual"], "o-", label="model")
    ax.set_xlabel("Predicted fantasy points (decile mean)")
    ax.set_ylabel("Actual fantasy points (decile mean)")
    ax.set_title("Model calibration")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def main() -> None:
    feat = data.load_df("features", folder=config.PROCESSED_DIR)
    if feat is None:
        print("No feature table found. Run: python scripts/02_build_features.py")
        return

    test_seasons = [int(a) for a in sys.argv[1:] if a.isdigit()] or None
    print("Running walk-forward backtest...\n")
    preds = evaluate.walk_forward_backtest(feat, test_seasons=test_seasons)

    if preds.empty:
        print("Not enough history to backtest. Add more seasons in config.py.")
        return

    summary = evaluate.summarize(preds)
    print("\nBacktest accuracy (model vs recent-form baseline):")
    print(summary.to_string(index=False))

    preds_path = data.save_df(preds, "backtest_predictions", folder=config.OUTPUT_DIR)
    chart_path = config.OUTPUT_DIR / "calibration.png"
    _calibration_chart(preds, chart_path)

    print(f"\nSaved per-game predictions to: {preds_path}")
    print(f"Saved calibration chart to:   {chart_path}")
    print("\nNext: python scripts/05_rank_players.py")


if __name__ == "__main__":
    main()
