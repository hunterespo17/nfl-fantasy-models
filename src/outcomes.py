"""How wrong is this projection likely to be, and in which direction?

Every other file here works towards one number per player. This one is about the
error bar around it, and it exists because a single number quietly tells the
drafter a lie: that the man projected for 240 points will score something like
240 points. He will not. Over six years of real drafts the tenth-percentile
outcome landed at about 40% of what the slot paid, and the difference between
that and the middle is your season.

WHY THIS IS HERE AND NOT IN THE PROJECTION.

The obvious way to express injury risk is to project fewer games for the players
who get hurt, and it was tried, and it does not work. Measured properly -- take
the market's own board over 2021-2025, discount every player by how durable his
last three seasons read, and score the re-ordered board against what players
really went on to do -- the improvement is +0.009 on a rank correlation of
+0.434, it wanders up and down as the discount is turned up rather than peaking,
and it makes the running back board WORSE at every setting tried.

The reason is not subtle. Availability is barely predictable: the best reading of
a man's history correlates +0.19 with his next season's games, and his own draft
price manages +0.08, so the market cannot do it either. And a discount that
lands on everybody equally does not reorder a board, it only shrinks it.

But availability is not unimportant -- it is about a THIRD of the variance in a
realised season (games 29-34% by position, the scoring rate 39-64%, the rest
covariance). So it belongs somewhere. It belongs here, in the width of the range
rather than the middle of it, because "he might not be out there" is a statement
about how badly this can go, not about what he does when he plays. That is also
what src/availability.py decided for its own reasons, and the two now agree.

WHERE THE NUMBERS COME FROM.

936 drafted player-seasons, 2020-2025, taken from preseason consensus rank down
to roughly what a 12-team league really drafts (QB24, RB48, WR60, TE24). Every
one of them counts, including the seven men who were drafted and never played a
snap -- dropping those is the single easiest way to make a floor look better than
it is.

Each man is priced off the realised points-by-slot curve for his position fitted
WITHOUT his own season, so nothing here has seen its own answer. What he really
scored, divided by that price, is the ratio the bands are built from.

THE JOIN BUG, because the numbers in this file were wrong once and the record of
how belongs next to them.

The first three fits of this table matched players to their statistics by name,
lowercased with the punctuation stripped. That turns "Patrick Mahomes II" into
"patrick mahomes ii" on one side of the join and "patrick mahomes" on the other,
so every man carrying Jr., Sr., II, III or IV silently failed to match -- and a
failed match was recorded as a season of ZERO POINTS by a player with no NFL
record behind him. Sixty-one fabricated zeros, roughly seven percent of the
sample, all of them landing exactly on the tenth percentile that this file
measures.

Two things came out of that and only one of them was real:

  * The bands were far too low. The old table gave a back drafted 25th-48th a
    floor of 0.02 and a tight end drafted 13th-24th a floor of 0.12. On the
    repaired join those are 0.27 and 0.37. The whole table below is refitted.
  * There appeared to be a large rookie effect -- rookies busting 53% of the time
    against 18%. There is not. Those "rookies" were Patrick Mahomes, Deebo
    Samuel, Chris Godwin and Michael Pittman Jr. On the repaired join the rookie
    bust rate is 18% against 20%, which is nothing. See the rookie note below.

The join now runs in four tiers -- exact, exact ignoring position, last-name-plus
-initial, and that ignoring position -- and matches 929 of 936. The seven that
still do not are named in the notes, and four of them (J.K. Dobbins 2021, Gus
Edwards 2021, Joe Mixon 2025, and a 2020 Robby Anderson spelling) genuinely
belong at or near zero.

TWO CORRECTIONS THAT SURVIVED THE REPAIR, both forced by measurement:

  * THE LEVEL IS NOT OURS TO APPLY. The raw median ratio still runs a few percent
    off 1.00 by band, so attaching it unaltered would print a middle that is not
    our own projection. That is not a finding about any player; it is a fact
    about the pricing curve, which is fitted through seasons including the zeros
    and therefore sits below the median player. So each band is divided by its
    own median. The middle now lands exactly on the projection and what survives
    is the SHAPE, which is the part that was measured.

  * THE FINE BANDS WERE NOISE. The first cut split each position's early rounds
    in two and the top six quarterbacks came back with a floor of 0.18 against
    0.36 for the men taken right after them. Bootstrapped, that cell's floor is
    0.00 with a 90% interval of [0.00, 0.56] -- one achilles tendon in 2023
    setting the tenth percentile of a 36-season sample. Every early split tried,
    at all four positions, failed the same test. So the early bands are merged,
    and what is left is the one split that does survive -- early rounds against
    late ones.

THE HONEST CAVEATS, because a range quoted too confidently is worse than none:

  * The ratio was measured against what a SLOT paid and is applied to what OUR
    model projects, and the band is chosen by OUR rank rather than the market's.
    Where we disagree with the market we are assuming our number is the better
    centre. That is the premise of the whole board, but it is an assumption and
    it lives here too.
  * Past the drafted depth there is no measurement at all -- nobody tracks what
    the 90th receiver did against his price -- so those rows extend the last
    measured band and are marked `range_measured = False`. Treat a range on a
    deep bench flier as a shape, not a figure.
  * A 10th and a 90th percentile are not a floor and a ceiling in the everyday
    sense. One player in ten does worse than the floor. That is what a floor is.
"""
from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# WHAT REALLY HAPPENED, BY POSITION AND BY HOW EARLY HE WENT
# ---------------------------------------------------------------------------
# (first rank, last rank, floor, ceiling, bust odds, boom odds)
#
# floor and ceiling are the 10th and 90th percentiles of the realised season, as
# a multiple of the projection, with the middle normalised to 1.00. bust =
# finished under 60% of it; boom = over 140%. Those two bars are round numbers
# chosen to be legible rather than measured, and they are only ever displayed.
#
# Each cell is shrunk towards its own position by n/(n+40), so a thin cell leans
# on the position and a fat one stands mostly on itself.
#
# Read the shape before the digits, because the shape is the finding:
#
#   RUNNING BACK IS THE VOLATILE POSITION and receiver is not. A back drafted
#   25th-48th runs 0.27 to 1.90 and booms 26% of the time; a receiver at the same
#   depth runs 0.42 to 1.70 and booms 19%. The whole running back board is wider
#   than the whole receiver board at every depth. That is the same fact the
#   draft-board slope fit reached from a completely different direction.
#
#   THE QUARTERBACK CEILING IS THE NARROWEST THING HERE. A top-twelve quarterback
#   booms 8% of the time against 24% for a back and 16% for a tight end. He is
#   the safest floor on the board and he almost never wins you the league by
#   himself, which is exactly why the board takes him late.
#
#   THE EARLY TIGHT END IS THE SAFEST CELL IN THE FILE -- 0.55 to 1.50, busting
#   13% of the time. The one drafted a round later is not: 0.37 to 1.45, busting
#   19%. That gap is the widest early-to-late step at any position.
BAND_RATIO: dict[str, list[tuple]] = {
    # all 144 drafted QBs: floor 0.44 median 1.00 ceiling 1.38, bust 19% boom 10%
    "QB": [(1, 12, 0.43, 1.34, 0.17, 0.08),     # n=72,  shrunk 36% to the position
           (13, 24, 0.51, 1.48, 0.20, 0.12)],   # n=72,  shrunk 36%
    # all 288 drafted RBs: floor 0.29 median 1.00 ceiling 1.72, bust 22% boom 24%
    "RB": [(1, 12, 0.45, 1.59, 0.16, 0.24),     # n=72,  shrunk 36%
           (13, 24, 0.34, 1.57, 0.20, 0.20),    # n=72,  shrunk 36%
           (25, 48, 0.27, 1.90, 0.26, 0.26)],   # n=144, shrunk 22%
    # all 360 drafted WRs: floor 0.41 median 1.00 ceiling 1.52, bust 20% boom 15%
    "WR": [(1, 12, 0.48, 1.42, 0.17, 0.12),     # n=72,  shrunk 36%
           (13, 30, 0.40, 1.43, 0.18, 0.12),    # n=108, shrunk 27%
           (31, 60, 0.42, 1.70, 0.23, 0.19)],   # n=180, shrunk 18%
    # all 144 drafted TEs: floor 0.48 median 1.00 ceiling 1.50, bust 16% boom 17%
    "TE": [(1, 12, 0.55, 1.50, 0.13, 0.16),     # n=72,  shrunk 36%
           (13, 24, 0.37, 1.45, 0.19, 0.18)],   # n=72,  shrunk 36%
}

