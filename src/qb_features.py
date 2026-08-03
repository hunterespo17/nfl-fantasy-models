"""
QB feature builder (Option A): one rich model that blends who a QB *is* with the
situation he's in.

Features are organized into four labeled GROUPS so the model can learn from all
of them and the explainer can show how each group moved a given projection:

  Archetype -- career-to-date identity (how much he passes vs runs, efficiency).
               Slow-moving; answers "what kind of QB is this?"
  Situation -- the offense/environment around him (team pass rate, PROE, pace,
               Vegas implied total & spread). Answers "what spot is he in?"
  Form      -- recent games (last 3/5). Answers "how's he playing lately?"
  Matchup   -- opponent's generosity to QBs, home/away, week.

Every feature is leak-free: archetype and form are lagged (prior games only),
situation tendencies are lagged season-to-date, the Vegas line is the pre-game
number, and matchup strength is the opponent's prior-games average.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config, scoring

FEATURE_GROUPS: dict[str, list[str]] = {
    "Archetype": ["arch_pass_att_pg", "arch_rush_att_pg", "arch_rush_yd_pg", "arch_fp_pg", "arch_ypa"],
    "Situation": ["sit_pass_rate", "sit_proe", "sit_plays_pg", "sit_implied_total", "sit_spread"],
    "Form": ["form_fp_roll3", "form_fp_roll5", "form_pass_att_roll3", "form_rush_att_roll3", "form_pass_yd_roll3"],
    "Matchup": ["mu_opp_pa", "mu_is_home", "mu_week"],
}


def _pick(df: pd.DataFrame, names: list[str]) -> pd.Series | None:
    for n in names:
        if n in df.columns:
            return df[n]
    return None


def _num(df: pd.DataFrame, names: list[str]) -> pd.Series:
    col = _pick(df, names)
    if col is None:
        return pd.Series(0.0, index=df.index)
    return pd.to_numeric(col, errors="coerce").fillna(0.0)


def _team_week_from_schedule(schedules: pd.DataFrame | None) -> pd.DataFrame | None:
    if schedules is None or schedules.empty:
        return None
    need = {"season", "week", "home_team", "away_team"}
    if not need.issubset(schedules.columns):
        return None
    home = schedules[["season", "week", "home_team", "away_team"]].rename(
        columns={"home_team": "team", "away_team": "opponent"}
    )
    home["mu_is_home"] = 1
    away = schedules[["season", "week", "away_team", "home_team"]].rename(
        columns={"away_team": "team", "home_team": "opponent"}
    )
    away["mu_is_home"] = 0
    tw = pd.concat([home, away], ignore_index=True)
    tw["season"] = pd.to_numeric(tw["season"], errors="coerce")
    tw["week"] = pd.to_numeric(tw["week"], errors="coerce")
    return tw


def build_qb_features(
    weekly: pd.DataFrame,
    schedules: pd.DataFrame | None = None,
    team_week: pd.DataFrame | None = None,
    scoring_rules: dict | None = None,
) -> pd.DataFrame:
    """Build the QB modeling table (one row per QB game-week)."""
    df = pd.DataFrame(index=weekly.index)
    df["player_id"] = _pick(weekly, ["player_id", "gsis_id"])
    df["player_name"] = _pick(weekly, ["player_display_name", "player_name", "full_name"])
    df["position"] = _pick(weekly, ["position", "position_group"])
    df["team"] = _pick(weekly, ["team", "recent_team"])
    df["season"] = pd.to_numeric(_pick(weekly, ["season"]), errors="coerce")
    df["week"] = pd.to_numeric(_pick(weekly, ["week"]), errors="coerce")
    stype = _pick(weekly, ["season_type"])
    df["season_type"] = stype if stype is not None else "REG"

    # Target and the raw stats we derive features from.
    df["fantasy_points"] = scoring.compute_fantasy_points(weekly, scoring_rules)
    df["pass_attempts"] = _num(weekly, ["attempts", "passing_attempts"])
    df["passing_yards"] = _num(weekly, ["passing_yards"])
    df["carries"] = _num(weekly, ["carries", "rushing_attempts"])
    df["rushing_yards"] = _num(weekly, ["rushing_yards"])

    # QBs, regular season, valid keys.
    df = df[df["position"] == "QB"]
    df = df[df["season_type"].isin(config.SEASON_TYPES)]
    df = df.dropna(subset=["player_id", "season", "week"]).reset_index(drop=True)

    # Opponent + home/away from the schedule.
    tw = _team_week_from_schedule(schedules)
    if tw is not None:
        df = df.merge(tw, on=["season", "week", "team"], how="left")
    else:
        df["opponent"] = _pick(weekly, ["opponent_team", "opponent"])
        df["mu_is_home"] = np.nan

    df = df.sort_values(["player_id", "season", "week"]).reset_index(drop=True)
    g = df.groupby("player_id")

    # --- Archetype: career-to-date, lagged ---------------------------------
    df["arch_pass_att_pg"] = g["pass_attempts"].transform(lambda s: s.shift(1).expanding().mean())
    df["arch_rush_att_pg"] = g["carries"].transform(lambda s: s.shift(1).expanding().mean())
    df["arch_rush_yd_pg"] = g["rushing_yards"].transform(lambda s: s.shift(1).expanding().mean())
    df["arch_fp_pg"] = g["fantasy_points"].transform(lambda s: s.shift(1).expanding().mean())
    cum_py = g["passing_yards"].transform(lambda s: s.shift(1).cumsum())
    cum_pa = g["pass_attempts"].transform(lambda s: s.shift(1).cumsum())
    df["arch_ypa"] = cum_py / cum_pa.replace(0, np.nan)

    # --- Form: recent games, lagged ----------------------------------------
    df["form_fp_roll3"] = g["fantasy_points"].transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean())
    df["form_fp_roll5"] = g["fantasy_points"].transform(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
    df["form_pass_att_roll3"] = g["pass_attempts"].transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean())
    df["form_rush_att_roll3"] = g["carries"].transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean())
    df["form_pass_yd_roll3"] = g["passing_yards"].transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean())

    # --- Matchup: opponent generosity to QBs (lagged), home/away, week -----
    if "opponent" in df.columns:
        dvp = (
            df.groupby(["season", "week", "opponent"], dropna=False)["fantasy_points"]
            .sum()
            .reset_index()
            .rename(columns={"opponent": "def_team"})
            .sort_values(["season", "def_team", "week"])
        )
        dvp["mu_opp_pa"] = dvp.groupby(["season", "def_team"])["fantasy_points"].transform(
            lambda s: s.shift(1).expanding().mean()
        )
        df = df.merge(
            dvp[["season", "week", "def_team", "mu_opp_pa"]],
            left_on=["season", "week", "opponent"],
            right_on=["season", "week", "def_team"],
            how="left",
        ).drop(columns=["def_team"])
    else:
        df["mu_opp_pa"] = np.nan
    df["mu_week"] = df["week"]

    # --- Situation: merge the team-week environment layer ------------------
    if team_week is not None and not team_week.empty:
        keep = ["season", "week", "team"] + [c for c in team_week.columns if c.startswith("sit_")]
        df = df.merge(team_week[keep], on=["season", "week", "team"], how="left")
    for col in FEATURE_GROUPS["Situation"]:
        if col not in df.columns:
            df[col] = np.nan

    return df.reset_index(drop=True)


def feature_list(df: pd.DataFrame) -> list[str]:
    """All grouped feature columns present in df and not entirely empty."""
    cols: list[str] = []
    for group in FEATURE_GROUPS.values():
        for c in group:
            if c in df.columns and df[c].notna().any():
                cols.append(c)
    return cols
