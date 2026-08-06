"""
Current-season ADP (average draft position) overlay -- now PER PLATFORM.

ADP isn't in nflverse (it's the fantasy market's opinion), so it lives in a
small, refreshable CSV. Different platforms draft QBs very differently -- ESPN
pools fade them hard, Sleeper takes them earliest, Underdog (best-ball) sits in
between -- so we keep each platform separate and also blend a consensus.

    data/adp.csv columns:  player, pos, sleeper, espn, underdog, ffc
       (each value is that platform's overall ADP pick number; blank = undrafted)

We convert each platform's raw ADP into a POSITIONAL rank (QB1, QB2, ...), which
is both what "where he's drafted within the position" means and the only unit
comparable across platforms with different pool depths. The consensus rank is
the average of a player's available per-platform ranks, re-ranked 1..N.

EVERYTHING IN HERE IS PER POSITION. That is not decoration -- it is the whole
reason the file was changed. Running backs outscore quarterbacks in half-PPR and
go much earlier, so pooling the two into one list would rank a mid-tier back
above a good quarterback and, worse, fit a single expectation curve across both.
Against a pooled curve every running back looks like a steal. It would read like
the model found an edge; it would only have found a mixed-up list.

`pos` is optional in the CSV. When it's missing every row is treated as a QB,
which is exactly what the file used to contain -- so an old file keeps working
and produces the same numbers it always did.

To refresh: replace data/adp.csv (same columns). Nothing else changes.
"""
from __future__ import annotations

import re

import pandas as pd

from . import config

# Display order. Sleeper/ESPN redraft, Underdog best-ball, FFC (Fantasy Football
# Calculator) redraft. FFC only publishes a top-N, so deeper QBs are blank there.
PLATFORMS = ["sleeper", "underdog", "espn", "ffc"]
PLATFORM_LABEL = {"sleeper": "Sleeper", "underdog": "Underdog", "espn": "ESPN", "ffc": "FFC"}

_NONALPHA = re.compile(r"[^a-z ]+")
_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")
_ALIAS = {
    "matt stafford": "matthew stafford",
    "kenneth pickett": "kenny pickett",
    "cameron ward": "cam ward",
    "gardner minshew ii": "gardner minshew",
    # Draft boards use the nickname; nflverse uses the birth name. Left alone,
    # five straight seasons of a first-round receiver never join the ADP curve
    # and he shows up in the "drafted but never played" list every year.
    # Draft boards use the nickname or the long form; nflverse picks one spelling
    # and both sides get normalised toward IT, never toward each other. Mapping
    # each name to the other would just swap them and they would still miss.
    "hollywood brown": "marquise brown",
    "joshua palmer": "josh palmer",
    # Same failure as the one above, on a tight end. nflverse has him as "Chig
    # Okonkwo"; the deeper of the two historical ADP sources spells him out in
    # full for 2022-24 and short for 2025, so three of his four seasons were
    # silently falling out of the TE expectation curve -- drafted, played a full
    # year, counted as "never played". Map the long form onto the nflverse
    # spelling, not the other way round, because the stats side is the one we
    # cannot edit.
    "chigoziem okonkwo": "chig okonkwo",
}


def norm(name) -> str:
    if name is None:
        return ""
    s = str(name).lower().replace(".", "").replace("'", "").replace("-", " ")
    s = _NONALPHA.sub("", s)
    s = _SUFFIX.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return _ALIAS.get(s, s)


DEFAULT_POS = "QB"      # what a row means when the file has no `pos` column


def _with_pos(df: pd.DataFrame) -> pd.DataFrame:
    """Guarantee a clean upper-case `pos` column, defaulting to QB."""
    if "pos" in df.columns:
        df["pos"] = df["pos"].astype(str).str.upper().str.strip().replace(
            {"": DEFAULT_POS, "NAN": DEFAULT_POS, "NONE": DEFAULT_POS})
    else:
        df["pos"] = DEFAULT_POS
    return df


