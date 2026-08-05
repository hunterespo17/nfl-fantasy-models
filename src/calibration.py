"""Turning a 0-100 index score into points per game -- for RBs and QBs alike.

This is one file because the RB board and the QB board had the SAME bugs, and
keeping one copy is the only way they stay fixed together.

What the boards do with this number
-----------------------------------
Every player gets a composite: a weighted average of factors, each scored 0-100
against his peers. That is a ranking device, not points. Somewhere it has to
become "12.4 points per game", and that conversion is what lives here.

It has to be right in TWO ways, because the board asks two things of it:

  "who should I take?"      -- needs the ORDER right
  "is he worth the pick?"   -- needs the POINTS right, because that answer is a
                               subtraction: what we project him for, minus what
                               history says a pick that expensive returns

Order survives anything that only ever goes up. Points do not. Both bugs below
broke points and left order alone, which is why they sat there unnoticed: the
board looked entirely reasonable and every number on it was too small.

Bug 1: the wrong crowd
----------------------
The line used to be fit across every player who ever recorded a snap, including
the several dozen per season nobody drafts, who score close to nothing. But the
number it gets subtracted from -- the ADP expectation curve -- is built only from
players who were drafted AND played. Two different crowds. Subtracting them
measured the gap between the crowds, not the gap between a player and his price,
and it did the most damage at the top. Fix: fit on drafted players only.

Bug 2: the wrong shape
----------------------
A composite is a blend of several percentile scores, so it piles up in the middle
and thins out at both ends -- a bell. Real scoring does not look like that. It is
lopsided: a handful of backs finish far above everyone and the bottom bunches up
just above zero. Draw one straight line from a bell to a lopsided pile and you
get the two complaints that started this:

  the top is too flat -- the best player on the board projects like the sixth
  best, because a straight line has no room to pull away at the end

  the bottom runs past zero -- deep backs get negative points, get clipped to
  0.0, and a dozen players end up tied on a floor nobody actually scores

So the conversion is no longer a single straight line. It is a short list of
points -- a bend at each one, straight in between -- fitted so that the player
our factors rank Nth gets what the market's Nth pick is expected to return. Same
idea as the line, with the freedom to be steeper at the top and flatter at the
bottom, which is where real scoring actually lives.

Bug 3: the wrong seasons
------------------------
The curve answers "what does a pick this expensive return per game". Every
drafted season went into that average, including the ones that ended in October.
A back who tore an ACL in week 3 and limped through two games on his way out
counts the same as a back who played sixteen -- and his two-game rate, put up
hurt, drags the average for his whole price bracket down.

That is the wrong question. Points per game on this board means what a player is
worth WHEN HE PLAYS; the games he misses are charged separately and in full, in
the season total. So the same rule has to hold on the other side of the
subtraction: a season only gets a vote on the curve if it was long enough to be
a season. Below MIN_GAMES it is not evidence about a rate, it is evidence about
an injury, and the injury is already paid for elsewhere.

Requiring it lifts the whole points column by roughly half a point through the
middle rounds AND fits better than the version that let the short years in --
which is the tell that they were noise rather than signal.

Fitted against the ADP curve, deliberately, and not against raw scoring. Raw
scoring includes the one lucky season somebody had; the curve is what a pick at
that price returns on average. Matching it means the projection column claims
exactly as much spread as the draft market already claims, and not one point
more. That is the ceiling on how confident this file is allowed to be.

The thing that is NOT a bug, and the thing that is
--------------------------------------------------
Fitting anything to data deliberately produces hedged answers. When a predictor
is imperfect the lowest-error guess always leans toward the middle, so a fitted
column comes out with less spread than real scoring. That is not a defect. In a
straight-line fit the spread of the projections equals the correlation times the
spread of real outcomes -- so a narrow projection column is just reporting,
honestly, how much the factors actually know.

Stretching that out past the ADP curve would be manufacturing confidence, and is
specifically not done here.

What IS a defect is hedging the two sides of the subtraction by DIFFERENT
amounts. When they differ, the gap between them carries that difference, and it
shows up as a lean -- early picks drifting toward "overpriced", late picks toward
"value" -- that has nothing to do with any actual player. So both correlations
get measured here, on the same rows in the same run. `hedge_gap` in the info dict
is the number that matters: near zero means the two sides are on equal footing
and the worth-the-pick column is a fair fight.

Two things this deliberately does not do:

  It does not re-order anybody. The knot list only ever goes up, so the ranking
  coming out is the ranking going in. There is a test on exactly that.

  It does not touch the backtest, which still fits its own straight line on its
  own training seasons, so its error score stays comparable to every earlier run.
  That is also why `fit` still returns (a, b): every existing caller keeps
  working, and the bent version rides along in `info["knots"]`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Below this many drafted rows the drafted-only fit is noise, so keep the old
# all-players fit instead. Two numbers off forty rows is already generous; the
# real files carry 276 (RB) and 95 (QB).
MIN_ROWS = 40

# Bug 3 (see docstring): a season has to be a real season before it gets a vote
# on what a pick at that price is worth. Eight games is the same bar the rest of
# the model already uses for "enough of a year to read".
MIN_GAMES = 8

# How many bends in the conversion. Enough to follow the curve's shape, few
# enough that each one still sits on ~a dozen real players instead of tracking
# noise. These ship to the page, so they also stay small on purpose.
N_KNOTS = 15

# How much of the top-end slope survives past the last knot. See `apply` for the
# argument; the short version is that above the top knot there is no data, so the
# curve should get less confident rather than more.
HI_DAMP = 0.5


# ---------------------------------------------------------------------------
# The fourth bug: the weights were never the weights
# ---------------------------------------------------------------------------
# The other three bugs in this file are about the conversion from composite to
# points. This one is upstream of it, in how the composite gets built at all,
# and it took the tight-end board to expose it -- but it was never a tight-end
# problem. All four boards had it.
#
# Every factor is scored as a percentile inside its season. A percentile rank is
# UNIFORM by construction: the gap from the 95th to the 99th is four points, the
# same four points as from the 50th to the 54th, no matter what the underlying
# measure did in between. That is fine for a factor whose raw values are spread
# evenly. It is destructive for one whose raw values are right-skewed -- which
# is every usage measure in football, because a handful of players get fed and a
# long tail of backups do not.
#
# The tell was Trey McBride. He beat Sam LaPorta on every single input -- 9.3
# targets a game against 5.8, a 0.270 target share against 0.187, more air
# yards, more yards per route, more first downs per route, more routes run --
# and came out BEHIND him on the board. The reason: those enormous raw gaps sat
# inside about three percentile points, because both men are near the top of a
# crowded list. Meanwhile Arizona's implied total is genuinely the worst in the
# league and Detroit's near the best, and team quality has no skew at all --
# thirty-two teams spread evenly -- so Vegas kept its full 0-100 range and swung
# nearly eight points of composite on its own.
#
# Measured across the top twenty-four of each board, weight x spread -- the say a
# factor ACTUALLY gets -- came out:
#
#     board   biggest separator in practice        what it should have been
#     QB      Talent      (w32, spread 22)  7.15   Talent -- healthy
#     RB      Vegas       (w10, spread 31)  3.07   Talent w14 got 1.11
#     WR      Vegas       (w14, spread 22)  3.04   Volume w19 got 0.99
#     TE      Vegas       (w9,  spread 29)  2.59   Volume w22 got 1.45
#
# On three of the four boards the single strongest separator was a factor with a
# middling weight, and the heaviest-weighted usage factor was doing about a third
# of its job. Those weights came off honest univariate fits against next season's
# points. The board simply wasn't using them.
#
# THE OBVIOUS FIX IS THE WRONG ONE, and the numbers said so. Muting Vegas --
# either halving its spread or halving its weight -- was tested first, and it
# HURT: paired against the shipped board on the same rows, halving the Vegas
# weight came out -0.028 points per game on tight ends (better on only 16% of
# bootstrap resamples), -0.007 on quarterbacks, -0.004 on backs. It helped
# receivers (+0.047) and nowhere else. Vegas is not too loud. It is doing real
# work, and turning it down throws away signal to make the board LOOK more
# sensible. That is what over-correcting looks like from the inside.
#
# What actually works is giving the usage factors their distance back. Push each
# percentile through the inverse normal curve: the tails stretch, the middle
# stays put. Every rank inside every factor is preserved EXACTLY -- this cannot
# reorder a single player within a factor. Only the gaps change, and they change
# back toward the shape the raw numbers already had.
#
# Paired bootstrap against the shipped board, same rows, same seasons, same
# walk-forward, positive = better:
#
#     board   gain (pts/game)   better on
#     QB      +0.038            72% of resamples
#     RB      +0.077            88%
#     WR      +0.063            83%
#     TE      +0.018            73%
#
# The only one of seven variants tested that improved all four. And the boards it
# produces move toward sanity without ever being told to: McBride to TE1 and
# Brock Bowers from 9th to 5th, Justin Jefferson from WR10 to WR5, Ashton Jeanty
# into the RB top six from outside it, Kyler Murray into the QB top six.
#
# SPREAD is not a tuned knob. 15, 20 and 25 were all tested: 15 and 20 agree to
# three decimals, because a pure rescale of every factor is absorbed by the
# calibration slope downstream. The only non-linear thing here is the clip at the
# ends, and at 20 it bites at about the top and bottom half-percent. If the gain
# moved when SPREAD moved, the gain would be coming from the clip rather than
# from the transform -- which would be a reason not to ship it.
SPREAD = 20.0
_CLIP = 0.005                      # keeps the inverse normal finite at the ends


def stretch(s, spread: float = SPREAD) -> pd.Series:
    """Percentile (0-100) -> same order, tails given their gaps back.

    Rank-preserving and monotone, so nothing this touches can reorder players
    within a factor. Standard library only -- no scipy import, because scipy is
    not in requirements.txt and this has to run on a laptop that only ever ran
    `pip install -r requirements.txt`.
    """
    from statistics import NormalDist
    inv = NormalDist().inv_cdf
    v = pd.to_numeric(pd.Series(s), errors="coerce")
    raw = v.to_numpy(dtype="float64")
    u = np.clip(raw / 100.0, _CLIP, 1.0 - _CLIP)
    z = np.array([inv(float(x)) for x in u])
    out = np.clip(50.0 + spread * z, 0.0, 100.0)
    return pd.Series(np.where(np.isnan(raw), np.nan, out), index=v.index)


def stretch_groups(p: pd.DataFrame, groups) -> pd.DataFrame:
    """Apply `stretch` to every factor column, in place.

    Called at exactly one point in each board -- after the factor columns are
    final and before they are averaged into the composite -- so what ships is
    the same thing the backtest above measured, not a near relative of it.
    """
    for g in groups:
        if g in p.columns:
            p[g] = stretch(p[g]).fillna(50.0)
    return p


def drafted_picks(pos: str = "RB") -> dict:
    """(season, name-key) -> draft pick, for everyone actually drafted that year.

    Straight off data/adp_history.csv through the same name-normalising the ADP
    expectation curve uses, because it has to be the SAME crowd of players.
    """
    try:
        from . import config
        from .adp import for_pos, load_adp_history, norm
        h = for_pos(load_adp_history(config.DATA_DIR / "adp_history.csv"), pos)
        if h is None or h.empty:
            return {}
        return {(int(y), norm(str(n))): float(a)
                for y, n, a in zip(h["year"], h["name"], h["adp"])}
    except Exception:  # noqa: BLE001
        # A missing or unreadable history file must never stop a build. The
        # caller falls back to the old fit, which is worse but still works.
        return {}


def _corr(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3 or np.std(x) == 0 or np.std(y) == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def apply(comp, a: float, b: float, knots=None):
    """composite -> points per game. The one place this maths lives.

    Kept in step with the copy on the page by hand (report.py, `projOf`), so any
    change here has to be made there too -- there is a test that projects the
    same board both ways and compares.

    Outside the fitted range it keeps going rather than flattening off, so an
    unusually good or bad score still moves the number. Never below zero.

    THE TOP END IS DAMPED, and it is worth saying why, because the obvious version
    of this is wrong in a way that is invisible until you plot the board.

    Above the last knot there is nobody. The slope up there was measured off the
    final pair of knots -- the two thinnest, luckiest points in the whole fit, the
    handful of players who happened to finish first -- and it is also the STEEPEST
    slope on the curve, because the curve bends up at the top. Running that slope
    out past the data multiplies the noisiest number by the largest lever, with
    nothing above it to argue back.

    On the 2026 running back board that produced a visible artefact: Bijan
    Robinson, Christian McCaffrey and Jahmyr Gibbs all landed past the top knot
    and got extrapolated to 22.5 / 20.9 / 20.8 while RB4 sat at 14.8 -- a 6.0 point
    step between RB3 and RB4. Real seasons do not do that. Over 2018-2025 the
    median RB3 -> RB4 step is 0.6 and the largest was 2.3. And a projection is an
    EXPECTATION, so it should be smoother than a realised season, not lumpier:
    the man who actually finishes RB1 got the breaks, and we do not know who he is.

    So beyond the fitted range the slope used is the average across the top third
    of the knots rather than the last pair -- a less noisy read on how steep the
    top of the board really is -- and it is halved, which is a plain statement that
    confidence falls off outside the data. Still monotone, so nothing reorders;
    the top of the board just stops running away from the rest of it.
    """
    c = np.asarray(comp, dtype="float64")
    if not knots or len(knots) < 2:
        return np.clip(a + b * c, 0, None)
    kx = np.array([float(k[0]) for k in knots], dtype="float64")
    ky = np.array([float(k[1]) for k in knots], dtype="float64")
    out = np.interp(c, kx, ky)
    lo_slope = (ky[1] - ky[0]) / (kx[1] - kx[0]) if kx[1] > kx[0] else 0.0

    # Top third of the fitted range, not the final pair. Falls back to the last
    # pair when there are too few knots for a third to mean anything.
    j = max(0, len(kx) - max(2, len(kx) // 3))
    hi_slope = ((ky[-1] - ky[j]) / (kx[-1] - kx[j])) if kx[-1] > kx[j] else 0.0
    if not np.isfinite(hi_slope) or hi_slope <= 0:
        hi_slope = (ky[-1] - ky[-2]) / (kx[-1] - kx[-2]) if kx[-1] > kx[-2] else 0.0
    hi_slope *= HI_DAMP

    out = np.where(c < kx[0], ky[0] + lo_slope * (c - kx[0]), out)
    out = np.where(c > kx[-1], ky[-1] + hi_slope * (c - kx[-1]), out)
    return np.clip(out, 0, None)


def _knots(c: np.ndarray, target: np.ndarray, tail_c=None, tail_y=None):
    """Bend the conversion so the Nth-ranked composite lands on the Nth target.

    Both arrays get sorted and lined up, then thinned to N_KNOTS evenly spaced
    positions. `tail_c`/`tail_y` add one anchor below the fitted range, so the
    undrafted end of the board lands on what undrafted players actually score
    instead of being extrapolated off the bottom into negative numbers.
    """
    if len(c) < N_KNOTS * 2:
        return []
    cs, ts = np.sort(c), np.sort(target)
    idx = np.unique(np.linspace(0, len(cs) - 1, N_KNOTS).round().astype(int))
    kx, ky = list(cs[idx]), list(ts[idx])

    if tail_c is not None and tail_y is not None and tail_c < kx[0]:
        # Only below the first bend, and only if it doesn't reverse the slope --
        # an anchor above the drafted floor would re-order the bottom of the board.
        ky0 = min(float(tail_y), ky[0] - 0.05)
        if ky0 < ky[0]:
            kx.insert(0, float(tail_c))
            ky.insert(0, max(0.0, ky0))

    # Strictly increasing on both axes or the interpolation is meaningless.
    out = [(kx[0], ky[0])]
    for x, y in zip(kx[1:], ky[1:]):
        if x > out[-1][0] + 1e-9 and y > out[-1][1] + 1e-9:
            out.append((float(x), float(y)))
    return [[round(x, 3), round(y, 3)] for x, y in out] if len(out) >= 2 else []


def fit(p: pd.DataFrame, pos: str = "RB",
        info: dict | None = None) -> tuple[float, float]:
    """Map composite -> points per game. Returns (a, b) for a + b*composite.

    Read the module docstring first; this is only the arithmetic. The bent
    version, when there was enough to build one, comes back in `info["knots"]` --
    callers that want it pass it to `apply()`; callers that don't (the backtest,
    the smoke test) carry on with the straight line and are unaffected.
    """
    d = p[p["actual_ppg"].notna() & p["composite"].notna()]
    if info is not None:
        info.update({"n_all": int(len(d)), "n_drafted": 0,
                     "anchor": "all players", "knots": [], "shape": "line"})
    if len(d) < 5:
        return 0.0, 0.25  # harmless fallback: an empty board beats a crash

    # ---- bug 3: a rate needs a real season behind it -----------------------
    # Guarded, not assumed: if the column isn't there, or throwing the short
    # years out would leave too little to fit, the old behaviour stands. Better
    # a slightly low curve than a curve built on thirty rows.
    if "actual_games" in d.columns:
        g = pd.to_numeric(d["actual_games"], errors="coerce")
        full = d[g >= MIN_GAMES]
        if len(full) >= MIN_ROWS:
            if info is not None:
                info.update({"n_short_dropped": int(len(d) - len(full)),
                             "min_games": MIN_GAMES})
            d = full

    # ---- bug 1: fit on the crowd the ADP curve was built from --------------
    picks = drafted_picks(pos)
    pk, undrafted = None, None
    if picks:
        from .adp import norm
        keyed = pd.Series([picks.get((int(s), norm(str(n))))
                           for s, n in zip(d["season"], d["player_name"])],
                          index=d.index, dtype="float64")
        sub = d[keyed.notna()]
        if info is not None:
            info["n_drafted"] = int(len(sub))
        if len(sub) >= MIN_ROWS:
            undrafted = d[keyed.isna()]
            d, pk = sub, keyed[keyed.notna()]
            if info is not None:
                info["anchor"] = "drafted players"
                info["seasons"] = sorted({int(s) for s in sub["season"]})

    c = d["composite"].to_numpy(dtype="float64")
    y = d["actual_ppg"].to_numpy(dtype="float64")
    b, a = np.polyfit(c, y, 1)
    a, b = float(a), float(b)
    if info is not None:
        info.update({"n_used": int(len(d)), "sd_actual": round(float(np.std(y)), 2),
                     "sd_line": round(abs(b) * float(np.std(c)), 2),
                     "a": round(a, 3), "b": round(b, 4)})

    if pk is None or info is None:
        return a, b

    # ---- how much does each side of the subtraction actually know? ---------
    # Measured on the very same rows, in the same run. If the composite knows
    # less than the draft pick does, the worth-the-pick column leans, and the
    # build says so out loud rather than quietly stretching anything.
    lp = np.log(np.clip(pk.to_numpy(dtype="float64"), 1.0, None))
    r_comp, r_pick = _corr(c, y), abs(_corr(lp, y))
    info.update({"r_composite": round(r_comp, 3), "r_pick": round(r_pick, 3),
                 "hedge_gap": round(r_comp - r_pick, 3)})

    # ---- bug 2: bend it to the shape of the ADP curve ----------------------
    # The curve gets re-fit here on these exact rows rather than imported, so
    # both sides of the subtraction are guaranteed to come off one crowd of
    # players in one run. cb must come out negative: pricier pick, more points.
    cb, ca = np.polyfit(lp, y, 1)
    if cb >= 0:
        return a, b
    target = ca + cb * lp
    tail_c = tail_y = None
    if undrafted is not None and len(undrafted) >= 10:
        tail_c = float(np.percentile(undrafted["composite"].to_numpy("float64"), 5))
        tail_y = float(np.median(undrafted["actual_ppg"].to_numpy("float64")))
    ks = _knots(c, target, tail_c, tail_y)
    if ks:
        fitted = apply(c, a, b, ks)
        info.update({"knots": ks, "shape": "curve",
                     "sd_curve": round(float(np.std(target)), 2),
                     "sd_proj": round(float(np.std(fitted)), 2),
                     "top": round(float(max(ky for _kx, ky in ks)), 2),
                     "floor": round(float(min(ky for _kx, ky in ks)), 2)})
    return a, b
