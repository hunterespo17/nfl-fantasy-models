"""
Feature engineering for weekly fantasy-point prediction.

THE most important idea in this whole project lives here: **no data leakage**.

When we build a feature for "week W", we may only use information that was
actually known BEFORE week W kicked off. If we accidentally let this week's
result sneak into the inputs, the model looks amazing in testing and then
falls apart in real life. Every feature below is therefore *lagged* -- it is
shifted so the current game is excluded.

The target we predict is `y` = the fantasy points the player actually scored
in week W (computed from that week's box score using YOUR scoring rules).

The features are things like:
  * the player's average fantasy points over their previous 3 / 5 / 10 games
  * their recent usage (targets, carries, snap share) -- opportunity is sticky
  * how many points the upcoming opponent's defense has allowed to this
    position so far this season
  * home vs away, week number, games played to date
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config, scoring

# Canonical stat columns we build rolling "recent form" features from, each
# with the possible source-column names (handles nflverse schema drift).
_ROLL_STATS: dict[str, list[str]] = {
    "fantasy_points": ["fantasy_points"],   # created below from scoring rules
    "targets": ["targets"],
    "receptions": ["receptions"],
    "carries": ["carries", "rushing_attempts"],
    "pass_attempts": ["attempts", "passing_attempts"],
    "passing_yards": ["passing_yards"],
    "rushing_yards": ["rushing_yards"],
    "receiving_yards": ["receiving_yards"],
    "passing_tds": ["passing_tds"],
    "rushing_tds": ["rushing_tds"],
    "receiving_tds": ["receiving_tds"],
    "snap_share": ["snap_share"],           # merged from snap counts, if available
}

# Non-rolling "context" features.
_EXTRA_NUMERIC = [
    "is_home",
    "week",
    "games_this_season_prior",
    "career_games_prior",
    "opp_points_allowed_to_pos",
]
_CATEGORICAL = ["position"]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _pick(df: pd.DataFrame, names: list[str]) -> pd.Series | None:
    """Return the first present column from `names`, else None."""
    for name in names:
        if name in df.columns:
            return df[name]
    return None


def _numeric(df: pd.DataFrame, names: list[str]) -> pd.Series:
    """First present column as floats (missing -> 0.0)."""
    col = _pick(df, names)
    if col is None:
        return pd.Series(0.0, index=df.index)
    return pd.to_numeric(col, errors="coerce").fillna(0.0)


def _norm_name(series: pd.Series) -> pd.Series:
    """Normalize player names for joining across datasets."""
    return (
        series.astype(str)
        .str.lower()
        .str.replace(r"[^a-z ]", "", regex=True)
        .str.strip()
    )


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------
def _standardize(weekly: pd.DataFrame, scoring_rules: dict | None) -> pd.DataFrame:
    """Create canonical id/context columns and the fantasy-point target."""
    df = pd.DataFrame(index=weekly.index)

    df["player_id"] = _pick(weekly, ["player_id", "gsis_id"])
    df["player_name"] = _pick(weekly, ["player_display_name", "player_name", "full_name"])
    df["position"] = _pick(weekly, ["position", "position_group"])
    df["team"] = _pick(weekly, ["team", "recent_team"])
    df["season"] = pd.to_numeric(_pick(weekly, ["season"]), errors="coerce")
    df["week"] = pd.to_numeric(_pick(weekly, ["week"]), errors="coerce")
    season_type = _pick(weekly, ["season_type"])
    df["season_type"] = season_type if season_type is not None else "REG"
    opp = _pick(weekly, ["opponent_team", "opponent"])
    if opp is not None:
        df["opponent"] = opp

    # The target: fantasy points scored THIS week, under our scoring rules.
    df["fantasy_points"] = scoring.compute_fantasy_points(weekly, scoring_rules)

    # Carry over the raw stat columns we roll on (canonical names).
    for canonical, aliases in _ROLL_STATS.items():
        if canonical == "fantasy_points" or canonical == "snap_share":
            continue  # created elsewhere
        df[canonical] = _numeric(weekly, aliases)
    return df


def _attach_schedule(df: pd.DataFrame, schedules: pd.DataFrame | None) -> pd.DataFrame:
    """Add opponent + home/away from the schedule (authoritative source)."""
    if schedules is None or schedules.empty:
        if "opponent" not in df.columns:
            df["opponent"] = np.nan
        if "is_home" not in df.columns:
            df["is_home"] = np.nan
        return df

    sched = schedules.copy()
    needed = {"season", "week", "home_team", "away_team"}
    if not needed.issubset(sched.columns):
        if "is_home" not in df.columns:
            df["is_home"] = np.nan
        return df

    home = sched[["season", "week", "home_team", "away_team"]].rename(
        columns={"home_team": "team", "away_team": "opponent"}
    )
    home["is_home"] = 1
    away = sched[["season", "week", "away_team", "home_team"]].rename(
        columns={"away_team": "team", "home_team": "opponent"}
    )
    away["is_home"] = 0
    team_week = pd.concat([home, away], ignore_index=True)
    team_week["season"] = pd.to_numeric(team_week["season"], errors="coerce")
    team_week["week"] = pd.to_numeric(team_week["week"], errors="coerce")

    # Prefer schedule-derived opponent/home; overwrite any weekly-derived one.
    df = df.drop(columns=[c for c in ("opponent", "is_home") if c in df.columns])
    df = df.merge(team_week, on=["season", "week", "team"], how="left")
    return df


def _attach_snap_share(df: pd.DataFrame, snaps: pd.DataFrame | None) -> pd.DataFrame:
    """Merge offensive snap share by (season, week, team, normalized name)."""
    if snaps is None or snaps.empty:
        df["snap_share"] = np.nan
        return df

    s = snaps.copy()
    pct = _pick(s, ["offense_pct", "offense_snaps_pct"])
    name = _pick(s, ["player", "player_name", "full_name"])
    team = _pick(s, ["team", "recent_team"])
    if pct is None or name is None or team is None:
        df["snap_share"] = np.nan
        return df

    s = pd.DataFrame(
        {
            "season": pd.to_numeric(_pick(s, ["season"]), errors="coerce"),
            "week": pd.to_numeric(_pick(s, ["week"]), errors="coerce"),
            "team": team,
            "name_key": _norm_name(name),
            "snap_share": pd.to_numeric(pct, errors="coerce"),
        }
    )
    # snap "pct" is sometimes 0-1 and sometimes 0-100; normalize to 0-1.
    if s["snap_share"].max(skipna=True) is not None and s["snap_share"].max() > 1.5:
        s["snap_share"] = s["snap_share"] / 100.0
    s = s.dropna(subset=["name_key"]).drop_duplicates(
        subset=["season", "week", "team", "name_key"]
    )

    df["name_key"] = _norm_name(df["player_name"])
    df = df.merge(s, on=["season", "week", "team", "name_key"], how="left")
    df = df.drop(columns=["name_key"])
    return df


def _add_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add lagged rolling & season-to-date averages for each usage/production stat."""
    df = df.sort_values(["player_id", "season", "week"]).reset_index(drop=True)

    present_stats = [s for s in _ROLL_STATS if s in df.columns]
    for stat in present_stats:
        grp = df.groupby("player_id")[stat]
        # Rolling averages over the previous N games (shift(1) excludes today).
        for window in config.ROLLING_WINDOWS:
            df[f"{stat}_roll{window}"] = grp.transform(
                lambda s, w=window: s.shift(1).rolling(w, min_periods=1).mean()
            )
        # Season-to-date average entering this game (also lagged).
        df[f"{stat}_szn"] = df.groupby(["player_id", "season"])[stat].transform(
            lambda s: s.shift(1).expanding().mean()
        )

    # Experience counters (number of PRIOR games, so leak-free by construction).
    df["games_this_season_prior"] = df.groupby(["player_id", "season"]).cumcount()
    df["career_games_prior"] = df.groupby("player_id").cumcount()
    return df


