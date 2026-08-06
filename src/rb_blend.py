"""
The RB index-blend model.

Same machine as the QB model: every factor becomes a 0-100 index (a back's
percentile among his peers), and the projection is an EXPLICIT weighted average
of those indices -- weights you can see and change -- calibrated to real fantasy
points per game.

    projection_ppg = a + b * ( sum(weight_i * index_i) / sum(weight_i) )

What's different about running backs, and why:

  * OPPORTUNITY IS THE PRODUCT. A quarterback's job is safe; a running back's
    job is the whole question. So the two biggest things here after raw scoring
    are Volume (how many touches he gets) and Backfield (what share of his own
    team's back-touches he takes). Those are the numbers that repeat.
  * A TARGET IS WORTH MORE THAN A CARRY. In half PPR a target is worth about
    1.8 carries (see TARGET_MULT below for the arithmetic), so "touches" are
    counted weighted, not raw. A back with 12 carries and 5 targets is a bigger
    asset than one with 20 carries and none, and raw touch counts say the
    opposite.
  * THE JOB IS KNOWN BEFORE THE SEASON STARTS. Where a back sits on the depth
    chart in August, multiplied by how much work that offense's backfield
    actually gets, is the Role factor. It is not a guess about the future --
    it is a fact about the present that last year's box score cannot see, and
    it is the single biggest thing this model used to leave on the table.
  * BACKS AGE EARLY, AND THE WINDOW IS A CLIFF, NOT A SLOPE. Every RB who ever
    became a league-winner from inside the first six rounds was either in one
    of his first four seasons OR had already been a league-winner before. So
    Window scores that rule as an OR: year five is a cliff for everyone who
    hasn't already cleared the bar. 85% of league-winning RB seasons came from
    backs 27 or younger, average age 25.1.
  * SHORTER MEMORY. RECENCY is 4 seasons, not the QB model's 5, and a healthy
    season is 10 games instead of 12. Backfields turn over fast and backs miss
    more time; a 2021 workload should not be shaping a 2026 projection.
  * TOUCHDOWNS ARE REGRESSED HARDER (K_TD = 10 vs the QB model's 8). Goal-line
    work moves around between seasons more than yardage does, so a back who
    vultured 14 scores is pulled further back toward what his yards predict.

Movers are handled the way the QB model handles them: a back who changed teams
has his team-based factors -- AND his backfield share -- pulled toward neutral,
because last year's share on last year's depth chart says very little about the
job he's walking into.

There is deliberately no archetype bucket and no hand-maintained backfield file
in here. The receiving-share archetypes were tested against this board and did
NOT explain where it disagrees with the market, so they aren't in the blend on
the strength of a story alone. Everything here is still free and measurable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import availability, calibration, config, rankings, scoring
from . import team_budget

# --- Model constants --------------------------------------------------------
K_TD = 10.0         # TD regression: games needed to fully trust observed TDs
K_CAREER = 10.0     # sample-size regression: shrink strength on career games
HEALTHY_GAMES = 10  # a "healthy" RB season is at least this many games
RECENCY = 4         # never reach back more than this many seasons for talent
REC_VOL_W = 0.5     # Receiving index: share given to target VOLUME vs production
MIN_CAREER_GAMES = 6    # below this we don't have enough to project a back
MIN_CAL_ROWS = calibration.MIN_ROWS   # kept as an alias; the real one lives there

# How many carries one target is worth, in THIS league's scoring.
#
#   a carry   ~ 4.3 yds x 0.1            + 0.031 TD/att x 6      ~ 0.61 pts
#   a target  ~ 0.64 catch x 0.5 (PPR pt) + 5.9 yds x 0.1 + TD   ~ 1.11 pts
#                                                          ratio ~ 1.8
#
# The same arithmetic in FULL PPR gives 2.45, which lands on the 2.55 figure
# Fantasy Points published -- that agreement is why we trust the half-PPR number.
# It is derived from the scoring settings, so if you ever switch back to full
# PPR this constant needs to move to about 2.5.
TARGET_MULT = 1.8

# The most points a back can score off a given workload.
#
# This is a physical bound, not a projection. The composite is a bell that
# bottoms out near the 50th percentile, and the calibration curve maps a
# composite of 50 to about 7.3 points a game -- so before this cap existed,
# EVERY rostered back projected around 7 regardless of whether he was going to
# touch the ball. A team's five backs summed to 27 points a game when a real
# backfield produces 20. It never moved the draft order (those players sit 64th
# and below), but it was wrong.
#
# Measured on 1000 RB seasons, 2018-2025, 4+ games: half-PPR points per weighted
# touch has a p99 envelope that is flat at 0.89-1.00 for any workload of 3+
# touches a game. It only appears to blow up below that, and when you list those
# seasons they are all the same thing -- fullbacks and emergency call-ups who
# vultured a goal-line score on almost no work (85% of them under 4 touches/gm,
# 46% under half a season). That is why the line gets a small intercept instead
# of running through the origin: the intercept covers the touchdown a low-work
# back can steal, the slope covers everything earned.
#
#     0.0 + 1.29 x touches   1.0% of real seasons above it
#     1.0 + 1.10 x touches   0.3%   <- this
#     1.5 + 0.90 x touches   0.3%
#
# It binds on about 38 of 100 rows and on NOBODY in the top 36 -- Gibbs' ceiling
# is 23.1 against a 21.6 projection, so the top of the board is untouched.
CEIL_BASE = 1.0     # points a back can score on essentially no workload
CEIL_SLOPE = 1.10   # additional points per weighted touch per game

# What share of his own team's backfield work a back actually went on to take,
# by the slot he entered the season in. Measured over 653 back-seasons from
# 2018-2025, not assumed:
#
#   slot 1  38.9%   slot 2  22.2%   slot 3  11.5%   slot 4  7.8%   slot 5  5.9%
#
# The gap between slot 1 and slot 2 is the whole reason this factor exists.
SLOT_SHARE = {1: 0.389, 2: 0.222, 3: 0.115, 4: 0.078, 5: 0.059}

# HOW BIG HIS BACKFIELD SHARE ACTUALLY IS, NOT HOW BIG SLOT 1's USUALLY IS.
#
# The table above is a league average. Every lead back in the league reads 38.9%
# of his own backfield, whether he is Ashton Jeanty at 83.1% or a lead back in a
# genuine committee at 45%. That number is all of Role and half of Backfield, so
# the board has been pricing the depth-chart line and never the workload.
#
# Measured against the season each back actually went on to have, over 830 back
# seasons: his own backfield share scores +0.695, the slot table +0.542. Where
# the measurement exists it should be most of the answer -- believed in
# proportion to how much of last season he played and whether it was even for
# this team, the same dial the receivers' board uses for the depth slot itself.
#
#   played 17 last year, same team   0.75 on the tape
#   played 13                        0.53
#   played 9 or fewer                0.30
#   changed teams                    0.15   -- wrong room entirely
#
# ROLE_TAPE 0.0 turns the whole thing off, back to the table alone.
TAPE_W_MAX, TAPE_W_MIN = 0.75, 0.30
TAPE_GAMES_HI, TAPE_GAMES_LO = 17.0, 9.0
TAPE_W_MOVED = 0.15
ROLE_TAPE = 1.0

# AN INJURY IS NOT A REASON TO STOP BELIEVING THE TAPE.
#
# The ramp above asks one question -- how much of LAST season did we watch him in
# this role -- and that question punishes exactly the wrong player. A back who
# held 80% of his backfield for two straight years and then missed five weeks of
# the second one reads as barely-watched, and half his job comes back from a
# league-average table that knows nothing about him. That is the same mistake the
# receivers' board made with CeeDee Lamb, and it gets the same answer: widen the
# window. `prev_games3` is the mean games over the recent seasons and is already
# on every row.
#
# Taking the larger of the two means a healthy player is unaffected (his two
# numbers agree), a player with one lost season is judged on the seasons around
# it, and a player who has been unavailable for years is still discounted,
# because then BOTH numbers are low.
#
# What this does NOT do is excuse him on availability. How many games he plays
# next year is priced separately, off dur3 -- and there the missed time still
# counts against him, as it should. This dial is only about whether we believe
# what we saw when he was on the field.
TAPE_WINDOW = True

# TOP-DOWN: DOES THIS ROSTER ADD UP TO ONE TEAM?
#
# Every share above is a bottom-up read of one player. Nothing checked the sum
# until a reconciliation pass measured it, and the sums were wrong -- badly on
# some rosters. src/team_budget.py holds the measured ceilings and the whole
# argument. Set False to switch the correction off; it is a straight A/B.
TEAM_BUDGET = True

# How hard to pull. 1.0 snaps the roster onto the budget; lower leaves room
# for a genuinely concentrated offence. Set from the A/B, per board.
# Swept 0 -> 1 on 830 back seasons: 0.7215 off, 0.7249 at 0.4, 0.7260 at 1.0.
# Full pull, because this board's gap is a near-uniform table error (top four
# backs given 80% of their own backfield when the real four take 99.6%), and a
# uniform error is exactly the kind you should correct all the way.
BUDGET_LAM = 1.0

# HOW MUCH OF A SEASON HAS TO BE THERE BEFORE ITS RATES ARE BELIEVED.
#
# HEALTHY_GAMES above was being spent as a turnstile -- a ten-game season counted
# whole, a nine-game season counted for nothing, and the direction of the error
# flips on one game either side of the line. These turn the same judgement into a
# weight: 0.15 at four games or fewer, full at fourteen. _bundle() is the only
# reader, and it now applies the 0.6/0.27/0.13 recency weights to the rate
# columns as well, which the docstring always claimed it did and it did not.
CRED_GAMES_LO, CRED_GAMES_HI = 4.0, 14.0
CRED_MIN = 0.15
CRED_MIN_GAMES = 2

# How far a team's backfield workload is pulled back toward the league median.
# Last year's team total is evidence about this year, not a promise.
BF_TO_MEDIAN = 0.25

# Volume = last season's touches per game blended with the touches his slot
# implies. This is the "combo of opportunity and prior output" -- without it,
# Volume is pure box score, so a back who was third on the chart last year
# carries a third-stringer's Volume into a season he starts.
VOL_ROLE_W = 0.25

# Heath's window, scored 0-100. Not an age curve -- a cliff at year five with an
# explicit exemption, because the rule it encodes is an OR: first four seasons,
# OR already a league-winner. A 30-year-old who has done it stays draftable; a
# 27-year-old who never has does not.
WINDOW_SCORES = {1: 90.0, 2: 100.0, 3: 95.0, 4: 85.0, 5: 55.0}
WINDOW_LATE = 30.0      # year six and beyond, never a league-winner
WINDOW_PROVEN = 65.0    # ...unless he already was one
ELITE_RANK = 12         # "has done it before" = a top-12 RB scoring season
ELITE_MIN_GAMES = 8     # ...over a real sample, not four hot weeks

# --- Will he be on the field in September? ----------------------------------
# Everything above this line describes a back's JOB. None of it knows whether
# he's healthy enough to hold it in week one, and that is a real hole: the board
# had Zach Charbonnet at RB16 in August 2026 while the market had him RB42,
# entirely because the model could see he was Seattle's listed starter and could
# not see the knee.
#
# This used to hedge: an expected 11 games got priced as about 13, on the theory
# that a return date is only an estimate. That reasoning was wrong and it is
# worth writing down why, because it is an easy mistake to make twice.
#
# A back projected for 11 games is not being asked to beat a soft August return
# date. The season starts in September and ends in January, so 11 games means
# roughly six REAL games -- weeks that count -- are already spoken for. Hedging
# up to 13 was quietly assuming the good half of that. It is also the wrong shape
# of bet: the upside is capped at 17 while the downside runs all the way to a
# setback and injured reserve, so "split the difference" is not neutral, it is
# optimistic. And the guide's own front page says these are 17-game projections
# with injuries NOT priced in -- so when it singles a back out for 11, that 11 is
# a specific, deliberate carve-out and not a rounding error.
#
#   games_ratio = 1 - NEWS_W * (1 - expected_games / 17)
#
# NEWS_W is 1.0: the number goes in at face value. Charbonnet at 11 games is
# priced as 11 games. Put down what you actually believe, because the model no
# longer argues with you. The dial stays here because it is the honest place to
# turn a source down if one ever deserves it -- not because 11 needs softening.
# A back nobody has reported anything about is 1.0 and is not touched at all.
NEWS_W = 1.0
MIN_GAMES_RATIO = 0.35      # nobody's season gets written off entirely in August

# A guide's games column answers two different questions with one number: "hurt,
# will miss time" and "third on the depth chart, will get mop-up work". Only the
# first is news. The second is a job description, and the job is already priced
# through Role and Backfield share -- taking it a second time here would charge a
# backup twice for being a backup. So a guide number below this is read as a
# depth-chart statement and ignored. Anything YOU type by hand is always taken.
GUIDE_GAMES_FLOOR = availability.GUIDE_FLOOR

# How much of a rookie's projection comes from an outside projection rather than
# from the size of his job. He has no NFL box score at all, so the usual
# sample-size shrink (career_games / (career_games + K_CAREER)) would be exactly
# zero and would rate him purely on his depth-chart slot. Half and half instead:
# the job AND somebody's number for him.
ROOKIE_TRUST = 0.5

# Raw signals surfaced in each back's detail panel, with friendly labels.
SIGNALS = {
    "talent_reg": "Talent · last healthy yrs (reg fp/gm)",
    "talent_final": "Talent · after sample-size reg",
    "rush_val": "Rushing value (reg fp/gm)",
    "rec_val": "Receiving value (reg fp/gm)",
    "carries_pg": "Carries/gm",
    "targets_pg": "Targets/gm",
    "opp_pg": "Weighted touches/gm (last yr)",
    "opp_blend": "Weighted touches/gm · blended w/ role",
    "ppg_ceiling": "Most pts/gm this workload can produce",
    "bf_share": "Backfield share (of team RB work)",
    "bf_carry_share": "Share of team RB carries",
    "bf_target_share": "Share of team RB targets",
    "depth_rank": "Depth-chart slot entering the year",
    "team_bf": "Team backfield touches/gm (last yr)",
    "depth_share": "Share of the backfield his slot gets",
    "role_opp": "Expected touches/gm from his slot",
    "yr_in_league": "NFL season number",
    "snap_pct": "Snap share",
    "ypc": "Yards per carry",
    "ypt": "Yards per target",
    "career_games": "Career games",
    "age": "Age",
    "durability": "Durability (3-yr, games/17)",
    "plays_pg": "Team plays/gm",
    "pass_rate": "Team pass rate",
    "implied_total_avg": "Team implied total (last yr)",
    "implied_fwd": "Vegas implied points/gm",
    "points_pg": "Team points/gm",
    "win_total": "Vegas win total",
    "clay_rank": "Outside guide's RB rank",
    "clay_games": "Games the outside guide expects",
    "proj_games": "Games this board expects",
}

# Factor -> weight (percent). These sum to 100 and are retunable live in the
# report.
#
# These moved a long way in August 2026, and the reason is worth writing down.
# The old set put 76 of its 100 points on percentiles of last season's box
# score, which made the board lean systematically OLD -- it kept paying proven
# veterans for work they had already done and had no way to pay a back for the
# job he is walking into. Against consensus RB ADP the rank correlation was
# 0.836 and the average disagreement 5.6 spots, and the size of the disagreement
# tracked age at +0.40.
#
# Taking 12 points out of Talent and 10 out of Volume to fund Window and Role
# fixes that: 0.881, 4.7 spots, and the age tilt collapses to +0.05. The
# backtest error improves too (2.75 from 2.81), so this is not a case of
# chasing the market at the cost of accuracy.
DEFAULT_WEIGHTS = {
    "Talent": 14,       # TD-regressed total fp/gm over his last healthy seasons
    "Receiving": 14,    # targets + receiving production (the half-PPR premium)
    "Window": 12,       # first four seasons, OR already a league-winner
    "Backfield": 12,    # his share of his own team's RB work (half from the chart)
    "Role": 10,         # depth-chart slot x how much work that backfield gets
    "Vegas": 10,        # preseason win total + implied team total
    "Availability": 10, # age curve x durability
    "Volume": 8,        # weighted touches per game (a target counts as 1.8)
    "Efficiency": 6,    # yards per carry & yards per target
    "Situation": 4,     # team pace & run lean
    "Matchup": 0,
}
GROUPS = list(DEFAULT_WEIGHTS.keys())

# Reuse the QB model's file loaders rather than keeping two copies of them --
# win totals and play-callers are league-wide facts, not position-specific.
from .qb_blend import (  # noqa: E402
    _birth_map, _first, _num, _numf, _pct_of, implied_totals, playcallers, win_totals,
)

__all__ = [
    "DEFAULT_WEIGHTS", "GROUPS", "SIGNALS", "TARGET_MULT",
    "SLOT_SHARE", "WINDOW_SCORES",
    "season_aggregates", "entering_profiles", "attach_role_window",
    "add_indices", "composite",
    "calibrate", "backtest", "run", "run_upcoming", "build_upcoming",
    "win_totals", "implied_totals", "playcallers", "depth_history",
]


def _age_curve(age: float) -> float:
    """RB aging: flat through 25, then down hard. 26 is the hinge, not 31.

    Returns a 0-1 multiplier on Availability. The numbers come from the shape of
    league-winning RB seasons -- average age 25.1, 85% of them 27 or younger --
    so a 29-year-old back has to be genuinely excellent everywhere else to rank
    where a 24-year-old ranks on merit.
    """
    if age is None or (isinstance(age, float) and np.isnan(age)):
        return 0.85
    if 22 <= age <= 25:
        return 1.0
    if age < 22:
        return 0.95     # young is fine; unproven is handled by sample-size regression
    return max(0.35, 1.0 - (age - 25) * 0.09)


# ---------------------------------------------------------------------------
# 0b. Two outside files: a published projection set, and your own injury notes
#
# Neither of these is allowed to become the model. A well-known analyst's RB
# ranks correlate 0.99 with consensus ADP, so blending his numbers into every
# projection would just turn this board into the market with extra steps and
# throw away the whole reason for having a board. They do two narrow jobs he is
# genuinely better placed to do than a box score is:
#
#   1. HOW MANY GAMES he expects a back to play. That is the only forward-looking
#      health information anywhere in this model.
#   2. A STARTING NUMBER FOR A ROOKIE, who has no NFL box score to regress.
#
# Both files are optional. A missing file is not an error -- the model just has
# no outside opinion, every back gets a full slate, and rookies stay off the
# board exactly as they did before.
# ---------------------------------------------------------------------------
_CLAY: dict = {}
_CLAY_LOADED = False


def clay_projections() -> dict:
    """{player_id: row} from data/clay_rb_<upcoming season>.csv.

    Written by scripts/import_clay.py, which reads the published PDF once a year.
    The build itself never opens a PDF.
    """
    global _CLAY_LOADED
    if _CLAY_LOADED:
        return _CLAY
    _CLAY_LOADED = True
    try:
        path = config.DATA_DIR / f"clay_rb_{config.UPCOMING_SEASON}.csv"
        if not path.exists():
            return _CLAY
        df = pd.read_csv(path)
        if not {"player_id", "clay_rank", "clay_games"}.issubset(df.columns):
            return _CLAY
        # His share of his own backfield in those projections, weighted the same
        # way touches are weighted everywhere else here.
        car = pd.to_numeric(df.get("carries"), errors="coerce").fillna(0.0)
        tgt = pd.to_numeric(df.get("targets"), errors="coerce").fillna(0.0)
        df["clay_opp"] = car + TARGET_MULT * tgt
        tot = df.groupby("team")["clay_opp"].transform("sum")
        df["clay_bf_share"] = df["clay_opp"] / tot.where(tot > 0)
        for row in df.to_dict("records"):
            _CLAY[str(row["player_id"])] = row
    except Exception:      # noqa: BLE001 -- an outside file must never fail a build
        pass
    return _CLAY


def expected_games() -> dict:
    """{normalized name: (games, note)} from data/rb_availability.csv.

    Hand-maintained, and deliberately tiny: it is where YOU put a report the
    published guide hasn't caught up with. When both have a number, yours wins --
    that's the point of it existing. The reading lives in src/availability.py so
    the QB board and this one can never drift apart on what the file means.
    """
    return availability.hand_notes("RB")


def _clay_bundle(c: dict | None, ppr: float = 0.5) -> dict | None:
    """A stand-in profile for a back with no NFL box score, from the guide.

    This is the second half of "rank a rookie on his job plus somebody's number".
    The first half -- the size of the job -- every back already gets from the
    depth chart through Role. What a rookie is missing is the prior-output half,
    and this fills it with a published projection instead of leaving the shrink
    to invent one out of the league average.

    Touchdowns are NOT regressed here the way a real season's are. Projected
    scores are already somebody's smoothed expectation; regressing them again
    would be pulling the same number toward the mean twice.
    """
    if not c:
        return None
    g = float(c.get("clay_games") or 0)
    if g <= 0:
        return None

    def f(k):
        v = c.get(k)
        return 0.0 if v is None or pd.isna(v) else float(v)

    car, tgt, rec = f("carries"), f("targets"), f("rec")
    rush_pg = (f("rush_yds") * 0.1 + f("rush_td") * 6.0) / g
    rec_pg = (f("rec_yds") * 0.1 + rec * ppr + f("rec_td") * 6.0) / g

    def sh(k):
        v = c.get(k)
        return np.nan if v is None or pd.isna(v) else float(v)

    return {
        "talent_reg": rush_pg + rec_pg,
        "rush_val": rush_pg,
        "rec_val": rec_pg,
        "carries_pg": car / g,
        "targets_pg": tgt / g,
        "opp_pg": (car + TARGET_MULT * tgt) / g,
        "bf_share": sh("clay_bf_share"),
        "bf_carry_share": sh("clay_carry_share"),
        "bf_target_share": sh("clay_target_share"),
        "snap_pct": np.nan,
        "ypc": (f("rush_yds") / car) if car else np.nan,
        "ypt": (f("rec_yds") / tgt) if tgt else np.nan,
        "career_games": 0.0,
        "healthy_recent": False,
        "prev_ppg": np.nan,
        "prev_games": np.nan,
        "dur3": np.nan,
        "prev_team": None,
        "prior_source": "clay",
        "trust_override": ROOKIE_TRUST,
    }


# ---------------------------------------------------------------------------
# 1. Season aggregates  (raw components + TD-regressed per-game value)
# ---------------------------------------------------------------------------
def _backfield_shares(w: pd.DataFrame) -> pd.DataFrame:
    """Each back's share of HIS OWN TEAM's running-back work, per season.

    Computed off weekly rows, so a back who was traded contributes to whichever
    team he was actually playing for that week. The share is then reported for
    the team he played the most games for -- a mid-season trade therefore reads
    as a partial share, which is the honest answer rather than a made-up one.

    Denominator is every RB on the roster, so this is "backfield competition"
    and "backfield share" in a single number: 0.75 means he took three quarters
    of the backfield's work, which necessarily means nobody else did.
    """
    cols = ["player_id", "season", "bf_carry_share", "bf_target_share", "bf_share"]
    if w.empty:
        return pd.DataFrame(columns=cols)

    # Team-season totals across all backs.
    team = w.groupby(["season", "team"], dropna=True).agg(
        t_car=("carries", "sum"), t_tgt=("targets", "sum")
    ).reset_index()

    # Player totals per team (so trades split correctly), plus games for tiebreak.
    ply = w.groupby(["player_id", "season", "team"], dropna=True).agg(
        p_car=("carries", "sum"), p_tgt=("targets", "sum"), p_gm=("carries", "size")
    ).reset_index()

    m = ply.merge(team, on=["season", "team"], how="left")
    m["bf_carry_share"] = m["p_car"] / m["t_car"].replace(0, np.nan)
    m["bf_target_share"] = m["p_tgt"] / m["t_tgt"].replace(0, np.nan)
    # One blended share, weighted the same way touches are weighted everywhere
    # else in this file, so the pass-catching back isn't punished for the fact
    # that his team runs the ball with someone else.
    p_opp = m["p_car"] + TARGET_MULT * m["p_tgt"]
    t_opp = (m["t_car"] + TARGET_MULT * m["t_tgt"]).replace(0, np.nan)
    m["bf_share"] = p_opp / t_opp

    # Keep the team he actually played for most that season.
    m = m.sort_values(["player_id", "season", "p_gm"], ascending=[True, True, False])
    m = m.groupby(["player_id", "season"], as_index=False).head(1)
    return m[cols]


def season_aggregates(weekly: pd.DataFrame, scoring_rules: dict | None,
                      snaps: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per (player_id, season) RB totals plus TD-regressed rush/rec fp per game.

    Keeps the raw components so the factors can be built from them, and adds
    `rush_fp_reg_pg` / `rec_fp_reg_pg` / `tot_fp_reg_pg` where touchdowns are
    regressed toward what the yardage predicts.

    `snaps` is optional. When it's supplied and joins cleanly it adds a snap
    share column; when it doesn't, everything else still works and snap share is
    simply absent. It is never allowed to break a build.
    """
    w = pd.DataFrame(index=weekly.index)
    w["player_id"] = _first(weekly, ["player_id", "gsis_id"]).astype(str)
    w["player_name"] = _first(weekly, ["player_display_name", "player_name"])
    w["position"] = _first(weekly, ["position", "position_group"])
    w["team"] = _first(weekly, ["team", "recent_team"])
    w["season"] = _num(weekly, "season")
    stype = _first(weekly, ["season_type"])
    w["season_type"] = stype if stype is not None else "REG"

    w["total_fp"] = scoring.compute_fantasy_points(weekly, scoring_rules)
    w["carries"] = _numf(weekly, ["carries", "rushing_attempts"])
    w["rush_yds"] = _numf(weekly, ["rushing_yards"])
    w["rush_tds"] = _numf(weekly, ["rushing_tds"])
    w["targets"] = _numf(weekly, ["targets"])
    w["receptions"] = _numf(weekly, ["receptions"])
    w["rec_yds"] = _numf(weekly, ["receiving_yards"])
    w["rec_tds"] = _numf(weekly, ["receiving_tds"])

    w = w[(w["position"] == "RB") & (w["season_type"].astype(str).str.upper() == "REG")]
    w = w.dropna(subset=["player_id", "season"])
    if w.empty:
        return pd.DataFrame(columns=["player_id", "season"])
    w["season"] = w["season"].astype(int)

    shares = _backfield_shares(w)

    grp = w.groupby(["player_id", "season"])
    sa = grp.agg(
        games=("total_fp", "size"),
        total_fp=("total_fp", "sum"),
        total_fp_pg=("total_fp", "mean"),
        carries=("carries", "sum"), rush_yds=("rush_yds", "sum"), rush_tds=("rush_tds", "sum"),
        targets=("targets", "sum"), receptions=("receptions", "sum"),
        rec_yds=("rec_yds", "sum"), rec_tds=("rec_tds", "sum"),
    ).reset_index()

    modal = grp["team"].agg(lambda s: s.mode().iat[0] if len(s.mode()) else None).rename("team")
    name = grp["player_name"].agg(
        lambda s: s.dropna().iloc[-1] if s.notna().any() else None).rename("player_name")
    sa = sa.merge(modal.reset_index(), on=["player_id", "season"])
    sa = sa.merge(name.reset_index(), on=["player_id", "season"])
    sa = sa.merge(shares, on=["player_id", "season"], how="left")

    # League TD-per-yard rates from the recent window (the baseline each back's
    # TDs are regressed toward). Rushing and receiving get their own rates
    # because a receiving yard is far less likely to end in the end zone.
    mx = int(sa["season"].max())
    ref = sa[(sa["season"] >= mx - RECENCY + 1) & (sa["games"] >= 8)]
    if ref.empty:
        ref = sa
    r_ty = float(ref["rush_tds"].sum()) / max(float(ref["rush_yds"].sum()), 1.0)
    c_ty = float(ref["rec_tds"].sum()) / max(float(ref["rec_yds"].sum()), 1.0)

    wt = sa["games"] / (sa["games"] + K_TD)               # trust in observed TDs
    reg_rush_td = wt * sa["rush_tds"] + (1 - wt) * sa["rush_yds"] * r_ty
    reg_rec_td = wt * sa["rec_tds"] + (1 - wt) * sa["rec_yds"] * c_ty

    g = sa["games"].replace(0, np.nan)
    rules = scoring_rules or {}
    ppr = float(rules.get("reception", 0.5))
    sa["rush_fp_reg_pg"] = (sa["rush_yds"] * 0.1 + reg_rush_td * 6) / g
    sa["rec_fp_reg_pg"] = (sa["rec_yds"] * 0.1 + sa["receptions"] * ppr + reg_rec_td * 6) / g
    sa["tot_fp_reg_pg"] = sa["rush_fp_reg_pg"] + sa["rec_fp_reg_pg"]

    # Opportunity. Carries and targets separately (they behave differently) and
    # blended into one weighted-touch number, which is the single best one-line
    # summary of an RB's fantasy job.
    sa["carries_pg"] = sa["carries"] / g
    sa["targets_pg"] = sa["targets"] / g
    sa["opp_pg"] = sa["carries_pg"] + TARGET_MULT * sa["targets_pg"]
    sa["ypc"] = sa["rush_yds"] / sa["carries"].replace(0, np.nan)
    sa["ypt"] = sa["rec_yds"] / sa["targets"].replace(0, np.nan)

    sa = _attach_snaps(sa, snaps)
    return sa