def load_adp(path=None) -> pd.DataFrame:
    """Read the multi-platform ADP CSV; empty frame if missing/unreadable."""
    p = path or (config.DATA_DIR / "adp.csv")
    try:
        df = pd.read_csv(p)
    except Exception:
        return pd.DataFrame(columns=["player", "pos", "key", *PLATFORMS])
    if "player" not in df.columns:
        return pd.DataFrame(columns=["player", "pos", "key", *PLATFORMS])
    df = _with_pos(df)
    df["key"] = df["player"].map(norm)
    for pf in PLATFORMS:
        df[pf] = pd.to_numeric(df[pf], errors="coerce") if pf in df.columns else pd.NA
    # De-duplicate WITHIN a position, not across the file. Two different players
    # can normalize to the same key across positions far more easily than within
    # one, and dropping a running back because a quarterback shares his name
    # would be a silent, invisible bug.
    return df.drop_duplicates(["pos", "key"], keep="first").reset_index(drop=True)


def for_pos(adp_df: pd.DataFrame, pos: str | None) -> pd.DataFrame:
    """Just the rows for one position (all rows when pos is None)."""
    if adp_df is None or adp_df.empty or pos is None:
        return adp_df
    if "pos" not in adp_df.columns:
        return adp_df if str(pos).upper() == DEFAULT_POS else adp_df.iloc[0:0]
    return adp_df[adp_df["pos"] == str(pos).upper()]


def _min_platform_rows() -> int:
    """How many players a site must price before its ranks mean anything.

    One starter per team: in a 12-team league a site that prices eleven tight
    ends has not seen a full round of them, and calling its cheapest one "TE1"
    is a statement about its own thin list rather than about the market.
    """
    try:
        return max(2, int(config.LEAGUE.get("teams", 12)))
    except Exception:  # noqa: BLE001
        return 12


def has_platforms(adp_df: pd.DataFrame) -> list[str]:
    """Which platforms carry ENOUGH data on this slice to be worth ranking.

    Callers always hand this one position's rows (see for_pos), so "enough" is
    per position -- and it has to be, because coverage is wildly uneven. The
    test used to be `.notna().any()`, which is one player. That is how Sleeper
    came to price exactly two tight ends in the file and have the cheaper of
    them, Harold Fannin Jr., printed on the board as Sleeper's TE1. He is TE7
    on ESPN, TE7 on Underdog and TE6 on FFC. The rank was not wrong about the
    arithmetic -- he really was the first of the two -- it was wrong about what
    it was counting, which is worse, because a positional rank looks like a
    market opinion and this one was an artefact of a missing feed.

    So a site now has to price a full round of the position (one starter per
    team) before it earns a column, a rank, or a vote in the consensus. Below
    that the column is dropped entirely rather than shown half-empty: a missing
    site reads as missing, a two-player site reads as a market.
    """
    if adp_df is None or adp_df.empty:
        return []
    floor = _min_platform_rows()
    return [pf for pf in PLATFORMS
            if pf in adp_df.columns and int(adp_df[pf].notna().sum()) >= floor]


def platform_pos_ranks(adp_df: pd.DataFrame, pos: str | None = DEFAULT_POS) -> dict:
    """{platform: {key: positional_rank}} -- rank within ONE position's players.

    The rank is computed after filtering to `pos`, so RB1 means the first back
    off the board and not "the first back once you've counted the quarterbacks".
    """
    sub_all = for_pos(adp_df, pos)
    out = {}
    if sub_all is None or sub_all.empty:
        return out
    for pf in has_platforms(sub_all):
        sub = sub_all.dropna(subset=[pf]).sort_values(pf)
        out[pf] = {k: i + 1 for i, k in enumerate(sub["key"])}
    return out


def platform_qb_ranks(adp_df: pd.DataFrame) -> dict:
    """Back-compat alias for the QB call site."""
    return platform_pos_ranks(adp_df, DEFAULT_POS)


def consensus_ranks(adp_df: pd.DataFrame, pranks: dict,
                    pos: str | None = DEFAULT_POS) -> tuple[dict, dict]:
    """(consensus_positional_rank, mean_of_platform_ranks) keyed by normalized name.

    Consensus = average of a player's available per-platform ranks, then the
    field is re-ranked 1..N so the anchor is a clean positional rank.
    """
    score = {}
    for _, r in for_pos(adp_df, pos).iterrows():
        k = r["key"]
        vals = [pranks[pf][k] for pf in pranks if k in pranks[pf]]
        if vals:
            score[k] = sum(vals) / len(vals)
    order = sorted(score, key=lambda k: score[k])
    crank = {k: i + 1 for i, k in enumerate(order)}
    return crank, score


