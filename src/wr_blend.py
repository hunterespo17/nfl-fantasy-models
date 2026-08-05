"""
WIDE RECEIVER PROJECTIONS -- the same machine as the backs, aimed at a different job.

Read src/rb_blend.py first. The shape here is deliberately identical -- season
aggregates, entering profiles, percentile indices, a weighted composite, a
calibration curve fitted to what receivers actually scored -- so that everything
downstream (ratings, report, the site) needs no new plumbing. What follows is
only the places where a receiver is not a running back, and why.

WHAT IS DIFFERENT, AND WHY
--------------------------

VOLUME IS THE WHOLE ARGUMENT, AND IT IS A DIFFERENT VOLUME. A back's opportunity
is touches. A receiver's is targets, and targets are not his to take -- they are
allocated by somebody else, from a pool the offence decides the size of. So the
two numbers that matter are his SHARE of that pool and the pool's SIZE, and they
have to be carried separately. Measured on 998 receiver seasons 2018-2025,
target share correlates 0.64 with next season's points per game and repeats at
0.74 year to year; targets per game 0.66 and 0.73. Nothing else on the position
is close on both axes at once.

EFFICIENCY GETS MODERATE WEIGHT AND NOT A GRAM MORE. This is the biggest
judgement call in the model and it is knowingly against the fashionable view.
Yards per route run correlates 0.56 with next year and repeats at only 0.55;
first downs per route run 0.55 and 0.57. Both are real. Both are beaten by
simply counting targets. Efficiency is how you separate two receivers with the
same job, not how you find out who has the job.

ROUTES ARE ESTIMATED, NOT COUNTED. Routes run is not in free nflverse data, so
every per-route rate here divides by `offense_pct x team dropbacks`. Two things
make that safe rather than sloppy: it validated at 99.2% coverage against the
weekly file, and every rate divides by the SAME estimate, so swapping in a real
routes column later is a one-line change and nothing downstream moves. The one
trap is the denominator itself -- pbp's `pass` column is already 1 on every
sack, so dropbacks are `sum(pass)`, NOT `pass + sack`. Counting sacks twice
makes every route estimate 6% generous and every efficiency rate 6% harsh.

TOUCHDOWNS ARE THROWN AWAY AND REBUILT. A receiver's TD count correlates 0.556
with next season's; his receiving YARDS correlate 0.585 -- volume predicts a
man's touchdowns better than his touchdowns do. So the count is pulled hard
toward a yards-based expectation (K_TD 18, against the backs' 10: a full season
keeps under half its own scores) and the gap between the two is published, so a
14-touchdown year reads as the warning it is rather than as evidence.

THE WINDOW IS A SLOPE, NOT A CLIFF. Backs fall off a table; receivers walk down
a ramp. Change in points per game entering each season: year two +0.6, year
three +0.6, year four -0.1, year five -0.1, year six -1.4, year seven and later
-0.8 to -1.6. So WINDOW_SCORES is flatter than the running-back version at both
ends, and a proven receiver in year six is docked, not written off.

VEGAS MATTERS MORE HERE THAN IT DOES AT RUNNING BACK. Season-long, a team's
implied total correlates +0.62 with what its receivers score and only +0.34 with
what its backs score; forward-looking on the early lines the model actually
uses, +0.41 against +0.25. The backs' board carries Vegas at 10. This one
carries it at 14.

NO SPREAD FACTOR. The spread is already inside the model -- implied total IS
(total line + spread) / 2. Adding spread on top moves R-squared 0.0273 to 0.0284
and the leftover coefficient comes out negative, which is double-counting with
extra steps. Game script turns out not to be a volume story anyway: receiver
targets go 7.2 to 6.9 between good and bad script. What moves is scoring, so
script belongs inside the touchdown expectation, which is where it is.

THE CEILING SHIPS ON DAY ONE. The projection scale is a percentile map, so an
uncapped fourth receiver is handed the same seven points a game as a starter's
floor and a team's receiving room sums to more points than any real offence
produces. Fitted the same way as the backs' -- see CEIL_SLOPE.

NO DEPTH-CHART HISTORY, AND IT TURNS OUT NOT TO MATTER. data.get_depth_history()
is running-back only. Rather than fake one, historical role is read off MEASURED
route share, which exists for every season and is the thing a depth chart is
trying to guess anyway. Only the upcoming season uses a published depth chart,
because for the upcoming season there is nothing measured to use instead.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from . import availability, calibration, config, rankings, scoring  # noqa: F401

# ---------------------------------------------------------------------------
# CONSTANTS -- every one of these is a decision, so each says what it decides
# ---------------------------------------------------------------------------

# How hard a touchdown count is pulled toward what his yardage says it should
# have been. Measured on 864 back-to-back receiver seasons: blending at K=18
# predicts next year's touchdowns at 0.601, against 0.556 for the raw count and
# 0.585 for the yards expectation alone. The curve is flat from 18 to 40, so
# this is the gentlest setting that gets the full benefit. A 16-game season
# keeps 47% of its own scores. The backs use 10 -- receivers get regressed
# harder because a receiver's touchdowns are a smaller sample of a noisier
# event, and the plan is explicit that the count has to be rebuilt, not trimmed.
K_TD = 18.0

# How much career length is worth against one season's rate, in the talent
# blend. Same as the backs: a receiver with 60 career games is trusted on his
# own numbers, one with 12 is mostly told what his job implies.
K_CAREER = 10.0

# What counts as a season worth learning from. Receivers miss fewer games than
# backs, so this goes back up to the honest twelve rather than the backs' ten.
HEALTHY_GAMES = 12

# How many seasons back the model will look. Four, same as the backs -- a fifth
# year of a receiver's twenties is a different player.
RECENCY = 4

# Games before a career record outweighs what the job implies.
MIN_CAREER_GAMES = 6
MIN_CAL_ROWS = calibration.MIN_ROWS

# ---------------------------------------------------------------------------
# THE WORKLOAD CEILING
# ---------------------------------------------------------------------------
# Measured on 1,533 receiver seasons 2018-2025 with 4+ games. Half-PPR points
# per target has a 99th-percentile envelope that flattens out for any real
# workload -- 2.08 at six-to-eight targets a game, 2.06 at eight-to-ten, 1.99
# above ten -- so a straight line through it caps nobody who matters.
#
# Candidates, and what share of real receiver seasons finished above each:
#
#     1.0 + 1.75 x targets    5.3% of all seasons, 5.5% of 3+ target seasons
#     1.0 + 1.85 x targets    3.4%   2.7%
#     1.0 + 1.90 x targets    2.8%   1.9%   <- this
#     1.0 + 2.00 x targets    2.2%   1.3%
#     1.0 + 2.10 x targets    1.5%   0.6%
#
# 1.90 is where it stops binding on anybody the board will ever project and
# starts binding hard on the bottom of it. At 1.5 targets a game it allows 3.8
# points; real receivers at that workload have a 95th percentile of 3.6. At ten
# targets a game it allows 20.0, and the best receiver season in eight years was
# 20.0. The 43 seasons it clips are Davante Adams 2020, Tyreek Hill 2020 and
# Deebo Samuel 2021 -- historic touchdown years nobody should be projecting.
#
# Anything this clips MUST be published on the row and re-applied in the page's
# JavaScript, because the reader recomputes every projection on every slider
# drag. See _assemble(), and `capped()` in src/report.py.
CEIL_BASE = 1.0
CEIL_SLOPE = 1.90

# ---------------------------------------------------------------------------
# WHAT A DEPTH-CHART SLOT IS ACTUALLY WORTH
# ---------------------------------------------------------------------------
# Mean route share by receiver rank within team-season, on 1,451 seasons of
# measured snap data 2018-2025. Unlike the backs' SLOT_SHARE these do not sum to
# one, because they are not shares of a fixed pool -- each is that receiver's
# own share of his team's dropbacks, which is what a route share is.
#
#   rank      n    mean    median    p25     p75    mean ppg
#   WR1     256    0.840   0.851    0.785   0.898     11.2
#   WR2     256    0.746   0.753    0.689   0.807      8.7
#   WR3     256    0.606   0.606    0.532   0.682      6.4
#   WR4     255    0.405   0.416    0.318   0.488      3.9
#   WR5     243    0.260   0.254    0.164   0.357      2.4
#   WR6     185    0.172   0.164    0.080   0.247      1.5
SLOT_ROUTE = {1: 0.840, 2: 0.746, 3: 0.606, 4: 0.405, 5: 0.260, 6: 0.172}

# Mean TEAM target share at each rank, from the same rows. This is what Role
# converts into an expected volume when a player has no measured season to read.
SLOT_TGT_SHARE = {1: 0.233, 2: 0.182, 3: 0.140, 4: 0.088, 5: 0.057, 6: 0.039}

# HOW MUCH OF THE SPOT COMES FROM LAST SEASON RATHER THAN THE PUBLISHED CHART.
# Entering a season there are two readings of where a receiver sits: where he
# actually ranked in routes last year, and where his team lists him in August.
# Neither is right on its own. The tape is a measurement, but it is a
# measurement of LAST year's team, and of however healthy he happened to be --
# a number one who missed six weeks on a bad ankle ranks like a number two
# without having lost the job. The chart is this year's information, including
# every trade and signing, but it is still somebody's guess made in shorts.
#
# So the spot is a weighted average of the two, and the weight is how much the
# tape deserves to be believed:
#
#   played 17 last year, same team   0.75 on the tape   -- we watched it
#   played 13                        0.53               -- half a story
#   played 9 or fewer                0.30               -- mostly the chart
#   changed teams                    0.15               -- wrong room entirely
#
# A finished season has no published chart, so none of this touches history or
# the backtest -- there, the measured rank is still the whole answer.
TAPE_W_MAX, TAPE_W_MIN = 0.75, 0.30
TAPE_GAMES_HI, TAPE_GAMES_LO = 17.0, 9.0
TAPE_W_MOVED = 0.15

# ---------------------------------------------------------------------------
# THE TWO SCREENS FROM HEATH'S RESEARCH
# ---------------------------------------------------------------------------
# THE ROUTE GATE. 88% of receivers who went on to score 12+ points a game had
# cleared 75% route share the year before. On 912 back-to-back pairs, clearing
# it was worth 9.9 points a game next season against 4.8, and 31.4% reached 12+
# against 4.8%. That is not a slider, it is a gate -- so it is published as a
# flag and left for the reader to filter on rather than folded into a weight.
ROUTE_GATE = 0.75

# THE FIRST-DOWN BADGE. First downs per route run, on a real sample of routes.
#
# Heath states this one at 0.115, and 0.115 is NOT the number here, which needs
# saying out loud. His routes are charted; ours are estimated -- snap share times
# team dropbacks -- and the two denominators are not the same size, so his
# constant does not survive the trip. Measured on ours, 0.115 flags 21 receiver
# seasons out of 855: a needle, not a screen, and a needle that separates WORSE
# than a looser bar because it has stopped describing a population.
#
# So the number is re-fitted and his idea kept. Across 855 seasons with 250+
# estimated routes, sorted by what the receiver did the FOLLOWING year:
#
#     0.080  ->  203 flagged, 11.2 ppg next season vs 5.6, 44% reach 12+
#     0.095  ->   87 flagged, 12.2 ppg next season vs 6.3, 58% reach 12+
#     0.100  ->   59 flagged, 12.5 ppg next season vs 6.5, 59% reach 12+
#     0.115  ->   21 flagged, 12.4 ppg next season vs 6.8, 52% reach 12+
#
# 0.095 is the last threshold that is still a screen -- roughly the top tenth of
# receivers, the widest gap on the table, and a filter that returns a dozen names
# on a 128-man board instead of three.
#
# It is a BADGE, not a factor, and deliberately so: the edge concentrates almost
# entirely at the top of the board (+2.1 points for receivers already scoring
# 13+, +1.5 in the 10-13 band, +0.8 in the 7-10 band), so weighting the whole
# board on it would be reading a top-of-market signal into the middle rounds.
FD_RR_BADGE = 0.095
FD_RR_MIN_ROUTES = 250

# ---------------------------------------------------------------------------
# CROWDED ROOMS
# ---------------------------------------------------------------------------
# Named, not modelled, and honestly labelled as such. Heath's claim is that
# crowded receiver rooms suppress everyone in them; I could not reproduce it. My
# own teammate test -- how a receiver does with one, two or three team-mates
# above 60% route share -- came out 8.5, 8.9 and 7.7 points a game, which is no
# effect at all. His claim is about ADP, not production: crowded rooms are
# priced as though somebody must lose, and that is a market observation worth
# showing rather than a projection input worth applying. So these five 2026
# offences get a flag on the row and nothing is deducted anywhere.
CROWDED_TEAMS = {"CIN", "LA", "LAR", "DET", "DAL", "CHI"}

# ---------------------------------------------------------------------------
# THE CAREER WINDOW
# ---------------------------------------------------------------------------
# Change in points per game entering each season, measured on 614 back-to-back
# pairs: year 2 +0.6, year 3 +0.6, year 4 -0.1, year 5 -0.1, year 6 -1.4, year 7
# and later -0.8 to -1.6. A ramp up, a plateau, and a slow walk down -- compare
# the backs, who go 90/100/95/85/55 and then fall off the end of the table.
WINDOW_SCORES = {1: 78.0, 2: 100.0, 3: 100.0, 4: 92.0, 5: 84.0}
WINDOW_LATE = 58.0        # year six and beyond, no elite season behind him
WINDOW_PROVEN = 72.0      # same, but he has actually been a WR16 -- docked, not written off

# What counts as having proved it. The board's replacement level is WR30-36, so
# "elite" has to sit meaningfully inside that: top 16 in a season, on a real
# sample of games.
ELITE_RANK = 16
ELITE_MIN_GAMES = 8

# ---------------------------------------------------------------------------
# DRAFT CAPITAL
# ---------------------------------------------------------------------------
# Next-season points per game by round: R1 9.9, R2 8.7, R3 9.7, R4 7.0, R5 6.3.
# A LEVEL indicator only -- year-over-year change is flat across every round, so
# capital tells you where a receiver starts and nothing about where he is going.
# The R3 number above R2 is 30 rows of noise, so the scale below is smoothed
# monotonic rather than fitted to it.
#
# It fades out over three seasons, because after three years of real snaps the
# snaps are the better evidence and the draft slot is just a fact about 2023.
DRAFT_SCORE = {1: 100.0, 2: 82.0, 3: 78.0, 4: 52.0, 5: 40.0, 6: 32.0, 7: 28.0}
DRAFT_UNDRAFTED = 22.0
DRAFT_FADE_SEASONS = 3.0

# The most of the Talent factor draft capital is ever allowed to be. It used to
# be all of it in year one, which meant a rookie's own projection did not touch
# his Talent score at all.
DRAFT_MAX_W = 0.6

# How much of Volume comes from the job the depth chart implies rather than the
# targets he actually got. A shade higher than the backs' 0.25 because receiver
# roles carry over more cleanly than backfield splits do.
VOL_ROLE_W = 0.30

# Within Volume, how the two best predictors split. Target share (0.64 next-year,
# 0.74 sticky) and targets per game (0.66, 0.73) are close enough to even that
# splitting them evenly is the honest answer.
TS_VOL_W = 0.5

# Within Efficiency, how first downs per route split against yards per route.
# First downs are the better stability bet (0.57 against 0.55) and the one Heath
# built his screen on, so they lead slightly.
FD_EFF_W = 0.55

# How many finished seasons the upcoming one is measured against. Every factor
# on this board is a rank inside its own season, and the upcoming season is a
# shorter list than a finished one -- about 130 receivers off a depth chart
# against 180 to 200 who actually played. A shorter list has a lower ceiling:
# eighth of 129 can only reach the 94.6th percentile, eighth of 190 reaches the
# 96.3rd. That is roughly two points of composite surrendered on every factor
# at once, for no reason but the length of the list, and the points scale is
# steep at the top -- it came out as about two points a game missing from the
# whole upper board. So the upcoming season is not ranked against itself. Each
# of its raw numbers is placed into the last three finished seasons one at a
# time and the three placements averaged, which is drift-proof and puts the
# answer on exactly the scale the points curve was fitted on.
REF_SEASONS = 3

NEWS_W = 1.0
MIN_GAMES_RATIO = 0.35
GUIDE_GAMES_FLOOR = availability.GUIDE_FLOOR

# How much of a rookie's row may lean on somebody else's projection.
#
# This is the shrink weight a rookie gets in place of the career-games curve,
# and 0.5 was too little. A veteran needs ten career games to earn 0.5, so a
# rookie was being told his whole projected season counts for as much as ten
# games of somebody else's snaps. It is also a second regression: the Clay row
# is already a smoothed full-season expectation -- _clay_bundle deliberately
# does not regress it on the way in, and then this pulled it halfway to the pool
# floor anyway. 0.7 leaves real uncertainty on a player nobody has watched take
# an NFL snap without flattening the eighteen of them onto one number.
ROOKIE_TRUST = 0.7

# ---------------------------------------------------------------------------
# WHAT THE PLAYER PANEL SHOWS
# ---------------------------------------------------------------------------
# Raw column -> the label a human reads. Adding a key here surfaces that column
# on the detail panel; it does not put it in the model. Several of these are
# here precisely BECAUSE they are not in the model -- yards per catch (0.13
# against next season), yards after catch per catch (0.10) and average depth of
# target (0.01) are the three numbers receivers get argued about with, and
# showing them next to the ones that actually predict is the fastest way to see
# why the board disagrees with the argument.
SIGNALS = {
    "target_share": "Target share",
    "targets_pg": "Targets / game",
    "wopr": "WOPR (targets + air yards)",
    "air_yards_share": "Air yards share",
    "route_share": "Route share",
    "est_routes": "Routes (estimated)",
    "yprr": "Yards / route run",
    "fd_rr": "1st downs / route run",
    "rec_pg": "Catches / game",
    "rec_yds_pg": "Receiving yards / game",
    "ypc": "Yards / catch",
    "yac_pc": "Yards after catch / catch",
    "adot": "Average depth of target",
    "td": "Touchdowns scored",
    "exp_td": "Touchdowns his volume implies",
    "td_gap": "Touchdown luck (scored minus implied)",
    "ts_trend": "Target share, last year vs the one before",
    "route_trend": "Route share, last year vs the one before",
    "snap_pct": "Snap share",
    "career_games": "Career games",
}

# ---------------------------------------------------------------------------
# THE WEIGHTS
# ---------------------------------------------------------------------------
# Volume, Opportunity and Role are 44 of the 100 between them, which is the
# plan's central claim made arithmetic: at this position the job is most of the
# answer. Efficiency at 11 is "moderate" as promised -- enough to separate two
# receivers with the same job, not enough to invent one.
#
# Vegas at 14 is the one number lifted straight from the research rather than
# from taste. The backs' board has it at 10; a team's implied total correlates
# nearly twice as strongly with its receivers' scoring as with its backs'.
DEFAULT_WEIGHTS = {
    "Volume": 19,        # target share + targets per game
    "Opportunity": 15,   # WOPR -- target share plus air yards share
    "Vegas": 14,         # implied team total + win total
    "Efficiency": 11,    # first downs per route + yards per route
    "Role": 10,          # route share, and what the depth chart implies
    "Talent": 9,         # career rate, shrunk toward the job; draft capital when young
    "Availability": 8,   # age curve x durability
    "Window": 6,         # year in league
    "Scoring": 4,        # touchdowns, regressed to a volume expectation
    "Situation": 4,      # pace and how much the offence throws
    "Matchup": 0,        # off by default, same as the other two boards
}
GROUPS = list(DEFAULT_WEIGHTS.keys())

from .qb_blend import (  # noqa: E402
    _birth_map,
    _first,
    _num,
    _numf,
    _pct_of,
    implied_totals,
    playcallers,
    win_totals,
)

__all__ = [
    "DEFAULT_WEIGHTS",
    "GROUPS",
    "SIGNALS",
    "SLOT_ROUTE",
    "SLOT_TGT_SHARE",
    "WINDOW_SCORES",
    "ROUTE_GATE",
    "FD_RR_BADGE",
    "CROWDED_TEAMS",
    "season_aggregates",
    "entering_profiles",
    "attach_role_window",
    "add_indices",
    "composite",
    "calibrate",
    "backtest",
    "run",
    "run_upcoming",
    "build_upcoming",
    "team_dropbacks",
    "win_totals",
    "implied_totals",
    "playcallers",
]

# Anything the build wants to warn about but that must never stop a build.
WARNINGS: list[str] = []


def _warn(msg: str) -> None:
    WARNINGS.append(msg)


def _age_curve(age) -> float:
    """Receivers hold their value later than backs do.

    The backs' curve starts docking at 26 and loses 9 points a year. Receivers
    peak later and decline more slowly -- the window research puts real decline
    at year six, which for a first-round receiver is age 27-28 -- so this one is
    flat through 27 and falls at 6 points a year after.
    """
    if age is None or (isinstance(age, float) and np.isnan(age)):
        return 0.85
    a = float(age)
    if a < 22:
        return 0.95
    if a <= 27:
        return 1.0
    return max(0.40, 1.0 - (a - 27) * 0.06)


# ---------------------------------------------------------------------------
# name matching
# ---------------------------------------------------------------------------
_SUFFIX = re.compile(r"\s+(jr|sr|ii|iii|iv|v)$")


def _full_key(s: pd.Series) -> pd.Series:
    """Normalised full name. The primary key -- exact, no guessing."""
    return (s.astype(str).str.lower()
            .str.replace(r"[.']", "", regex=True)
            .str.replace("-", " ", regex=False)
            .str.replace(_SUFFIX, "", regex=True)
            .str.replace(r"\s+", " ", regex=True).str.strip())


def _short_key(full: pd.Series) -> pd.Series:
    """First initial plus surname. The fallback, and only where it is unique."""
    parts = full.str.split()
    return parts.str[0].str[0].fillna("") + " " + parts.str[-1].fillna("")


# ---------------------------------------------------------------------------
# Mike Clay's projections -- a directional sense-check, never the whole row
# ---------------------------------------------------------------------------
_CLAY: dict | None = None


def clay_projections() -> dict:
    """player_id -> Clay's 2026 line, if the export is there. Never required."""
    global _CLAY
    if _CLAY is not None:
        return _CLAY
    _CLAY = {}
    try:
        path = config.DATA_DIR / f"clay_wr_{config.UPCOMING_SEASON}.csv"
        if not path.exists():
            return _CLAY
        c = pd.read_csv(path)
        if not {"player_id", "clay_rank", "clay_games"}.issubset(c.columns):
            return _CLAY
        c = c[c["player_id"].notna()].copy()
        for col in ("clay_rank", "clay_games", "targets", "rec", "rec_yds",
                    "rec_td", "carries", "rush_yds", "rush_td", "clay_ppr",
                    "clay_target_share"):
            if col in c.columns:
                c[col] = pd.to_numeric(c[col], errors="coerce")
            else:
                c[col] = np.nan
        # His own target share where he published one; otherwise back one out of
        # the team's projected targets, so every row carries the same field.
        if "team" in c.columns:
            tm = c.groupby("team")["targets"].transform("sum")
            backed = c["targets"] / tm.replace(0, np.nan)
            c["clay_target_share"] = c["clay_target_share"].fillna(backed)
        _CLAY = {str(r["player_id"]): r for _, r in c.iterrows()}
    except Exception:  # noqa: BLE001
        # A missing or malformed Clay file costs the board its rookies. It must
        # never cost the board its build.
        _CLAY = {}
    return _CLAY


