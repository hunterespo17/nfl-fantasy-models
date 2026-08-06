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

HOW THE NUMBER IS FITTED

  One premium per position, in season points, added to points over replacement.
  Chosen by coordinate descent to minimise, jointly:

    TIMING  the median gap between where our board puts a position's top 24 and
            where the room puts those same 24 men, summed over positions; and
    MIX     how far our positional mix inside the top 12/24/36/48/72/96/120/168
            is from the room's, weighted half again as heavily so timing cannot
            be bought at the cost of drafting the wrong shape of roster.

  Zero gap does NOT mean agreeing with the market. It means agreeing about WHEN
  quarterbacks go while disagreeing freely about WHICH quarterback -- which is
  the whole point. Running back is pinned at zero, because only the differences
  between positions can change a ranking, and that makes the other three
  readable as premiums and discounts against the back.
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

# How heavily the shape of the roster counts against the timing of the picks.
MIX_WEIGHT = 1.5

# How many of each position's own men the timing is measured over. Two rounds'
# worth of that position, which is everybody you would realistically consider.
TOP_N = 24

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
    """Fit one season-points premium per position. Running back is the zero.

    `boards` is render_site's by-position dict of finished boards. Returns a
    block the page can carry as-is; on anything it can't fit (one position, no
    market prices at all) it returns zeros, which makes the draft board fall
    back to exactly the VORP ranking rather than to nonsense.
    """
    full = float(config.LEAGUE.get("games_per_season", 17)) or 17.0
    order = tuple(positions or boards.keys())
    blank = {"premium": {p: 0.0 for p in order}, "pull": DEFAULT_PULL,
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

    def rank_of(adj: np.ndarray) -> np.ndarray:
        r = np.empty(n)
        r[np.argsort(-(vor + adj[pidx]))] = np.arange(1, n + 1)
        return r

    def cost(adj: np.ndarray) -> float:
        r = rank_of(adj)
        timing = 0.0
        for j in range(k):
            m = pidx == j
            if not m.any():
                continue
            take = np.argsort(r[m])[:TOP_N]
            timing += abs(float(np.median(mkt[m][take]) - np.median(r[m][take])))
        o = np.argsort(r)
        mix = sum(int(np.abs(np.bincount(pidx[o[:N]], minlength=k) - target[i]).sum())
                  for i, N in enumerate(DEPTHS))
        return timing + MIX_WEIGHT * mix

    adj = np.zeros(k)
    best = cost(adj)
    for _ in range(8):
        moved = False
        for j in range(k):
            keep = adj[j]
            for v in GRID:
                adj[j] = v
                c = cost(adj)
                if c < best - 1e-9:
                    best, keep, moved = c, float(v), True
            adj[j] = keep
        if not moved:
            break
    zero = adj[order.index("RB")] if "RB" in order else 0.0
    adj = np.round(adj - zero, 1)

    r = rank_of(adj)
    gap, mix = {}, {}
    for j, p in enumerate(order):
        m = pidx == j
        if not m.any():
            continue
        take = np.argsort(r[m])[:TOP_N]
        gap[p] = round(float(np.median(mkt[m][take]) - np.median(r[m][take])), 1)
    o, mo = np.argsort(r), np.argsort(mkt)
    for N in (24, 48, 96, 168):
        mix[N] = {"ours": {p: int(np.bincount(pidx[o[:N]], minlength=k)[j])
                           for j, p in enumerate(order)},
                  "room": {p: int(np.bincount(pidx[mo[:N]], minlength=k)[j])
                           for j, p in enumerate(order)}}
    return {"premium": {p: float(adj[j]) for j, p in enumerate(order)},
            "pull": DEFAULT_PULL, "full": full, "fitted": True,
            "gap": gap, "mix": mix, "n": int(n)}


def describe(block: dict) -> str:
    """The fit as a few lines of build log, so a bad one is visible at a glance."""
    if not block.get("fitted"):
        return "draft board: no positional fit (falling back to plain VOR)"
    prem = block["premium"]
    lines = ["draft board -- positional premium, in season points over replacement",
             "  " + "   ".join(f"{p} {v:+.0f}" for p, v in prem.items()),
             "  where each position's top 24 lands against the room "
             "(+ = we take him earlier)",
             "  " + "   ".join(f"{p} {v:+.1f}" for p, v in block["gap"].items())]
    for N, m in block["mix"].items():
        ours = " ".join(f"{p}{m['ours'][p]}" for p in prem)
        room = " ".join(f"{p}{m['room'][p]}" for p in prem)
        lines.append(f"  top {N:<4} ours {ours:<22} room {room}")
    return "\n".join(lines)
