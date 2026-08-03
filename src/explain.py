"""
Per-player factor attribution -- "how was each factor weighted for this player?"

Gradient-boosting models don't hand you clean per-feature weights, and the
usual tool (SHAP) is a heavy dependency that won't install cleanly everywhere.
So we use a transparent, dependency-free approach: group ablation.

For a given player we start from the model's projection, then neutralize one
FACTOR GROUP at a time (set those features to a league-average QB's values) and
see how much the projection moves. That movement is the group's contribution.
The result is an intuitive breakdown:

    league-average QB ............ 17.8 pts
    + Archetype (dual-threat) .... +3.1
    + Situation (pass-heavy, high total) .. +1.9
    + Form (hot last 3 weeks) .... +0.7
    ------------------------------------
    projection ................... 23.5 pts

It's an approximation (a gradient booster has interactions, so the pieces don't
sum *perfectly*), so we scale the pieces to add up to the total gap from the
baseline. It's honest about magnitude and direction, which is what you want for
understanding a ranking.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def league_baseline(reference: pd.DataFrame, feature_cols: list[str]) -> dict[str, float]:
    """A 'league-average QB': the median of every feature over a reference set."""
    return {c: float(reference[c].median()) for c in feature_cols}


def group_attributions(
    model,
    X: pd.DataFrame,
    groups: dict[str, list[str]],
    reference: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Attribute each player's projection to factor groups.

    Parameters
    ----------
    model : a fitted FantasyModel (has .numeric and .predict).
    X : rows to explain (must contain the model's feature columns).
    groups : {group_name: [feature columns]}.
    reference : rows defining the league-average baseline (defaults to X).

    Returns
    -------
    DataFrame indexed like X with one column per group (points contributed),
    plus 'prediction' and 'baseline'.
    """
    feats = list(model.numeric)
    ref = reference if reference is not None else X
    baseline_vals = league_baseline(ref, feats)

    # Only attribute over features the model actually used.
    used = {g: [c for c in cols if c in feats] for g, cols in groups.items()}

    full = np.asarray(model.predict(X), dtype=float)

    base_row = pd.DataFrame([baseline_vals])[feats]
    baseline_pred = float(model.predict(base_row)[0])

    raw = {}
    for group, cols in used.items():
        if not cols:
            raw[group] = np.zeros(len(X))
            continue
        X_neutral = X.copy()
        for c in cols:
            X_neutral[c] = baseline_vals[c]
        pred_without = np.asarray(model.predict(X_neutral), dtype=float)
        raw[group] = full - pred_without  # effect of this player's actual values

    contrib = pd.DataFrame(raw, index=X.index)

    # Scale the pieces so they sum to the true gap from baseline (clean waterfall).
    total_gap = full - baseline_pred
    raw_sum = contrib.sum(axis=1).to_numpy()
    scale = np.divide(total_gap, raw_sum, out=np.ones_like(total_gap), where=np.abs(raw_sum) > 1e-9)
    contrib = contrib.mul(scale, axis=0)

    contrib["prediction"] = full
    contrib["baseline"] = baseline_pred
    return contrib
