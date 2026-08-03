"""
Fantasy scoring: turn a player's raw box-score stats into fantasy points.

Why this is its own module
--------------------------
nflverse already ships pre-computed `fantasy_points` (standard) and
`fantasy_points_ppr` columns. But every league is a little different
(half-PPR, custom TE premium, -1 vs -2 per interception, ...). Computing
points ourselves from the component stats means the model's target always
matches YOUR league's rules, which live in `config.SCORING`.

Robustness note
---------------
Column names in the nflverse data have shifted slightly across versions
(e.g. `interceptions` -> `passing_interceptions`, a single `fumbles_lost`
split into `sack_fumbles_lost` / `rushing_fumbles_lost` / ...). To avoid
breaking when that happens, we look up each stat by a list of possible
names and treat anything missing as zero.
"""
from __future__ import annotations

import pandas as pd

from . import config

# For each scoring category, the possible column names in the source data,
# tried in order. The first one present in the DataFrame is used.
_STAT_ALIASES: dict[str, list[str]] = {
    "passing_yards": ["passing_yards"],
    "passing_td": ["passing_tds", "passing_td"],
    "interception": ["passing_interceptions", "interceptions"],
    "passing_2pt": ["passing_2pt_conversions", "passing_two_point_conversions"],
    "rushing_yards": ["rushing_yards"],
    "rushing_td": ["rushing_tds", "rushing_td"],
    "rushing_2pt": ["rushing_2pt_conversions", "rushing_two_point_conversions"],
    "reception": ["receptions"],
    "receiving_yards": ["receiving_yards"],
    "receiving_td": ["receiving_tds", "receiving_td"],
    "receiving_2pt": ["receiving_2pt_conversions", "receiving_two_point_conversions"],
}

# Fumbles are handled separately because newer data splits them into several
# columns that we want to SUM together.
_FUMBLE_COLUMNS = [
    "sack_fumbles_lost",
    "rushing_fumbles_lost",
    "receiving_fumbles_lost",
    "fumbles_lost",  # older single column; only used if the split ones are absent
]


def _numeric_col(df: pd.DataFrame, names: list[str]) -> pd.Series:
    """Return the first matching column as floats (missing -> 0.0)."""
    for name in names:
        if name in df.columns:
            return pd.to_numeric(df[name], errors="coerce").fillna(0.0)
    # None of the candidate columns exist -> a column of zeros.
    return pd.Series(0.0, index=df.index)


def _fumbles_lost(df: pd.DataFrame) -> pd.Series:
    """Total fumbles lost, summing the split columns when they exist."""
    split_cols = [c for c in _FUMBLE_COLUMNS[:3] if c in df.columns]
    if split_cols:
        total = pd.Series(0.0, index=df.index)
        for c in split_cols:
            total = total + pd.to_numeric(df[c], errors="coerce").fillna(0.0)
        return total
    # Fall back to a single legacy column if present.
    return _numeric_col(df, ["fumbles_lost"])


def compute_fantasy_points(
    df: pd.DataFrame,
    scoring: dict[str, float] | None = None,
) -> pd.Series:
    """
    Compute fantasy points for each row using the given scoring rules.

    Parameters
    ----------
    df : weekly player stats (one row per player-game).
    scoring : mapping of category -> points. Defaults to config.SCORING.

    Returns
    -------
    pandas Series of fantasy points, aligned to df's index.
    """
    scoring = scoring or config.SCORING

    points = (
        _numeric_col(df, _STAT_ALIASES["passing_yards"]) * scoring["passing_yards"]
        + _numeric_col(df, _STAT_ALIASES["passing_td"]) * scoring["passing_td"]
        + _numeric_col(df, _STAT_ALIASES["interception"]) * scoring["interception"]
        + _numeric_col(df, _STAT_ALIASES["passing_2pt"]) * scoring["passing_2pt"]
        + _numeric_col(df, _STAT_ALIASES["rushing_yards"]) * scoring["rushing_yards"]
        + _numeric_col(df, _STAT_ALIASES["rushing_td"]) * scoring["rushing_td"]
        + _numeric_col(df, _STAT_ALIASES["rushing_2pt"]) * scoring["rushing_2pt"]
        + _numeric_col(df, _STAT_ALIASES["reception"]) * scoring["reception"]
        + _numeric_col(df, _STAT_ALIASES["receiving_yards"]) * scoring["receiving_yards"]
        + _numeric_col(df, _STAT_ALIASES["receiving_td"]) * scoring["receiving_td"]
        + _numeric_col(df, _STAT_ALIASES["receiving_2pt"]) * scoring["receiving_2pt"]
        + _fumbles_lost(df) * scoring["fumble_lost"]
    )
    return points.rename("fantasy_points")


def add_fantasy_points(
    df: pd.DataFrame,
    scoring: dict[str, float] | None = None,
    column: str = "fantasy_points",
) -> pd.DataFrame:
    """Return a copy of df with a fantasy-points column added."""
    out = df.copy()
    out[column] = compute_fantasy_points(df, scoring)
    return out