def expected_games() -> dict:
    return availability.hand_notes("WR")


def _clay_bundle(c, ppr: float = 0.5) -> dict | None:
    """Turn one Clay row into the same bundle a measured season produces.

    For rookies and for anyone with no NFL history, this is the only row there
    is. Everything it can honestly fill, it fills; everything it cannot -- snap
    share, route share, career games -- comes back NaN rather than zero, so the
    percentile map skips him instead of ranking him last.
    """
    if c is None:
        return None
    g = float(c.get("clay_games") or 0)
    if g <= 0:
        return None

    rec = float(c.get("rec") or 0)
    tgt = float(c.get("targets") or 0)
    ryd = float(c.get("rec_yds") or 0)
    rtd = float(c.get("rec_td") or 0)
    car = float(c.get("carries") or 0)
    rud = float(c.get("rush_yds") or 0)
    utd = float(c.get("rush_td") or 0)

    # Deliberately NOT regressed. A projection is already somebody's smoothed
    # expectation; regressing it again pulls the same number to the mean twice.
    rec_pg = (ryd * 0.1 + rec * ppr + rtd * 6.0) / g
    rush_pg = (rud * 0.1 + utd * 6.0) / g

    ts = c.get("clay_target_share")
    ts = float(ts) if ts is not None and not pd.isna(ts) else np.nan

    return {
        "talent_reg": rec_pg + rush_pg,
        "rec_val": rec_pg,
        "rush_val": rush_pg,
        "targets_pg": tgt / g,
        "rec_pg": rec / g,
        "rec_yds_pg": ryd / g,
        "target_share": ts,
        # Air yards, routes and snaps are not in the projection, and a guessed
        # WOPR would be a made-up number wearing a measured number's name.
        "wopr": np.nan,
        "air_yards_share": np.nan,
        "route_share": np.nan,
        "est_routes": np.nan,
        "snap_pct": np.nan,
        "yprr": np.nan,
        "fd_rr": np.nan,
        "ypc": (ryd / rec) if rec else np.nan,
        "yac_pc": np.nan,
        "adot": np.nan,
        "td": rtd,
        "exp_td": rtd,
        "td_gap": 0.0,
        "ts_trend": np.nan,
        "route_trend": np.nan,
        "career_games": 0.0,
        "healthy_recent": False,
        "prev_ppg": np.nan,
        "prev_games": np.nan,
        "prev_games3": np.nan,
        "dur3": np.nan,
        # A rookie has no last season, so this is left blank on purpose --
        # availability.py reads the blank three-year record and uses the rookie
        # number instead of the line. See ROOKIE_GAMES there.
        "prev_role": np.nan,
        "prev_team": None,
        "prior_source": "clay",
        "trust_override": ROOKIE_TRUST,
    }


