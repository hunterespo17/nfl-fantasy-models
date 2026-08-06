"""LAST SEASON'S FACTS, rebuilt the same way the screen was fitted on them.

The league-winner screens for running backs and tight ends are thresholds on
what a player did in the season BEFORE the one being drafted. This module is
the single place those facts are computed, and it exists for one reason: the
screen has to be measured on the board exactly the way it was measured on
history, or the hit rates printed next to it are advertising rather than
evidence.

Why not just read the board payload? Three of its fields look like they would
do and none of them will:

  * `snap_pct` is on a 0-100 scale on the RB board and a 0-1 scale on the TE
    board. A 0.80 threshold silently passes every back and almost no tight end.
  * `games` and `targets_pg` are 2026 PROJECTIONS -- every player carries
    games=17 -- so "came off a short season" read off the payload is always
    false, and "3+ targets a game last year" is really "3+ targets a game next
    year", which is our own opinion fed back to us as evidence.
  * the share of a position group's expected points is not on the payload at
    all.

So the facts are recomputed here from the same three raw files the fitting
bench used (`player_weekly_stats.csv`, `snap_counts.csv`, `players.csv`), with
the same definitions, in about a second and a half. Definitions, verbatim from
the bench:

  half-PPR points  fantasy_points + 0.5 * receptions, regular season only
  expected points  carries * (league pts per carry) + targets * (league pts per
                   target), with those two rates refit SEPARATELY EACH SEASON
                   so a scoring-environment shift cannot leak backwards
  xfp_share        a player's expected points over his own position group's
                   expected points on his team that season
  snap share       mean offensive snap percentage across his regular-season
                   games, normalised to 0-1
  "last season"    the most recent season strictly earlier than this one in
                   which he actually appeared -- not literally season - 1, so a
                   player who missed a whole year is measured on the last year
                   he played rather than treated as having no history

Everything here is knowable in August. Nothing is read from the season being
projected. When a file is missing the loader returns an empty map, which makes
every check read "not measured" rather than "failed" -- an unmeasured check
must never condemn a player.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from . import adp as adp_mod

# Only these are needed off the 145-column weekly file; the full read is 66 MB
# and this subset is about a second.
_USE = ["player_id", "player_display_name", "position", "season", "week",
        "season_type", "team", "carries", "rushing_yards", "rushing_tds",
        "targets", "receptions", "receiving_yards", "receiving_tds",
        "target_share", "fantasy_points"]

_LOOKBACK = 8          # seasons of history to read; the screens only need one
_MIN_LEAGUE = 500      # carries/targets under this means a season is too thin
                       # to fit league rates on (a strike-shortened or partial file)

_CACHE: dict = {}


def _root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _seasons(season: int) -> pd.DataFrame:
    """Season-level player aggregates with expected points and snap share."""
    key = ("_szn", int(season))
    if key in _CACHE:
        return _CACHE[key]
    root = _root()
    path = os.path.join(root, "data", "raw", "player_weekly_stats.csv")
    if not os.path.exists(path):
        _CACHE[key] = pd.DataFrame()
        return _CACHE[key]
    w = pd.read_csv(path, low_memory=False, usecols=_USE)
    w = w[w["season_type"].astype(str).str.upper().isin(("REG", "REGULAR"))]
    w = w[pd.to_numeric(w["season"], errors="coerce") >= int(season) - _LOOKBACK]
    for c in ("carries", "rushing_yards", "rushing_tds", "targets", "receptions",
              "receiving_yards", "receiving_tds", "target_share", "fantasy_points"):
        w[c] = pd.to_numeric(w[c], errors="coerce").fillna(0.0)
    w["half"] = w["fantasy_points"] + 0.5 * w["receptions"]

    szn = (w.groupby(["player_id", "season"])
           .agg(name=("player_display_name", "first"),
                pos=("position", "first"),
                team=("team", lambda s: s.mode().iat[0] if len(s.mode()) else None),
                games=("week", "nunique"),
                pts=("half", "sum"),
                car=("carries", "sum"),
                ry=("rushing_yards", "sum"),
                rtd=("rushing_tds", "sum"),
                tgt=("targets", "sum"),
                rec=("receptions", "sum"),
                recy=("receiving_yards", "sum"),
                rectd=("receiving_tds", "sum"),
                tshare=("target_share", "mean"))
           .reset_index())
    szn["ppg"] = szn["pts"] / szn["games"].clip(lower=1)

    # League points per carry and per target, refit each season.
    rows = []
    skill = szn[szn["pos"].isin(("RB", "WR", "TE"))]
    for s, g in skill.groupby("season"):
        car, tgt = g["car"].sum(), g["tgt"].sum()
        if car < _MIN_LEAGUE or tgt < _MIN_LEAGUE:
            continue
        rows.append({
            "season": s,
            "pt_car": (0.1 * g["ry"].sum() + 6 * g["rtd"].sum()) / car,
            "pt_tgt": (0.1 * g["recy"].sum() + 6 * g["rectd"].sum()
                       + 0.5 * g["rec"].sum()) / tgt,
        })
    if rows:
        szn = szn.merge(pd.DataFrame(rows), on="season", how="left")
    else:
        szn["pt_car"] = szn["pt_tgt"] = np.nan
    szn["xfp"] = szn["car"] * szn["pt_car"] + szn["tgt"] * szn["pt_tgt"]

    # Share of the position group's expected points on that team that season.
    szn["_tk"] = szn["team"].astype(str) + "|" + szn["season"].astype(str)
    szn["xfp_share"] = np.nan
    szn["car_share"] = np.nan
    for p in ("RB", "TE", "WR"):
        m = szn["pos"] == p
        if not m.any():
            continue
        tot = szn[m].groupby("_tk")["xfp"].transform("sum")
        szn.loc[m, "xfp_share"] = szn.loc[m, "xfp"] / tot.replace(0, np.nan)
        tc = szn[m].groupby("_tk")["car"].transform("sum")
        szn.loc[m, "car_share"] = szn.loc[m, "car"] / tc.replace(0, np.nan)

    # snap share, joined on the normalised name (the snap file has no gsis id)
    sp = os.path.join(root, "data", "raw", "snap_counts.csv")
    szn["key"] = szn["name"].map(adp_mod.norm)
    szn["snap_pct"] = np.nan
    if os.path.exists(sp):
        sn = pd.read_csv(sp, low_memory=False,
                         usecols=["season", "game_type", "player", "offense_pct"])
        sn = sn[sn["game_type"].astype(str).str.upper().isin(("REG", "REGULAR"))]
        sn = sn[pd.to_numeric(sn["season"], errors="coerce") >= int(season) - _LOOKBACK]
        sn["offense_pct"] = pd.to_numeric(sn["offense_pct"], errors="coerce")
        snap = (sn.groupby(["player", "season"])["offense_pct"].mean().reset_index()
                .rename(columns={"offense_pct": "snap_pct"}))
        snap["key"] = snap["player"].map(adp_mod.norm)
        szn = szn.drop(columns=["snap_pct"]).merge(
            snap[["key", "season", "snap_pct"]], on=["key", "season"], how="left")
        mx = szn["snap_pct"].max()
        if pd.notna(mx) and mx > 1.5:       # the file ships 0-100; the screen is 0-1
            szn["snap_pct"] = szn["snap_pct"] / 100.0

    _CACHE[key] = szn
    return szn


def draft_capital() -> dict:
    """gsis_id -> {'round': int|None, 'pick': int|None}, including this year's rookies."""
    if "_draft" in _CACHE:
        return _CACHE["_draft"]
    path = os.path.join(_root(), "data", "raw", "players.csv")
    out: dict = {}
    if os.path.exists(path):
        pl = pd.read_csv(path, low_memory=False,
                         usecols=["gsis_id", "draft_round", "draft_pick"])
        for r in pl.itertuples():
            rd = pd.to_numeric(r.draft_round, errors="coerce")
            pk = pd.to_numeric(r.draft_pick, errors="coerce")
            out[str(r.gsis_id)] = {
                "round": (int(rd) if pd.notna(rd) else None),
                "pick": (int(pk) if pd.notna(pk) else None),
            }
    _CACHE["_draft"] = out
    return out