def _attach_snaps(sa: pd.DataFrame, snaps: pd.DataFrame | None) -> pd.DataFrame:
    """Optional snap-share column, joined on normalized name + season + team.

    nflverse's snap-count table is keyed by Pro-Football-Reference IDs, not the
    GSIS IDs everything else here uses, so the join has to go through names. That
    is a genuinely fragile join, which is why the whole thing is wrapped: if it
    matches nothing, or the table's shape changed, the model carries on without
    it rather than failing or -- worse -- silently filling zeros.

    Coverage is reported by `snap_coverage()` so the build script can print it
    instead of leaving it to be discovered later.
    """
    sa["snap_pct"] = np.nan
    if snaps is None or getattr(snaps, "empty", True):
        return sa
    try:
        from .adp import norm
        s = snaps.copy()
        pos = _first(s, ["position"])
        if pos is not None and pos.notna().any():
            s = s[pos.astype(str).str.upper() == "RB"]
        pct = _first(s, ["offense_pct", "off_pct", "offense_snap_pct"])
        if pct is None or not pct.notna().any():
            return sa
        src_id = _first(s, ["pfr_player_id", "pfr_id", "player_id"])
        j = pd.DataFrame({
            "season": pd.to_numeric(_first(s, ["season"]), errors="coerce"),
            "nkey": _first(s, ["player", "player_name", "full_name"]).map(norm),
            "pct": pd.to_numeric(pct, errors="coerce"),
            "src": (src_id.astype(str) if src_id is not None else ""),
        }).dropna(subset=["season", "nkey"])
        if j.empty:
            return sa
        j["season"] = j["season"].astype(int)

        # Two different backs whose names normalize to the same key would get
        # averaged together into a number that is wrong for both of them, and
        # nothing downstream would ever look suspicious. Drop those keys instead:
        # a missing snap share is handled everywhere; a quietly wrong one isn't.
        if (j["src"] != "").any():
            amb = j.groupby(["season", "nkey"])["src"].nunique()
            bad = set(amb[amb > 1].index)
            if bad:
                j = j[~j.set_index(["season", "nkey"]).index.isin(bad)]
                if j.empty:
                    return sa

        # Snap counts are per game; a season's snap share is the mean of them.
        j = j.groupby(["season", "nkey"], as_index=False)["pct"].mean()
        # nflverse reports this as 0-1 in some years and 0-100 in others.
        if float(j["pct"].max()) <= 1.5:
            j["pct"] = j["pct"] * 100.0
        sa["nkey"] = sa["player_name"].map(norm)
        sa = sa.drop(columns=["snap_pct"]).merge(
            j.rename(columns={"pct": "snap_pct"}), on=["season", "nkey"], how="left")
        sa = sa.drop(columns=["nkey"])
    except Exception:      # noqa: BLE001 -- a cosmetic signal must never fail a build
        if "snap_pct" not in sa.columns:
            sa["snap_pct"] = np.nan
    return sa