# ---------------------------------------------------------------------------
# the route estimate
# ---------------------------------------------------------------------------
def team_dropbacks(pbp: pd.DataFrame | None) -> pd.DataFrame:
    """Team dropbacks per season -- the denominator of every route estimate.

    `pass` is already 1 on every sack in nflverse play-by-play (checked: all
    1,352 sacks in 2025 carry pass=1 and play_type='pass'), so adding sacks back
    counts them twice and inflates every receiver's route count by about 6%.
    That would make every per-route rate 6% harsh and quietly move the badge
    threshold off the value it was fitted at. Dropbacks are `sum(pass)`.
    """
    empty = pd.DataFrame(columns=["season", "team", "dropbacks"])
    if pbp is None or pbp.empty or "posteam" not in pbp.columns:
        return empty
    p = pbp.dropna(subset=["posteam"]).copy()
    if "pass" in p.columns:
        flag = pd.to_numeric(p["pass"], errors="coerce").fillna(0.0)
    else:
        flag = (p.get("play_type") == "pass").astype(float)
    p = p.assign(_db=flag)
    out = (p.groupby([pd.to_numeric(p["season"], errors="coerce"), p["posteam"]])["_db"]
           .sum().reset_index())
    out.columns = ["season", "team", "dropbacks"]
    out["dropbacks"] = out["dropbacks"].replace(0, np.nan)
    return out