def prior_facts(pos: str, season: int) -> dict:
    """{name_key: facts} for the last season each `pos` player actually played.

    Returns an empty dict if the raw files are not present, so callers degrade
    to "not measured" instead of to "failed".
    """
    pos = str(pos).upper().strip()
    season = int(season)
    key = (pos, season)
    if key in _CACHE:
        return _CACHE[key]
    szn = _seasons(season)
    if szn.empty:
        _CACHE[key] = {}
        return {}
    d = szn[(szn["pos"] == pos) & (szn["season"] < season)]
    if d.empty:
        _CACHE[key] = {}
        return {}
    # the most recent season he appeared in, not literally season - 1
    d = d.sort_values("season").groupby("key", as_index=False).tail(1)
    out = {}
    for r in d.itertuples():
        gm = max(int(r.games), 1)
        f = lambda v: (float(v) if pd.notna(v) else None)  # noqa: E731
        out[r.key] = {
            "p_season": int(r.season),
            "p_games": int(r.games),
            "p_ppg": f(r.ppg),
            "p_snap": f(r.snap_pct),
            "p_tgt_pg": float(r.tgt) / gm,
            "p_car_pg": float(r.car) / gm,
            "p_xfp_share": f(r.xfp_share),
            "p_car_share": f(r.car_share),
            "p_tshare": f(r.tshare),
            "p_team": (r.team if isinstance(r.team, str) else None),
        }
    _CACHE[key] = out
    return out
