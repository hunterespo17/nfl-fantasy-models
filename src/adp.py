"""
Current-season ADP (average draft position) overlay -- now PER PLATFORM.

ADP isn't in nflverse (it's the fantasy market's opinion), so it lives in a
small, refreshable CSV. Different platforms draft QBs very differently -- ESPN
pools fade them hard, Sleeper takes them earliest, Underdog (best-ball) sits in
between -- so we keep each platform separate and also blend a consensus.

    data/adp.csv columns:  player, sleeper, espn, underdog, ffc
       (each value is that platform's overall ADP pick number; blank = undrafted)

We convert each platform's raw ADP into a POSITIONAL rank (QB1, QB2, ...), which
is both what "where he's drafted within the position" means and the only unit
comparable across platforms with different pool depths. The consensus rank is
the average of a QB's available per-platform ranks, re-ranked 1..N.

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
}


def norm(name) -> str:
    if name is None:
        return ""
    s = str(name).lower().replace(".", "").replace("'", "").replace("-", " ")
    s = _NONALPHA.sub("", s)
    s = _SUFFIX.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return _ALIAS.get(s, s)


def load_adp(path=None) -> pd.DataFrame:
    """Read the multi-platform ADP CSV; empty frame if missing/unreadable."""
    p = path or (config.DATA_DIR / "adp.csv")
    try:
        df = pd.read_csv(p)
    except Exception:
        return pd.DataFrame(columns=["player", "key", *PLATFORMS])
    if "player" not in df.columns:
        return pd.DataFrame(columns=["player", "key", *PLATFORMS])
    df["key"] = df["player"].map(norm)
    for pf in PLATFORMS:
        df[pf] = pd.to_numeric(df[pf], errors="coerce") if pf in df.columns else pd.NA
    return df.drop_duplicates("key", keep="first").reset_index(drop=True)


def has_platforms(adp_df: pd.DataFrame) -> list[str]:
    """Which platforms actually carry any data."""
    if adp_df is None or adp_df.empty:
        return []
    return [pf for pf in PLATFORMS if pf in adp_df.columns and adp_df[pf].notna().any()]


def platform_qb_ranks(adp_df: pd.DataFrame) -> dict:
    """{platform: {key: qb_positional_rank}} -- rank within each platform's QBs."""
    out = {}
    for pf in has_platforms(adp_df):
        sub = adp_df.dropna(subset=[pf]).sort_values(pf)
        out[pf] = {k: i + 1 for i, k in enumerate(sub["key"])}
    return out


def consensus_ranks(adp_df: pd.DataFrame, pranks: dict) -> tuple[dict, dict]:
    """(consensus_qb_rank, mean_of_platform_ranks) keyed by normalized name.

    Consensus = average of a QB's available per-platform QB-ranks, then the
    field is re-ranked 1..N so the anchor is a clean QB positional rank.
    """
    score = {}
    for _, r in adp_df.iterrows():
        k = r["key"]
        vals = [pranks[pf][k] for pf in pranks if k in pranks[pf]]
        if vals:
            score[k] = sum(vals) / len(vals)
    order = sorted(score, key=lambda k: score[k])
    crank = {k: i + 1 for i, k in enumerate(order)}
    return crank, score


def raw_picks(adp_df: pd.DataFrame) -> dict:
    """{key: {platform: overall_pick_or_None}}."""
    out = {}
    for _, r in adp_df.iterrows():
        out[r["key"]] = {
            pf: (round(float(r[pf]), 1) if pf in adp_df.columns and pd.notna(r[pf]) else None)
            for pf in PLATFORMS
        }
    return out


def source_label(adp_df: pd.DataFrame) -> str:
    pfs = has_platforms(adp_df)
    return " / ".join(PLATFORM_LABEL[p] for p in pfs) + " 2026" if pfs else "ADP"


# ---------------------------------------------------------------------------
# ADP EXPECTATION CURVE
# ---------------------------------------------------------------------------
# "Is he good?" and "is he good FOR THE PRICE?" are different questions. The
# board already answers the first. This answers the second in POINTS instead of
# in draft slots, which is the unit that actually decides leagues: a QB who beats
# what his draft slot is worth by +5 pts/gm wins you weeks; one who beats it by
# two ranking spots may win you nothing.
#
# The curve is fit on real history -- data/adp_history.csv (FFC QB ADP by year)
# joined to what those QBs actually averaged that season:
#
#     expected_fpg(pick) = a + b * ln(pick)          (b is negative)
#
# Log, not linear, because draft cost is compressive: the gap between pick 20 and
# pick 40 is enormous and the gap between 140 and 160 is nearly nothing.
#
# Two honest caveats, both surfaced in the fit metadata rather than buried:
#  * Both sides are PER GAME. A QB who got hurt is measured on the games he
#    played, not punished twice -- availability is already its own factor in the
#    blend. So read the residual as "per game he plays, is he worth the pick".
#  * QBs who were drafted and then never played enough to measure are DROPPED
#    from the fit (`missed` in the metadata counts them). Those are mostly busts,
#    so the curve sits slightly optimistic at the late picks. Erring that way is
#    the safe direction: it makes a late-round "value" tag harder to earn.
HISTORY_FILE = "adp_history.csv"
MIN_GAMES_HIST = 4      # a 1-2 game cameo is noise, not a season


def load_adp_history(path=None) -> pd.DataFrame:
    """Read data/adp_history.csv -> year, name, adp, key. Empty frame if missing."""
    p = path or (config.DATA_DIR / HISTORY_FILE)
    try:
        df = pd.read_csv(p)
    except Exception:
        return pd.DataFrame(columns=["year", "name", "adp", "key"])
    need = {"year", "name", "adp"}
    if not need.issubset(df.columns):
        return pd.DataFrame(columns=["year", "name", "adp", "key"])
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df["adp"] = pd.to_numeric(df["adp"], errors="coerce")
    df = df.dropna(subset=["year", "adp"])
    df["year"] = df["year"].astype(int)
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


def fit_expectation_curve(hist: pd.DataFrame, actual: dict) -> dict:
    """Fit the historical curve. `actual` is {(year, key): actual_fp_per_game}.

    Returns {} when there isn't enough overlap to fit something trustworthy, so
    the caller can fall back rather than publish a made-up curve.
    """
    if hist is None or hist.empty or not actual:
        return {}
    picks, ppgs, missed, yrs = [], [], 0, set()
    for r in hist.itertuples():
        v = actual.get((int(r.year), r.key))
        if v is None:
            missed += 1
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
        "source": "history",
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