def snap_coverage(sa: pd.DataFrame) -> float:
    """Fraction of RB seasons that actually got a snap share (0.0 - 1.0)."""
    if sa is None or sa.empty or "snap_pct" not in sa.columns:
        return 0.0
    return float(sa["snap_pct"].notna().mean())


def _recent_pool(sa: pd.DataFrame) -> pd.DataFrame:
    """Reference pool for cross-season percentiles = last RECENCY seasons, games>=8."""
    if sa is None or sa.empty:
        return sa
    mx = int(sa["season"].max())
    pool = sa[(sa["season"] >= mx - RECENCY + 1) & (sa["games"] >= 8)]
    return pool if not pool.empty else sa


# ---------------------------------------------------------------------------
# 2. Talent bundle  (healthy + recency-capped, most-recent weighted)
# ---------------------------------------------------------------------------
_BUNDLE_MEANS = ["rush_fp_reg_pg", "rec_fp_reg_pg", "carries_pg", "targets_pg",
                 "opp_pg", "bf_share", "bf_carry_share", "bf_target_share",
                 "snap_pct", "ypc", "ypt"]


def _bundle(pdf: pd.DataFrame, as_of: int) -> dict | None:
    """What a back brings into `as_of`, built only from his prior seasons.

    Uses his last 3 HEALTHY seasons inside the recency window; falls back to any
    recent season, then to any prior season at all. The most recent one counts
    most, and more steeply than the QB model does it (.6/.27/.13 vs .5/.33/.17)
    because a back's job changes faster than a quarterback's.
    """
    prior = pdf[pdf["season"] < as_of]
    if prior.empty:
        return None
    cand = prior[prior["season"] >= as_of - RECENCY]
    healthy = cand[cand["games"] >= HEALTHY_GAMES]

    # A PARTIAL SEASON IS EVIDENCE, JUST WEAKER EVIDENCE. See CRED_GAMES_LO.
    # A one-game cameo is noise rather than a season and would otherwise take up
    # one of the three slots; `prior` is left alone, so career_games, prev_games
    # and durability still read every appearance.
    pool = cand if len(cand) else prior
    rate_pool = pool[pd.to_numeric(pool["games"], errors="coerce").fillna(0)
                     >= CRED_MIN_GAMES]
    use = (rate_pool if len(rate_pool) else pool).sort_values(
        "season", ascending=False).head(3)
    if use.empty:
        return None
    rec = np.array([0.6, 0.27, 0.13][: len(use)], dtype=float)
    g = pd.to_numeric(use["games"], errors="coerce").fillna(0.0)
    cred = ((g - CRED_GAMES_LO) / (CRED_GAMES_HI - CRED_GAMES_LO)).clip(CRED_MIN, 1.0)
    wts = rec * cred.to_numpy(dtype=float)
    if not np.isfinite(wts).any() or wts.sum() <= 0:
        wts = rec
    wts = wts / wts.sum()

    out = {"talent_reg": float(np.average(use["tot_fp_reg_pg"].to_numpy(), weights=wts))}
    for col in _BUNDLE_MEANS:
        key = col.replace("_fp_reg_pg", "_val")
        if col not in use.columns:
            out[key] = np.nan
            continue
        v = pd.to_numeric(use[col], errors="coerce").to_numpy(dtype="float64")
        m = np.isfinite(v)
        # WEIGHTED, not the flat mean this used to take. The docstring has always
        # said the most recent season counts most; only talent_reg above actually
        # did it, so every rate column -- backfield share included -- was reading
        # a three-year average with a hurt season in it at full strength.
        out[key] = float((v[m] * wts[m]).sum() / wts[m].sum()) if m.any() else np.nan

    prior_sorted = prior.sort_values("season")
    last = prior_sorted.iloc[-1]
    out.update({
        "career_games": float(prior["games"].sum()),
        "healthy_recent": bool(len(healthy) > 0),
        "prev_ppg": float(prior_sorted["total_fp_pg"].iloc[-1]),
        "prev_games": float(last["games"]),
        # Games a season over his last three, not just last year's. One season is
        # a tiny sample to judge a body on, and reading only the most recent one
        # writes off a durable back who happened to break a bone. Tested on
        # seasons the fit never saw, three years beats one at both positions.
        # This is the flat mean, which only availability.py uses. The
        # Availability index reads `dur3` just below -- same three years, but
        # weighted toward the recent one.
        "prev_games3": float(prior_sorted["games"].tail(3).mean()),
        # Three years of availability, weighted toward the recent one. See
        # availability.DUR_WEIGHTS for why this is not just last season.
        "dur3": availability.durability(
            list(prior_sorted["games"].tail(3))[::-1]),
        # How big last season's job was, on a 0-to-1 scale where 1 is a genuine
        # workhorse's 18 carries a game. Only used to work out how many games he
        # plays NEXT year -- a back who missed time while carrying a real load is
        # a different bet from a backup who was simply never active, and the
        # games model can't tell them apart without this. See availability.py.
        "prev_role": float(np.clip(
            (float(last["carries"]) / max(float(last["games"]), 1.0)) / 18.0, 0.0, 1.0)),
        "prev_team": prior_sorted["team"].iloc[-1],
    })
    return out


