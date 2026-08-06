"""Turning the value board into a board you can actually draft off.

Points over replacement is the right way to compare a quarterback with a
running back, and it is still what the VORP Rankings tab shows. It is not by
itself a draft board, and the reason is the one Hunter put his finger on: you
start one quarterback and one tight end but two or three backs and receivers,
so the same points-over-replacement is worth less at the thin end of the roster
than at the thick end. A board that ignores that takes tight ends far too
early -- measurably, on this year's projections, THIRTY-TWO PICKS too early.

Everything below is the correction, and it is one number per position.

WHAT WAS MEASURED FIRST, BECAUSE TWO OBVIOUS EXPLANATIONS TURNED OUT TO BE WRONG

  "Backs and receivers are drafted much deeper than their starter count, and
  quarterbacks and tight ends are not."  No. Across the first 168 picks the
  room takes 25 QB / 50 RB / 70 WR / 23 TE against starter-count baselines of
  12 / 30 / 30 / 12 -- about twice the baseline at EVERY position (2.1x, 1.7x,
  2.3x, 1.9x). The depth of the draft is not the asymmetry.

  "Then price the cost of waiting directly -- what does the next man at this
  position, one round-trip later, cost you."  Tried three ways and it broke
  every time. Anchored on the player it rewards whoever the market is coldest
  on (it put a backup quarterback ninth overall, on the strength of the market
  disliking him rather than us liking him); anchored on the position and solved
  to a fixed point it fixed that and still would not move tight ends.

WHAT THE ACTUAL MECHANISM IS

  A projection is E[points | this player]. The realised points-by-rank curve is
  an ORDER STATISTIC -- it is measured after the season has already thrown out
  every injury, benching and disappearance -- so it is far steeper than any
  projection curve can be. Measured over 2022-25: the RB1 slot projects 246 and
  delivers 345; the RB50 slot projects 94 and delivers 31. A replacement level
  read off our own projections is therefore not replacement level, and it is
  wrong by a different amount at each position.

  And the board is DENSE where it matters. Between picks 30 and 60 a ten-point
  season error is worth about thirty draft picks. That is why a tight end
  discount that sounds like a rounding error moves the position most of a
  round and a half.

WHAT THE SIMULATION SAID, INCLUDING THE PART THAT WENT AGAINST ME

  Forty-eight drafts -- four seasons, twelve seats, paired opponents -- scored
  on the best legal starting lineup from what actually happened. Every board
  built out of projected value lost to simply following the room: raw projected
  points by 148 points of starting lineup, points-over-replacement by 85, and a
  replacement level explicitly FITTED to maximise real points and then held out
  on an unseen season still lost by 27 while beating today's board by 51.

  So the room's sense of WHICH POSITION goes when is better than ours. Its
  sense of WHICH PLAYER is a separate question and that lab cannot answer it,
  because in it our projections were the room's projections by construction.

  That splits the job exactly where it should be split:

      the room decides    how the positions interleave
      the model decides   who fills each position's slots

  The simulation sets the SIGN of the correction -- fade quarterback, fade
  tight end, leave running back alone. It does NOT set the size: its lab had
  the QB1 slot 127 points clear of the RB1 slot where our 2026 board has it 44
  clear, so its magnitudes do not transfer, and applying them raw drops the
  first quarterback to pick 36. The size is fitted here, on our own numbers.

WHY A PREMIUM ALONE WAS NOT ENOUGH  (Hunter: "Josh Allen still seems high")

  The first version of this fitted ONE number per position and scored itself on
  the median gap over each position's top 24. Both halves of that were wrong,
  and the quarterbacks are where it showed.

  A MEDIAN CANNOT SEE SHAPE. Quarterback's median over its top 24 came out one
  pick late -- fixed, apparently -- while its top EIGHT was still thirteen picks
  early, because being early at the top and late in the teens nets to nothing in
  the middle. Tight end read as one and a half picks late over its top 24 and
  nineteen and a half picks early over its top 8. So timing is now measured at
  the top 4, 8, 16 and 24 of each position. Those sets are nested, so a man in
  his position's top four is counted four times and the top of the board carries
  the weight it deserves.

  A CONSTANT CANNOT FLATTEN A POSITION. It lifts a position's first and its
  twelfth by the same amount, so the only way to move Allen from ninth overall
  to where the room takes him was a discount so large it buried the twelfth
  quarterback fifty picks past his price. Each position therefore also gets a
  SLOPE, and its board value is  slope x VOR + premium.

  AND THE MIX WAS COUNTED IN THE WRONG UNIT. Being one quarterback ahead of the
  room inside the first 24 picks is a quarter of the picks made so far; being
  one ahead inside 168 is under four percent. The old objective added both raw
  and so weighed them the same. Errors are now per round -- 12 x wrong / depth.

WHAT THE SLOPE CAME OUT AT, AND THE CHECK THAT IT IS NOT JUST CURVE-FITTING

  Fitted against the room: QB 0.60, RB 1.00 (the anchor), WR 0.90, TE 1.00. Read
  that as: our quarterback spread is about 40% too wide and the other three are
  right. It is stable -- the quarterback slope sits between 0.55 and 0.65 for
  every roster-shape weight from 1 to 8, and the whole solution is unchanged
  across 2 to 4, which is why the weight is 3.

  Then measured independently, with no market input at all: take the preseason
  consensus rank 2020-2025 as a SLOT, score what the man drafted there actually
  returned under this league's rules, and compare it with our own VOR, band for
  band. Least squares through the origin over the first twelve slots gives

      QB 0.10 (-0.48 to 0.68)   RB 0.91 (0.74 to 1.07)
      WR 0.85 ( 0.50 to 1.21)   TE 0.94 (0.62 to 1.26)

  Same verdict, from six years of realised points instead of from ADP: three
  positions right, quarterback far too steep. The number behind it is blunt --
  the top three quarterback slots returned 4 points LESS than the QB10-14 slots
  over those six years, against the 52 our board pays for them. The fitted 0.60
  is well inside that interval and much the more conservative of the two, which
  is deliberate: six years is six draws, and the market is not the only thing
  that can be wrong.

HOW THE NUMBERS ARE FITTED

  A slope and a premium per position, by coordinate descent, minimising:

    TIMING  the median gap between where our board puts a position's top 4 / 8 /
            16 / 24 and where the room puts those same men, averaged over the
            four depths and summed over positions; and
    MIX     how far our positional mix inside the top 12/24/36/48/72/96/120/168
            is from the room's, per round, weighted three times as heavily so
            timing cannot be bought at the cost of the wrong shape of roster.

  Zero gap does NOT mean agreeing with the market. It means agreeing about WHEN
  quarterbacks go while disagreeing freely about WHICH quarterback -- which is
  the whole point, and it is why tight end still comes out taking Kelce, Kittle
  and Pitts fifty picks before the room will: the room has written off three
  veterans, and that is a disagreement about men, not about timing.

  Running back is pinned at premium 0 and slope 1. Only the differences between
  positions can change a ranking, and scaling every position at once changes
  nothing, so without an anchor the search wanders; pinning the back also makes
  the other three readable as premiums and discounts against him.
"""
from __future__ import annotations

