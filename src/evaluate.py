"""
Backtesting and accuracy metrics.

Golden rule of evaluating a time-series model: **never test on the past.**
We train only on seasons that came *before* the season we score. This
"walk-forward" setup mimics real life -- you always project the future using
only what you knew at the time. A random train/test split would leak future
information and flatter the model.

We always report the model alongside the recent-form BASELINE. A model is only
worth using if it beats that baseline.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

from . import features, model


def _rmse(y_true, y_pred) -> float:
    return float(np.sqrt(mean_squared_error(y_true, y_pred)))


def metrics(y_true, y_pred) -> dict[str, float]:
    """Mean absolute error, root mean squared error, and correlation."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    ok = ~(np.isnan(y_true) | np.isnan(y_pred))
    y_true, y_pred = y_true[ok], y_pred[ok]
    if len(y_true) == 0:
        return {"n": 0, "mae": np.nan, "rmse": np.nan, "corr": np.nan}
    corr = np.corrcoef(y_true, y_pred)[0, 1] if len(y_true) > 1 else np.nan
    return {
        "n": int(len(y_true)),
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": _rmse(y_true, y_pred),
        "corr": float(corr),
    }


def walk_forward_backtest(
    feat_df: pd.DataFrame,
    test_seasons: list[int] | None = None,
    min_train_seasons: int = 1,
) -> pd.DataFrame:
    """
    For each test season, train on all EARLIER seasons and predict that season.

    Returns a per-player-game DataFrame with columns: actual, model_pred,
    baseline_pred (plus ids), ready to feed into `summarize`.
    """
    numeric, categorical = features.feature_columns(feat_df)
    seasons_sorted = sorted(int(s) for s in feat_df["season"].dropna().unique())
    if test_seasons is None:
        test_seasons = seasons_sorted[-2:]  # default: most recent two seasons

    chunks = []
    for test_season in test_seasons:
        train = feat_df[feat_df["season"] < test_season]
        test = feat_df[feat_df["season"] == test_season]
        if test.empty or train["season"].nunique() < min_train_seasons:
            print(f"  [skip] season {test_season}: not enough training history")
            continue

        fitted = model.train_weekly_model(train, numeric, categorical)
        out = test[
            ["player_id", "player_name", "position", "season", "week", model.TARGET]
        ].copy()
        out = out.rename(columns={model.TARGET: "actual"})
        out["model_pred"] = fitted.predict(test)
        out["baseline_pred"] = model.baseline_predict(test)
        chunks.append(out)
        print(f"  [ok]   season {test_season}: predicted {len(out):,} player-games")

    if not chunks:
        return pd.DataFrame(
            columns=["player_id", "player_name", "position", "season", "week",
                     "actual", "model_pred", "baseline_pred"]
        )
    return pd.concat(chunks, ignore_index=True)


def summarize(preds: pd.DataFrame) -> pd.DataFrame:
    """Overall and per-position accuracy, model vs baseline."""
    if preds.empty:
        return pd.DataFrame()

    groups = [("ALL", preds)]
    for pos in sorted(preds["position"].dropna().unique()):
        groups.append((pos, preds[preds["position"] == pos]))

    rows = []
    for label, sub in groups:
        m_model = metrics(sub["actual"], sub["model_pred"])
        m_base = metrics(sub["actual"], sub["baseline_pred"])
        rows.append(
            {
                "group": label,
                "n": m_model["n"],
                "model_mae": round(m_model["mae"], 3),
                "baseline_mae": round(m_base["mae"], 3),
                "mae_improvement": round(m_base["mae"] - m_model["mae"], 3),
                "model_rmse": round(m_model["rmse"], 3),
                "baseline_rmse": round(m_base["rmse"], 3),
                "model_corr": round(m_model["corr"], 3),
            }
        )
    return pd.DataFrame(rows)