def _merge_team_env(prof: pd.DataFrame, team_season: pd.DataFrame) -> pd.DataFrame:
    """Attach the CURRENT team's prior-season environment (handles movers)."""
    if team_season is None or team_season.empty:
        return prof
    ts = team_season.copy()
    ts["season"] = pd.to_numeric(ts["season"], errors="coerce")
    prof["prev_season"] = prof["season"] - 1
    prof = prof.merge(ts, left_on=["prev_season", "team"], right_on=["season", "team"],
                      how="left", suffixes=("", "_ts"))
    if "season_ts" in prof.columns:
        prof = prof.drop(columns=["season_ts"])
    return prof


# ---------------------------------------------------------------------------
# 3. Entering-season profiles (historical, for calibration + backtest)
# ---------------------------------------------------------------------------
def entering_profiles(sa: pd.DataFrame, team_season: pd.DataFrame,
                      players: pd.DataFrame | None, pool: pd.DataFrame) -> pd.DataFrame:
    """One row per (back, completed season) with everything built from prior years."""
    if sa is None or sa.empty:
        return pd.DataFrame()
    birth = _birth_map(players)

    rows = []
    for pid, pdf in sa.sort_values("season").groupby("player_id"):
        for _, cur in pdf.iterrows():
            season = int(cur["season"])
            b = _bundle(pdf, season)
            if b is None:
                continue
            rows.append({
                "player_id": str(pid),
                "player_name": cur["player_name"],
                "season": season,
                "team": cur["team"],
                "actual_ppg": float(cur["total_fp_pg"]),
                # How much season is behind that rate. NOT a factor -- nothing
                # scores it, nothing ranks on it. calibration.py reads it to
                # throw out the years that ended in October before working out
                # what a pick at a given price returns per game.
                "actual_games": float(cur.get("games", np.nan)),
                "age": season - birth.get(str(pid), np.nan),
                "durability": b.get("dur3", np.nan),
                "win_total": win_totals().get((season, cur["team"])),
                # Vegas's own number for how many points this team scores, from
                # the lines posted for the front of THIS season -- not from what
                # the team scored last year.
                "implied_fwd": implied_totals().get((season, cur["team"])),
                **b,
            })
    prof = pd.DataFrame(rows)
    if prof.empty:
        return prof
    prof["mover"] = (prof["team"] != prof["prev_team"]) & prof["prev_team"].notna()
    return _merge_team_env(prof, team_season)