import numpy as np

from . import config

# The depths the positional mix is checked at: a round, two rounds, three, four,
# six, eight, ten, and fourteen -- the last being roughly where a 12-team draft
# stops taking players it has an opinion about.
DEPTHS = (12, 24, 36, 48, 72, 96, 120, 168)

# The premium is fitted over this range, a point at a time. Wider than anything
# the fit has ever wanted (the biggest is a ten-point tight end discount), so
# the bounds are a guard rail and not a constraint.
GRID = np.arange(-90.0, 91.0, 1.0)

# The slope is fitted over this range. Below 0.4 a position stops being ranked
# by our own opinion of it at all, and above 1.2 the fit would be claiming our
# spread is too NARROW, which nothing measured has ever suggested.
SLOPE_GRID = np.round(np.arange(0.40, 1.201, 0.05), 2)

# How heavily the shape of the roster counts against the timing of the picks.
# Both terms are in draft picks now, so this is readable: a player in the wrong
# position bucket costs three times a pick of bad timing. The whole solution is
# unchanged anywhere from 2 to 4.
MIX_WEIGHT = 3.0

# How deep into each position the timing is measured. Nested on purpose: a man
# in his position's top four is inside all four sets and so counts four times.
# The old version used the median of the top 24 alone and that is exactly what
# let the quarterbacks stay thirteen picks early while reading as fixed.
TIMING_DEPTHS = (4, 8, 16, 24)
TOP_N = TIMING_DEPTHS[-1]