# How deep the measurement actually goes. Past this the last band is extended
# and the row is flagged, because nobody has ever measured what the 90th
# receiver did against his price.
MEASURED_TO = {"QB": 24, "RB": 48, "WR": 60, "TE": 24}

# ---------------------------------------------------------------------------
# HOW MUCH BEING A SHAKY BET MOVES THAT RANGE
# ---------------------------------------------------------------------------
# Measured on the 862 drafted seasons with an NFL record behind them, split by
# the model's own shakiness score -- but by his PERCENTILE within his own
# position, not by the raw number.
#
# That axis is not a nicety, it is the whole thing. The raw score is
# position-shifted: with no job term, a veteran tight end with a PERFECT
# three-year record still scores 0.60, while a receiver with the same record
# scores 0.41 and a quarterback 0.19. Cutting the pooled sample on the raw score
# therefore sorts tight ends from quarterbacks rather than fragile players from
# durable ones -- which is how the first attempt at this came back with the sign
# BACKWARDS, reporting that the shakiest players had the higher floors.
#
#   veterans, by shakiness percentile     floor  ceiling  bust  boom
#     most durable quarter    n=224        0.53    1.59    14%   19%
#     most fragile quarter    n=225        0.29    1.57    28%   17%
#
# So the floor moves 0.31 across the axis and the bust odds move 18 points, and
# both are as certain as this sample gets: the durable quarter beats the fragile
# quarter in 100% of resamples on the floor and 100% on the bust rate.
#
# THE CEILING DOES NOT MOVE. 1.587 against 1.565, which is 60% of resamples --
# a coin. Neither does the boom rate (74%, under the 90% bar this file uses).
# An earlier version of this module shifted both, by 0.18 and 0.06, and those
# numbers were never supported by anything. Being fragile costs a player his
# floor. It does not cost him his ceiling, which makes sense: the seasons where
# he stays on the field are the same seasons anybody else has.
HURT_MID = 0.50          # the middle of the position, in percentile terms
FLOOR_HURT = 0.31
CEIL_HURT = 0.00         # measured flat -- see above
BUST_HURT = 0.18
BOOM_HURT = 0.00         # measured flat -- see above