# ---------------------------------------------------------------------------
# season aggregates
# ---------------------------------------------------------------------------
def season_aggregates(weekly: pd.DataFrame, scoring_rules: dict | None,
                      snaps: pd.DataFrame | None = None,
                      pbp: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per receiver-season, with everything the indices read.

    The weekly file already carries `wopr`, `target_share`, `air_yards_share`
    and `receiving_first_downs`, so opportunity quality needs no derivation at
    all -- only routes have to be estimated.
    """
    rules = scoring_rules or config.SCORING
    ppr = float(rules.get("reception", 0.5))

    w = pd.DataFrame({
        "player_id": _first(weekly, ["player_id", "gsis_id"]).astype(str),
        "player_name": _first(weekly, ["player_display_name", "player_name", "full_name"]),
        "position": _first(weekly, ["position", "position_group"]).astype(str).str.upper(),
        "season": _num(weekly, "season"),
        "week": _num(weekly, "week"),
        "season_type": _first(weekly, ["season_type", "game_type"]).astype(str),
        "team": _first(weekly, ["team", "recent_team", "team_abbr"]),
        # _numf takes a LIST of candidate column names -- a bare string would be
        # iterated character by character, match nothing, and hand back a column
        # of zeros without complaining. Every one of these is a list on purpose.
        "targets": _numf(weekly, ["targets"]),
        "receptions": _numf(weekly, ["receptions"]),
        "rec_yds": _numf(weekly, ["receiving_yards"]),
        "rec_td": _numf(weekly, ["receiving_tds"]),
        "rec_fd": _numf(weekly, ["receiving_first_downs"]),
        "air_yards": _numf(weekly, ["receiving_air_yards"]),
        "yac": _numf(weekly, ["receiving_yards_after_catch"]),
        "target_share": _num(weekly, "target_share"),
        "air_yards_share": _num(weekly, "air_yards_share"),
        "wopr": _num(weekly, "wopr"),
        "carries": _numf(weekly, ["carries"]),
        "rush_yds": _numf(weekly, ["rushing_yards"]),
        "rush_td": _numf(weekly, ["rushing_tds"]),
        "fum": (_numf(weekly, ["receiving_fumbles_lost"])
                + _numf(weekly, ["rushing_fumbles_lost"])),
    })
    # ---- the team's WHOLE target pool, counted before the receiver filter ----
    # SLOT_TGT_SHARE was measured off the weekly file's `target_share`, and that
    # column is a share of everything the offence threw -- backs and tight ends
    # included, about 35 a game. Summing targets after the WR filter counts only
    # about 21. Multiplying one by the other understates every receiver's role by
    # roughly forty per cent, so the pool has to be counted the same way the
    # shares were: all positions, then divide by games the team actually played.
    _all = w[(w["season_type"].str.upper() == "REG") & w["season"].notna()
             & w["team"].notna()]
    team_tgt = (_all.groupby(["season", "team"], as_index=False)
                .agg(t_tgt=("targets", "sum"), t_gm=("week", "nunique")))
    team_tgt["team_tgt_pg"] = team_tgt["t_tgt"] / team_tgt["t_gm"].replace(0, np.nan)

    w = w[(w["position"] == "WR") & (w["season_type"].str.upper() == "REG")].copy()
    w = w[w["season"].notna()]

    # A column that came back empty is the one failure this file cannot survive
    # and will not otherwise announce: the board still builds, every receiver
    # scores zero, and the ranking becomes noise. Catch it at the door.
    for _c in ("targets", "receptions", "rec_yds"):
        if not w.empty and float(w[_c].abs().sum()) == 0.0:
            raise ValueError(
                f"season_aggregates: every '{_c}' value is zero. The weekly file is "
                "missing that column or it did not parse — the receiver board would "
                "be built on nothing. Re-pull with scripts/01_pull_data.py.")

    w["rec_fp"] = w["rec_yds"] * 0.1 + w["rec_td"] * 6.0 + w["receptions"] * ppr
    w["rush_fp"] = w["rush_yds"] * 0.1 + w["rush_td"] * 6.0
    w["total_fp"] = w["rec_fp"] + w["rush_fp"] - w["fum"] * 2.0

    sa = w.groupby(["player_id", "season"], as_index=False).agg(
        games=("total_fp", "size"),
        total_fp=("total_fp", "sum"),
        rec_fp=("rec_fp", "sum"),
        rush_fp=("rush_fp", "sum"),
        targets=("targets", "sum"),
        receptions=("receptions", "sum"),
        rec_yds=("rec_yds", "sum"),
        rec_td=("rec_td", "sum"),
        rec_fd=("rec_fd", "sum"),
        air_yards=("air_yards", "sum"),
        yac=("yac", "sum"),
        carries=("carries", "sum"),
        rush_yds=("rush_yds", "sum"),
        rush_td=("rush_td", "sum"),
        target_share=("target_share", "mean"),
        air_yards_share=("air_yards_share", "mean"),
        wopr=("wopr", "mean"),
    )

    # The team he played most for that season, and the last name he appeared
    # under -- players get traded and get renamed, and neither should split a row.
    tm = (w.groupby(["player_id", "season", "team"], as_index=False)
          .agg(gm=("total_fp", "size"))
          .sort_values(["player_id", "season", "gm"], ascending=[True, True, False])
          .groupby(["player_id", "season"], as_index=False).head(1)[["player_id", "season", "team"]])
    nm = (w[w["player_name"].notna()].sort_values(["player_id", "season", "week"])
          .groupby(["player_id", "season"], as_index=False).tail(1)[
              ["player_id", "season", "player_name"]])
    sa = sa.merge(tm, on=["player_id", "season"], how="left")
    sa = sa.merge(nm, on=["player_id", "season"], how="left")
    sa = sa.merge(team_tgt[["season", "team", "team_tgt_pg"]],
                  on=["season", "team"], how="left")

    g = sa["games"].replace(0, np.nan)

    # ---- touchdowns, thrown away and rebuilt ------------------------------
    # The league's own rate over the recent window, applied to HIS yardage. On
    # 864 back-to-back pairs this beats his own count at predicting next year's
    # count, 0.585 to 0.556, and blending the two at K_TD beats both at 0.601.
    mx = sa["season"].max()
    ref = sa[(sa["season"] >= mx - RECENCY + 1) & (sa["games"] >= 8)]
    r_ty = (ref["rec_td"].sum() / ref["rec_yds"].sum()) if ref["rec_yds"].sum() else 0.0061
    wt = sa["games"] / (sa["games"] + K_TD)
    sa["exp_td"] = sa["rec_yds"] * r_ty
    sa["reg_rec_td"] = wt * sa["rec_td"] + (1 - wt) * sa["exp_td"]
    sa["td_gap"] = sa["rec_td"] - sa["exp_td"]

    sa["rec_fp_reg_pg"] = (sa["rec_yds"] * 0.1 + sa["receptions"] * ppr
                           + sa["reg_rec_td"] * 6.0) / g
    sa["rush_fp_reg_pg"] = sa["rush_fp"] / g
    sa["tot_fp_reg_pg"] = sa["rec_fp_reg_pg"] + sa["rush_fp_reg_pg"]
    sa["total_fp_pg"] = sa["total_fp"] / g

    sa["targets_pg"] = sa["targets"] / g
    sa["rec_pg"] = sa["receptions"] / g
    sa["rec_yds_pg"] = sa["rec_yds"] / g
    sa["ypc"] = sa["rec_yds"] / sa["receptions"].replace(0, np.nan)
    sa["yac_pc"] = sa["yac"] / sa["receptions"].replace(0, np.nan)
    sa["adot"] = sa["air_yards"] / sa["targets"].replace(0, np.nan)
    sa["td"] = sa["rec_td"]

    sa = _attach_snaps(sa, snaps)
    sa = _attach_routes(sa, pbp)
    return sa


def _attach_snaps(sa: pd.DataFrame, snaps: pd.DataFrame | None) -> pd.DataFrame:
    """Snap share per receiver-season. Route share is read straight off this.

    Two-tier match, and the second tier has to be EARNED. Exact normalised name
    plus team first; the first-initial-plus-surname fallback only where that key
    is unique on both sides of the season.

    That last clause is the whole point. On a single-tier fallback "a brown" is
    both A.J. Brown and Amon-Ra St. Brown, and averaging their snap shares hands
    each of them the other's route share -- two of the twelve best receivers in
    the league, silently wrong, on a number that feeds three separate factors.
    There are 44 such collisions across eight seasons. Every one of them is
    resolved by exact name instead, and anything that survives both tiers is
    warned about rather than guessed at.
    """
    sa = sa.copy()
    sa["snap_pct"] = np.nan
    if snaps is None or len(snaps) == 0:
        return sa
    try:
        s = snaps.copy()
        pos = _first(s, ["position", "pos"]).astype(str).str.upper()
        s = s[pos == "WR"]
        gt = _first(s, ["game_type", "season_type"])
        if gt is not None and gt.notna().any():
            s = s[gt.astype(str).str.upper() == "REG"]
        if s.empty:
            return sa

        pct = pd.to_numeric(_first(s, ["offense_pct", "off_pct", "offense_snap_pct"]),
                            errors="coerce")
        j = pd.DataFrame({
            "season": _num(s, "season"),
            "team": _first(s, ["team", "recent_team", "club_code"]),
            "name": _first(s, ["player", "player_name", "player_display_name"]),
            "pct": pct,
        }).dropna(subset=["season", "name", "pct"])
        if j.empty:
            return sa
        if j["pct"].max() > 1.5:            # some seasons ship 0-100, some 0-1
            j["pct"] = j["pct"] / 100.0

        j["fk"] = _full_key(j["name"])
        j["sk"] = _short_key(j["fk"])
        sa["fk"] = _full_key(sa["player_name"].fillna(""))
        sa["sk"] = _short_key(sa["fk"])

        # tier 1 -- exact name on the same team
        ex = j.groupby(["season", "team", "fk"], as_index=False)["pct"].mean()
        sa = sa.merge(ex.rename(columns={"pct": "_p_exact"}),
                      on=["season", "team", "fk"], how="left")

        # tier 2 -- initial + surname, only where nobody else answers to it
        j_u = j.groupby(["season", "sk"])["fk"].nunique()
        s_u = sa.groupby(["season", "sk"])["fk"].nunique()
        safe = ({k for k, v in j_u.items() if v == 1}
                & {k for k, v in s_u.items() if v == 1})
        mask = [(a, b) in safe for a, b in zip(j["season"], j["sk"])]
        fb = j[mask].groupby(["season", "sk"], as_index=False)["pct"].mean()
        sa = sa.merge(fb.rename(columns={"pct": "_p_fb"}), on=["season", "sk"], how="left")

        sa["snap_pct"] = sa["_p_exact"].fillna(sa["_p_fb"])

        # Anything that needed the fallback, could not have it, and did not
        # match exactly either. Named, not swallowed -- the plan is explicit
        # that a collision should print rather than silently pick one.
        lost = sa[sa["snap_pct"].isna() & (sa["games"] >= 6)]
        for _, r in lost.iterrows():
            other = sorted(set(sa[(sa["season"] == r["season"]) & (sa["sk"] == r["sk"])
                                  & (sa["fk"] != r["fk"])]["player_name"].dropna()))
            if other:
                _warn(f"name collision {int(r['season'])} '{r['player_name']}' shares a "
                      f"key with {other} and has no exact snap row -- no route share")
            else:
                _warn(f"no snap row for {r['player_name']} {int(r['season'])} "
                      f"({int(r['games'])} games) -- no route share")
        sa = sa.drop(columns=[c for c in ("_p_exact", "_p_fb") if c in sa.columns])
    except Exception as exc:  # noqa: BLE001
        # Route share is a big part of this board, but a snap file that has
        # changed shape must degrade the board, not end it.
        _warn(f"snap counts unusable ({exc}) -- route share is off for this build")
        sa["snap_pct"] = np.nan
    return sa


def _attach_routes(sa: pd.DataFrame, pbp: pd.DataFrame | None) -> pd.DataFrame:
    """route share, estimated routes, and the two per-route rates."""
    sa = sa.copy()
    sa["route_share"] = pd.to_numeric(sa.get("snap_pct"), errors="coerce")
    db = team_dropbacks(pbp)
    if db.empty:
        sa["est_routes"] = np.nan
        _warn("no play-by-play -- routes could not be estimated, "
              "so yards and first downs per route are blank this build")
    else:
        sa = sa.merge(db, on=["season", "team"], how="left")
        sa["est_routes"] = sa["route_share"] * sa["dropbacks"]
    r = pd.to_numeric(sa["est_routes"], errors="coerce").replace(0, np.nan)
    sa["yprr"] = sa["rec_yds"] / r
    sa["fd_rr"] = sa["rec_fd"] / r
    return sa


def snap_coverage(sa: pd.DataFrame) -> float:
    return float(pd.to_numeric(sa.get("snap_pct"), errors="coerce").notna().mean())


def _recent_pool(sa: pd.DataFrame) -> pd.DataFrame:
    mx = sa["season"].max()
    return sa[(sa["season"] >= mx - RECENCY + 1) & (sa["games"] >= 8)]


# ---------------------------------------------------------------------------
# per-player bundle
# ---------------------------------------------------------------------------
# Everything that gets a recency-weighted average across his healthy seasons.
_BUNDLE_MEANS = [
    "rec_fp_reg_pg", "rush_fp_reg_pg", "targets_pg", "rec_pg", "rec_yds_pg",
    "target_share", "air_yards_share", "wopr", "route_share", "est_routes",
    "yprr", "fd_rr", "ypc", "yac_pc", "adot", "snap_pct", "td", "exp_td", "td_gap",
]


def _bundle(pdf: pd.DataFrame, as_of) -> dict | None:
    """Recency-weighted read of one receiver, as of the start of `as_of`.

    Only seasons he was actually available for -- a six-game year is a fact
    about his hamstring, not about his rate -- and only inside the recency
    window. Weights 0.6 / 0.27 / 0.13, same as the backs.
    """
    hist = pdf[(pdf["season"] < as_of) & (pdf["season"] >= as_of - RECENCY)]
    if hist.empty:
        return None
    healthy = hist[hist["games"] >= HEALTHY_GAMES]
    use = (healthy if not healthy.empty else hist).sort_values("season", ascending=False).head(3)
    wts = np.array([0.6, 0.27, 0.13][:len(use)], dtype="float64")
    wts = wts / wts.sum()

    def wavg(col):
        v = pd.to_numeric(use[col], errors="coerce").to_numpy(dtype="float64")
        m = ~np.isnan(v)
        if not m.any():
            return np.nan
        return float((v[m] * wts[m]).sum() / wts[m].sum())

    out = {"talent_reg": wavg("tot_fp_reg_pg")}
    for c in _BUNDLE_MEANS:
        key = c.replace("_fp_reg_pg", "_val")
        out[key] = wavg(c)

    last = hist.sort_values("season").tail(1).iloc[0]
    prev3 = hist.sort_values("season").tail(3)
    out.update({
        "career_games": float(hist["games"].sum()),
        "healthy_recent": bool((hist["games"] >= HEALTHY_GAMES).any()),
        "prev_ppg": float(last["total_fp_pg"]) if pd.notna(last["total_fp_pg"]) else np.nan,
        "prev_games": float(last["games"]),
        "prev_games3": float(prev3["games"].mean()),
        # Three years of availability, weighted toward the recent one. See
        # availability.DUR_WEIGHTS for why this is not just last season.
        "dur3": availability.durability(
            list(prev3.sort_values("season", ascending=False)["games"])),
        # How big last season's job was, 0 to 1, where 1 is a true alpha's nine
        # targets a game. Only availability.py reads it, and only to work out how
        # many games he plays NEXT year. Without it "played 11 games" describes
        # both a number one who missed six weeks hurt and a fourth receiver who
        # was simply inactive, and the two are not the same bet. The backs use
        # carries over 18 and the passers throws over 32 for the same reason.
        "prev_role": float(np.clip(
            float(last.get("targets_pg") or 0.0) / 9.0, 0.0, 1.0)),
        "prev_team": last.get("team"),
        "prior_source": "history",
    })

    # TRENDS. Shown, not weighted -- measured against next season these come in
    # at -0.02 and -0.01, which is nothing. They are on the panel because a
    # receiver whose route share is climbing reads differently to one whose is
    # falling, even when this year's number is identical and the model, quite
    # correctly, cannot tell them apart.
    two = hist.sort_values("season").tail(2)
    if len(two) == 2:
        a, b = two.iloc[0], two.iloc[1]
        out["ts_trend"] = _diff(b.get("target_share"), a.get("target_share"))
        out["route_trend"] = _diff(b.get("route_share"), a.get("route_share"))
    else:
        out["ts_trend"] = np.nan
        out["route_trend"] = np.nan
    return out


def _diff(a, b):
    a, b = pd.to_numeric(a, errors="coerce"), pd.to_numeric(b, errors="coerce")
    if pd.isna(a) or pd.isna(b):
        return np.nan
    return float(a) - float(b)


def _merge_team_env(prof: pd.DataFrame, team_season: pd.DataFrame | None) -> pd.DataFrame:
    if team_season is None or team_season.empty:
        return prof
    ts = team_season.copy()
    ts["season"] = pd.to_numeric(ts["season"], errors="coerce")
    prof = prof.copy()
    prof["prev_season"] = prof["season"] - 1
    out = prof.merge(ts, left_on=["prev_season", "team"], right_on=["season", "team"],
                     how="left", suffixes=("", "_ts"))
    return out.drop(columns=[c for c in out.columns if c.endswith("_ts")])


def entering_profiles(sa: pd.DataFrame, team_season, players, pool) -> pd.DataFrame:
    """One row per (receiver, completed season) -- what was knowable beforehand."""
    birth = _birth_map(players)
    wt = win_totals()
    fwd = implied_totals()
    rows = []
    for pid, pdf in sa.groupby("player_id"):
        pdf = pdf.sort_values("season")
        for _, cur in pdf.iterrows():
            season = int(cur["season"])
            b = _bundle(pdf, season)
            if b is None:
                continue
            team = cur.get("team")
            age = np.nan
            by = birth.get(str(pid))
            if by:
                age = season - by
            rows.append({
                "player_id": str(pid),
                "player_name": cur.get("player_name"),
                "season": season,
                "team": team,
                "actual_ppg": float(cur["total_fp_pg"]) if pd.notna(cur["total_fp_pg"]) else np.nan,
                "actual_games": float(cur["games"]),
                "age": age,
                "durability": b.get("dur3", np.nan),
                "win_total": wt.get((season, team)),
                "implied_fwd": fwd.get((season, team)),
                **b,
            })
    prof = pd.DataFrame(rows)
    if prof.empty:
        return prof
    prof["mover"] = (prof["team"] != prof["prev_team"]) & prof["prev_team"].notna()
    return _merge_team_env(prof, team_season)


# ---------------------------------------------------------------------------
# role and window
# ---------------------------------------------------------------------------
def _rookie_years(players) -> dict:
    """player_id -> the season he entered the league."""
    out = {}
    if players is None or getattr(players, "empty", True):
        return out
    idc = next((c for c in ("gsis_id", "player_id") if c in players.columns), None)
    yrc = next((c for c in ("rookie_season", "rookie_year", "entry_year")
                if c in players.columns), None)
    if not idc or not yrc:
        return out
    for i, y in zip(players[idc], pd.to_numeric(players[yrc], errors="coerce")):
        if pd.notna(i) and pd.notna(y):
            out[str(i)] = int(y)
    return out


def _draft_rounds(players) -> dict:
    """player_id -> draft round. Missing means undrafted, which is information.

    UNLESS THE CLASS ITSELF IS MISSING. nflverse does not carry a draft round
    for the incoming class until well after the draft -- every 2026 receiver in
    the file has draft_round blank and draft_year blank while carrying
    rookie_season 2026. Reading that blank as "round 0, undrafted" priced
    seventeen of the eighteen rookies on this board at DRAFT_UNDRAFTED, and
    because draft capital has not faded at all in year one, that 22.0 WAS their
    entire Talent score: a real first-round receiver and a camp body got the
    same number. A blank on a player whose class predates the file is genuine
    information and still means undrafted; a blank on a player whose class the
    file has not filled in yet means nobody has said, so it comes back None and
    Talent falls through to what he is actually projected to do.
    """
    out = {}
    if players is None or getattr(players, "empty", True):
        return out
    idc = next((c for c in ("gsis_id", "player_id") if c in players.columns), None)
    if not idc or "draft_round" not in players.columns:
        return out
    rd_all = pd.to_numeric(players["draft_round"], errors="coerce")
    # A class is "covered" once anybody who entered that year has a round on
    # file. That keeps a genuinely undrafted 2019 receiver reading as undrafted.
    rk_col = next((c for c in ("rookie_season", "draft_year", "entry_year")
                   if c in players.columns), None)
    covered = None
    if rk_col is not None:
        rk_all = pd.to_numeric(players[rk_col], errors="coerce")
        covered = {int(s) for s in rk_all[rd_all.notna()].dropna().unique()}
    for n, (i, r) in enumerate(zip(players[idc], rd_all)):
        if pd.isna(i):
            continue
        if pd.notna(r):
            out[str(i)] = int(r)
            continue
        if covered is not None:
            cls = rk_all.iat[n]
            if pd.isna(cls) or int(cls) not in covered:
                continue                      # class not on file yet: unknown
        out[str(i)] = 0                       # genuinely undrafted
    return out


def _elite_seasons(sa: pd.DataFrame) -> set:
    """(player_id, season) for every top-ELITE_RANK finish on a real sample."""
    out = set()
    d = sa[sa["games"] >= ELITE_MIN_GAMES]
    for season, g in d.groupby("season"):
        top = g.sort_values("total_fp_pg", ascending=False).head(ELITE_RANK)
        out |= {(str(p), int(season)) for p in top["player_id"]}
    return out


def attach_role_window(prof: pd.DataFrame, sa: pd.DataFrame, players) -> pd.DataFrame:
    """Depth slot, the job it implies, career year, and availability.

    THE HISTORICAL DEPTH SLOT IS NOT A DEPTH CHART. data.get_depth_history() is
    running-back only, and rather than invent a receiver version this reads the
    slot off MEASURED route share -- rank within team-season. A depth chart is a
    guess at exactly that ranking made in August; where the season is already
    played, the measurement is strictly better information.

    Only the upcoming season uses a published chart, because for the upcoming
    season there is nothing measured to use instead. build_upcoming() supplies
    that as `depth_rank`.
    """
    p = prof.copy()
    if p.empty:
        return p

    # ---- 1. slot ----------------------------------------------------------
    hist = sa[sa["games"] >= 4].copy()
    hist["_rank"] = (hist.groupby(["season", "team"])["route_share"]
                     .rank(ascending=False, method="first"))
    rank_map = {(str(a), int(b)): float(c)
                for a, b, c in zip(hist["player_id"], hist["season"], hist["_rank"])
                if pd.notna(c)}
    # His slot LAST season -- what was knowable entering this one.
    measured = pd.Series(
        [rank_map.get((str(i), int(s) - 1), np.nan)
         for i, s in zip(p["player_id"], p["season"])], index=p.index)
    live = pd.to_numeric(p.get("depth_rank"), errors="coerce") if "depth_rank" in p.columns \
        else pd.Series(np.nan, index=p.index)

    # Where both readings exist -- which only ever happens for the upcoming
    # season -- blend them instead of letting one win outright, leaning on the
    # tape in proportion to how much of last season he actually played and
    # whether it was even for this team. See TAPE_W_MAX above.
    pg = pd.to_numeric(p.get("prev_games"), errors="coerce")
    ramp = ((pg - TAPE_GAMES_LO) / (TAPE_GAMES_HI - TAPE_GAMES_LO)).clip(0.0, 1.0)
    tape_w = TAPE_W_MIN + (TAPE_W_MAX - TAPE_W_MIN) * ramp
    if "mover" in p.columns:
        tape_w = tape_w.where(~p["mover"].fillna(False).astype(bool), TAPE_W_MOVED)
    tape_w = tape_w.fillna(TAPE_W_MIN)

    p["slot"] = measured.fillna(live).clip(upper=6)
    both = measured.notna() & live.notna()
    p.loc[both, "slot"] = (tape_w[both] * measured[both]
                           + (1.0 - tape_w[both]) * live[both]).clip(upper=6)
    p["tape_w"] = tape_w.where(both)

    # ---- 2. the size of the pool -----------------------------------------
    # The team's whole target pool, shifted forward a season, so a player's role
    # is scaled by how many balls his offence actually throws. season_aggregates
    # counts this BEFORE the receiver filter, on purpose: SLOT_TGT_SHARE is a
    # share of all targets, so the pool it multiplies has to be all targets too.
    # Counting receivers only was a forty-per-cent haircut on every projection.
    team_pool = (sa.dropna(subset=["team_tgt_pg"])
                 .groupby(["season", "team"], as_index=False)
                 .agg(team_tgt_pg=("team_tgt_pg", "max")))
    med = team_pool.groupby("season")["team_tgt_pg"].transform("median")
    team_pool["team_tgt_pg"] = 0.75 * team_pool["team_tgt_pg"] + 0.25 * med
    team_pool["season"] = team_pool["season"] + 1          # entering the NEXT season
    p = p.merge(team_pool[["season", "team", "team_tgt_pg"]],
                on=["season", "team"], how="left")
    p["team_tgt_pg"] = p["team_tgt_pg"].fillna(p["team_tgt_pg"].median())

    # ---- 3. what that slot is worth --------------------------------------
    # Read straight off the table between the whole numbers, rather than
    # rounding the spot first. A blended 1.5 is a real statement -- the chart
    # says one, last year said two -- and rounding it back to 2 would throw the
    # blend away. Every historical row is a whole number anyway, so this leaves
    # the seasons the model is fitted on exactly where they were.
    ks = np.array(sorted(SLOT_ROUTE), dtype=float)
    slot_f = p["slot"].clip(1, 6).astype(float)
    p["slot_route"] = pd.Series(
        np.interp(slot_f, ks, [SLOT_ROUTE[int(k)] for k in ks]), index=p.index)
    p["slot_tgt_share"] = pd.Series(
        np.interp(slot_f, ks, [SLOT_TGT_SHARE[int(k)] for k in ks]), index=p.index)
    p["role_tgt"] = p["team_tgt_pg"] * p["slot_tgt_share"]
    p["role_route"] = p["slot_route"]

    # ---- 4. career year and draft capital --------------------------------
    rook = _rookie_years(players)
    first_seen = sa.groupby("player_id")["season"].min().to_dict()
    yr, cap = [], []
    rounds = _draft_rounds(players)
    for pid, season in zip(p["player_id"], p["season"]):
        r = rook.get(str(pid)) or first_seen.get(str(pid))
        yr.append(int(season) - int(r) + 1 if r else np.nan)
        rd = rounds.get(str(pid))
        cap.append(DRAFT_SCORE.get(rd, DRAFT_UNDRAFTED) if rd is not None else np.nan)
    p["yr_in_league"] = yr
    p["draft_score"] = cap

    elite = _elite_seasons(sa)
    p["proven"] = [any((str(i), s) in elite for s in range(2000, int(y)))
                   for i, y in zip(p["player_id"], p["season"])]

    return _attach_availability(p)


def _attach_availability(p: pd.DataFrame) -> pd.DataFrame:
    return availability.attach(p, "WR", NEWS_W, MIN_GAMES_RATIO)


# ---------------------------------------------------------------------------
# shrinkage
# ---------------------------------------------------------------------------
def _role_prior(prof: pd.DataFrame, col: str) -> pd.Series:
    """What his slot alone says the column should be, fitted per season."""
    out = pd.Series(np.nan, index=prof.index, dtype="float64")
    x_all = pd.to_numeric(prof.get("role_tgt"), errors="coerce")
    y_all = pd.to_numeric(prof.get(col), errors="coerce")
    for season, idx in prof.groupby("season").groups.items():
        idx = list(idx)
        x, y = x_all.loc[idx], y_all.loc[idx]
        m = np.isfinite(x) & np.isfinite(y)
        # A flat x makes the least-squares solve singular -- numpy raises rather
        # than returning a slope of zero, so the whole build dies on what is
        # really just "this season has no spread in role". Fall back to the mean.
        if m.sum() >= 20 and float(x[m].std()) > 1e-9:
            k, c = np.polyfit(x[m], y[m], 1)
            out.loc[idx] = k * x + c
        else:
            out.loc[idx] = y[m].mean() if m.any() else np.nan
    return out


def _shrink_target(prof: pd.DataFrame, col: str) -> pd.Series:
    """The floor a thin record is pulled up to -- never a ceiling pulled down.

    Same asymmetry as the backs: the prior is allowed to say "his job is bigger
    than his resume", never "ignore the targets he actually got".
    """
    prior = _role_prior(prof, col)
    pool = pd.to_numeric(prof.get(col), errors="coerce").mean()
    return pd.Series(np.maximum(prior.fillna(pool), pool), index=prof.index)


# ---------------------------------------------------------------------------
# indices
# ---------------------------------------------------------------------------
def add_indices(prof: pd.DataFrame, weights: dict | None = None) -> pd.DataFrame:
    """Every factor, as a 0-100 percentile within its own season."""
    p = prof.copy()
    if p.empty:
        return p
    weights = weights or DEFAULT_WEIGHTS

    # ---- how much of his own record to believe ---------------------------
    cg = pd.to_numeric(p.get("career_games"), errors="coerce").fillna(0.0)
    wc = cg / (cg + K_CAREER)
    if "trust_override" in p.columns:
        ov = pd.to_numeric(p["trust_override"], errors="coerce")
        wc = wc.where(ov.isna(), ov)
    p["reg_shrink"] = 1.0 - wc

    # A MISSING MEASUREMENT IS NOT A ZERO. `wc * v.fillna(0)` reads "he ran no
    # routes" out of "nobody has measured him yet", and then keeps the answer as
    # a real number, which is the expensive half: Opportunity is written as
    # wopr -> air yards -> Volume precisely so a receiver with no WOPR falls
    # back to his target volume, and a manufactured zero stops that chain from
    # ever firing. Twelve of the eighteen rookies came out on the same
    # 10.6th-percentile Opportunity floor -- not a low score, the same score,
    # which is what a floor looks like. Where the raw column is blank the answer
    # is the job prior alone, and where the column is blank AND the prior cannot
    # be fitted the answer stays blank so the fallback chain does its work.
    def _final(col: str) -> pd.Series:
        v = pd.to_numeric(p[col], errors="coerce")
        blended = wc * v + (1 - wc) * _shrink_target(p, col)
        return blended.where(v.notna(), np.nan)

    if "talent_reg" in p.columns:
        p["talent_final"] = _final("talent_reg")
    else:
        p["talent_final"] = np.nan
    for col in ("targets_pg", "target_share", "wopr", "rec_val"):
        if col in p.columns:
            p[col + "_final"] = _final(col)

    # ---- which rows are the season nobody has played yet ------------------
    # Ranking those against each other is the denominator trap REF_SEASONS
    # describes: a shorter list caps its own top. They get placed into finished
    # seasons instead. Everything else keeps ranking inside its own season,
    # which is what the points scale was fitted on and what the backtest reads.
    sn = pd.to_numeric(p["season"], errors="coerce")
    act = pd.to_numeric(p.get("actual_ppg", pd.Series(np.nan, index=p.index)),
                        errors="coerce")
    smax = sn.max()
    up = (sn == smax) & act.isna()
    if not (up.any() and (sn == smax).equals(up) and (~up).any()):
        up = pd.Series(False, index=p.index)      # a backtest run: no such season
    ref_seasons = sorted(sn[~up].dropna().unique())[-REF_SEASONS:] if up.any() else []

    def pct(col):
        if col not in p.columns:
            return pd.Series(np.nan, index=p.index)
        v = pd.to_numeric(p[col], errors="coerce")
        out = v.groupby(p["season"]).transform(lambda s: s.rank(pct=True) * 100)
        if not up.any():
            return out
        x = v[up].to_numpy(dtype=float)
        placed, used = np.zeros(len(x)), 0
        for s in ref_seasons:
            base = np.sort(v[(~up) & (sn == s)].dropna().to_numpy(dtype=float))
            if len(base) < 30:
                continue
            lo = np.searchsorted(base, x, side="left")
            hi = np.searchsorted(base, x, side="right")
            placed += (lo + hi + 1) / 2.0 / len(base) * 100.0
            used += 1
        if used:
            out.loc[up] = np.where(np.isnan(x), np.nan,
                                   np.clip(placed / used, 0.0, 100.0))
        return out

    # ---- VOLUME. Target share and targets per game, half each, each blended
    # with what his slot implies. The single heaviest thing on the board.
    ts_b = ((1 - VOL_ROLE_W) * pct("target_share_final")
            + VOL_ROLE_W * pct("slot_tgt_share"))
    tg_b = ((1 - VOL_ROLE_W) * pct("targets_pg_final")
            + VOL_ROLE_W * pct("role_tgt"))
    p["Volume"] = TS_VOL_W * ts_b + (1 - TS_VOL_W) * tg_b

    # ---- OPPORTUNITY. WOPR, already computed in the weekly file, backed by
    # air yards share where WOPR is missing.
    wo = pct("wopr_final")
    p["Opportunity"] = wo.fillna(pct("air_yards_share")).fillna(p["Volume"])

    # ---- EFFICIENCY. Both per-route rates, first downs leading slightly.
    p["Efficiency"] = (FD_EFF_W * pct("fd_rr") + (1 - FD_EFF_W) * pct("yprr"))

    # ---- ROLE. Measured route share, falling back to the slot table.
    rs = pct("route_share")
    p["Role"] = rs.fillna(pct("role_route"))

    # ---- VEGAS. Implied total and win total. Carries 14 here, against the
    # backs' 10 -- a team's implied total correlates +0.62 with what its
    # receivers score and +0.34 with what its backs do.
    p["Vegas"] = pd.concat([pct("win_total"), pct("implied_fwd")], axis=1).mean(axis=1)

    # ---- SCORING. The regressed touchdown, not the raw one.
    p["Scoring"] = pct("td_final") if "td_final" in p.columns else pct("exp_td")
    if "exp_td" in p.columns:
        p["Scoring"] = pd.concat([pct("exp_td"), pct("td")], axis=1).mean(axis=1)

    # ---- SITUATION. Pace, and how much the offence throws. The receiver
    # version is the mirror of the backs': they want the run, this wants the pass.
    p["Situation"] = pd.concat([pct("plays_pg"), pct("pass_rate")], axis=1).mean(axis=1)

    # ---- AVAILABILITY. Age curve times his three-year durability, weighted
    # toward last season. Not a percentile -- an
    # absolute read, so a healthy field doesn't manufacture injury risk.
    dur = pd.to_numeric(p.get("durability"), errors="coerce")
    p["Availability"] = [
        _age_curve(a) * (float(d) if pd.notna(d) else 0.8) * 100.0
        for a, d in zip(p.get("age", pd.Series(np.nan, index=p.index)), dur)]

    # ---- TALENT. His own rate, shrunk toward his job -- plus draft capital
    # while it still means something. Capital fades linearly over three seasons
    # because after three years of snaps the snaps are the better evidence.
    #
    # CAPITAL NEVER OWNS THE WHOLE FACTOR. The fade ran to a full 1.0 in year
    # one, so a rookie's Talent was his draft slot and nothing else -- the
    # projection sitting right there in the same row was not consulted. Where he
    # was picked is the better evidence early, not the only evidence, so the
    # capital share is capped and the rest is always what he is projected to do.
    tal_pct = pct("talent_final")
    yr = pd.to_numeric(p.get("yr_in_league"), errors="coerce")
    fade = ((DRAFT_FADE_SEASONS - (yr - 1)) / DRAFT_FADE_SEASONS).clip(0.0, 1.0).fillna(0.0)
    fade = fade.clip(upper=DRAFT_MAX_W)
    cap = pd.to_numeric(p.get("draft_score"), errors="coerce")
    p["Talent"] = np.where(cap.notna() & tal_pct.notna(),
                           (1 - fade) * tal_pct + fade * cap,
                           np.where(cap.notna(), cap, tal_pct))

    # ---- WINDOW. A ramp, not a cliff.
    win = yr.map(WINDOW_SCORES)
    late = np.where(p.get("proven", False), WINDOW_PROVEN, WINDOW_LATE)
    p["Window"] = pd.Series(np.where(yr >= 6, late, win), index=p.index).where(yr.notna(), 50.0)

    p["Matchup"] = 50.0

    # ---- a move blurs everything about the offence around him -------------
    if "mover" in p.columns:
        mv = p["mover"].fillna(False).astype(bool)
        for c in ("Situation", "Vegas", "Role"):
            p.loc[mv, c] = 0.6 * pd.to_numeric(p.loc[mv, c], errors="coerce") + 0.4 * 50.0

    for gcol in GROUPS:
        if gcol not in p.columns:
            p[gcol] = 50.0
        p[gcol] = pd.to_numeric(p[gcol], errors="coerce").fillna(50.0)

    p["composite"] = composite(p, weights)
    return p


def composite(p: pd.DataFrame, weights: dict | None = None) -> pd.Series:
    weights = weights or DEFAULT_WEIGHTS
    total = sum(weights.values()) or 1
    return sum(w * pd.to_numeric(p[g], errors="coerce") for g, w in weights.items()) / total


def calibrate(p: pd.DataFrame, pos: str = "WR", info: dict | None = None):
    return calibration.fit(p, pos=pos, info=info)


BACKTEST_SEASONS = 3


def backtest(p: pd.DataFrame) -> dict:
    """Walk forward a season at a time; beat last year's points per game or don't.

    Two decisions in here are worth the words, because getting either wrong
    produces a number that looks like a verdict and isn't.

    IT SCORES DRAFTED RECEIVERS ONLY. calibration.py's own bug 1 is "the wrong
    crowd": the points scale is fitted on drafted players, because that is the
    crowd the ADP curve it gets subtracted from is built from. Score that scale
    against every receiver who ever ran a route and roughly half the test set is
    a WR6 who caught eleven balls all year. The scale says seven points a game;
    he scored one and a half; "last year he scored one and a half" wins by a mile
    and the model looks broken. It isn't -- it is being asked about people it was
    never built to price, and people nobody drafts. Measured on the crowd it
    ships to, it wins: 2.84 against 2.86, and it orders them better too.

    IT NEVER FITS ON THE FUTURE. Each test season is scored by a scale fitted
    only on seasons before it, one at a time, then the errors are pooled. A
    single train/test split with the scale fitted once across everything earlier
    is close enough on this data, but this costs nothing and removes the doubt.
    """
    d = p[p["actual_ppg"].notna() & p["composite"].notna()]
    if d.empty:
        return {}
    picks = calibration.drafted_picks("WR")
    if not picks:
        return {}
    from .adp import norm as _adp_norm       # same key the scale was fitted with
    d = d.copy()
    d["_drafted"] = [(int(s), _adp_norm(n)) in picks if pd.notna(n) and pd.notna(s) else False
                     for s, n in zip(d["season"], d["player_name"])]

    # Only seasons that actually have an ADP file can be tested -- 2025's is
    # missing, and a season with no drafted rows is not a season with a bad model.
    have = sorted({int(s) for s in d.loc[d["_drafted"], "season"].unique()})
    if not have:
        return {}
    tested, chunks = [], []
    for s in have[-BACKTEST_SEASONS:]:
        train = d[d["season"] < s]
        test = d[(d["season"] == s) & d["_drafted"]]
        if len(train) < MIN_CAL_ROWS or test.empty:
            continue
        # Fit the BENT scale, not just the line, because the bend is what ships.
        # A backtest of a model the board doesn't use is a number about nothing.
        info: dict = {}
        a, b = calibration.fit(train, pos="WR", info=info)
        test = test.copy()
        test["_pred"] = calibration.apply(test["composite"], a, b, info.get("knots") or [])
        chunks.append(test)
        tested.append(s)
    if not chunks:
        return {}
    t = pd.concat(chunks, ignore_index=True)
    mae = float(np.mean(np.abs(t["_pred"] - t["actual_ppg"])))
    # Baseline on the rows that HAVE a prior season -- filling the gaps with the
    # pool mean would flatter the baseline on exactly the players it knows
    # nothing about.
    base = t.dropna(subset=["prev_ppg"])
    mae_base = (float(np.mean(np.abs(base["prev_ppg"] - base["actual_ppg"])))
                if len(base) else float("nan"))
    rho = t["_pred"].corr(t["actual_ppg"], method="spearman")
    rho_b = (base["prev_ppg"].corr(base["actual_ppg"], method="spearman")
             if len(base) else float("nan"))
    # Key names match the running-back board because the page's JavaScript reads
    # them by name for every position.
    return {"n": int(len(t)), "model_mae": round(mae, 2),
            "baseline_mae": round(mae_base, 2),
            "model_rho": round(float(rho), 3) if pd.notna(rho) else None,
            "baseline_rho": round(float(rho_b), 3) if pd.notna(rho_b) else None,
            "population": "drafted receivers",
            "seasons": tested}


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------
def _empty(weights, extra=None):
    out = {"payload": [], "calib": {"a": 0.0, "b": 0.0, "knots": []},
           "backtest": {}, "weights": dict(weights or DEFAULT_WEIGHTS), "groups": GROUPS}
    if extra:
        out.update(extra)
    return out


def _r(row, key, nd=2):
    """Round for publication. Asking for zero decimals returns a whole number,
    not 26.0 -- the chip row prints these straight, and the other two boards
    have always said "Age 26"."""
    v = row.get(key)
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    try:
        return round(float(v)) if nd == 0 else round(float(v), nd)
    except (TypeError, ValueError):
        return None


def _row_flags(row) -> dict:
    """The tier-two screens, as facts on the row.

    None of these change a projection. They are what the filter dropdown reads
    and what the card shows, and they are computed here rather than in the page
    so that dragging a weight slider cannot move them.
    """
    rs = _r(row, "route_share", 3)
    fd = _r(row, "fd_rr", 4)
    rt = _r(row, "est_routes", 0)
    yr = _r(row, "yr_in_league", 0)
    gap = _r(row, "td_gap", 2)
    team = str(row.get("team") or "")
    return {
        "gate75": bool(rs is not None and rs >= ROUTE_GATE),
        "fd_badge": bool(fd is not None and rt is not None
                         and rt >= FD_RR_MIN_ROUTES and fd >= FD_RR_BADGE),
        "prime": bool(yr is not None and 3 <= yr <= 5),
        "ascending": bool(yr is not None and yr <= 2),
        "late": bool(yr is not None and yr >= 6),
        "crowded": team in CROWDED_TEAMS,
        "td_lucky": bool(gap is not None and gap >= 2.0),
        "td_unlucky": bool(gap is not None and gap <= -2.0),
    }


def _assemble(cur, a, b, bt, weights, extra=None) -> dict:
    weights = weights or DEFAULT_WEIGHTS
    if cur is None or cur.empty:
        return _empty(weights, extra)
    cur = cur.copy()

    knots = ((extra or {}).get("calibration") or {}).get("knots") or []
    cur["proj_ppg"] = calibration.apply(cur["composite"], a, b, knots)

    # ---- THE CEILING -----------------------------------------------------
    # An expected-targets number, not last year's -- the same blend Volume
    # reads, so a receiver whose job grew is capped on the job he has.
    _t = pd.to_numeric(cur.get("targets_pg_final"), errors="coerce")
    if _t.isna().all():
        _t = pd.to_numeric(cur.get("targets_pg"), errors="coerce")
    _role = pd.to_numeric(cur.get("role_tgt"), errors="coerce")
    _w = ((1 - VOL_ROLE_W) * _t).add(VOL_ROLE_W * _role, fill_value=0.0)
    _w = _w.where(_t.notna() | _role.notna())
    cur["exp_targets"] = _w
    cur["ppg_ceiling"] = CEIL_BASE + CEIL_SLOPE * _w
    cur["proj_ppg"] = np.where(_w.notna(),
                               np.minimum(cur["proj_ppg"], cur["ppg_ceiling"]),
                               cur["proj_ppg"])

    cur["position"] = "WR"
    if "proj_games" not in cur.columns:
        cur["proj_games"] = 17.0
    cur["proj_games"] = (pd.to_numeric(cur["proj_games"], errors="coerce")
                         .fillna(17.0).clip(lower=1.0, upper=17.0))

    board = rankings.build_rankings(
        cur[["player_id", "player_name", "position", "proj_ppg", "proj_games"]],
        ppg_col="proj_ppg")

    # Walk the BOARD, not the profile table -- build_rankings has already sorted
    # by value over replacement, and its rank column is `overall_rank`. Reading
    # a "rank" key that does not exist is how every receiver ends up tied at 999.
    by_id = {str(r["player_id"]): r for r in cur.to_dict("records")}
    payload = []
    for _, br in board.iterrows():
        pid = str(br["player_id"])
        row = by_id.get(pid, {})
        flags = _row_flags(row)
        payload.append({
            "rank": int(br["overall_rank"]),
            "player_id": pid,
            "name": br.get("player_name") or row.get("player_name"),
            "team": row.get("team"),
            "archetype": "",
            "mover": bool(row.get("mover", False)),
            "starter": bool(row.get("is_starter", False)),
            "depth_rank": _r(row, "depth_rank", 0),
            "proj_ppg": _r(row, "proj_ppg"),
            "ceil": _r(row, "ppg_ceiling"),
            "proj_total": _r(br, "proj_points_total", 1) if hasattr(br, "get") else None,
            "tier": int(br.get("tier", 0)) if hasattr(br, "get") else 0,
            "vor": _r(br, "vor", 1) if hasattr(br, "get") else None,
            "career_games": _r(row, "career_games", 0),
            "age": _r(row, "age", 0),
            # volume and opportunity
            "targets_pg": _r(row, "targets_pg"),
            "targets_pace": _r(row, "targets_pace", 0),
            "exp_targets": _r(row, "exp_targets"),
            "target_share": _r(row, "target_share", 3),
            "air_yards_share": _r(row, "air_yards_share", 3),
            "wopr": _r(row, "wopr", 3),
            "route_share": _r(row, "route_share", 3),
            "est_routes": _r(row, "est_routes", 0),
            "snap_pct": _r(row, "snap_pct", 3),
            # efficiency
            "yprr": _r(row, "yprr", 2),
            "fd_rr": _r(row, "fd_rr", 4),
            "ypc": _r(row, "ypc"),
            "yac_pc": _r(row, "yac_pc"),
            "adot": _r(row, "adot"),
            # production
            "rec_pg": _r(row, "rec_pg"),
            "rec_yds_pg": _r(row, "rec_yds_pg"),
            "rec_fpg": _r(row, "rec_val"),
            "rush_fpg": _r(row, "rush_val"),
            "td": _r(row, "td", 1),
            "exp_td": _r(row, "exp_td", 1),
            "td_gap": _r(row, "td_gap", 1),
            "ts_trend": _r(row, "ts_trend", 3),
            "route_trend": _r(row, "route_trend", 3),
            "yr_in_league": _r(row, "yr_in_league", 0),
            # availability
            "durability": _r(row, "durability"),
            "avail_games": _r(row, "avail_games"),
            "avail_risk": _r(row, "avail_risk"),
            "injury_risk": _r(row, "injury_risk"),
            "games": _r(row, "proj_games", 1),
            "games_note": row.get("games_note") or "",
            "injury": row.get("injury") or "",
            "clay_rank": _r(row, "clay_rank", 0),
            "rookie": bool(row.get("prior_source") == "clay"),
            "wr_flags": flags,
            "indices": {g: _r(row, g, 1) for g in GROUPS},
            "signals": {k: _r(row, k, 4) for k in SIGNALS if k in cur.columns},
        })
    payload.sort(key=lambda q: q["rank"])

    out = {"payload": payload, "calib": {"a": float(a), "b": float(b), "knots": knots},
           "backtest": bt or {}, "weights": dict(weights), "groups": GROUPS}
    if extra:
        out.update(extra)
    return out


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------
def run(weekly, team_season, players, scoring_rules, season, weights=None,
        snaps=None, pbp=None) -> dict:
    """Backtest-style run: rebuild one completed season from what came before."""
    weights = weights or DEFAULT_WEIGHTS
    sa = season_aggregates(weekly, scoring_rules, snaps, pbp)
    if sa.empty:
        return _empty(weights)
    pool = _recent_pool(sa)
    prof = entering_profiles(sa, team_season, players, pool)
    if prof.empty:
        return _empty(weights)
    prof = attach_role_window(prof, sa, players)
    prof = add_indices(prof, weights)
    info: dict = {}
    a, b = calibrate(prof[prof["season"] < season], info=info)
    bt = backtest(prof)
    cur = prof[prof["season"] == season].copy()
    return _assemble(cur, a, b, bt, weights, {"calibration": info})


def build_upcoming(sa, team_season, players, current_map, season, pool) -> tuple:
    """A row for every receiver on a 2026 depth chart, history or not."""
    birth = _birth_map(players)
    wt = win_totals()
    fwd = implied_totals()
    clay = clay_projections()
    rows, skipped = [], []
    for _, cm in current_map.iterrows():
        pid = str(cm.get("gsis_id") or "")
        if not pid or pid == "nan":
            continue
        pdf = sa[sa["player_id"] == pid].sort_values("season")
        b = _bundle(pdf, season) if not pdf.empty else None
        if b is None:
            b = _clay_bundle(clay.get(pid))
        if b is None:
            skipped.append(cm.get("name") or pid)
            continue
        team = cm.get("team")
        age = np.nan
        by = birth.get(pid)
        if by:
            age = season - by
        c = clay.get(pid)
        rows.append({
            "player_id": pid,
            "player_name": cm.get("name"),
            "season": season,
            "team": team,
            "actual_ppg": np.nan,
            "actual_games": np.nan,
            "age": age,
            "durability": b.get("dur3", np.nan),
            "win_total": wt.get((season, team)),
            "implied_fwd": fwd.get((season, team)),
            "is_starter": bool(cm.get("is_starter", False)),
            "depth_rank": cm.get("depth_rank"),
            "clay_rank": (float(c["clay_rank"]) if c is not None
                          and pd.notna(c.get("clay_rank")) else np.nan),
            **b,
        })
    up = pd.DataFrame(rows)
    if up.empty:
        return up, skipped
    up["mover"] = (up["team"] != up["prev_team"]) & up["prev_team"].notna()
    return _merge_team_env(up, team_season), skipped


def run_upcoming(weekly, team_season, players, current_map, scoring_rules, season,
                 weights=None, snaps=None, pbp=None) -> dict:
    """The board. Historical seasons fit the curve; the upcoming one rides it."""
    weights = weights or DEFAULT_WEIGHTS
    WARNINGS.clear()
    sa = season_aggregates(weekly, scoring_rules, snaps, pbp)
    if sa.empty:
        return _empty(weights)
    pool = _recent_pool(sa)
    hist = entering_profiles(sa, team_season, players, pool)
    up, skipped = build_upcoming(sa, team_season, players, current_map, season, pool)
    if up.empty:
        return _empty(weights, {"skipped_rookies": skipped})

    allp = pd.concat([hist, up], ignore_index=True, sort=False)
    allp = attach_role_window(allp, sa, players)
    allp = add_indices(allp, weights)

    info: dict = {}
    a, b = calibrate(allp[allp["season"] < season], info=info)
    bt = backtest(allp)

    cur = allp[allp["season"] == season].copy()
    keep = (pd.to_numeric(cur["career_games"], errors="coerce").fillna(0) >= MIN_CAREER_GAMES)
    if "prior_source" in cur.columns:
        keep = keep | (cur["prior_source"] == "clay")
    cur = cur[keep]

    return _assemble(cur, a, b, bt, weights, {
        "skipped_rookies": skipped,
        "snap_coverage": snap_coverage(sa),
        "calibration": info,
        "warnings": list(WARNINGS),
    })
