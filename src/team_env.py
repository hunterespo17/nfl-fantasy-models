"""What the betting market expects each team to score, for the site's team filter.

The board tells you what one player does. It cannot tell you whether the eleven
men you just filtered to add up to a real football team, and that is the whole
reason to look at a roster together. This module supplies the outside number to
hold them against: the points per game the betting market implies for each team
in the upcoming season.

An implied total is half the game total, moved by half the spread. A home
favourite carries a negative spread_line, so it takes half of it back:

    implied = total / 2 - sign * spread / 2       (sign: -1 at home, +1 away)

Two honest limits, both reported to the page rather than hidden in it:

  * Only the first few weeks of a season are priced this far out -- typically
    three or four games of seventeen. That is a real market view, but it is a
    market view of a specific early-season schedule, not of the whole year.
  * A team with no priced game at all gets nothing. It is left out rather than
    filled with a league-average guess, because a made-up yardstick that looks
    like a real one is worse than no yardstick.

The page prints how many games back each number so nobody mistakes a three-game
read for a season projection.
"""
from __future__ import annotations

import pandas as pd

from . import config, data

# A season is only worth pricing off if somebody actually posted a line for it.
_MIN_GAMES = 1


def implied_totals(season: int | None = None) -> dict[str, dict]:
    """Per team: the market's implied points per game, and how many games back it.

    Returns ``{"BUF": {"implied": 25.5, "n": 3, "lo": 23.0, "hi": 27.8}, ...}``.
    A team with no posted line is absent from the dict, not present with a zero.

    Never raises. The site build calls this as a nicety on top of a page that
    has to render either way, so a missing or reshaped schedule file costs you
    the comparison strip and nothing else.
    """
    season = config.UPCOMING_SEASON if season is None else season
    try:
        sched = data.get_schedules(config.SEASONS)
    except Exception:
        return {}
    if not isinstance(sched, pd.DataFrame) or sched.empty:
        return {}
    need = {"season", "home_team", "away_team", "total_line", "spread_line"}
    if not need.issubset(sched.columns):
        return {}

    up = sched[sched["season"] == season].copy()
    if up.empty:
        return {}
    up["total_line"] = pd.to_numeric(up["total_line"], errors="coerce")
    up["spread_line"] = pd.to_numeric(up["spread_line"], errors="coerce")

    # One row per team per game. sgn flips the spread's meaning for the away side.
    legs = []
    for tcol, sgn in (("home_team", -1.0), ("away_team", +1.0)):
        g = up[[tcol, "total_line", "spread_line"]].copy()
        g.columns = ["team", "total_line", "spread_line"]
        g["implied"] = g["total_line"] / 2.0 - sgn * g["spread_line"] / 2.0
        legs.append(g)
    long = pd.concat(legs, ignore_index=True).dropna(subset=["implied"])
    if long.empty:
        return {}

    out: dict[str, dict] = {}
    for team, g in long.groupby("team"):
        if len(g) < _MIN_GAMES:
            continue
        out[str(team)] = {
            "implied": round(float(g["implied"].mean()), 2),
            "n": int(len(g)),
            "lo": round(float(g["implied"].min()), 2),
            "hi": round(float(g["implied"].max()), 2),
        }
    return out


# How a real team's scoreboard relates to the touchdowns its skill players score.
# Fitted on 254 team-seasons, 2018-2025: points = SLOPE * offensive TDs/gm + BASE,
# r = +0.955. The slope lands near seven because it is a touchdown plus the extra
# point; the intercept is the kicking, defence and special-teams scoring that no
# fantasy board contains, which is why a roster of skill players can never add up
# to a Vegas total on its own.
#
# A passing touchdown and the receiving touchdown that scores it are ONE event.
# Offensive TDs are passing + rushing. Adding receiving on top double-counts
# every one of them.
TD_TO_POINTS_SLOPE = 6.76
TD_TO_POINTS_BASE = 6.43


# Backing counting stats out of fantasy points needs two rates the board does not
# carry. A back's catch rate and yards per catch turn his targets into receptions
# and receiving yards; yards per carry turns his carries into rushing yards.
# Whatever fantasy points are left over after paying for those are touchdowns.
# League medians, deliberately blunt -- they are used to SPLIT a projection that
# is already made, never to make one.
RB_CATCH_RATE = 0.75
RB_YARDS_PER_CATCH = 7.6
RB_YARDS_PER_CARRY = 4.35
QB_YARDS_PER_CARRY = 5.20


def for_site(season: int | None = None) -> dict:
    """The whole block the page needs, in one JSON-safe dict.

    The scoring settings travel with it rather than being written into the
    page's script, so a league that changes its scoring gets a team strip that
    changes with it instead of one quietly still doing half-PPR arithmetic.
    """
    return {
        "season": config.UPCOMING_SEASON if season is None else season,
        "implied": implied_totals(season),
        "slope": TD_TO_POINTS_SLOPE,
        "base": TD_TO_POINTS_BASE,
        "scoring": {k: float(v) for k, v in dict(config.SCORING).items()
                    if isinstance(v, (int, float))},
        "rates": {
            "rb_catch_rate": RB_CATCH_RATE,
            "rb_ypc_rec": RB_YARDS_PER_CATCH,
            "rb_ypc": RB_YARDS_PER_CARRY,
            "qb_ypc": QB_YARDS_PER_CARRY,
        },
        "games": int(config.LEAGUE.get("games_per_season", 17)),
    }
