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

    Outside the fitted range it keeps going at whatever slope the end bend had,
    rather than flattening off, so an unusually good or bad score still moves the
    number. Never below zero.
    """
    c = np.asarray(comp, dtype="float64")
    if not knots or len(knots) < 2:
        return np.clip(a + b * c, 0, None)
    kx = np.array([float(k[0]) for k in knots], dtype="float64")
    ky = np.array([float(k[1]) for k in knots], dtype="float64")
    out = np.interp(c, kx, ky)
    lo_slope = (ky[1] - ky[0]) / (kx[1] - kx[0]) if kx[1] > kx[0] else 0.0
    hi_slope = (ky[-1] - ky[-2]) / (kx[-1] - kx[-2]) if kx[-1] > kx[-2] else 0.0
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