# Where the dial starts: a light pull toward the room. Hunter asked for "a blend
# of pure value and when he'll be gone", and this is the blend -- 0 is the
# board's own opinion, 1 would be handing the draft to consensus. At 0.15 about
# two thirds of the players inside the room's top 168 still move a full round or
# more on our board, so the model's opinion is very much still there.
DEFAULT_PULL = 0.15

# Anything priced at or past this pick is off the end of somebody's board rather
# than genuinely valued there -- ESPN stacks its long tail at 169.9 and does not
# mean it. Used only to decide who is IN the drafted pool for the fit.
DRAFTED_POOL = 169.0


def _rows(boards: dict) -> tuple:
    """Flatten every position's board into parallel arrays for the fit."""
    pos, vor, pick = [], [], []
    for p, bd in boards.items():
        # "qbs" is the site payload's key at every position -- a misnomer the
        # browser script depends on in about forty places -- and "payload" is
        # what a freshly built result calls the same list. Accept both so this
        # can be fed either a saved board or render_site's own dict.
        bd = bd or {}
        payload = bd.get("payload")
        if payload is None:
            payload = bd.get("qbs") or []
        if isinstance(payload, dict):                    # older single-key shape
            payload = payload.get("qbs") or []
        for x in payload:
            v = x.get("vor")
            if v is None:
                continue
            prices = [q for q in (x.get("adp_picks") or {}).values()
                      if q is not None and q < DRAFTED_POOL]
            pos.append(p)
            vor.append(float(v))
            pick.append(float(np.mean(prices)) if prices else np.nan)
    return np.array(pos), np.array(vor, float), np.array(pick, float)