# ---------------------------------------------------------------------------
# 3b. Role and Window inputs
#
# These two factors need things the profile rows don't already carry: the depth
# chart a back entered each season on, how much work his whole backfield gets,
# how many years he's been in the league, and whether he has ever finished a
# season as a top-12 back. All four are cheap and free; none of them were being
# used. This section attaches the RAW numbers, and add_indices() turns them into
# indices like everything else.
# ---------------------------------------------------------------------------
_DEPTH_HIST: dict = {}
_DEPTH_SHARE: dict = {}
_DEPTH_LOADED = False


def _load_depth() -> None:
    """Read the depth history once and build both maps off it."""
    global _DEPTH_LOADED
    if _DEPTH_LOADED:
        return
    _DEPTH_LOADED = True
    try:
        from . import data as _data          # local import: keeps src/ import-light
        dc = _data.get_depth_history()
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] Depth-chart history unavailable ({exc}).")
        return
    if dc is None or dc.empty:
        return
    d = dc.copy()
    d["slot"] = pd.to_numeric(d["depth"], errors="coerce").clip(upper=5)
    d = d.dropna(subset=["slot"])
    if d.empty:
        return
    d["slot"] = d["slot"].astype(int)
    # Two backs listed as co-starters split a starter's share of the backfield
    # rather than both being handed a full starter's workload.
    tied = d.groupby(["season", "team", "slot"])["slot"].transform("size")
    d["share"] = d["slot"].map(SLOT_SHARE) / tied
    for row in d.itertuples():
        try:
            key = (str(row.gsis_id), int(row.season))
        except (TypeError, ValueError):
            continue
        _DEPTH_HIST[key] = int(row.slot)
        if pd.notna(row.share):
            _DEPTH_SHARE[key] = float(row.share)


def depth_history() -> dict:
    """(player_id, season) -> depth-chart slot entering that season, capped at 5.

    Loaded once per run and cached in memory. If the pull fails we return an
    empty map and the model carries on with no Role information rather than
    stopping -- see add_indices(), where Role falls back to Volume.
    """
    _load_depth()
    return _DEPTH_HIST


def depth_shares() -> dict:
    """(player_id, season) -> his share of the backfield's work, per the chart."""
    _load_depth()
    return _DEPTH_SHARE


def _rookie_years(players: pd.DataFrame | None) -> dict:
    """player_id -> the season he entered the league."""
    if players is None or players.empty:
        return {}
    cols = {str(c).lower(): c for c in players.columns}
    id_col = cols.get("gsis_id") or cols.get("player_id")
    yr_col = cols.get("rookie_season") or cols.get("rookie_year") or cols.get("entry_year")
    if not id_col or not yr_col:
        return {}
    out = {}
    for pid, yr in zip(players[id_col], players[yr_col]):
        if pd.notna(pid) and pd.notna(yr):
            try:
                out[str(pid)] = int(yr)
            except (TypeError, ValueError):
                continue
    return out


def _elite_seasons(sa: pd.DataFrame) -> dict:
    """player_id -> the seasons he finished a top-12 RB. Heath's 'done it before'.

    Top 12 by points per game among backs with at least 8 games, which is the
    closest free stand-in for "league-winner" -- an RB1 season on a real sample.
    """
    if sa is None or sa.empty:
        return {}
    games = pd.to_numeric(sa.get("games"), errors="coerce")
    e = sa[games.fillna(0) >= ELITE_MIN_GAMES].copy()
    if e.empty:
        return {}
    e["_rk"] = e.groupby("season")["total_fp_pg"].rank(ascending=False, method="min")
    out: dict = {}
    for row in e[e["_rk"] <= ELITE_RANK].itertuples():
        out.setdefault(str(row.player_id), []).append(int(row.season))
    return out


def attach_role_window(prof: pd.DataFrame, sa: pd.DataFrame,
                       players: pd.DataFrame | None) -> pd.DataFrame:
    """Attach the raw inputs behind Role and Window. No percentiles here."""
    if prof is None or prof.empty:
        return prof
    p = prof.copy()
    hist = depth_history()

    # 1. Depth slot. History covers completed seasons; the upcoming season's
    #    slot already came through build_upcoming() off the live depth chart.
    given = (pd.to_numeric(p["depth_rank"], errors="coerce")
             if "depth_rank" in p.columns else pd.Series(np.nan, index=p.index))
    slots = []
    for pid, season, live in zip(p["player_id"], p["season"], given):
        slot = hist.get((str(pid), int(season)))
        if slot is None and pd.notna(live):
            slot = int(live)
        slots.append(np.nan if slot is None else float(min(int(slot), 5)))
    p["depth_rank"] = pd.Series(slots, index=p.index, dtype=float)

    # 2. How much work the whole backfield gets, from last season's team total.
    #    Offenses change more slowly than depth charts do, so carrying the prior
    #    year forward is fair; a team we've never seen gets the league median.
    #
    #    Team carries and targets divided by team GAMES. The old version summed
    #    each back's per-GAME rate, which counts a 17-game starter and a two-game
    #    callup the same and had Arizona's backfield at 66 touches a game when a
    #    whole NFL offense runs about 65 plays. Jacksonville read last in the
    #    league on that arithmetic and is actually mid-pack.
    g = sa.groupby(["team", "season"]).agg(_car=("carries", "sum"),
                                           _tgt=("targets", "sum")).reset_index()
    g["_gm"] = np.where(g["season"] <= 2020, 16.0, 17.0)
    g["team_bf"] = (g["_car"] + TARGET_MULT * g["_tgt"]) / g["_gm"]
    g["season"] = g["season"] + 1
    bf_map = {(str(r.team), int(r.season)): float(r.team_bf) for r in g.itertuples()}
    median_bf = float(g["team_bf"].median()) if not g.empty else np.nan
    raw_bf = pd.Series([bf_map.get((str(t), int(s)), median_bf)
                        for t, s in zip(p["team"], p["season"])],
                       index=p.index, dtype=float)
    p["team_bf"] = (1 - BF_TO_MEDIAN) * raw_bf + BF_TO_MEDIAN * median_bf

    # 3. The product, and the point of the whole exercise: the touches his SLOT
    #    normally gets on THIS offense. A back with no NFL history at all still
    #    gets a real number here, which is exactly where the old model was blind.
    #    Co-starters split the slot; rows with no chart in the history (every
    #    upcoming-season row) fall back to the league-average share for the slot.
    shares = depth_shares()
    sh = pd.Series([shares.get((str(i), int(s)))
                    for i, s in zip(p["player_id"], p["season"])],
                   index=p.index, dtype=float)
    p["depth_share"] = sh.fillna(p["depth_rank"].map(SLOT_SHARE))

    # 3b. AND THEN THE SIZE OF THE JOB HE ACTUALLY HELD. See ROLE_TAPE above.
    #     Both numbers so far are chart readings: one from the published chart,
    #     one from the league-average table behind it. Neither knows the
    #     difference between a lead back who takes 83% of his backfield and one
    #     who splits it down the middle. His measured share does, so blend it in
    #     on the believe-the-tape ramp -- full weight to a back who played a
    #     whole season for this team, almost none to one who just moved.
    #
    #     No leakage: bf_share here is the recency-weighted read of seasons
    #     STRICTLY BEFORE this row's season, built by entering_profiles, so the
    #     backtest is testing the change rather than being told the answer.
    if ROLE_TAPE > 0:
        pg = pd.to_numeric(p.get("prev_games"), errors="coerce")
        if TAPE_WINDOW:                          # see TAPE_WINDOW -- the Lamb case
            pg = pd.concat([pg, pd.to_numeric(p.get("prev_games3"), errors="coerce")],
                           axis=1).max(axis=1)
        ramp = ((pg - TAPE_GAMES_LO) / (TAPE_GAMES_HI - TAPE_GAMES_LO)).clip(0.0, 1.0)
        tape_w = TAPE_W_MIN + (TAPE_W_MAX - TAPE_W_MIN) * ramp
        if "mover" in p.columns:
            tape_w = tape_w.where(~p["mover"].fillna(False).astype(bool), TAPE_W_MOVED)
        tape_w = tape_w.fillna(TAPE_W_MIN)
        meas = pd.to_numeric(p.get("bf_share"), errors="coerce")
        w = (tape_w * ROLE_TAPE).clip(0.0, 1.0).where(meas.notna(), 0.0)
        p["depth_share"] = (1.0 - w) * p["depth_share"] + w * meas.fillna(0.0)
        p["role_tape_w"] = w

    # ---- 3c. make the backfield add up to one backfield --------------------
    # See src/team_budget.py. This one ran the other way: the depth table gave
    # a team's top four backs 80% of their own backfield, when the real top four
    # take 99.6% of it -- the RB board was quietly leaving a fifth of every
    # backfield to nobody.
    # This one runs the other way, so the share being handed OUT goes to the
    # backs the board is guessing about rather than to the measured lead back --
    # same rule, opposite sign. See CREDIT_WEIGHTED in src/team_budget.py.
    if TEAM_BUDGET:
        p["depth_share"] = team_budget.scale(
            p, "depth_share", team_budget.RB_BF_BUDGET,
            out_col="budget_mult", lam=BUDGET_LAM,
            credit=p.get("role_tape_w"))

    p["role_opp"] = p["team_bf"] * p["depth_share"]

    # 4. Where he is in his career, and whether he's already cleared the bar.
    rookie = _rookie_years(players)
    first_seen = {str(k): v for k, v in sa.groupby("player_id")["season"].min().items()}
    elite = _elite_seasons(sa)
    years, proven = [], []
    for pid, season in zip(p["player_id"], p["season"]):
        start = rookie.get(str(pid), first_seen.get(str(pid)))
        years.append(np.nan if start is None or pd.isna(start)
                     else int(season) - int(start) + 1)
        proven.append(any(y < int(season) for y in elite.get(str(pid), ())))
    p["yr_in_league"] = pd.Series(years, index=p.index, dtype=float)
    p["proven"] = pd.Series(proven, index=p.index, dtype=bool)

    # 5. Will he be on the field? See NEWS_W above for why this is a dial and
    #    not a switch.
    return _attach_availability(p)


