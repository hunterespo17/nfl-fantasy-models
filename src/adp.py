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