def _add_opponent_strength(df: pd.DataFrame) -> pd.DataFrame:
    """
    "Defense vs position": how many fantasy points the upcoming opponent has
    allowed to this position so far this season (entering the game -- lagged).
    """
    if "opponent" not in df.columns:
        df["opp_points_allowed_to_pos"] = np.nan
        return df

    # Points each defense allowed to each position, per week.
    dvp = (
        df.groupby(["season", "week", "opponent", "position"], dropna=False)[
            "fantasy_points"
        ]
        .sum()
        .reset_index()
        .rename(columns={"opponent": "def_team"})
        .sort_values(["season", "def_team", "position", "week"])
    )
    # Season-to-date average allowed, entering the week (shift(1) = leak-free).
    dvp["opp_points_allowed_to_pos"] = dvp.groupby(
        ["season", "def_team", "position"]
    )["fantasy_points"].transform(lambda s: s.shift(1).expanding().mean())

    df = df.merge(
        dvp[["season", "week", "def_team", "position", "opp_points_allowed_to_pos"]],
        left_on=["season", "week", "opponent", "position"],
        right_on=["season", "week", "def_team", "position"],
        how="left",
    ).drop(columns=["def_team"])
    return df


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def build_features(
    weekly: pd.DataFrame,
    schedules: pd.DataFrame | None = None,
    snaps: pd.DataFrame | None = None,
    scoring_rules: dict | None = None,
) -> pd.DataFrame:
    """
    Turn raw weekly stats (+ optional schedules & snap counts) into a modeling
    table: one row per player-game, with a `fantasy_points` target and a set of
    strictly leak-free feature columns.
    """
    df = _standardize(weekly, scoring_rules)

    # Keep only the skill positions we model, regular season by default.
    df = df[df["position"].isin(config.FANTASY_POSITIONS)]
    df = df[df["season_type"].isin(config.SEASON_TYPES)]
    df = df.dropna(subset=["player_id", "season", "week"]).reset_index(drop=True)

    df = _attach_schedule(df, schedules)
    df = _attach_snap_share(df, snaps)
    df = _add_rolling_features(df)
    df = _add_opponent_strength(df)

    return df.reset_index(drop=True)


def feature_columns(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    """
    Return (numeric_features, categorical_features) present in df.

    Model code calls this so it never has to hard-code the (many) rolling
    column names.
    """
    def _usable(col: str) -> bool:
        # Present AND not entirely empty (e.g. snap_share when snaps weren't loaded).
        return col in df.columns and df[col].notna().any()

    numeric: list[str] = []
    for stat in _ROLL_STATS:
        for window in config.ROLLING_WINDOWS:
            col = f"{stat}_roll{window}"
            if _usable(col):
                numeric.append(col)
        szn = f"{stat}_szn"
        if _usable(szn):
            numeric.append(szn)
    numeric += [c for c in _EXTRA_NUMERIC if _usable(c)]

    categorical = [c for c in _CATEGORICAL if c in df.columns]
    return numeric, categorical