def _attach_availability(p: pd.DataFrame) -> pd.DataFrame:
    """Attach clay_rank / clay_games / games_ratio / proj_games / games_note.

    All of the actual work lives in src/availability.py, on purpose: the
    quarterback board calls the identical function, so the two boards can never
    quietly drift apart on what a games number means. Only the upcoming season
    gets touched, so nothing an outside guide says about 2026 can leak backwards
    into the backtest -- it still scores this model on the same information it
    always had.
    """
    return availability.attach(p, "RB", NEWS_W, MIN_GAMES_RATIO)


# ---------------------------------------------------------------------------
# 4. Indices + composite
# ---------------------------------------------------------------------------
def _role_prior(prof: pd.DataFrame, col: str) -> pd.Series:
    """What a back in this job typically posts -- a straight line fitted across
    the whole pool each season, read at his own expected opportunity.

    It uses none of the player's own results, only the size of the job he holds,
    so it is a fair thing for a thin sample to lean on.
    """
    y = pd.to_numeric(prof.get(col), errors="coerce")
    x = pd.to_numeric(prof.get("role_opp"), errors="coerce")
    out = pd.Series(np.nan, index=prof.index, dtype=float)
    if y is None or x is None or x.notna().sum() == 0:
        return out
    for _, idx in prof.groupby("season").groups.items():
        ys, xs = y.loc[idx], x.loc[idx]
        ok = ys.notna() & xs.notna()
        if ok.sum() >= 20:
            b, a = np.polyfit(xs[ok].to_numpy(), ys[ok].to_numpy(), 1)
            out.loc[idx] = a + b * xs
        out.loc[idx] = out.loc[idx].fillna(ys.mean())
    return out


def _shrink_target(prof: pd.DataFrame, col: str) -> pd.Series:
    """Where a thin sample regresses to: an average back IN HIS ROLE.

    The old target was the average of every back in the league, which is how a
    starter with six career games ended up rated like a committee back -- and it
    is the single biggest reason the board disagreed with the market on young
    starters. Floored at the pool mean on purpose: the prior may say "his job is
    bigger than his resume", never "ignore the touches he actually got".
    """
    y = pd.to_numeric(prof.get(col), errors="coerce")
    pool = y.groupby(prof["season"]).transform("mean")
    rp = _role_prior(prof, col).fillna(pool)
    return pd.Series(np.maximum(rp, pool), index=prof.index).fillna(pool)


def add_indices(prof: pd.DataFrame, weights: dict | None = None) -> pd.DataFrame:
    weights = weights or DEFAULT_WEIGHTS
    p = prof.copy()

    # Sample-size regression: shrink talent toward each season-cohort's mean by
    # how thin the career is. Backs produce sooner than quarterbacks do, so the
    # shrink is gentler here (K_CAREER 10 vs 12) -- but a six-game hot streak
    # still can't crown anyone.
    cg = pd.to_numeric(p["career_games"], errors="coerce").fillna(0.0)
    wc = cg / (cg + K_CAREER)
    # A rookie has zero career games, so the line above would trust his number
    # not at all and rate him purely on the size of his job. Rows carrying an
    # outside projection instead of an NFL box score get a fixed half-trust --
    # the job AND the number, which is the whole reason they're on the board.
    if "trust_override" in p.columns:
        _ov = pd.to_numeric(p["trust_override"], errors="coerce")
        wc = wc.where(_ov.isna(), _ov)
    p["talent_final"] = wc * p["talent_reg"] + (1 - wc) * _shrink_target(p, "talent_reg")
    p["reg_shrink"] = (1 - wc)          # 0 = fully trusted, 1 = fully to the role

    def pct(col):
        if col not in p.columns:
            return pd.Series(np.nan, index=p.index)
        return p.groupby("season")[col].transform(lambda s: s.rank(pct=True) * 100)

    p["Talent"] = pct("talent_final")

    # Volume: weighted touches per game -- last season's, blended a quarter of
    # the way toward what his current slot implies. Prior output on its own is
    # the most repeatable thing a back has, but it describes the job he HAD.
    _opp = pd.to_numeric(p.get("opp_pg"), errors="coerce")
    _ro = (pd.to_numeric(p.get("role_opp"), errors="coerce")
           if "role_opp" in p.columns else pd.Series(np.nan, index=p.index))
    p["opp_blend"] = np.where(_ro.notna() & _opp.notna(),
                              (1 - VOL_ROLE_W) * _opp + VOL_ROLE_W * _ro, _opp)
    p["Volume"] = pct("opp_blend")

    # Receiving: half target VOLUME, half receiving PRODUCTION -- the same split
    # the QB model uses for rushing, and for the same reason. Targets are a
    # coaching decision and repeat; receiving yards and scores wobble. Both are
    # shrunk toward the role the same way talent is, so a pass-catching job on a
    # thin resume isn't scored as if the player had no receiving future.
    p["rec_val_final"] = (wc * pd.to_numeric(p.get("rec_val"), errors="coerce")
                          + (1 - wc) * _shrink_target(p, "rec_val"))
    p["targets_final"] = (wc * pd.to_numeric(p.get("targets_pg"), errors="coerce")
                          + (1 - wc) * _shrink_target(p, "targets_pg"))
    _rec_prod = pct("rec_val_final")
    _rec_vol = pct("targets_final")
    if _rec_vol.notna().any():
        p["Receiving"] = (1 - REC_VOL_W) * _rec_prod + REC_VOL_W * _rec_vol.fillna(_rec_prod)
    else:
        p["Receiving"] = _rec_prod

    # Backfield: his share of his own team's back-work. Snap share is folded in
    # only where it actually joined, so a missing snap table quietly leaves this
    # as pure touch share instead of dragging half the field to the middle.
    _share = pct("bf_share")
    _snap = pct("snap_pct")
    if _snap.notna().sum() >= max(10, int(0.5 * len(p))):
        p["Backfield"] = pd.concat([_share, _snap.fillna(_share)], axis=1).mean(axis=1)
    else:
        p["Backfield"] = _share

    p["Efficiency"] = pd.concat([pct("ypc"), pct("ypt")], axis=1).mean(axis=1)
    # Vegas: the preseason win total and Vegas's implied points for the front of
    # the season. Both are forward-looking, which is the point.
    #
    # The second half of this used to be implied_total_avg -- LAST season's
    # average implied total, attached through _merge_team_env's prev_season
    # join. That is a fine description of where a team has been and a poor one
    # of where it is going: against what a backfield actually scored it reads
    # r=+0.24, where the posted lines for the coming season read r=+0.33. Same
    # source, same kind of number, one season later, and it is the only one of
    # the two that a drafter in August could not have looked up for himself.
    #
    # Weight stays at 10 of 100 and it enters as a percentile, so this steers
    # the ordering without being allowed to set the level of anyone's points.
    p["Vegas"] = pd.concat([pct("win_total"), pct("implied_fwd")], axis=1).mean(axis=1)
    # Situation for a back is pace plus run lean -- more snaps and more handoffs.
    # Note the sign flip against the QB model: a pass-happy offense helps a
    # quarterback and (mostly) hurts a runner, so pass rate enters negated.
    if "pass_rate" in p.columns:
        p["neg_pass"] = -pd.to_numeric(p["pass_rate"], errors="coerce")
    p["Situation"] = pd.concat([pct("plays_pg"), pct("neg_pass")], axis=1).mean(axis=1)
    # Age curve x his three-year durability, weighted toward last season.
    # Both look backwards, and that is the
    # whole of it -- NOTE WHAT IS DELIBERATELY NOT IN HERE: this year's news.
    #
    # It used to be. The games ratio was multiplied in as a third term, on the
    # argument that a back coming off a knee is worth a little less in the games
    # he DOES play, because he ramps up and splits the work while he proves it.
    # That argument is true. It is just already paid for, one line down in
    # rankings.py, where a missed week is charged at MISSED_WEEK_VALUE and the
    # ramp is one of the four reasons that number is not 1.0. Leaving it here too
    # billed the same injury twice.
    #
    # And billing it here specifically is the wrong place, because this index
    # feeds the points-per-game figure, and points-per-game is the one number on
    # this whole board that is meant to answer "what is he worth WHEN HE PLAYS".
    # A hurt man's rate is his rate. What a shorter season costs you belongs in
    # the season total, where you can see it, and it is charged there in full.
    p["Availability"] = [
        _age_curve(a) * (d if pd.notna(d) else 0.8) * 100
        for a, d in zip(p["age"], p["durability"])
    ]
    p["Matchup"] = 50.0

    # Movers: shrink team-based factors toward neutral. BACKFIELD IS IN THIS
    # LIST and it isn't in the QB model's -- a back's share of last year's
    # backfield tells you almost nothing about the depth chart he just joined,
    # and leaving it un-shrunk is how a change-of-scenery back ends up ranked on
    # a job he no longer has.
    for col in ["Situation", "Vegas", "Backfield"]:
        m = p["mover"] == True  # noqa: E712
        p.loc[m, col] = 0.6 * p.loc[m, col] + 0.4 * 50

    # ---- Role: the job he has, not the box score of whoever had it last -----
    # Depth-chart slot x how much work that backfield gets. Note it is NOT in
    # the mover-shrink list above, and that's deliberate: for a back who just
    # changed teams this is the ONLY factor that describes his actual new job.
    # It is worth its own weight -- adding it lifts the R-squared on next-season
    # points from .52 to .56 on top of prior-year opportunity, and it holds for
    # thin-sample backs and 45-game veterans alike.
    _role = pct("role_opp")
    p["Role"] = _role.fillna(p["Volume"])          # no chart -> say nothing new

    # ---- Window: Heath's rule, as an OR ------------------------------------
    # First four seasons, OR already a league-winner. A plain age slope was
    # tried first and it broke Derrick Henry -- it kept marking down backs who
    # have very obviously proven they can still do it. The exemption is the
    # whole point of the rule, so it's in the code.
    if "yr_in_league" in p.columns:
        _yr = pd.to_numeric(p["yr_in_league"], errors="coerce")
        _clamped = _yr.clip(lower=1)
        _win = _clamped.map(WINDOW_SCORES).fillna(WINDOW_LATE)
        if "proven" in p.columns:
            _done = p["proven"].fillna(False).astype(bool) & (_clamped >= 5)
            _win = _win.where(~_done, WINDOW_PROVEN)
        p["Window"] = _win.where(_yr.notna(), 50.0)

    # ---- Backfield gets half its answer from the chart too ------------------
    # Same argument as Role, applied to share instead of volume. For a back who
    # changed teams last year's share is close to meaningless; the slot he's
    # entering camp in is not.
    #
    # READS depth_share RATHER THAN THE RAW SLOT TABLE. They are the same thing
    # for a back with nothing measured behind him, and for everyone else
    # depth_share is that table already blended with the share he actually held
    # -- see ROLE_TAPE. Mapping depth_rank straight onto SLOT_SHARE here gave
    # every RB1 in the league the identical number, which is precisely the half
    # of this factor that could not tell an 83%-of-the-backfield lead back from a
    # nominal one, and it was throwing away the half that could.
    _slot = (pd.to_numeric(p.get("depth_share"), errors="coerce")
             if ROLE_TAPE > 0 and "depth_share" in p.columns
             else p["depth_rank"].map(SLOT_SHARE) if "depth_rank" in p.columns
             else None)
    if _slot is not None and _slot.notna().any():
        _slot_pct = _slot.groupby(p["season"]).rank(pct=True) * 100
        p["Backfield"] = np.where(_slot.notna(),
                                  0.5 * p["Backfield"] + 0.5 * _slot_pct,
                                  p["Backfield"])

    for gcol in GROUPS:
        p[gcol] = pd.to_numeric(p.get(gcol), errors="coerce").fillna(50.0)

    # Give the factors their gaps back before averaging them. See
    # calibration.SPREAD: a percentile rank is uniform by construction, so the
    # right-skewed usage measures lose their distance at the top of the board
    # exactly where the board is being read, and team quality -- which has no
    # skew -- ends up the loudest thing on it. Rank-preserving, so this cannot
    # reorder anyone within a factor; it only changes how far apart they sit.
    p = calibration.stretch_groups(p, GROUPS)

    p["composite"] = composite(p, weights)
    return p


