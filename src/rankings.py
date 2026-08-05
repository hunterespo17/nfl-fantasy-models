"""
Season-long / draft rankings from per-game projections.

Two ideas make draft rankings smarter than "just sort by projected points":

1. VALUE OVER REPLACEMENT (VOR). A 300-point QB isn't as valuable as a
   300-point RB, because QB is deep -- you could get a nearly-as-good QB off
   waivers, but not a nearly-as-good RB. VOR measures each player against a
   "replacement" player (the best guy you could get for free at that
   position), so positions are comparable on one board.

2. TIERS. Ranks pretend player #14 and #15 are meaningfully different. Tiers
   group players of similar value, so on draft day you know when a cliff is
   coming and can plan around it.

This module takes a projection table (one row per player, with projected
points per game) and produces a ranked, tiered draft board.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config

# ---------------------------------------------------------------------------
# WHAT A WEEK HE MISSES IS ACTUALLY WORTH TO YOU
# ---------------------------------------------------------------------------
# This is the one number that decides how far a hurt player falls, and it is a
# judgement, so it lives on its own line where you can argue with it.
#
# The board's whole job is to say what a man is worth WHEN HE PLAYS. That is the
# point of the model and nothing here changes it: his points-per-game is his
# rate, healthy, full stop. The question this number answers is different -- on
# draft day, what is the season worth?
#
# Start with what is obviously true. A back down for six weeks does not score
# zero in those weeks, because you start somebody else, and this board already
# prices somebody else: he is the free agent every Over-replacement number is
# measured against. So the six weeks are worth replacement, not nothing.
#
# But they are not worth FULL replacement either, and pretending they are is how
# a man missing a third of the year moves one single spot on the board. Four
# things you don't get back:
#
#   THE ROSTER SPOT. You hold him from August to November. That bench slot spent
#   six weeks doing nothing while everyone else's was catching the waiver hit of
#   the year.
#   THE TIMING. He misses the START. Replacement level is what the free agent
#   pool averages over a season; in September you are picking from what is left
#   after eleven other people panicked, and you are doing it blind.
#   THE ONE-SIDED CALENDAR. A October target becomes November. It never becomes
#   September. Every surprise about a return date points the same way.
#   THE RAMP. He comes back on a snap count and splits the backfield for a
#   fortnight. His rate says 10.3; his first two games back are not 10.3.
#
# Two thirds is the honest split of those. Turn it DOWN toward 0 and the board
# stops trusting hurt players at all; turn it UP toward 1 and it goes back to
# treating a missed week as a free swap. It only ever touches players somebody
# has actually reported an injury on -- for the other 99 rows the term is zero,
# because 17 minus 17 is 17 minus 17.
MISSED_WEEK_VALUE = 0.65


def replacement_ranks(league: dict | None = None) -> dict[str, int]:
    """
    How many players at each position are 'startable' league-wide. The player
    just past this count defines replacement level for VOR.
    """
    league = league or config.LEAGUE
    teams = league["teams"]
    starters = league["starters"]
    flex = league.get("flex_spots", 0)

    ranks = {pos: teams * starters.get(pos, 0) for pos in config.FANTASY_POSITIONS}
    # FLEX is usually filled by RB/WR; split those spots between them.
    if "RB" in ranks:
        ranks["RB"] += teams * flex / 2
    if "WR" in ranks:
        ranks["WR"] += teams * flex / 2
    return {pos: int(round(val)) for pos, val in ranks.items()}


def _assign_tiers(values_desc: np.ndarray) -> np.ndarray:
    """
    Group a descending-sorted value array into tiers. A new tier starts when
    the drop to the next player is unusually large (> mean + 1 std of drops).
    """
    vals = np.asarray(values_desc, dtype=float)
    n = len(vals)
    if n <= 1:
        return np.ones(n, dtype=int)

    drops = -np.diff(vals)  # gap from each player to the next (positive)
    threshold = drops.mean() + drops.std()

    tiers = np.ones(n, dtype=int)
    current = 1
    for i in range(1, n):
        if drops[i - 1] > threshold:
            current += 1
        tiers[i] = current
    return tiers


def build_rankings(
    projections: pd.DataFrame,
    league: dict | None = None,
    ppg_col: str = "proj_ppg",
    games_col: str = "proj_games",
) -> pd.DataFrame:
    """
    Build a draft board from a projection table.

    `projections` must contain: player_name, position, and a projected
    points-per-game column (default 'proj_ppg'). An optional games-played
    column ('proj_games') defaults to a full season.
    """
    league = league or config.LEAGUE
    df = projections.copy()
    df = df[df["position"].isin(config.FANTASY_POSITIONS)].copy()

    full = float(league.get("games_per_season", 17))
    if games_col not in df.columns:
        df[games_col] = full
    df[games_col] = df[games_col].astype(float).fillna(full).clip(0.0, full)

    repl = replacement_ranks(league)

    # A player expected for eleven games does not score nothing in the other
    # six -- you start somebody else, and this board already prices somebody
    # else: he is the free agent every VOR number below is measured against.
    # So the weeks a hurt player misses are worth replacement, not zero.
    # Charging them at zero drops a real top-twenty back below a fullback,
    # which is correct arithmetic to the wrong question.
    #
    # Replacement is read off the PER-GAME order, never the season order, so it
    # can't depend on the very fill it's being used for. And the fill is capped
    # at the player's own rate, so missing games can never help anybody.
    fill = pd.Series(0.0, index=df.index)
    for pos, sub in df.groupby("position"):
        rates = np.sort(sub[ppg_col].astype(float).to_numpy())[::-1]
        if not len(rates):
            continue
        r = min(max(int(repl.get(pos, len(rates))), 1), len(rates))
        fill.loc[sub.index] = np.minimum(float(rates[r - 1]), sub[ppg_col].astype(float))

    df["proj_points_total"] = (df[ppg_col] * df[games_col]
                               + fill * (full - df[games_col]) * MISSED_WEEK_VALUE)

    frames = []
    for pos, sub in df.groupby("position"):
        sub = sub.sort_values("proj_points_total", ascending=False).reset_index(drop=True)
        sub["position_rank"] = np.arange(1, len(sub) + 1)

        # Replacement value = the projected points of the player at the
        # replacement rank for this position (or the last player if shallow).
        r = repl.get(pos, len(sub))
        idx = min(max(r, 1), len(sub)) - 1
        replacement_points = float(sub.loc[idx, "proj_points_total"]) if len(sub) else 0.0

        sub["vor"] = sub["proj_points_total"] - replacement_points
        sub["tier"] = _assign_tiers(sub["proj_points_total"].to_numpy())
        frames.append(sub)

    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values("vor", ascending=False).reset_index(drop=True)
    out["overall_rank"] = np.arange(1, len(out) + 1)

    preferred = [
        "overall_rank", "position", "position_rank", "tier", "player_name",
        "player_id", ppg_col, games_col, "proj_points_total", "vor",
    ]
    cols = [c for c in preferred if c in out.columns]
    # round the numeric display columns
    for c in (ppg_col, "proj_points_total", "vor"):
        if c in out.columns:
            out[c] = out[c].round(2)
    return out[cols]