# A floor cannot reach the middle and a ceiling cannot fall to it, whatever the
# arithmetic does at the extremes.
MIN_SPREAD = 0.05

# The reference cohort has to be big enough to have a shape before percentiles
# off it mean anything. Under this, everybody sits at the middle and no shift is
# applied at all.
MIN_COHORT = 8

# ---------------------------------------------------------------------------
# THE ROOKIE QUESTION, ANSWERED AND CLOSED
# ---------------------------------------------------------------------------
# There is no rookie term in this file, and it took three passes to be sure.
#
# The buggy join said drafted rookies bust 53% of the time against 18%. On the
# repaired join it is 18% against 20% -- nothing.
#
# What DOES show up pooled is that rookies look more explosive: ceiling 1.90
# against 1.53, booming 28% against 16%, in 96% and 99% of resamples. That is
# the sort of thing this file would normally act on. It does not survive the
# obvious control. Held inside each slot band, where the price is roughly fixed,
# the lift is exactly zero on average -- +0.24 and +0.22 for the two deep bands
# where the rookies actually are, -0.64 and -0.12 for the early ones. Rookies
# cluster at the back of the board, and the back of the board is already the
# widest part of this table. The bands were carrying it all along.
#
# So: nothing to add. Worth writing down anyway, because "we checked and it was
# the price" is a real answer and next year somebody will ask again.
#
# One loose end, deliberately NOT acted on here. On the repaired join the rookie
# MEDIAN sits at 1.08 against the veterans' 0.99 (95% of resamples), and our own
# board prices rookies at about 0.78 of what it prices a veteran at the same
# slot. Together those hint that the model fades rookies harder than the record
# supports. That is a question about the projection, not about the error bar
# around it, and moving the middle is not this file's job.


