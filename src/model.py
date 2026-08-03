"""
Weekly fantasy-point prediction models.

Two models live here, and you should always look at them together:

1. BASELINE -- "predict roughly what the player has been averaging lately."
   This is deliberately dumb, and it is the bar every real model must clear.
   In fantasy, recent-form averages are a genuinely strong predictor, so if a
   fancy model can't beat this, the fancy model isn't helping.

2. GRADIENT BOOSTING -- scikit-learn's HistGradientBoostingRegressor. It's a
   strong, fast, tabular-data workhorse that:
     * needs no extra packages (installs cleanly, including on Windows/ARM),
     * handles missing values natively (early-season rows have blank rolling
       features -- no imputation gymnastics required).

We keep the trained model together with the exact feature lists it was trained
on, wrapped in `FantasyModel`, so prediction never uses the wrong columns.
"""
from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from . import config, features

TARGET = "fantasy_points"


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------
def baseline_predict(df: pd.DataFrame) -> np.ndarray:
    """
    Recent-form baseline: the player's lagged average fantasy points.

    Prefers the last-5-game average, falling back to season-to-date, then the
    last-3-game average, then a small constant for players with no history.
    All of these inputs are already lagged (leak-free) from features.py.
    """
    candidates = ["fantasy_points_roll5", "fantasy_points_szn", "fantasy_points_roll3"]
    pred = pd.Series(np.nan, index=df.index)
    for col in candidates:
        if col in df.columns:
            pred = pred.fillna(df[col])
    # Anyone still missing (true rookies, week 1) gets a neutral small value.
    return pred.fillna(pred.median() if pred.notna().any() else 4.0).to_numpy()


# ---------------------------------------------------------------------------
# Gradient boosting model
# ---------------------------------------------------------------------------
def build_pipeline(numeric: list[str], categorical: list[str]) -> Pipeline:
    """One-hot encode categoricals, pass numerics through, then boost."""
    transformers = [("num", "passthrough", numeric)]
    if categorical:
        transformers.append(
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categorical)
        )
    pre = ColumnTransformer(transformers, remainder="drop")

    regressor = HistGradientBoostingRegressor(
        loss="squared_error",
        learning_rate=0.05,
        max_iter=300,
        max_depth=None,
        l2_regularization=1.0,
        # early_stopping is disabled on purpose. In scikit-learn 1.9 the
        # histogram-binning step runs on the internal early-stopping split and
        # raises "window shape cannot be larger than input array shape" if any
        # feature has a single distinct value in that split. Binning the full
        # training set instead -- together with dropping constant features in
        # train_weekly_model() -- sidesteps that bug completely.
        early_stopping=False,
        random_state=config.RANDOM_SEED,
    )
    return Pipeline([("pre", pre), ("gbr", regressor)])


class FantasyModel:
    """A fitted pipeline bundled with the feature columns it expects."""

    def __init__(self, pipeline: Pipeline, numeric: list[str], categorical: list[str]):
        self.pipeline = pipeline
        self.numeric = numeric
        self.categorical = categorical

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        X = df[self.numeric + self.categorical]
        return self.pipeline.predict(X)


def train_weekly_model(
    train_df: pd.DataFrame,
    numeric: list[str] | None = None,
    categorical: list[str] | None = None,
) -> FantasyModel:
    """Fit the gradient-boosting model on a training table."""
    if numeric is None or categorical is None:
        numeric, categorical = features.feature_columns(train_df)

    data = train_df.dropna(subset=[TARGET])

    # Drop numeric features that are constant (a single distinct value) in this
    # training set. They carry no information, and scikit-learn's histogram
    # binning (>=1.9) errors on them. Categoricals are one-hot encoded and are
    # unaffected, so we leave them alone.
    usable = [c for c in numeric if data[c].nunique(dropna=True) >= 2]
    dropped = [c for c in numeric if c not in usable]
    if dropped:
        print(f"  [info] skipping {len(dropped)} constant feature(s): {', '.join(dropped)}")
    numeric = usable

    X = data[numeric + categorical]
    y = data[TARGET].to_numpy()

    pipeline = build_pipeline(numeric, categorical)
    pipeline.fit(X, y)
    return FantasyModel(pipeline, numeric, categorical)


def train_position_model(train_df: pd.DataFrame, feature_cols: list[str]) -> FantasyModel:
    """
    Train a single-position model (e.g. QB) from an explicit feature list.

    A per-position model has no 'position' column to encode (every row is the
    same position), so it's numeric features only -- simpler and lets each
    position's features mean exactly what they should.
    """
    return train_weekly_model(train_df, numeric=list(feature_cols), categorical=[])


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def save_model(model: FantasyModel, path: Path | str | None = None) -> Path:
    path = Path(path) if path else config.MODELS_DIR / "weekly_gbr.joblib"
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    return path


def load_model(path: Path | str | None = None) -> FantasyModel:
    path = Path(path) if path else config.MODELS_DIR / "weekly_gbr.joblib"
    return joblib.load(path)