def premiums(boards: dict, positions=None) -> dict:
    """Fit a slope and a season-points premium per position, against the room.

    A position's draft value is  slope[p] * VOR + premium[p], with the running
    back pinned at slope 1 and premium 0. The premium moves a whole position up
    or down the board; the slope decides how far its first man sits above its
    twelfth, which is the part a premium cannot touch and the part the
    quarterbacks needed.

    `boards` is render_site's by-position dict of finished boards. Returns a
    block the page can carry as-is; on anything it can't fit (one position, no
    market prices at all) it returns a neutral block -- slope 1, premium 0 --
    which makes the draft board fall back to exactly the VORP ranking rather
    than to nonsense.
    """
    full = float(config.LEAGUE.get("games_per_season", 17)) or 17.0
    order = tuple(positions or boards.keys())
    blank = {"premium": {p: 0.0 for p in order},
             "slope": {p: 1.0 for p in order}, "pull": DEFAULT_PULL,
             "full": full, "fitted": False, "gap": {}, "mix": {}}

    pos, vor, pick = _rows(boards)
    if len(order) < 2 or len(pos) < 50 or not np.isfinite(pick).any():
        return blank

    # Market rank: everybody with a price, in price order, then everybody
    # without one behind them. Overall pick and not a positional rank, because
    # that is the only ADP unit that means the same thing at every position.
    mkt = np.empty(len(pos), float)
    mkt[np.argsort(np.where(np.isfinite(pick), pick, np.inf), kind="stable")] = \
        np.arange(1, len(pos) + 1)

    pidx = np.array([order.index(p) for p in pos])
    n, k = len(pos), len(order)
    mo = np.argsort(mkt)
    target = np.array([np.bincount(pidx[mo[:N]], minlength=k) for N in DEPTHS])

    masks = [pidx == j for j in range(k)]

    def rank_of(slope: np.ndarray, adj: np.ndarray) -> np.ndarray:
        r = np.empty(n)
        r[np.argsort(-(slope[pidx] * vor + adj[pidx]))] = np.arange(1, n + 1)
        return r

    def cost(slope: np.ndarray, adj: np.ndarray) -> float:
        r = rank_of(slope, adj)
        timing = 0.0
        for j in range(k):
            m = masks[j]
            if not m.any():
                continue
            o = np.argsort(r[m])
            for d in TIMING_DEPTHS:
                t = o[:d]
                timing += abs(float(np.median(mkt[m][t]) - np.median(r[m][t])))
        timing /= len(TIMING_DEPTHS)
        o = np.argsort(r)
        mix = 0.0
        for i, N in enumerate(DEPTHS):
            wrong = int(np.abs(np.bincount(pidx[o[:N]], minlength=k)
                               - target[i]).sum())
            mix += 12.0 * wrong / N          # players per round in the wrong bucket
        return timing + MIX_WEIGHT * mix

    # Coordinate descent over both parameters of every position except the back,
    # whose slope stays 1 and whose premium is subtracted off at the end. Ten
    # sweeps is generous; it has never taken more than four to stop moving.
    anchor = order.index("RB") if "RB" in order else -1
    slope, adj = np.ones(k), np.zeros(k)
    best = cost(slope, adj)
    for _ in range(10):
        moved = False
        for j in range(k):
            keep = adj[j]
            for v in GRID:
                adj[j] = v
                c = cost(slope, adj)
                if c < best - 1e-9:
                    best, keep, moved = c, float(v), True
            adj[j] = keep
            if j == anchor:
                continue
            keep = slope[j]
            for v in SLOPE_GRID:
                slope[j] = v
                c = cost(slope, adj)
                if c < best - 1e-9:
                    best, keep, moved = c, float(v), True
            slope[j] = keep
        if not moved:
            break
    zero = adj[anchor] if anchor >= 0 else 0.0
    adj = np.round(adj - zero, 1)

    r = rank_of(slope, adj)
    gap, mix = {}, {}
    for j, p in enumerate(order):
        m = masks[j]
        if not m.any():
            continue
        o = np.argsort(r[m])
        gap[p] = {int(d): round(float(np.median(mkt[m][o[:d]])
                                     - np.median(r[m][o[:d]])), 1)
                  for d in TIMING_DEPTHS}
    o, mo = np.argsort(r), np.argsort(mkt)
    for N in (24, 48, 96, 168):
        mix[N] = {"ours": {p: int(np.bincount(pidx[o[:N]], minlength=k)[j])
                           for j, p in enumerate(order)},
                  "room": {p: int(np.bincount(pidx[mo[:N]], minlength=k)[j])
                           for j, p in enumerate(order)}}
    return {"premium": {p: float(adj[j]) for j, p in enumerate(order)},
            "slope": {p: round(float(slope[j]), 2) for j, p in enumerate(order)},
            "pull": DEFAULT_PULL, "full": full, "fitted": True,
            "gap": gap, "mix": mix, "n": int(n)}


def describe(block: dict) -> str:
    """The fit as a few lines of build log, so a bad one is visible at a glance."""
    if not block.get("fitted"):
        return "draft board: no positional fit (falling back to plain VOR)"
    prem = block["premium"]
    slope = block.get("slope") or {}
    lines = ["draft board -- board value = slope x VOR + premium, running back "
             "pinned at 1.00 and +0",
             "  slope    " + "   ".join(f"{p} {slope.get(p, 1.0):.2f}" for p in prem),
             "  premium  " + "   ".join(f"{p} {v:+.0f}" for p, v in prem.items())
             + "   season points",
             "  where each position's top N lands against the room "
             "(+ = we take him earlier)"]
    depths = sorted({int(d) for g in block["gap"].values() for d in g}) or [TOP_N]
    lines.append("  " + " ".join(f"{'top ' + str(d):>10}" for d in depths))
    for p, g in block["gap"].items():
        g = g if isinstance(g, dict) else {TOP_N: g}
        lines.append(f"  {p:<4}" + " ".join(
            f"{g.get(d, g.get(str(d), 0.0)):>+9.1f}" for d in depths))
    for N, m in block["mix"].items():
        ours = " ".join(f"{p}{m['ours'][p]}" for p in prem)
        room = " ".join(f"{p}{m['room'][p]}" for p in prem)
        lines.append(f"  top {N:<4} ours {ours:<22} room {room}")
    return "\n".join(lines)