def composite(p: pd.DataFrame, weights: dict) -> pd.Series:
    total_w = sum(weights.values()) or 1
    acc = pd.Series(0.0, index=p.index)
    for gcol, w in weights.items():
        acc = acc + w * p[gcol]
    return acc / total_w


def _drafted_keys(pos: str = "RB") -> set:
    """Kept only so older test scripts that import it keep running."""
    return set(calibration.drafted_picks(pos))


def calibrate(p: pd.DataFrame, pos: str = "RB",
              info: dict | None = None) -> tuple[float, float]:
    """Map composite -> points per game. See src/calibration.py for the why.

    Two bugs lived here and both are now fixed in that one shared file, because
    the QB board had exactly the same two: the points were anchored on a
    different crowd of players than the ADP curve they get compared against, and
    the fitted line spread players out LESS than their draft slot alone does.
    """
    return calibration.fit(p, pos=pos, info=info)


BACKTEST_SEASONS = 3


def backtest(p: pd.DataFrame) -> dict:
    """Walk forward a season at a time; beat last year's points per game or don't.

    THIS REPLACES A TEST THAT WAS ANSWERING THE WRONG QUESTION, and the old
    version's verdict -- "model 2.63, last-year-repeats 2.50, the model loses to
    doing nothing" -- was an artefact of how it was scored, not a fact about the
    model. Three things were wrong with it and all three are fixed here.

    IT SAID TWO SEASONS AND TESTED ONE. `seasons[-2:]` came back [2025, 2026],
    and 2026 has not been played, so every one of the 115 scored rows was 2025.
    The page printed "Backtested on 2025 & 2026". Walking forward over the last
    three seasons that actually have both a price and a result fixes the label
    and triples the sample in one move.

    IT SCORED EVERY BACK WHO EVER TOUCHED THE BALL. Half the test set was backs
    nobody drafts -- 52 of 115 scored under four points a game the year before
    and under three the year after. The points scale is fitted on drafted
    players, because the ADP curve it gets subtracted from is built from drafted
    players, so on a fullback it reads five points and he scores one and a half.
    "Last year he scored one and a half" wins that matchup every time, and it
    wins it without knowing anything. Scored on the backs a draft actually
    reaches -- the identical rule the receiver and tight-end boards already use
    -- the model beats the baseline by about a third of a point a game.

    IT ONLY ASKED ABOUT LEVEL. A board is read in order, so it also reports rank
    correlation. Getting Bijan's exact 16.4 wrong but putting him above the back
    who scored 11 is the version of right that wins a draft.

    A caveat that survives all three fixes: this is still a MEAN error, so it is
    almost blind to whether the model found the one back who won a league. That
    is the wrong question for running backs specifically, and it is why
    scripts/13_backtest_rb.py exists to ask the screen question separately.
    """
    d = p[p["actual_ppg"].notna() & p["composite"].notna()]
    if d.empty:
        return {}
    picks = calibration.drafted_picks("RB")
    if not picks:
        return {}
    from .adp import norm as _adp_norm       # same key the scale was fitted with
    d = d.copy()
    d["_drafted"] = [(int(s), _adp_norm(n)) in picks
                     if pd.notna(n) and pd.notna(s) else False
                     for s, n in zip(d["season"], d["player_name"])]

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
        a, b = calibration.fit(train, pos="RB", info=info)
        test = test.copy()
        test["_pred"] = calibration.apply(test["composite"], a, b,
                                          info.get("knots") or [])
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
    return {"n": int(len(t)), "model_mae": round(mae, 2),
            "baseline_mae": round(mae_base, 2),
            "model_rho": round(float(rho), 3) if pd.notna(rho) else None,
            "baseline_rho": round(float(rho_b), 3) if pd.notna(rho_b) else None,
            "population": "drafted running backs",
            "seasons": tested}


# ---------------------------------------------------------------------------
# 5. Payload assembly (shared by both entry points)
# ---------------------------------------------------------------------------
def _empty(weights: dict, extra: dict | None = None) -> dict:
    out = {"payload": [], "calib": {"a": 0.0, "b": 0.25}, "backtest": {},
           "weights": weights, "groups": [g for g in GROUPS if weights.get(g, 0) > 0]}
    if extra:
        out.update(extra)
    return out


def _r(row, key, nd=2):
    """Round a payload value, or None when it isn't there."""
    v = row.get(key)
    if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v):
        return None
    return round(float(v), nd)


