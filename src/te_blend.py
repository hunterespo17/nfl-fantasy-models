"""
TIGHT END PROJECTIONS -- the receivers' machine, re-fitted to a position that
only lets one man play.

Read src/wr_blend.py first. The shape here is deliberately identical -- season
aggregates, entering profiles, percentile indices, a weighted composite, a
calibration curve fitted to what tight ends actually scored -- so that everything
downstream (ratings, report, the site) needs no new plumbing. Nothing in the
FRAMEWORK is new. What follows is only the places where a tight end is not a
wide receiver, and every one of them is a measurement rather than an opinion.

Everything below was fitted on the same cached 2018-2025 nflverse data the other
three boards use: 1,028 tight end seasons, 95.4% snap coverage (96.4% on seasons
of eight games or more), 472 back-to-back pairs.

WHAT IS DIFFERENT, AND WHY
--------------------------

THE SIGNAL ORDER IS THE SAME. VOLUME STILL WINS. Against next season's points
per game, and how well each repeats year to year: WOPR 0.72/0.81, receiving
yards per game 0.75/0.78, points per game 0.74/0.74, target share 0.72/0.79,
targets per game 0.71/0.78, air yards share 0.70/0.81, catches per game
0.70/0.75, yards per route 0.62/0.60, route share 0.59/0.68, first downs per
route 0.57/0.55, touchdowns 0.55/0.43, yards per catch 0.26/0.28, average depth
of target 0.20/0.40, yards after catch per catch 0.09/0.13. Same conclusion the
receivers' file reached, on a different population: how much a man is thrown at
beats how well he does with it, and it is not close.

BUT ROUTE SHARE IS A WEAKER SIGNAL HERE, AND THE GATE HAS TO MOVE. At receiver,
route share correlates 0.66 with next season. At tight end it is 0.59, and the
level is completely different: the average TE1 runs 73% of his team's routes,
which is BELOW the receivers' 75% gate. Screening tight ends at the receivers'
bar would fail the median starter at the position. See ROUTE_GATE.

YARDS PER ROUTE BEATS FIRST DOWNS PER ROUTE -- the exact reverse of receiver.
0.62 against 0.57 on next season, 0.60 against 0.55 on repeatability. So
FD_EFF_W flips from the receivers' 0.55 to 0.45. Heath's first-down insight
still earns its badge; it just stops leading the efficiency blend.

YARDS AFTER CATCH IS NOISE. 0.09 against next season, 0.13 year to year. It is
still shown on the panel, because it is one of the numbers tight ends get argued
about with, and showing it next to what actually predicts is the point.

THE DEPTH CHART IS A CLIFF, NOT A SLOPE. This is the single biggest structural
difference at the position. Receiver rooms share; tight end rooms do not -- one
man plays and the rest block. Mean route share and team target share by rank
within a team-season: TE1 0.727 / 0.147 / 6.82 ppg, TE2 0.450 / 0.068 / 2.99,
TE3 0.283 / 0.045 / 1.83, TE4 0.186 / 0.035 / 1.40. The TE1-to-TE2 target share
gap is a factor of 2.2. The WR1-to-WR2 gap is a factor of 1.28. Because the job
carries that much more information here, VOL_ROLE_W goes up from 0.30 to 0.35.

VEGAS MATTERS ABOUT TWO THIRDS AS MUCH AS IT DOES AT RECEIVER, AND IT ARRIVES BY
A DIFFERENT ROAD. A team's implied total correlates +0.31 with what its tight
end room scores, against +0.54 for its receivers and +0.52 for its backs; on the
early lines the model actually reads, +0.25 against +0.40 and +0.40. So the
weight comes down from the receivers' 14 to 9. The mechanism is worth knowing,
because it changes where the weight goes: a high implied total buys the TE room
touchdowns (+0.41) and points (+0.31) far more than it buys targets (+0.10), and
it buys the room's SHARE of the passing pool essentially nothing (+0.03). Rising
tides raise tight ends by putting them in the end zone, not by throwing to them
more. That is why Scoring goes UP from 4 to 6 as Vegas comes down.

NO SPREAD FACTOR, for the same reason as the other boards -- implied total IS
(total line + spread) / 2. Adding spread on top of it moves R-squared 0.0296 to
0.0296 and leaves a coefficient of +0.001.

CROWDED ROOMS DO NOT EXIST AT THIS POSITION, SO NOTHING IS FLAGGED. The
receivers' board names five crowded offences without deducting anything. I ran
the equivalent test here and there is nothing to name: across 254 TE1 seasons,
the TE1's points per game correlates +0.004 with the second tight end's route
share. TE1s average 7.83 points a game when the TE2 runs 15-30% of routes, 6.98
when the TE2 runs more than half. A blocking tight end is not competition. The
constant stays in the file as an empty set so nothing downstream has to change.

THE CAREER WINDOW OPENS LATER AND STAYS OPEN LONGER. Within-player change in
points per game entering each season: year 2 +0.40, year 3 +0.29, year 4 +0.28,
year 5 -0.69, year 6 -0.05, year 7 -0.18, year 8 -0.89, year 9 -1.39. The peak
is year four, not year two, and the decline does not really begin until year
eight. Receivers peak at two-to-three and start walking down at six. So the
explicit table runs to year seven here rather than year five.

TOUCHDOWNS ARE REGRESSED HARDER THAN ANYWHERE ELSE ON THE SITE. A tight end's
touchdown count predicts next season's at 0.433; a yards-based expectation
predicts it at 0.550 -- the gap is wider than at receiver, so the count deserves
less of itself. K_TD is 40 against the receivers' 18 and the backs' 10: a
sixteen-game season keeps 29% of its own scores.

ROUTES ARE ESTIMATED, NOT COUNTED -- inherited unchanged from the receivers'
file, including the trap in the denominator. pbp's `pass` column is already 1 on
every sack, so dropbacks are `sum(pass)`, NOT `pass + sack`.

THE CEILING SHIPS ON DAY ONE, and it is steeper here because the position's
points come in lumps. See CEIL_SLOPE.

ONE THING THIS BOARD DOES NOT DO, SAID OUT LOUD. Replacement level for tight end
comes out of rankings.replacement_ranks() as TE12 -- twelve teams, one starter,
and none of the flex spot, which the league config splits between backs and
receivers only. In a real 12-team half-PPR league some managers do start a second
tight end in the flex. That would push replacement nearer TE14-15 and lift every
tight end's value against the field. It is a LEAGUE setting, not a modelling
choice, so it is left alone and flagged here rather than quietly changed.
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
# have been. Measured on 472 back-to-back tight end seasons. The raw count
# predicts next year's at 0.433 and a yards-based expectation at 0.550 -- so
# unlike receiver, where the two were close, here the count is clearly the worse
# of the two numbers and is treated accordingly. Blending:
#
#     K=18  0.528     K=40  0.5457  <- this
#     K=24  0.536     K=50  0.5482
#     K=30  0.541     K=60  0.5497
#                     K=120 0.5517  (the peak, and effectively "ignore the count")
#
# The curve is flat from 40 up, so 40 is the gentlest setting that gets the
# benefit. A 16-game season keeps 29% of its own scores, against 47% at receiver
# and 62% at running back. Tight end touchdowns are the noisiest event the site
# projects: a red-zone role can appear and vanish with one coordinator change.
K_TD = 40.0

# How much career length is worth against one season's rate, in the talent
# blend. Higher than the receivers' 10, and measured. A tight end's career-to-
# date rate correlates with what he does this season at 0.508 when he has 6-11
# career games behind him, 0.697 at 12-19, 0.738 at 20-34 and 0.766 at 35-59 --
# so a half-season of career snaps is genuinely uninformative, worse than the
# 27-row 1-5 game bucket. 14 puts the halfway point of trust at 14 career games,
# which is where the measured curve actually crosses.
K_CAREER = 14.0

# What counts as a season worth learning from. Down from the receivers' 12 to
# the backs' 10, and measured rather than assumed. A season's points per game
# predicts the next season's at 0.539 when it is 7-9 games long, 0.710 at 10-12,
# 0.710 at 13-15 and 0.696 at 16-17. The break is at ten, and it is a real
# break, not a slope. Cumulatively the sample peaks there too: 10+ games gives
# 0.748 against 0.740 at 12+ and 0.729 at 14+, so demanding twelve throws away
# rows without buying accuracy.
HEALTHY_GAMES = 10

# How many seasons back the model will look. Four, and now measured rather than
# inherited. Each prior season on its own predicts at 0.741 (one year back),
# 0.657 (two), 0.593 (three) -- and then 0.638 and 0.632, which is survivorship,
# not signal: only the good ones are still playing five years later. As a
# weighted blend the last N seasons predict at 0.741 (N=1), 0.749, 0.751, 0.753,
# 0.753. Four is the last N that buys anything at all.
RECENCY = 4

# Career games before a player is allowed onto the board on his own record. This
# is an INCLUSION floor, not a trust weight -- anyone Clay projects comes on
# regardless, which is how rookies and new starters get rows.
MIN_CAREER_GAMES = 6
MIN_CAL_ROWS = calibration.MIN_ROWS

# ---------------------------------------------------------------------------
# THE WORKLOAD CEILING
# ---------------------------------------------------------------------------
# Measured on 829 tight end seasons 2018-2025 with 4+ games. Half-PPR points per
# target has a 99th-percentile envelope of 2.50 at two-to-four targets a game,
# 2.31 at four-to-six, 2.01 at six-to-eight and 1.78 above eight -- steeper than
# the receivers' at every workload, because tight end scoring is lumpier: a
# six-target tight end who catches two touchdowns has a bigger week than a
# six-target receiver ever will.
#
# Candidates, and what share of real tight end seasons finished above each:
#
#     1.0 + 1.60 x targets    8.2% of all seasons, 10.2% of 3+ target, 9.0% of 5+
#     1.0 + 1.80 x targets    4.8%   4.0%   2.3%
#     1.0 + 2.00 x targets    2.9%   2.0%   0.8%   <- this
#     1.0 + 2.10 x targets    2.3%   1.0%   0.8%
#
# 2.00 clips 24 seasons of 829, and the list is exactly who it should be: mostly
# Taysom Hill, who is a quarterback filed at tight end and whose points do not
# come from targets at all, plus Tucker Kraft 2025, Jared Cook 2019, Will Dissly
# 2019, Robert Tonyan 2020 and Mark Andrews 2024 -- historic touchdown seasons
# nobody should be projecting forward.
#
# Anything this clips MUST be published on the row and re-applied in the page's
# JavaScript, because the reader recomputes every projection on every slider
# drag. See _assemble(), and `capped()` in src/report.py.
CEIL_BASE = 1.0
CEIL_SLOPE = 2.00

# ---------------------------------------------------------------------------
# WHAT A DEPTH-CHART SLOT IS ACTUALLY WORTH
# ---------------------------------------------------------------------------
# Mean route share by tight end rank within team-season, on measured snap data
# 2018-2025. Same construction as the receivers' table -- each is that player's
# own share of his team's dropbacks -- and the contrast with it is the whole
# story of the position:
#
#   rank      n    route share   team target share   mean ppg      (WR route)
#   TE1     254      0.727            0.147            6.82          0.840
#   TE2     254      0.450            0.068            2.99          0.746
#   TE3     202      0.283            0.045            1.83          0.606
#   TE4      75      0.186            0.035            1.40          0.405
#   TE5      10      0.145            0.030            1.46          0.260
#
# The receivers' rows walk down. These fall off a step. A team's second receiver
# still runs three quarters of the routes; a team's second tight end runs fewer
# than half, and is targeted less than half as often as the first.
SLOT_ROUTE = {1: 0.727, 2: 0.450, 3: 0.283, 4: 0.186, 5: 0.145}

# Mean TEAM target share at each rank, from the same rows. This is what Role
# converts into an expected volume when a player has no measured season to read.
SLOT_TGT_SHARE = {1: 0.147, 2: 0.068, 3: 0.045, 4: 0.035, 5: 0.030}

# HOW MUCH OF THE SPOT COMES FROM LAST SEASON RATHER THAN THE PUBLISHED CHART.
# Inherited unchanged from the receivers' board, where it was argued out in full:
# the tape is a measurement of last year's team and of however healthy he was;
# the chart is this year's information but is somebody's guess made in shorts.
# The weights are how much the tape deserves to be believed.
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
# THE ROUTE GATE, RE-FITTED. The receivers' gate is 0.75. It cannot be used here:
# among tight ends with eight or more games the median route share is 0.503 and
# the 75th percentile is 0.684, so the average starting tight end -- the TE1 row
# above, at 0.727 -- sits below the receivers' bar. A 0.75 screen at this
# position fails most of the players it is supposed to find.
#
# Re-fitted on 472 back-to-back pairs, of the 33 tight end seasons that reached
# 10 points a game, the share that had cleared each gate the year before:
#
#     0.50 -> 91%      0.70 -> 76%
#     0.60 -> 88%      0.75 -> 73%
#     0.65 -> 88%      0.80 -> 61%
#
# 0.65 is the last bar that still holds 88% of the hits, and it separates: 140
# tight ends cleared it, scoring 7.04 points a game the following season against
# 3.48, with 20.7% reaching double digits against 1.3%.
#
# Note the bar for "worth having" is 10 points a game here, not the receivers'
# 12. That is the position, not a softer test -- 10 ppg is a top-six tight end.
ROUTE_GATE = 0.65

# THE FIRST-DOWN BADGE. First downs per route run, on a real sample of routes.
#
# Same argument as the receivers' file: Heath states this at 0.115, his routes
# are charted and ours are estimated, so the constant does not survive the trip
# and has to be re-fitted rather than copied. Tight end rates run lower again --
# among tight ends with 150+ estimated routes the median is 0.0385 and the 90th
# percentile 0.0736, so the receivers' 0.095 flags nobody at all.
#
# Across 395 seasons with 200+ estimated routes, sorted by the FOLLOWING year:
#
#     0.060  ->  87 flagged, 7.69 ppg next season vs 4.13, 25.3% reach 10+
#     0.065  ->  71 flagged, 7.99 ppg next season vs 4.24, 28.2% reach 10+
#     0.070  ->  55 flagged, 8.31 ppg next season vs 4.36
#
# The route minimum drops from the receivers' 250 to 200 for the same reason the
# gate moved: tight ends run fewer routes, and 250 would exclude most starters.
#
# It is a BADGE, not a factor, and deliberately so: the edge concentrates at the
# top of the board (+0.07 points for tight ends already scoring 5-8, +0.41 in the
# 8-11 band, +2.97 above 11), so weighting the whole board on it would be reading
# a top-of-market signal into the last two rounds.
FD_RR_BADGE = 0.065
FD_RR_MIN_ROUTES = 200

# ---------------------------------------------------------------------------
# CROWDED ROOMS -- MEASURED, AND THERE IS NOTHING THERE
# ---------------------------------------------------------------------------
# The receivers' board names five crowded offences and deducts nothing, on the
# grounds that the crowding claim is about ADP rather than production. At tight
# end there is not even that much to say. Across 254 TE1 seasons, the TE1's
# points per game correlates +0.004 with the second tight end's route share and
# -0.177 with the second tight end's target share -- and by band, the TE1
# averages 7.83 points a game when his backup runs 15-30% of routes, 6.69 at
# 30-50%, and 6.98 above half. There is no monotone effect to model, and the
# reason is obvious once stated: the second tight end is usually on the field to
# block, and a blocking tight end is not competition for targets.
#
# The name stays so that _row_flags and the site do not have to change shape.
# The set is empty because the honest answer is that nothing belongs in it.
CROWDED_TEAMS: set[str] = set()

# ---------------------------------------------------------------------------
# THE CAREER WINDOW
# ---------------------------------------------------------------------------
# Change in points per game entering each season, measured WITHIN player so that
# survivorship cannot flatter the late years: year 2 +0.40, year 3 +0.29, year 4
# +0.28, year 5 -0.69, year 6 -0.05, year 7 -0.18, year 8 -0.89, year 9 -1.39.
#
# So the position climbs for three seasons, peaks in year four, dips, holds a
# plateau through years six and seven and only then goes. The rate of finishing
# as a TE12 backs it up: year 1 8.5%, year 2 12.1%, year 3 10.2%, year 4 14.0%,
# year 5 10.1%, year 6 16.4%, year 7 15.5%, year 8 14.0%.
#
# Compare receivers, who peak at years two and three and are docked from six, and
# backs, who fall off the end of the table entirely. A 28-year-old tight end in
# his sixth season is not an old player; he is usually a player who has just
# figured it out. The explicit table therefore runs to year seven here, and
# add_indices switches to the LATE score at year eight rather than year six.
WINDOW_SCORES = {1: 76.0, 2: 86.0, 3: 94.0, 4: 100.0, 5: 85.0, 6: 84.0, 7: 81.0}
WINDOW_LATE = 64.0        # year eight and beyond, no elite season behind him
WINDOW_PROVEN = 76.0      # same, but he has actually been a TE6 -- docked, not written off

# What counts as having proved it. The receivers' board uses top 16 against a
# replacement level of WR30-36. Replacement here is TE12, so the equivalent
# "meaningfully inside it" mark is top 6, on a real sample of games.
ELITE_RANK = 6
ELITE_MIN_GAMES = 8

# ---------------------------------------------------------------------------
# DRAFT CAPITAL
# ---------------------------------------------------------------------------
# Next-season points per game by round, years one to five: R1 7.10, R2 5.52,
# R3 4.50, R4 3.84, R5 3.34, R6 2.35, R7 2.21, undrafted 2.56. Cleanly monotonic
# -- cleaner than the receivers' table, where R3 came out above R2 on noise --
# and worth about 14.7 points of this scale per point of ppg.
#
# The undrafted number sitting a hair above round seven is 46 rows against 21 and
# well inside noise, so the scale below is smoothed monotonic rather than fitted
# to it. It fades out over three seasons, because after three years of real snaps
# the snaps are the better evidence and the draft slot is just a fact about 2023.
DRAFT_SCORE = {1: 100.0, 2: 77.0, 3: 62.0, 4: 52.0, 5: 45.0, 6: 30.0, 7: 28.0}
DRAFT_UNDRAFTED = 25.0
DRAFT_FADE_SEASONS = 3.0

# The most of the Talent factor draft capital is ever allowed to be. It used to
# be all of it in year one, which meant a rookie's own projection did not touch
# his Talent score at all. Carried across from the receivers' board.
DRAFT_MAX_W = 0.6

# How much of Volume comes from the job the depth chart implies rather than the
# targets he actually got. Up from the receivers' 0.30, because of the slot table
# above: the TE1-to-TE2 target share gap is a factor of 2.2 against the
# WR1-to-WR2 gap of 1.28. Knowing which tight end a team plays tells you more
# than knowing which receiver it plays, so the job is allowed to carry more.
VOL_ROLE_W = 0.35

# Within Volume, how the two best predictors split. Target share (0.72 next-year,
# 0.79 sticky) and targets per game (0.71, 0.78) are as close here as they were
# at receiver, so an even split is still the honest answer.
TS_VOL_W = 0.5

# Within Efficiency, how first downs per route split against yards per route.
# THIS IS FLIPPED FROM THE RECEIVERS' BOARD, and it is a measurement, not a
# preference: at receiver first downs lead on both axes (0.55/0.57 against
# 0.56/0.55). At tight end yards per route wins both (0.62/0.60 against
# 0.57/0.55). So the number goes from 0.55 to 0.45 and yards per route leads.
FD_EFF_W = 0.45

# How many finished seasons the upcoming one is measured against. Every factor
# on this board is a rank inside its own season, and the upcoming season is a
# shorter list than a finished one. A shorter list has a lower ceiling, which
# costs the whole upper board points for no reason but the length of the list.
# So the upcoming season is not ranked against itself: each of its raw numbers is
# placed into the last three finished seasons one at a time and the three
# placements averaged. Argued out in full in src/wr_blend.py.
REF_SEASONS = 3

NEWS_W = 1.0
MIN_GAMES_RATIO = 0.35
GUIDE_GAMES_FLOOR = availability.GUIDE_FLOOR

# How much of a rookie's row may lean on somebody else's projection.
#
# Carried across from the receivers' board, where 0.5 was found to be too little:
# a veteran needs ten career games to earn 0.5, so a rookie was being told his
# whole projected season counts for as much as ten games of somebody else's
# snaps. It is also a second regression -- the Clay row is already a smoothed
# full-season expectation. 0.7 leaves real uncertainty on a player nobody has
# watched take an NFL snap without flattening the whole class onto one number.
ROOKIE_TRUST = 0.7

# ---------------------------------------------------------------------------
# WHAT THE PLAYER PANEL SHOWS
# ---------------------------------------------------------------------------
# Raw column -> the label a human reads. Adding a key here surfaces that column
# on the detail panel; it does not put it in the model. Several are here
# precisely BECAUSE they are not in the model -- yards per catch (0.26 against
# next season), average depth of target (0.20) and yards after catch per catch
# (0.09, which is noise) are numbers tight ends get argued about with, and
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
# Volume, Opportunity and Role are 47 of the 100 between them -- more than the
# receivers' 44, which is the slot table made arithmetic. At a position where the
# second man on the depth chart is targeted less than half as often as the first,
# having the job IS most of the answer.
#
# Three numbers moved off the receivers' board, and all three are measured:
#
#   Vegas 14 -> 9    the team-level correlation is +0.31 here against +0.54 there
#   Role  10 -> 7    route share predicts at 0.59 here against 0.66 there
#   Scoring 4 -> 6   because of where the Vegas signal went: a high implied total
#                    buys the tight end room touchdowns (+0.41) far more than it
#                    buys it targets (+0.10), so the effect belongs in Scoring
#
# Efficiency stays at 11 -- the blend inside it flipped, but its total worth
# against volume did not.
DEFAULT_WEIGHTS = {
    "Volume": 22,        # target share + targets per game, tilted to the job
    "Opportunity": 18,   # WOPR -- target share plus air yards share
    "Efficiency": 11,    # yards per route + first downs per route
    "Vegas": 9,          # implied team total + win total
    "Talent": 9,         # career rate, shrunk toward the job; draft capital when young
    "Availability": 8,   # age curve x durability
    "Role": 7,           # route share, and what the depth chart implies
    "Window": 6,         # year in league
    "Scoring": 6,        # touchdowns, regressed hard to a volume expectation
    "Situation": 4,      # pace and how much the offence throws
    "Matchup": 0,        # off by default, same as the other three boards
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
    """Tight ends hold their value later than anyone else on the board.

    Backs start being docked at 26 and lose 9 points a year; receivers at 27 and
    lose 6. This one is flat through 29 and loses 4, and the reason is in the
    window numbers above: within-player change in points per game does not go
    properly negative until year eight, which for a tight end drafted at 22 is
    age 29. Mean points per game by age band says the same thing even more
    strongly -- 21-23 4.29, 24-25 3.94, 26-27 3.83, 28-29 4.66, 30-31 4.21,
    32-34 6.27 -- though that table is heavy with survivorship at the top end,
    which is exactly why the slope here is gentle rather than positive.
    """
    if age is None or (isinstance(age, float) and np.isnan(age)):
        return 0.85
    a = float(age)
    if a < 22:
        return 0.95
    if a <= 29:
        return 1.0
    return max(0.40, 1.0 - (a - 29) * 0.04)


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
        path = config.DATA_DIR / f"clay_te_{config.UPCOMING_SEASON}.csv"
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
    return availability.hand_notes("TE")


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
    counts them twice and inflates every tight end's route count by about 6%.
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
    """One row per tight-end-season, with everything the indices read.

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
    # ---- the team's WHOLE target pool, counted before the position filter ----
    # SLOT_TGT_SHARE was measured off the weekly file's `target_share`, and that
    # column is a share of everything the offence threw -- backs and receivers
    # included, about 35 a game. Summing targets after the TE filter counts only
    # about 5. The error this guards against is far bigger here than it was on
    # the receivers' board: multiplying a share-of-everything by a pool-of-tight-
    # ends-only would understate the position by a factor of seven. So the pool
    # is counted the same way the shares were: all positions, then divided by the
    # games the team actually played.
    _all = w[(w["season_type"].str.upper() == "REG") & w["season"].notna()
             & w["team"].notna()]
    team_tgt = (_all.groupby(["season", "team"], as_index=False)
                .agg(t_tgt=("targets", "sum"), t_gm=("week", "nunique")))
    team_tgt["team_tgt_pg"] = team_tgt["t_tgt"] / team_tgt["t_gm"].replace(0, np.nan)

    w = w[(w["position"] == "TE") & (w["season_type"].str.upper() == "REG")].copy()
    w = w[w["season"].notna()]

    # A column that came back empty is the one failure this file cannot survive
    # and will not otherwise announce: the board still builds, every tight end
    # scores zero, and the ranking becomes noise. Catch it at the door.
    for _c in ("targets", "receptions", "rec_yds"):
        if not w.empty and float(w[_c].abs().sum()) == 0.0:
            raise ValueError(
                f"season_aggregates: every '{_c}' value is zero. The weekly file is "
                "missing that column or it did not parse — the tight end board would "
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
    """Snap share per tight-end-season. Route share is read straight off this.

    Two-tier match, and the second tier has to be EARNED. Exact normalised name
    plus team first; the first-initial-plus-surname fallback only where that key
    is unique on both sides of the season.

    That last clause is the whole point, and it bites harder here than anywhere.
    On a single-tier fallback "d smith" is both Dalton Schultz's era-mates and,
    on this position list, "j smith" collides Jonnu Smith with Jeff Smith, while
    "t hill" collides Taysom Hill with nobody at all only by luck. Averaging two
    players' snap shares hands each of them the other's route share, silently,
    on a number that feeds three separate factors. Anything that survives both
    tiers is warned about rather than guessed at.
    """
    sa = sa.copy()
    sa["snap_pct"] = np.nan
    if snaps is None or len(snaps) == 0:
        return sa
    try:
        s = snaps.copy()
        pos = _first(s, ["position", "pos"]).astype(str).str.upper()
        s = s[pos == "TE"]
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
    """Recency-weighted read of one tight end, as of the start of `as_of`.

    Only seasons he was actually available for -- a six-game year is a fact
    about his hamstring, not about his rate -- and only inside the recency
    window. Weights 0.6 / 0.27 / 0.13, same as the other three boards, and see
    RECENCY above for why four years back is the right window at this position.
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
        # How big last season's job was, 0 to 1, where 1 is a true every-down
        # tight end's six targets a game. Only availability.py reads it, and only
        # to work out how many games he plays NEXT year. Without it "played 11
        # games" describes both a starter who missed six weeks hurt and a third
        # tight end who was simply inactive, and the two are not the same bet.
        # The denominator is 6 rather than the receivers' 9 because that is what
        # the position's alpha workload actually is: the mean TE1 sees 0.147 of a
        # 35-target pool, which is 5.1 a game, and the top of the position lives
        # around six to eight. Leaving it at 9 would have told availability.py
        # that every tight end in the league is a part-time player.
        "prev_role": float(np.clip(
            float(last.get("targets_pg") or 0.0) / 6.0, 0.0, 1.0)),
        "prev_team": last.get("team"),
        "prior_source": "history",
    })

    # TRENDS. Shown, not weighted -- measured against next season these come in
    # at -0.02 and -0.01, which is nothing. They are on the panel because a
    # tight end whose route share is climbing reads differently to one whose is
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
    """One row per (tight end, completed season) -- what was knowable beforehand."""
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
    for the incoming class until well after the draft -- every 2026 tight end in
    the file has draft_round blank and draft_year blank while carrying
    rookie_season 2026. Reading that blank as "round 0, undrafted" priced
    seventeen of the eighteen rookies on this board at DRAFT_UNDRAFTED, and
    because draft capital has not faded at all in year one, that 22.0 WAS their
    entire Talent score: a real first-round tight end and a camp body got the
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
    # file. That keeps a genuinely undrafted 2019 tight end reading as undrafted.
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
    running-back only, and rather than invent a tight-end version this reads the
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

    # Clipped at five rather than the receivers' six: SLOT_ROUTE stops at TE5,
    # because a sixth tight end on a depth chart is a special-teams body and
    # there were only ten TE5 seasons in eight years to measure in the first
    # place. Anything deeper reads as a five, which is already 1.5 points a game.
    p["slot"] = measured.fillna(live).clip(upper=5)
    both = measured.notna() & live.notna()
    p.loc[both, "slot"] = (tape_w[both] * measured[both]
                           + (1.0 - tape_w[both]) * live[both]).clip(upper=5)
    p["tape_w"] = tape_w.where(both)

    # ---- 2. the size of the pool -----------------------------------------
    # The team's whole target pool, shifted forward a season, so a player's role
    # is scaled by how many balls his offence actually throws. season_aggregates
    # counts this BEFORE the position filter, on purpose: SLOT_TGT_SHARE is a
    # share of all targets, so the pool it multiplies has to be all targets too.
    # Counting tight ends only would be a seven-fold haircut on every projection.
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
    slot_f = p["slot"].clip(1, 5).astype(float)
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
    return availability.attach(p, "TE", NEWS_W, MIN_GAMES_RATIO)


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
    # wopr -> air yards -> Volume precisely so a tight end with no WOPR falls
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

    # ---- EFFICIENCY. Both per-route rates, yards leading slightly. This is the
    # one place the tight-end file reverses the receivers'. There, first downs
    # per route is the better of the two on both axes. Here yards per route wins
    # both: 0.618 against next season's points per game where first downs get
    # 0.572, and 0.601 sticky year to year where first downs get 0.546. So
    # FD_EFF_W is 0.45, not 0.55, and the yards term is the majority partner.
    p["Efficiency"] = (FD_EFF_W * pct("fd_rr") + (1 - FD_EFF_W) * pct("yprr"))

    # ---- ROLE. Measured route share, falling back to the slot table.
    rs = pct("route_share")
    p["Role"] = rs.fillna(pct("role_route"))

    # ---- VEGAS. Implied total and win total. Carries 9 here, against the
    # receivers' 14 -- a team's implied total correlates +0.31 with what its
    # tight end room scores, where the same measure gets +0.54 for its receivers
    # and +0.52 for its backs. Two-thirds strength, so two-thirds the weight.
    # It arrives mostly through touchdowns (+0.41 with the room's scores) rather
    # than through targets (+0.10), which is why the Scoring factor next door
    # matters more here than the raw target counts would suggest.
    p["Vegas"] = pd.concat([pct("win_total"), pct("implied_fwd")], axis=1).mean(axis=1)

    # ---- SCORING. The regressed touchdown, not the raw one.
    p["Scoring"] = pct("td_final") if "td_final" in p.columns else pct("exp_td")
    if "exp_td" in p.columns:
        p["Scoring"] = pd.concat([pct("exp_td"), pct("td")], axis=1).mean(axis=1)

    # ---- SITUATION. Pace, and how much the offence throws. Same direction as
    # the receivers' -- pass volume is the friend here, not the run -- but worth
    # only 4 points against their 8. A tight end's share of the pool barely
    # moves with the pass rate (+0.03), so a throwing offence lifts him only by
    # throwing more overall, which the Volume factor is already reading.
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

    # ---- WINDOW. A ramp, not a cliff, and it runs later than the receivers'.
    # The boundary moves from year six to year eight because WINDOW_SCORES now
    # carries real numbers through year seven. Within-player change in points
    # per game does not go properly negative until year eight (-0.89, then -1.39
    # in year nine); years six and seven are -0.05 and -0.18, which is flat, and
    # the TE12-finish rate in those two years is the highest on the table at
    # 16.4% and 15.5%. Docking a sixth-year tight end the way the receivers'
    # board does would be backwards.
    win = yr.map(WINDOW_SCORES)
    late = np.where(p.get("proven", False), WINDOW_PROVEN, WINDOW_LATE)
    p["Window"] = pd.Series(np.where(yr >= 8, late, win), index=p.index).where(yr.notna(), 50.0)

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

    # Give the factors their gaps back before averaging them. See
    # calibration.SPREAD: a percentile rank is uniform by construction, so the
    # right-skewed usage measures lose their distance at the top of the board
    # exactly where the board is being read, and team quality -- which has no
    # skew -- ends up the loudest thing on it. Rank-preserving, so this cannot
    # reorder anyone within a factor; it only changes how far apart they sit.
    p = calibration.stretch_groups(p, GROUPS)

    p["composite"] = composite(p, weights)
    return p


def composite(p: pd.DataFrame, weights: dict | None = None) -> pd.Series:
    weights = weights or DEFAULT_WEIGHTS
    total = sum(weights.values()) or 1
    return sum(w * pd.to_numeric(p[g], errors="coerce") for g, w in weights.items()) / total


def calibrate(p: pd.DataFrame, pos: str = "TE", info: dict | None = None):
    return calibration.fit(p, pos=pos, info=info)


BACKTEST_SEASONS = 3


def backtest(p: pd.DataFrame) -> dict:
    """Walk forward a season at a time; beat last year's points per game or don't.

    Two decisions in here are worth the words, because getting either wrong
    produces a number that looks like a verdict and isn't.

    IT SCORES DRAFTED TIGHT ENDS ONLY. calibration.py's own bug 1 is "the wrong
    crowd": the points scale is fitted on drafted players, because that is the
    crowd the ADP curve it gets subtracted from is built from. Score that scale
    against every tight end who ever ran a route and most of the test set is a
    TE3 who caught eleven balls all year -- and the tight-end pool is worse for
    this than the receivers', because a third of it is blockers who are on the
    field for reasons the box score never records. The scale says five points a
    game; he scored one and a half; "last year he scored one and a half" wins by
    a mile and the model looks broken. It isn't -- it is being asked about people
    it was never built to price, and people nobody drafts.

    IT NEVER FITS ON THE FUTURE. Each test season is scored by a scale fitted
    only on seasons before it, one at a time, then the errors are pooled. A
    single train/test split with the scale fitted once across everything earlier
    is close enough on this data, but this costs nothing and removes the doubt.
    """
    d = p[p["actual_ppg"].notna() & p["composite"].notna()]
    if d.empty:
        return {}
    picks = calibration.drafted_picks("TE")
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
        a, b = calibration.fit(train, pos="TE", info=info)
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
            "population": "drafted tight ends",
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

    THE KEY NAMES ARE THE WIRE FORMAT, NOT THE THRESHOLDS. "gate75" is read by
    name in report.py's filter table, which is deliberately position-blind -- one
    handler serves every board. The name is the receivers' 75% written into a
    key; the number it actually tests is this file's ROUTE_GATE, which is 0.65.
    Renaming it here would mean a second copy of the same handler in the page,
    so the name stays and the caption on the control says 65%.

    "crowded" is always False on this board. CROWDED_TEAMS is deliberately empty
    -- a second tight end costs the first nothing measurable (TE1 points against
    the TE2's route share, r=+0.004 across 254 seasons), so there is nothing to
    name. The key is kept so every board hands the page the same shape, and the
    tight-end filter simply doesn't offer the option.

    The two career-year flags run later than the receivers'. "prime" is years
    three to seven rather than three to five, and "late" starts at eight rather
    than six, matching the window the model itself scores: within-player change
    in points per game is flat at years six and seven (-0.05, -0.18) and only
    turns properly negative in year eight (-0.89).
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
        "prime": bool(yr is not None and 3 <= yr <= 7),
        "ascending": bool(yr is not None and yr <= 2),
        "late": bool(yr is not None and yr >= 8),
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
    # reads, so a tight end whose job grew is capped on the job he has.
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

    cur["position"] = "TE"
    if "proj_games" not in cur.columns:
        cur["proj_games"] = 17.0
    cur["proj_games"] = (pd.to_numeric(cur["proj_games"], errors="coerce")
                         .fillna(17.0).clip(lower=1.0, upper=17.0))

    board = rankings.build_rankings(
        cur[["player_id", "player_name", "position", "proj_ppg", "proj_games"]],
        ppg_col="proj_ppg")

    # Walk the BOARD, not the profile table -- build_rankings has already sorted
    # by value over replacement, and its rank column is `overall_rank`. Reading
    # a "rank" key that does not exist is how every tight end ends up tied at 999.
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
            "te_flags": flags,
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
    """A row for every tight end on a 2026 depth chart, history or not."""
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
