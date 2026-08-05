"""
Who do we actually expect to be on the field?

Every factor in every position model describes a player's JOB -- how big it is,
how good he is at it, how good his team is around him. None of that knows whether
he is healthy enough to hold the job in week one, and for a long time this board
simply assumed everybody played all seventeen. That assumption is the reason it
had Zach Charbonnet at RB16 in August 2026 while the market had him RB42: the
model could see he was Seattle's listed starter and could not see the knee.

This module is the one place that gap gets filled, and it is shared by every
position so a quarterback and a running back are treated the same way.

There are two separate questions here, and keeping them apart is the whole point
of the file.

FIRST: how many games does a player like this normally play? That is base_games()
below, and it applies to everybody whether or not anyone has reported anything.
"Everybody plays seventeen" was the single worst assumption in this model. Tested
on seasons the fit never saw, it misses a back's real games count by 5.6 and a
quarterback's by 7.9. Three seasons of games played plus the size of last year's
job cuts that to 3.9 and 3.4. It is not a precise number and it is not supposed
to be; it is a very cheap way to stop crediting a fourth stringer with a full
season he has never once played, without writing off a starter who got hurt once.

SECOND: has anyone said something specific about THIS player THIS year? That is
the news path, and it comes from two sources, in priority order:

  1. data/<pos>_availability.csv -- yours. Hand-typed, deliberately tiny, and it
     always wins. It is where you put a report the published guide hasn't caught
     up with.
  2. data/clay_<pos>_<season>.csv -- the outside guide, written once a year by
     scripts/import_clay.py. Its games column is the only forward-looking health
     information in the model that doesn't come from you.

News REPLACES the baseline rather than discounting it. If you type 11, he is
priced at 11 -- not at 11/17ths of what a back like him usually plays, which
would quietly punish him twice. Both files are optional; missing files are not an
error, and without them everyone simply gets the baseline.

Two things this module deliberately does NOT do.

It does not touch a completed season. Only rows for the upcoming season move off
a full slate, so nothing a 2026 guide says can leak backwards into a backtest
scored on 2019 information.

And it does not use the guide's games column below GUIDE_FLOOR. That column
answers two different questions with one number -- "hurt, will miss time" and
"third on the depth chart, will get mop-up work" -- and only the first is news.
The second is a job description, already priced through Role and depth-chart
share, and taking it again here would charge a backup twice for being a backup.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config

# Below this, a guide's games number is a depth-chart statement rather than an
# injury report, and is ignored. Anything hand-typed is always taken.
GUIDE_FLOOR = 8.0

# How many games a player plays next year, from two things: how available he has
# been over his last THREE seasons, and how big a job he had last year.
#
#     games_next = intercept + a * (games a season over his last 3 / 17)
#                            + b * (job size)
#
# where job size is 0 to 1 -- a back's carries per game over 18, a quarterback's
# throws per game over 32. Fitted on 2019-2023 and checked on 2024-2025, which
# the fit never saw, over players already carrying the career games each board
# requires (6 for backs, 8 for passers). Average games missed:
#
#                                  backs   quarterbacks
#     3 years of games + job        3.92       3.38     <- shipped
#     last year's games + job       3.97       3.67
#     last year's games alone       4.11       3.72
#     one flat average              4.82       5.15
#     "everybody plays 17"          5.56       7.89
#
# Reading three seasons instead of one is the whole ballgame at quarterback, and
# it is there to stop the model doing something plainly unfair. One season is a
# very small sample to judge a body on. Read only the most recent one and a
# quarterback who started 17 games twice and then broke a toe is filed next to a
# man who has never been healthy -- they both "played 9 games last year." Among
# passers who played 11 or fewer, the ones with a strong three-year record came
# back for 10.8 games; the ones without came back for 5.1.
#
# The job-size term fixes a second confusion. "Played 11 games" describes both a
# starter who missed six weeks hurt and a backup who got six weeks of mop-up
# duty. Among backs who played 11 or fewer, the ones carrying a real load when
# active came back for 11.1 games; the ones who were never more than a backup
# came back for 7.9. Without it everyone in that bucket gets the same number and
# the hurt starter eats the backup's discount.
#
# Two more things worth noticing. A full season last year does NOT predict a full
# season this year -- it predicts about 14.7 for a workhorse back and the same
# for a starting quarterback, because almost nobody repeats it (11.7% of backs,
# 12.5% of passers). And the two positions land in nearly the same place at the
# top, which is what keeps a back's season total honestly comparable to a
# passer's on the combined board.
#
#                  intercept  3yr avail   job
BASE_FIT = {"RB": (3.66, 8.80, 2.77),
            "QB": (0.56, 13.08, 1.18)}
BASE_DEFAULT = (3.66, 8.80, 2.77)
BASE_MIN, BASE_MAX = 4.0, 17.0

# A rookie has no games played, so the line above has nothing to read. Feeding it
# a zero would price every first-year player as a career backup, which is exactly
# backwards -- measured over 2019-2025, a rookie who actually got a job played
# MORE than a veteran coming off a full season:
#
#     rookie backs with 50+ carries       n=79   13.8 games   (median 15)
#     rookie passers with 100+ attempts   n=44   10.8 games   (median 10)
#
# which makes sense. They are the freshest bodies in the league, and the reason
# they got the job in the first place is usually that they were available for it.
# Rookies with no job average far less (8.2 and 6.3), but those are camp bodies
# whose per-game rate already buries them; crediting them a starter's slate
# doesn't move them. The sharper version of this reads a rookie's depth-chart
# slot instead of using one number for all of them -- worth doing, not done yet.
ROOKIE_GAMES = {"RB": 13.5, "QB": 10.5}
ROOKIE_DEFAULT = 13.5

_HAND: dict[str, dict] = {}
_GUIDE: dict[str, dict] = {}


def base_games(avail3, pos: str = "RB", job=None) -> float:
    """Games a player like this normally plays, before anybody reports anything.

    `avail3` is games a season over his last three, divided by 17. `job` is how
    big last season's workload was, 0 to 1. A missing `avail3` means no NFL
    season behind him at all -- see ROOKIE_GAMES.
    """
    pos = str(pos).upper()
    if avail3 is None or pd.isna(avail3):
        return float(ROOKIE_GAMES.get(pos, ROOKIE_DEFAULT))
    b0, b1, b2 = BASE_FIT.get(pos, BASE_DEFAULT)
    j = 0.0 if job is None or pd.isna(job) else float(np.clip(job, 0.0, 1.0))
    return float(np.clip(b0 + b1 * np.clip(float(avail3), 0.0, 1.0) + b2 * j,
                         BASE_MIN, BASE_MAX))


def clear_cache() -> None:
    """Forget both files. Only needed by tests and weight sweeps."""
    _HAND.clear()
    _GUIDE.clear()


def hand_notes(pos: str) -> dict:
    """{normalized name: (games, note)} from data/<pos>_availability.csv."""
    pos = str(pos).lower()
    if pos in _HAND:
        return _HAND[pos]
    out: dict = {}
    _HAND[pos] = out
    try:
        path = config.DATA_DIR / f"{pos}_availability.csv"
        if not path.exists():
            return out
        from .adp import norm

        df = pd.read_csv(path, comment="#")
        if "player" not in df.columns or "expected_games" not in df.columns:
            return out
        gms = pd.to_numeric(df["expected_games"], errors="coerce")
        notes = (df["note"] if "note" in df.columns
                 else pd.Series([""] * len(df), index=df.index))
        for name, g, note in zip(df["player"], gms, notes):
            if pd.isna(g) or not str(name).strip():
                continue
            out[norm(str(name))] = (float(np.clip(g, 0.0, 17.0)),
                                    "" if pd.isna(note) else str(note).strip())
    except Exception:      # noqa: BLE001 -- an outside file must never fail a build
        pass
    return out


def guide_ranks(pos: str) -> dict:
    """{player_id: {"rank": float, "games": float}} from the guide CSV."""
    pos = str(pos).lower()
    if pos in _GUIDE:
        return _GUIDE[pos]
    out: dict = {}
    _GUIDE[pos] = out
    try:
        path = config.DATA_DIR / f"clay_{pos}_{config.UPCOMING_SEASON}.csv"
        if not path.exists():
            return out
        df = pd.read_csv(path)
        if not {"player_id", "clay_rank", "clay_games"}.issubset(df.columns):
            return out
        for row in df.to_dict("records"):
            out[str(row["player_id"])] = {"rank": float(row["clay_rank"]),
                                          "games": float(row["clay_games"])}
    except Exception:      # noqa: BLE001
        pass
    return out


def ratio(expected: float | None, news_w: float, floor: float) -> float:
    """Turn "we think he plays N games" into a multiplier on his season value.

    news_w is 1.0 everywhere today, i.e. the number goes in at face value. The
    dial survives because it is the honest place to turn a source down if one
    ever earns it -- see the long note above NEWS_W in rb_blend.py for why
    hedging a stated games count is the wrong instinct.
    """
    if expected is None or pd.isna(expected):
        return 1.0
    return float(np.clip(1.0 - news_w * (1.0 - float(expected) / 17.0), floor, 1.0))


def resolve(pos: str, player_id, name: str, is_upcoming: bool,
            news_w: float, floor: float) -> dict:
    """One player's availability: guide rank, expected games, ratio, and why."""
    from .adp import norm

    g = guide_ranks(pos).get(str(player_id)) if is_upcoming else None
    out = {"clay_rank": g["rank"] if g else np.nan,
           "clay_games": g["games"] if g else np.nan,
           "news_games": np.nan, "games_ratio": 1.0, "games_note": ""}
    if not is_upcoming:
        return out

    exp, why = np.nan, ""
    mine = hand_notes(pos).get(norm(str(name)))
    if mine is not None:                                  # yours beats the guide
        exp, why = mine[0], mine[1]
    elif g is not None and GUIDE_FLOOR <= g["games"] < 17:
        exp = g["games"]
        why = f"the guide has him down for {int(round(exp))} games"

    r = ratio(exp, news_w, floor)
    out["news_games"] = exp
    out["games_ratio"] = r
    out["games_note"] = "" if r >= 1.0 else why           # a full slate isn't news
    return out