def raw_picks(adp_df: pd.DataFrame, pos: str | None = DEFAULT_POS) -> dict:
    """{key: {platform: overall_pick_or_None}} for one position's rows.

    Filtered by position on purpose. The dict is keyed by normalized name, and
    once the file holds more than one position two different players can share a
    key -- at which point the last row read silently wins and a back inherits a
    quarterback's draft picks. Filtering first makes that collision impossible.
    """
    sub = for_pos(adp_df, pos)
    out = {}
    if sub is None or sub.empty:
        return out
    for _, r in sub.iterrows():
        out[r["key"]] = {
            pf: (round(float(r[pf]), 1) if pf in sub.columns and pd.notna(r[pf]) else None)
            for pf in PLATFORMS
        }
    return out


def source_label(adp_df: pd.DataFrame, pos: str | None = None) -> str:
    """Name the platforms whose prices the board is actually showing.

    Filtered by position, because the file will not be evenly filled: the
    quarterback rows carry four sites and the running-back rows carry only FFC.
    An unfiltered label on the RB board would credit three sites that contributed
    nothing to it -- a small lie, but the kind that makes you trust a number you
    shouldn't.
    """
    pfs = has_platforms(for_pos(adp_df, pos) if pos else adp_df)
    year = getattr(config, "UPCOMING_SEASON", "")
    return " / ".join(PLATFORM_LABEL[p] for p in pfs) + f" {year}".rstrip() if pfs else "ADP"


# ---------------------------------------------------------------------------
# ADP EXPECTATION CURVE
# ---------------------------------------------------------------------------
# "Is he good?" and "is he good FOR THE PRICE?" are different questions. The
# board already answers the first. This answers the second in POINTS instead of
# in draft slots, which is the unit that actually decides leagues: a QB who beats
# what his draft slot is worth by +5 pts/gm wins you weeks; one who beats it by
# two ranking spots may win you nothing.
#
# The curve is fit on real history -- data/adp_history.csv (FFC ADP by year)
# joined to what those players actually averaged that season:
#
#     expected_fpg(pick) = a + b * ln(pick)          (b is negative)
#
# Log, not linear, because draft cost is compressive: the gap between pick 20 and
# pick 40 is enormous and the gap between 140 and 160 is nearly nothing.
#
# ONE CURVE PER POSITION. Backs and quarterbacks are drafted from completely
# different price ranges and score completely different amounts, so a single
# pooled fit would be wrong for both -- and wrong in a flattering direction for
# running backs, who would all come out looking like steals against a curve that
# quarterbacks dragged down. `fit_expectation_curve` takes a `pos` and filters
# before fitting. There is no way to accidentally get the pooled version.
#
# Two honest caveats, both surfaced in the fit metadata rather than buried:
#  * Both sides are PER GAME. A player who got hurt is measured on the games he
#    played, not punished twice -- availability is already its own factor in the
#    blend. So read the residual as "per game he plays, is he worth the pick".
#  * Players who were drafted and then never played enough to measure are DROPPED
#    from the fit (`missed` in the metadata counts them). Those are mostly busts,
#    so the curve sits slightly optimistic at the late picks. Erring that way is
#    the safe direction: it makes a late-round "value" tag harder to earn.
HISTORY_FILE = "adp_history.csv"

# How much season a player has to have played before his rate gets a vote on
# what a pick at his price is worth.
#
# This was 4, and four is not a season. It let a back who tore something in
# week 3 report a two-game rate, put up hurt, into the average for his whole
# price bracket -- and there are enough of those to matter. Raising it to eight
# lifted the curve about half a point through the early and middle picks AND
# improved the fit, which is how you know the short years were noise and not
# signal: throwing data away is only supposed to make a fit worse.
#
# Eight is not a new idea here. It is already the bar for the cross-season
# reference pool in both blends and for the elite-finish check. One standard.
#
# It has to match calibration.MIN_GAMES, and for a real reason, not tidiness.
# The worth-the-pick column is a subtraction: what we project him for, minus
# what this curve says his price returns. Hold the two sides to different
# standards and the difference between the standards shows up as a lean on
# every player -- everyone a value, or everyone a reach. Change one, change both.
MIN_GAMES_HIST = 8


