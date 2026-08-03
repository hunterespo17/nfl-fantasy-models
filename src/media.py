"""
Player headshot URLs for the board.

The report is a static HTML file, so images are *referenced* by URL rather than
embedded. Everything here is best-effort: if nflverse changes a column name, or
a player has no picture, we simply return nothing for him and the board falls
back to an initials avatar. Nothing in this module is allowed to break a build,
which is why every lookup is defensive and the caller wraps it in a try/except.

Team logos are not handled here — the report builds those in the browser from
the team abbreviation, so they work without any extra data.
"""
from __future__ import annotations

import pandas as pd

# nflverse spells the headshot column differently across tables and versions
# (players vs. rosters, and it has been renamed before). Try them in order.
_URL_COLS = ["headshot", "headshot_url", "espn_headshot", "headshot_href", "photo_url"]
_GSIS_COLS = ["gsis_id", "player_id", "gsis_it_id"]
_ESPN_COLS = ["espn_id"]

# ESPN's headshot pattern — the same one nflverse stores in `headshot_url`. Used
# only when a table gives us an ESPN id but no ready-made URL.
_ESPN_FMT = "https://a.espncdn.com/i/headshots/nfl/players/full/{}.png"


def _col(df: pd.DataFrame, aliases: list[str]) -> str | None:
    for a in aliases:
        if a in df.columns:
            return a
    return None


def _clean_url(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    if not s or s.lower() in {"nan", "none", "null"}:
        return None
    return s if s.startswith("http") else None


def _espn_url(v) -> str | None:
    """espn_id often arrives as a float ('3918298.0') — normalize to an int."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    if not s or s.lower() in {"nan", "none", "null"}:
        return None
    try:
        s = str(int(float(s)))
    except (TypeError, ValueError):
        return None
    return _ESPN_FMT.format(s)


def _from_frame(df) -> dict[str, str]:
    """gsis_id -> headshot URL for one nflverse table."""
    out: dict[str, str] = {}
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return out
    gc = _col(df, _GSIS_COLS)
    if gc is None:
        return out
    uc, ec = _col(df, _URL_COLS), _col(df, _ESPN_COLS)
    if uc is None and ec is None:
        return out
    keep = [c for c in (gc, uc, ec) if c]
    for row in df[keep].to_dict("records"):
        gid = row.get(gc)
        if gid is None or (isinstance(gid, float) and pd.isna(gid)):
            continue
        url = _clean_url(row.get(uc)) if uc else None
        if url is None and ec:
            url = _espn_url(row.get(ec))
        if url:
            out[str(gid).strip()] = url
    return out


def headshot_map(players=None, rosters=None) -> dict[str, str]:
    """Merge every source we have into one gsis_id -> headshot URL lookup.

    Rosters win where both have a picture: that table is season-scoped, so its
    photo is the one in the player's current uniform.
    """
    out = _from_frame(rosters)
    for gid, url in _from_frame(players).items():
        out.setdefault(gid, url)
    return out


def attach_headshots(payload: list[dict], players=None, rosters=None) -> int:
    """Add a `headshot` URL to each QB dict in place. Returns how many matched."""
    shots = headshot_map(players, rosters)
    if not shots:
        return 0
    n = 0
    for q in payload:
        url = shots.get(str(q.get("player_id") or "").strip())
        if url:
            q["headshot"] = url
            n += 1
    return n