def _assemble(cur: pd.DataFrame, a: float, b: float, bt: dict, weights: dict,
              extra: dict | None = None) -> dict:
    cur = cur.copy()
    # The bends, when calibration managed to fit them. They live inside `extra`
    # because both callers already hand their calibration detail through there.
    # No bends -> apply() is the same straight line this always was.
    knots = ((extra or {}).get("calibration") or {}).get("knots") or []
    cur["proj_ppg"] = calibration.apply(cur["composite"], a, b, knots)

    # Nobody scores points he never had the ball for. See CEIL_BASE/CEIL_SLOPE:
    # the curve above is a percentile map, so it happily hands a third-stringer
    # the same 7 points a game it hands a starter's floor. Clip to what his
    # expected workload can physically produce. Rows with no workload estimate
    # are left alone rather than guessed at.
    _w = pd.to_numeric(cur.get("opp_blend"), errors="coerce")
    cur["ppg_ceiling"] = CEIL_BASE + CEIL_SLOPE * _w
    cur["proj_ppg"] = np.where(_w.notna(),
                               np.minimum(cur["proj_ppg"], cur["ppg_ceiling"]),
                               cur["proj_ppg"])
    cur["position"] = "RB"
    # Rank on SEASON value, not on rate. A draft board is a season-value list --
    # that is what ADP is pricing -- and until this line existed a back expected
    # to miss a month sat exactly where a back playing all seventeen sat. Every
    # healthy back is 17 games, so this reorders nobody except the ones there is
    # actual news about.
    if "proj_games" not in cur.columns:
        cur["proj_games"] = 17.0
    cur["proj_games"] = (pd.to_numeric(cur["proj_games"], errors="coerce")
                         .fillna(17.0).clip(lower=1.0, upper=17.0))
    board = rankings.build_rankings(
        cur[["player_id", "player_name", "position", "proj_ppg", "proj_games"]],
        ppg_col="proj_ppg",
    )
    by_id = {r["player_id"]: r for r in cur.to_dict("records")}
    payload = []
    for _, r in board.iterrows():
        row = by_id.get(r["player_id"], {})
        payload.append({
            "rank": int(r["overall_rank"]),
            "player_id": str(r["player_id"]),
            "name": r["player_name"],
            "team": row.get("team", ""),
            "archetype": "",          # tier 2 (XFP-share buckets); blank keeps the UI happy
            "mover": bool(row.get("mover", False)),
            "starter": bool(row.get("is_starter")) if row.get("is_starter") is not None else None,
            "depth_rank": (int(row["depth_rank"]) if pd.notna(row.get("depth_rank")) else None),
            "proj_ppg": round(float(r["proj_ppg"]), 2),
            # The workload ceiling travels with the row because the page
            # re-projects everybody itself every time a slider moves. Without it
            # published here, dragging any weight would hand the third-stringers
            # their 7 points a game straight back.
            "ceil": _r(row, "ppg_ceiling"),
            "proj_total": round(float(r["proj_points_total"]), 1),
            "tier": int(r["tier"]),
            "vor": round(float(r["vor"]), 1),
            "career_games": (round(float(row["career_games"]))
                             if pd.notna(row.get("career_games")) else None),
            "age": (round(float(row["age"])) if pd.notna(row.get("age")) else None),
            # Explicit numeric fields, so ratings.py and the report can test
            # published thresholds directly instead of parsing labels.
            "carries_pg": _r(row, "carries_pg"),
            "targets_pg": _r(row, "targets_pg"),
            "targets_pace": (round(float(row["targets_pg"]) * 17.0)
                             if pd.notna(row.get("targets_pg")) else None),
            "opp_pg": _r(row, "opp_pg"),
            "bf_share": _r(row, "bf_share", 3),
            "snap_pct": _r(row, "snap_pct", 1),
            "rush_fpg": _r(row, "rush_val"),
            "rec_fpg": _r(row, "rec_val"),
            # Games played per 17. Published on its own and not folded into the
            # Availability index, because that index is age x durability -- a
            # perfectly healthy 30-year-old scores low on it, and a flag that
            # said "injury history" off that number would be inventing one.
            "durability": _r(row, "durability", 2),
            # How long a body with his history normally lasts, and that as a
            # 0-to-1 worry score. These do NOT cut his games -- he is projected
            # for a full season like everybody else. They drive his RISK rating,
            # which is where an injury history belongs. See src/availability.py.
            "avail_games": _r(row, "avail_games", 1),
            "avail_risk": _r(row, "avail_risk", 2),
            # And what he is carrying INTO the season, which is a separate thing
            # from his record. Zero for anyone nobody has reported on. A man who
            # has been cleared keeps all seventeen games and still scores here,
            # because "cleared" and "never hurt" are different bets.
            "injury_risk": _r(row, "injury_risk", 2),
            # How many of the 17 we expect him to play, why, and what an outside
            # guide thinks of him. `games` is the one the page ranks on, and it
            # is seventeen unless somebody reported something specific.
            "games": round(float(row.get("proj_games", 17.0)), 1),
            "games_note": (str(row.get("games_note") or "") or None),
            "injury": (str(row.get("injury") or "") or None),
            "clay_rank": (int(row["clay_rank"]) if pd.notna(row.get("clay_rank")) else None),
            "rookie": bool(str(row.get("prior_source") or "") == "clay"),
            "indices": {g: round(float(row.get(g, 50.0)), 1) for g in GROUPS},
            "signals": {label: round(float(row[col]), 3 if "share" in col else 2)
                        for col, label in SIGNALS.items()
                        if col in row and pd.notna(row.get(col))},
        })
    # The page recomputes every projection itself whenever a slider moves, so it
    # needs the bends, not just the line. Same numbers, same order, both sides.
    out = {"payload": payload,
           "calib": {"a": round(a, 3), "b": round(b, 4), "knots": knots},
           "backtest": bt,
           "weights": weights, "groups": [g for g in GROUPS if weights.get(g, 0) > 0]}
    if extra:
        out.update(extra)
    return out


# ---------------------------------------------------------------------------
# 6. Entry point A -- historical projection (fallback when no current roster)
# ---------------------------------------------------------------------------
def run(weekly, team_season, players, scoring_rules, season, weights=None,
        snaps=None) -> dict:
    weights = weights or DEFAULT_WEIGHTS
    sa = season_aggregates(weekly, scoring_rules, snaps)
    if sa.empty:
        return _empty(weights)
    prof = entering_profiles(sa, team_season, players, _recent_pool(sa))
    if prof.empty:
        return _empty(weights)
    prof = attach_role_window(prof, sa, players)
    prof = add_indices(prof, weights)
    cal: dict = {}
    a, b = calibrate(prof, info=cal)
    # backtest() deliberately keeps its own all-backs fit. It exists to answer
    # "does the composite predict better than last year's points?", which is a
    # question about ordering, and its number stays comparable to every previous
    # run that way. The calibration above only decides what SCALE those ordered
    # projections print in.
    bt = backtest(prof)
    cur = prof[(prof["season"] == season) & (prof["career_games"] >= MIN_CAREER_GAMES)].copy()
    if cur.empty:
        return _empty(weights)
    return _assemble(cur, a, b, bt, weights, {"calibration": cal})


# ---------------------------------------------------------------------------
# 7. Entry point B -- upcoming season, driven by the CURRENT roster/depth chart
# ---------------------------------------------------------------------------
def build_upcoming(sa, team_season, players, current_map, season,
                   pool) -> tuple[pd.DataFrame, list[str]]:
    """One profile row per current RB: current team + historical production."""
    birth = _birth_map(players)
    by_pid = {str(pid): pdf for pid, pdf in sa.groupby("player_id")}

    clay = clay_projections()

    rows, skipped = [], []
    for _, cm in current_map.iterrows():
        pid = str(cm["gsis_id"])
        pdf = by_pid.get(pid)
        b = _bundle(pdf, season) if pdf is not None else None
        if b is None:
            # No NFL history at all. He used to be dropped here, which is how a
            # rookie starting for a real team ended up missing from a draft board
            # the market was already pricing in the third round. If an outside
            # guide has a number on him he gets a row instead -- ranked roughly
            # is a great deal better than not ranked.
            b = _clay_bundle(clay.get(pid))
        if b is None:
            if cm.get("name"):
                skipped.append(str(cm["name"]))
            continue
        name = cm.get("name")
        if not name and pdf is not None:
            name = pdf.sort_values("season")["player_name"].iloc[-1]
        if not name:
            name = (clay.get(pid) or {}).get("name")
        rows.append({
            "player_id": pid,
            "player_name": name or pid,
            "season": season,
            "team": cm.get("team"),
            "actual_ppg": np.nan,
            "age": season - birth.get(pid, np.nan),
            "durability": b.get("dur3", np.nan),
            "win_total": win_totals().get((season, cm.get("team"))),
            "implied_fwd": implied_totals().get((season, cm.get("team"))),
            "is_starter": cm.get("is_starter"),
            "depth_rank": cm.get("depth_rank"),
            **b,
        })
    prof = pd.DataFrame(rows)
    if prof.empty:
        return prof, skipped
    prof["mover"] = (prof["team"] != prof["prev_team"]) & prof["prev_team"].notna()
    return _merge_team_env(prof, team_season), skipped


def run_upcoming(weekly, team_season, players, current_map, scoring_rules, season,
                 weights=None, snaps=None) -> dict:
    """Project the UPCOMING season using current teams/depth charts + history."""
    weights = weights or DEFAULT_WEIGHTS
    sa = season_aggregates(weekly, scoring_rules, snaps)
    if sa.empty:
        return _empty(weights, {"skipped_rookies": []})
    pool = _recent_pool(sa)
    hist = entering_profiles(sa, team_season, players, pool)          # calibration/backtest
    up, skipped = build_upcoming(sa, team_season, players, current_map, season, pool)
    if up.empty:
        return _empty(weights, {"skipped_rookies": skipped})

    allp = pd.concat([hist, up], ignore_index=True, sort=False)
    allp = attach_role_window(allp, sa, players)
    allp = add_indices(allp, weights)
    cal: dict = {}
    a, b = calibrate(allp, info=cal)
    # See run() above: the backtest keeps the all-backs fit on purpose so its
    # score still means the same thing it meant last run.
    bt = backtest(allp)

    # MIN_CAREER_GAMES exists to keep four-game cameos off the board. A rookie
    # has no career games by definition, so the rows built off an outside
    # projection have to be let through it explicitly or the whole point of
    # adding them is lost on the last line of the function.
    keep = pd.to_numeric(allp["career_games"], errors="coerce").fillna(0.0) >= MIN_CAREER_GAMES
    if "prior_source" in allp.columns:
        keep = keep | (allp["prior_source"].astype(str) == "clay")
    cur = allp[(allp["season"] == season) & keep].copy()
    if cur.empty:
        return _empty(weights, {"skipped_rookies": skipped})
    return _assemble(cur, a, b, bt, weights,
                     {"skipped_rookies": skipped,
                      "snap_coverage": round(snap_coverage(sa), 3),
                      "calibration": cal})