def _band(pos: str, rank) -> tuple:
    rows = BAND_RATIO.get(str(pos).upper()) or BAND_RATIO["WR"]
    try:
        r = int(rank)
    except (TypeError, ValueError):
        r = rows[-1][0]
    for row in rows:
        if r <= row[1]:
            return row
    return rows[-1]          # deeper than anyone has measured -- see the caveats


def shakiness(q: dict):
    """The worse of the two ways a player can be a bad bet, or None if neither.

    Identical in spirit to the `hurt` term in ratings.py, and deliberately so:
    `avail_risk` is his RECORD and `injury_risk` is what he is carrying RIGHT
    NOW. A clean record does not undo a torn ACL and being cleared does not undo
    five broken seasons, so the worse of the two is the one that prices him.
    """
    vals = [float(v) for v in (q.get("avail_risk"), q.get("injury_risk"))
            if v is not None]
    return float(np.clip(max(vals), 0.0, 1.0)) if vals else None


def _percentiles(payload: list[dict], pos: str) -> list[float]:
    """Where each man sits among the players who actually get drafted at his
    position -- 0.0 the most durable, 1.0 the shakiest.

    The reference cohort is the drafted depth only, because that is the sample
    the shift was measured on. Everybody deeper is scored against that same
    cohort rather than against the 128-man board, which would otherwise squash
    the drafted players into the top third of their own axis.
    """
    depth = MEASURED_TO.get(pos, 60)
    scores = [shakiness(q) for q in payload]
    ref = []
    for q, s in zip(payload, scores):
        if s is None:
            continue
        try:
            if int(q.get("rank")) <= depth:
                ref.append(s)
        except (TypeError, ValueError):
            continue
    if len(ref) < MIN_COHORT:                       # no shape to rank against
        return [HURT_MID] * len(payload)
    ref = np.sort(np.asarray(ref, dtype=float))
    out = []
    for s in scores:
        if s is None:
            out.append(HURT_MID)                    # no reading, no shift
            continue
        # midpoint of the empirical CDF, so ties land in the middle of their run
        lo = float(np.searchsorted(ref, s, side="left"))
        hi = float(np.searchsorted(ref, s, side="right"))
        out.append(float(np.clip(((lo + hi) / 2.0) / len(ref), 0.0, 1.0)))
    return out


def attach(payload: list[dict], pos: str) -> list[dict]:
    """Add a measured range of outcomes to every row. Mutates in place.

    Writes seven keys, none of which collide with anything already on a payload
    row -- note in particular that RB/WR/TE already carry `ceil`, which is the
    volume cap on a per-game rate and has nothing to do with this:

        season_floor / season_mid / season_ceil   season points
        floor_ratio  / ceil_ratio                 multiples of the projection
        bust_odds    / boom_odds                  percentages, display only
        range_measured                            False past the drafted depth
    """
    pos = str(pos).upper().strip()
    depth = MEASURED_TO.get(pos, 60)
    pcts = _percentiles(payload, pos)
    for q, pct in zip(payload, pcts):
        total = q.get("proj_total")
        if total is None:
            total = float(q.get("proj_ppg") or 0.0) * float(q.get("games") or 17.0)
        total = float(total)

        _lo, _hi, f, c, bust, boom = _band(pos, q.get("rank"))
        d = HURT_MID - pct                   # positive = more durable than his position

        f = float(np.clip(f + FLOOR_HURT * d, 0.0, 1.0 - MIN_SPREAD))
        c = float(max(c + CEIL_HURT * d, 1.0 + MIN_SPREAD))

        try:
            measured = int(q.get("rank")) <= depth
        except (TypeError, ValueError):
            measured = False

        q["floor_ratio"] = round(f, 2)
        q["ceil_ratio"] = round(c, 2)
        q["season_floor"] = round(f * total, 1)
        q["season_mid"] = round(total, 1)
        q["season_ceil"] = round(c * total, 1)
        q["range_measured"] = bool(measured)
        # A range on a player projected for nothing is arithmetic, not
        # information, so the odds are withheld rather than printed as 43%.
        if total <= 1.0:
            q["bust_odds"] = q["boom_odds"] = None
        else:
            q["bust_odds"] = int(round(100 * float(np.clip(bust - BUST_HURT * d, 0.02, 0.60))))
            q["boom_odds"] = int(round(100 * float(np.clip(boom + BOOM_HURT * d, 0.02, 0.60))))
    return payload
