"""Make a team's players add up to one team.

Every board prices a player's job as a SHARE -- what fraction of the targets, or
of the backfield, is his. Nothing until now ever checked the obvious top-down
consequence: the shares on one roster have to add up to that roster. They did
not. Summed over each team's kept players on the 2026 boards, before this
module existed:

    WR + TE target share   min 0.758   median 0.967   max 1.125
    RB backfield share     min 0.680   median 0.951   max 1.108

The median team was handing its receivers 97% of the passing game with nothing
left for the backs, and the spread from Tennessee to Miami was 48% -- not a
statement about those offences, just the depth-chart lookup tables drifting.

Those tables are the cause. Summed across the slots each board actually keeps:

    slot                     table sum   real          over/under
    WR ranks 1-5             0.700       0.5707        +23%
    TE ranks 1-3             0.260       0.1996        +30%
    RB ranks 1-4 (backfield) 0.804       0.9960        -19%

The "real" column is measured here, not assumed: 256 team-seasons of 2018-2025
weekly data, players sorted within each team by season-long share, cumulative
share read off at each depth. That is what the tables below hold.

The per-slot values cannot be compared one-to-one with the tables, because the
tables are keyed on DEPTH-CHART rank while the measurement sorts by actual
share, and the depth chart is wrong often enough to flatten the curve. The SUM
over a whole team is the same quantity either way, which is why the fix works on
sums and leaves the within-team ordering the board computed completely alone.

`scale()` divides each team's shares by their own sum and multiplies by the
budget for a group that size. A team stays exactly as internally spread out as
the board made it; only the level moves, and only where the level was wrong.

The uniform part of that correction does nothing to the rankings -- every factor
downstream is percentile-ranked within a season, so multiplying every team by
1.25 cancels. What survives is the part that differs BETWEEN teams, which is the
part that was a real error.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Cumulative share of ALL team targets held by the top-N at the position.
# Median over 256 team-seasons, 2018-2025, teams with 200+ targets.
WR_TGT_BUDGET = {1: 0.2246, 2: 0.3712, 3: 0.4686, 4: 0.5349, 5: 0.5707,
                 6: 0.5834, 7: 0.5933}
TE_TGT_BUDGET = {1: 0.1319, 2: 0.1785, 3: 0.1996, 4: 0.2049, 5: 0.2051}

# Cumulative share of the BACKFIELD (carries + targets to RBs) held by the
# top-N running backs -- a different denominator from the two above, because
# that is what the RB board's depth_share is a share of.
RB_BF_BUDGET = {1: 0.5598, 2: 0.8584, 3: 0.9657, 4: 0.9960, 5: 1.0}

# A group whose shares sum to almost nothing, or to something absurd, is a data
# problem rather than an unusual offence. Rescaling it by 40x would turn that
# problem into a projection, so the multiplier is held inside a sane band and
# anything outside is left as the board had it.
SCALE_LO, SCALE_HI = 0.5, 2.0

# TAKE THE CUT FROM THE PLAYER WE ARE GUESSING ABOUT, NOT THE ONE WE MEASURED.
#
# The correction above is uniform: every player on a roster is multiplied by the
# same number. That is the wrong place to take it from, and the tight ends show
# why. Arizona's three kept tight ends sum over budget, so all three are cut 22%
# -- including Trey McBride, whose share is not a guess at all. He played 17
# games and took 27.0% of the targets, and three quarters of his number is that
# measurement. The other two are almost pure lookup-table, and the lookup table
# is the thing that is 30% too generous in the first place. So the roster's error
# is created by the backups and paid for by the starter.
#
# What it costs: our most central tight end lands at 18.6% of his team's targets
# when the top tight end on a team has cleared 22% in 28 of the last 252 seasons
# and 25% in eleven of them. Our board gives that to nobody -- median 13.8%,
# ceiling 18.6%, against a real ceiling of 28.7%. The offences built around one
# tight end come out looking like the offences that are not, which is the exact
# opposite of pricing how central a player is.
#
# So spread the correction by how little each estimate is worth. `credit` is the
# tape weight the board already computed -- 1.0 means the share is entirely his
# own measured usage, 0.0 means it is entirely the table. Solve
#
#     sum_i  s_i * (1 - k*(1 - c_i))  =  budget
#
# for k, so the roster still lands on its budget while a fully-measured player is
# left alone and a fully-guessed one absorbs the whole thing. If the budget runs
# the other way -- the RB table under-allocates -- k comes out negative and the
# extra share goes to the guessed players instead, which is the same rule.
#
# With every credit equal this is algebraically the old uniform multiplier, so
# this is a strict generalisation.
#
# IT IS OFF, BECAUSE IT DOES NOT SURVIVE THE MEASUREMENT. The argument above is
# sound and the tight ends do prefer it, but it was A/B'd on all three boards and
# two of them got worse:
#
#   TE   composite rho  0.69240 -> 0.69371   share rho 0.6598 -> 0.6671
#        backtest mae        1.87 -> 1.86    rank rho  0.695  -> 0.694
#   WR   composite rho  0.75844 -> 0.75749   share rho 0.7094 -> 0.7119
#        backtest mae        2.55 -> 2.59    rank rho  0.664  -> 0.656
#   RB   composite rho  0.72582 -> 0.72263   share rho 0.7116 -> 0.6995
#        backtest mae        2.63 -> 2.65
#
# A tenth of a MAE point on the receivers is a real cost and the tight ends' gain
# is a thousandth of a rho. Worse, it does not even buy what it was built for:
# the most central tight end goes from 18.6% of his team's targets to 19.8%, and
# the real ceiling is 28.7%. It moves the number a tenth of the way and charges
# two boards for it.
#
# The diagnosis it came from is still correct and still unfixed -- see the
# COMPRESSION note below. This particular answer is just the wrong one.
CREDIT_WEIGHTED = False

# THE TOP END IS SQUASHED, AND NOTHING IN THIS FILE FIXES IT YET.
#
# Measured on the 2026 tight end board against 252 team-seasons of history, the
# best tight end on each roster:
#
#                    median   p90      max     over 22%   over 25%
#   history          0.1483   0.2244   0.2873   28/252     11/252
#   our board        0.1381   0.1614   0.1860    0/32       0/32
#
# The middle is close to right and the top end is gone. Mark Andrews took 28.7%
# of Baltimore's targets in 2022 and Trey McBride 28.6% of Arizona's in 2024; our
# board's ceiling for anyone is 18.6%. Two haircuts stack to produce that. The
# share is first shrunk toward a league-average lookup -- even a tight end who
# played all 17 games keeps only 75% of his own measured usage -- and then the
# roster budget cuts every one of the 32 teams again, by a median 13%.
#
# BOTH HAIRCUTS WERE THEN ATTACKED DIRECTLY, AND BOTH DEFENDED THEMSELVES.
# CREDIT_WEIGHTED went after the roster budget and is off above. TAPE_W_MAX --
# the 0.75 ceiling on how much of his own measured usage a player keeps -- was
# swept to 0.85 and 0.95 on all three boards:
#
#           TE composite   TE mae    WR composite   WR mae    RB composite  RB mae
#   0.75      0.69240       1.87       0.75844       2.55       0.72582      2.63
#   0.85      0.69187       1.87       0.75834       2.55       0.72513      2.64
#   0.95      0.69159       1.87       0.75826       2.55       0.72353      2.64
#
# Monotonically worse on every board, and it buys almost nothing anyway: at 0.95
# the most central tight end reaches 20.0% against a real ceiling of 28.7%.
#
# So the squash is not a bug. It is regression toward the mean doing its job, and
# it is priced about right. The median top tight end takes 14.8% of his team's
# targets; the seasons above 25% are eleven out of 252 and they are mostly not
# repeated by the same player the following year. A projection that hands the
# reigning leader his 28% back would be a description of last season rather than
# a forecast of the next one.
#
# What that means when this board is read next to a published projection set:
# ours will look timid at the top of every position, and it should. Those sets
# are point estimates of the most likely usage. This one is shrunk on purpose,
# and every attempt to un-shrink it made the predictions worse. Recorded here so
# the next person to notice the gap does not spend the same two days on it.


# If a roster is nearly all measured there is no one to take the cut from and k
# explodes. Below this much guessed share, fall back to the uniform multiplier.
CREDIT_MIN_MASS = 0.02


def budget_for(n: int, table: dict) -> float:
    """What n players at this position are collectively allowed to hold."""
    if n <= 0:
        return float("nan")
    keys = sorted(table)
    return float(table[min(max(n, keys[0]), keys[-1])])


def scale(prof: pd.DataFrame, share_col: str, table: dict,
          group_cols=("season", "team"), out_col: str | None = None,
          lam: float = 1.0, credit=None, fit=None) -> pd.Series:
    """Pull each team-season's shares toward its measured budget by `lam`.

    lam = 1.0 snaps the sum onto the budget exactly. That is right only if every
    bit of the gap is table drift, and it is not: a tight end room really is a
    bigger slice of the passing game in Kansas City than in Chicago, and the
    budget is a MEDIAN, so snapping every roster onto it flattens exactly the
    top-end spread the board needs. Measured, lam = 1.0 costs the TE board
    -0.0014 of composite rho and 0.057 off role_tgt on its own.

    lam < 1 splits the difference -- part of the gap is drift, part is a real
    offence. Each board sets its own from the A/B; see the constant next to
    TEAM_BUDGET in wr_blend, te_blend and rb_blend.

    `credit` is optional and is how much of each player's share is his own
    measured usage rather than a lookup. Pass it and the roster still lands on
    the same budget, but the correction is taken from the guessed players first.
    See CREDIT_WEIGHTED.

    `fit` is optional and is a per-row multiplier on the budget itself, for the
    case where the position's slice of an offence is genuinely a property of that
    offence rather than a league constant. The tables here are league MEDIANS, so
    without it this function would flatten exactly the between-team difference the
    caller is trying to price -- an offence that really does feed its tight ends
    would be cut back to the median every time. One value per group is expected;
    the group's median is used if they disagree. See te_blend.TEAM_FIT.

    Rows with no team, no share, or a group whose sum is unusable come back
    untouched, so this can only ever tighten the numbers it can actually check.
    """
    s = pd.to_numeric(prof.get(share_col), errors="coerce")
    if s is None or s.isna().all():
        return s
    keys = [c for c in group_cols if c in prof.columns]
    if not keys:
        return s

    g = prof.groupby(keys, dropna=True)[share_col]
    tot = g.transform(lambda v: pd.to_numeric(v, errors="coerce").sum(min_count=1))
    cnt = g.transform(lambda v: pd.to_numeric(v, errors="coerce").notna().sum())

    want = cnt.map(lambda n: budget_for(int(n), table) if pd.notna(n) else np.nan)

    # ---- the budget is a league median; some offences are not the median ----
    if fit is not None:
        f = pd.to_numeric(fit, errors="coerce").reindex(prof.index)
        f = f.groupby([prof[k] for k in keys]).transform("median")
        want = want * f.where(f.notna() & (f > 0), 1.0)

    mult = (want / tot).replace([np.inf, -np.inf], np.nan)

    # ---- take the cut from the guessed players first. See CREDIT_WEIGHTED ----
    if CREDIT_WEIGHTED and credit is not None:
        c = pd.to_numeric(credit, errors="coerce").reindex(prof.index)
        c = c.clip(0.0, 1.0).fillna(0.0)              # unknown = pure guess
        guess = (s.fillna(0.0) * (1.0 - c))
        # how much guessed share the roster is carrying, and the gap to close
        mass = guess.groupby([prof[k] for k in keys]).transform("sum")
        k_ = ((tot - want) / mass.replace(0, np.nan))
        wmult = 1.0 - k_ * (1.0 - c)
        use = (mass >= CREDIT_MIN_MASS) & k_.notna() & np.isfinite(k_)
        mult = wmult.where(use, mult)

    mult = 1.0 + float(lam) * (mult - 1.0)
    ok = mult.notna() & (tot > 0) & mult.between(SCALE_LO, SCALE_HI)
    out = s.where(~ok, s * mult)
    if out_col:
        prof[out_col] = mult.where(ok, 1.0)
    return out


def audit(prof: pd.DataFrame, share_col: str, table: dict,
          group_cols=("season", "team")) -> pd.DataFrame:
    """Per-team sum against budget -- what the reconciliation report prints."""
    keys = [c for c in group_cols if c in prof.columns]
    d = prof.copy()
    d[share_col] = pd.to_numeric(d[share_col], errors="coerce")
    g = d.groupby(keys, dropna=True)[share_col].agg(["sum", "count"])
    g["budget"] = g["count"].map(lambda n: budget_for(int(n), table))
    g["over_pct"] = (g["sum"] / g["budget"] - 1.0) * 100.0
    return g.sort_values("over_pct", ascending=False)