def load_adp_history(path=None) -> pd.DataFrame:
    """Read data/adp_history.csv -> year, name, adp, pos, key. Empty if missing.

    `pos` is optional in the file, exactly as it is in adp.csv. A file without it
    is read as all-QB, which is what the historical file contained before running
    backs existed, so the QB curve refits to the same numbers it always did.
    """
    p = path or (config.DATA_DIR / HISTORY_FILE)
    empty = pd.DataFrame(columns=["year", "name", "adp", "pos", "key"])
    try:
        df = pd.read_csv(p)
    except Exception:
        return empty
    need = {"year", "name", "adp"}
    if not need.issubset(df.columns):
        return empty
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df["adp"] = pd.to_numeric(df["adp"], errors="coerce")
    df = df.dropna(subset=["year", "adp"])
    df["year"] = df["year"].astype(int)
    df = _with_pos(df)
    df["key"] = df["name"].map(norm)
    return df.reset_index(drop=True)


def _fit_log(picks, ppgs) -> tuple[float, float, float] | None:
    """Least-squares fit of ppg = a + b*ln(pick). Returns (a, b, r2) or None."""
    import numpy as np
    x = np.log(np.asarray(picks, dtype=float))
    y = np.asarray(ppgs, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if len(x) < 8 or float(np.ptp(x)) < 0.5:
        return None
    b, a = np.polyfit(x, y, 1)
    resid = y - (a + b * x)
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return float(a), float(b), float(r2)


def fit_expectation_curve(hist: pd.DataFrame, actual: dict,
                          pos: str | None = DEFAULT_POS) -> dict:
    """Fit the historical curve FOR ONE POSITION.

    `actual` is {(year, key): actual_fp_per_game}. `pos` filters the history rows
    before anything is fit -- pass RB and only running backs shape the curve.

    Returns {} when there isn't enough overlap to fit something trustworthy, so
    the caller can fall back rather than publish a made-up curve.
    """
    if hist is None or hist.empty or not actual:
        return {}
    sub = for_pos(hist, pos)
    if sub is None or sub.empty:
        return {}
    picks, ppgs, missed, yrs, missed_names = [], [], 0, set(), []
    for r in sub.itertuples():
        v = actual.get((int(r.year), r.key))
        if v is None:
            # Two very different things land here and it matters which: a player
            # who was drafted and then barely played (a bust or an injury), and a
            # player whose NAME simply failed to match the stats. The first is
            # expected and harmless. The second silently shrinks the fit and is
            # invisible unless we say who it was -- so record the names and let
            # the build script print them.
            missed += 1
            missed_names.append(f"{int(r.year)} {r.name}")
            continue
        picks.append(float(r.adp))
        ppgs.append(float(v))
        yrs.add(int(r.year))
    fit = _fit_log(picks, ppgs)
    if fit is None:
        return {}
    a, b, r2 = fit
    if b >= 0:      # later picks scoring MORE is nonsense -- refuse to ship it
        return {}
    return {
        "a": round(a, 4), "b": round(b, 4), "r2": round(r2, 3),
        "n": len(picks), "missed": missed, "seasons": sorted(yrs),
        "lo": round(min(picks), 1), "hi": round(max(picks), 1),
        "pos": str(pos).upper() if pos else "ALL",
        "source": "history",
        # Build-time diagnostic only. `ratings.attach` lifts this off the curve
        # before the curve reaches the page, so it never ships to the browser.
        "missed_names": missed_names,
    }


def fit_curve_from_board(picks, ppgs) -> dict:
    """Fallback curve fit on THIS year's board (pick -> projected ppg).

    Self-referential -- it measures the market's own shape, not whether the
    market was right -- so it can only ever say "cheap relative to this year's
    price curve". Used only when data/adp_history.csv is missing or won't join.
    """
    fit = _fit_log(picks, ppgs)
    if fit is None:
        return {}
    a, b, r2 = fit
    if b >= 0:
        return {}
    ps = [float(p) for p in picks]
    return {
        "a": round(a, 4), "b": round(b, 4), "r2": round(r2, 3),
        "n": len(ps), "missed": 0, "seasons": [],
        "lo": round(min(ps), 1), "hi": round(max(ps), 1),
        "source": "board",
    }


def expected_fpg(pick, curve: dict):
    """Points per game a QB drafted at `pick` has historically been worth.

    The pick is clamped to the fitted range: a log curve extrapolates fast and we
    would rather flatten the ends than invent value outside the data.
    """
    import numpy as np
    if not curve or pick is None:
        return None
    try:
        p = float(pick)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(p) or p <= 0:
        return None
    p = min(max(p, float(curve["lo"])), float(curve["hi"]))
    return float(curve["a"] + curve["b"] * np.log(p))