def attach(p: pd.DataFrame, pos: str, news_w: float = 1.0,
           floor: float = 0.35) -> pd.DataFrame:
    """Add clay_rank / clay_games / games_ratio / games_note / proj_games.

    Two columns come out of here and they do different jobs, which is worth being
    precise about because mixing them up double-counts a player's health.

    `games_ratio` is NEWS ONLY -- 1.0 for everyone nobody has reported anything
    about. It is what the Availability index multiplies by, and that index already
    has last season's games in it, so putting the baseline here too would charge a
    player twice for the same missed time.

    `proj_games` is how many games the board expects, and it is the one that turns
    a per-game rate into a season. Baseline for everybody, replaced outright by a
    reported number when there is one. Completed seasons keep a full slate so the
    backtest still scores this model on the information it always had.
    """
    if p.empty:
        return p
    up = pd.to_numeric(p["season"], errors="coerce") == config.UPCOMING_SEASON
    rows = [resolve(pos, pid, nm, bool(u), news_w, floor)
            for pid, nm, u in zip(p["player_id"], p["player_name"], up)]
    for col, typ in (("clay_rank", float), ("clay_games", float),
                     ("news_games", float), ("games_ratio", float),
                     ("games_note", object)):
        p[col] = pd.Series([r[col] for r in rows], index=p.index, dtype=typ)

    # Three seasons of availability, not one. `durability` is last year only and
    # is left alone deliberately -- it does a different job in the Availability
    # index, where recency is the point.
    if "prev_games3" in p.columns:
        av3 = pd.to_numeric(p["prev_games3"], errors="coerce") / 17.0
    elif "durability" in p.columns:
        av3 = pd.to_numeric(p["durability"], errors="coerce")
    else:
        av3 = pd.Series(np.nan, index=p.index)
    job = (p["prev_role"] if "prev_role" in p.columns
           else pd.Series(np.nan, index=p.index))
    base = [base_games(d, pos, j) for d, j in zip(av3, job)]
    p["proj_games"] = [
        17.0 if not u else (float(np.clip(n, 0.0, 17.0)) if pd.notna(n) else b)
        for u, n, b in zip(up, p["news_games"], base)
    ]
    return p
