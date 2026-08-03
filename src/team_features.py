"""
Team-situation features -- the "opportunity/environment" half of a projection.

A player's fantasy output depends heavily on the offense around them, and the
fantasy-relevant fingerprint of a coaching staff/scheme shows up in *measurable
team tendencies*. We don't need to know the coordinator's name -- we measure
what the offense actually does:

  sit_pass_rate  -- how pass-happy the offense is (season-to-date, lagged)
  sit_proe       -- pass rate OVER what the situation expects (scheme lean)
  sit_plays_pg   -- pace / volume: plays per game (more plays = more chances)
  sit_implied_total -- Vegas' expected points for this team THIS game
  sit_spread     -- game spread from this team's perspective (game script)

The play-by-play tendencies are lagged (they summarize prior games only, so no
leakage). The Vegas numbers are the actual pre-game betting line -- known before
kickoff, so they're fair game and capture the upcoming game's environment.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _num(df: pd.DataFrame, name: str) -> pd.Series:
    if name in df.columns:
        return pd.to_numeric(df[name], errors="coerce")
    return pd.Series(np.nan, index=df.index)


def _team_tendencies(pbp: pd.DataFrame | None) -> pd.DataFrame:
    """Per team-game pass rate / PROE / plays, then lagged season-to-date."""
    empty = pd.DataFrame(columns=["season", "week", "team", "sit_pass_rate", "sit_proe", "sit_plays_pg"])
    if pbp is None or pbp.empty or "posteam" not in pbp.columns:
        return empty

    df = pbp.copy()
    # pass / rush flags (prefer explicit indicator columns, fall back to play_type)
    if "pass" in df.columns:
        is_pass = _num(df, "pass").fillna(0)
    else:
        is_pass = (df.get("play_type") == "pass").astype(float)
    if "rush" in df.columns:
        is_rush = _num(df, "rush").fillna(0)
    else:
        is_rush = (df.get("play_type") == "run").astype(float)

    # pass rate over expected: prefer nflverse's pass_oe, else pass - xpass
    if "pass_oe" in df.columns:
        proe = _num(df, "pass_oe")
    elif "xpass" in df.columns:
        proe = is_pass - _num(df, "xpass")
    else:
        proe = pd.Series(np.nan, index=df.index)

    df = df.assign(_pass=is_pass, _rush=is_rush, _play=((is_pass + is_rush) > 0).astype(float), _proe=proe)
    grouped = df.groupby(["season", "week", "posteam"], dropna=True).agg(
        pass_plays=("_pass", "sum"),
        rush_plays=("_rush", "sum"),
        plays=("_play", "sum"),
        proe=("_proe", "mean"),
    ).reset_index().rename(columns={"posteam": "team"})

    denom = (grouped["pass_plays"] + grouped["rush_plays"]).replace(0, np.nan)
    grouped["pass_rate"] = grouped["pass_plays"] / denom

    # Lag to season-to-date averages entering each game (shift(1) => leak-free).
    grouped = grouped.sort_values(["season", "team", "week"])
    for src, dst in [("pass_rate", "sit_pass_rate"), ("proe", "sit_proe"), ("plays", "sit_plays_pg")]:
        grouped[dst] = grouped.groupby(["season", "team"])[src].transform(
            lambda s: s.shift(1).expanding().mean()
        )
    return grouped[["season", "week", "team", "sit_pass_rate", "sit_proe", "sit_plays_pg"]]


def _vegas(schedules: pd.DataFrame | None) -> pd.DataFrame:
    """Implied team total & spread for each team-game, from the betting line."""
    empty = pd.DataFrame(columns=["season", "week", "team", "sit_implied_total", "sit_spread"])
    if schedules is None or schedules.empty:
        return empty
    need = {"season", "week", "home_team", "away_team"}
    if not need.issubset(schedules.columns):
        return empty

    s = schedules.copy()
    total = _num(s, "total_line")
    # nflverse convention: spread_line > 0 means the HOME team is favored.
    spread = _num(s, "spread_line")

    home = pd.DataFrame({
        "season": _num(s, "season"), "week": _num(s, "week"), "team": s["home_team"],
        "sit_implied_total": (total + spread) / 2.0,
        "sit_spread": spread,
    })
    away = pd.DataFrame({
        "season": _num(s, "season"), "week": _num(s, "week"), "team": s["away_team"],
        "sit_implied_total": (total - spread) / 2.0,
        "sit_spread": -spread,
    })
    return pd.concat([home, away], ignore_index=True)


def build_team_week_features(
    pbp: pd.DataFrame | None,
    schedules: pd.DataFrame | None,
) -> pd.DataFrame:
    """Combine tendencies + Vegas into one team-week table keyed (season, week, team)."""
    tendencies = _team_tendencies(pbp)
    vegas = _vegas(schedules)

    if tendencies.empty and vegas.empty:
        return pd.DataFrame(columns=["season", "week", "team"])
    if tendencies.empty:
        return vegas
    if vegas.empty:
        return tendencies

    for frame in (tendencies, vegas):
        frame["season"] = pd.to_numeric(frame["season"], errors="coerce")
        frame["week"] = pd.to_numeric(frame["week"], errors="coerce")

    return tendencies.merge(vegas, on=["season", "week", "team"], how="outer")


# Feature columns this module contributes (used by the model + explainer).
SITUATION_FEATURES = ["sit_pass_rate", "sit_proe", "sit_plays_pg", "sit_implied_total", "sit_spread"]


def build_team_season_features(
    pbp: pd.DataFrame | None,
    schedules: pd.DataFrame | None,
    weekly: pd.DataFrame | None,
) -> pd.DataFrame:
    """
    Per (season, team) environment aggregates used by the index-blend model:
    pass rate, PROE, pace, sack rate (O-line proxy), average implied total &
    points/game (scoring environment), and WR/TE production (supporting cast).
    """
    frames = []

    # ---- from play-by-play: pass rate, PROE, pace, sack rate ----
    if pbp is not None and not pbp.empty and "posteam" in pbp.columns:
        df = pbp.copy()
        is_pass = _num(df, "pass").fillna(0) if "pass" in df.columns else (df.get("play_type") == "pass").astype(float)
        is_rush = _num(df, "rush").fillna(0) if "rush" in df.columns else (df.get("play_type") == "run").astype(float)
        sack = _num(df, "sack").fillna(0) if "sack" in df.columns else pd.Series(0.0, index=df.index)
        if "pass_oe" in df.columns:
            proe = _num(df, "pass_oe")
        elif "xpass" in df.columns:
            proe = is_pass - _num(df, "xpass")
        else:
            proe = pd.Series(float("nan"), index=df.index)
        df = df.assign(_p=is_pass, _r=is_rush, _s=sack, _pl=((is_pass + is_rush) > 0).astype(float), _proe=proe)
        gp = df.groupby(["season", "posteam"])
        games = df.groupby(["season", "posteam"])["week"].nunique().rename("games")
        agg = gp.agg(pass_plays=("_p", "sum"), rush_plays=("_r", "sum"),
                     sacks=("_s", "sum"), plays=("_pl", "sum"), proe=("_proe", "mean")).join(games)
        agg = agg.reset_index().rename(columns={"posteam": "team"})
        denom = (agg["pass_plays"] + agg["rush_plays"]).replace(0, np.nan)
        agg["pass_rate"] = agg["pass_plays"] / denom
        agg["sack_rate"] = agg["sacks"] / agg["pass_plays"].replace(0, np.nan)
        agg["plays_pg"] = agg["plays"] / agg["games"].replace(0, np.nan)
        frames.append(agg[["season", "team", "pass_rate", "proe", "plays_pg", "sack_rate"]])

    # ---- from schedules: implied total & points per game ----
    if schedules is not None and not schedules.empty and {"home_team", "away_team"}.issubset(schedules.columns):
        vegas = _vegas(schedules)
        if not vegas.empty:
            vg = vegas.groupby(["season", "team"])["sit_implied_total"].mean().reset_index()
            vg = vg.rename(columns={"sit_implied_total": "implied_total_avg"})
            frames.append(vg)
        if {"home_score", "away_score"}.issubset(schedules.columns):
            s = schedules
            home = pd.DataFrame({"season": _num(s, "season"), "team": s["home_team"], "pf": _num(s, "home_score")})
            away = pd.DataFrame({"season": _num(s, "season"), "team": s["away_team"], "pf": _num(s, "away_score")})
            pts = pd.concat([home, away], ignore_index=True).dropna(subset=["pf"])
            pts = pts.groupby(["season", "team"])["pf"].mean().reset_index().rename(columns={"pf": "points_pg"})
            frames.append(pts)

    # ---- from weekly stats: WR/TE production (supporting cast) ----
    if weekly is not None and not weekly.empty:
        w = weekly.copy()
        pos = w.get("position", pd.Series(index=w.index))
        team = w["team"] if "team" in w.columns else w.get("recent_team")
        recy = _num(w, "receiving_yards")
        wk = _num(w, "week")
        wt = pd.DataFrame({"season": _num(w, "season"), "team": team, "week": wk,
                           "pos": pos, "recy": recy})
        wt = wt[wt["pos"].isin(["WR", "TE"])]
        if not wt.empty:
            per_game = wt.groupby(["season", "team", "week"])["recy"].sum().reset_index()
            cast = per_game.groupby(["season", "team"])["recy"].mean().reset_index()
            cast = cast.rename(columns={"recy": "wrte_rec_yds_pg"})
            frames.append(cast)

    if not frames:
        return pd.DataFrame(columns=["season", "team"])

    out = frames[0]
    for f in frames[1:]:
        f["season"] = pd.to_numeric(f["season"], errors="coerce")
        out["season"] = pd.to_numeric(out["season"], errors="coerce")
        out = out.merge(f, on=["season", "team"], how="outer")
    return out


TEAM_SEASON_FEATURES = [
    "pass_rate", "proe", "plays_pg", "sack_rate",
    "implied_total_avg", "points_pg", "wrte_rec_yds_pg",
]
