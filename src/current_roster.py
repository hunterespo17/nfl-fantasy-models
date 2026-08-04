"""
Map each player to his CURRENT team and depth-chart spot from live depth charts
+ rosters (nflverse refreshes both daily, so this reflects the current offseason).

This is the "current mapping" half of the model: production/talent comes from
historical games, but *which team a player is on now* and *where he sits on the
depth chart* must come from today's depth chart -- not last year's game logs.

Works for any position. `pos="QB"` is the default and behaves exactly as it
always did; `pos="RB"` is the other one in use today.

One real difference between the two, and the reason `keep_depth` exists: a team
has ONE quarterback who matters, so the QB board wants depth rank 1 and nothing
else. A backfield routinely has two or three backs who all touch the ball, and
the second one is frequently the better draft pick, so the RB board keeps ranks
1 through 3. Filtering an RB board down to lead backs would delete exactly the
players worth finding.

Depth-chart columns changed in the 2025+ nflverse format, and this runs on the
user's machine where we can't see the exact schema in advance, so column lookups
are defensive and we emit a debug summary of what was actually found.
"""
from __future__ import annotations

import pandas as pd

# pos_abb is the position abbreviation in nflverse's 2025+ depth-chart format; it
# must be tried before group columns like pos_grp ("OFF"). Order matters.
_POS = ["pos_abb", "position", "pos", "depth_position", "pos_name", "football_position"]
_GSIS = ["gsis_id", "player_id", "gsis_it_id", "pfr_id"]
_TEAM = ["team", "club_code", "team_abbr", "recent_team", "posteam"]
_NAME = ["full_name", "player_name", "football_name", "player", "gsis_name", "display_name"]
_RANK = ["depth_team", "depth_team_seq", "rank", "depth_chart_order", "order",
         "string_depth_team", "pos_rank", "depth_position_rank"]
_TIME = ["dt", "last_updated", "updated", "dt_updated", "report_date", "gameday", "week"]


def _col(df: pd.DataFrame, aliases: list[str]) -> str | None:
    for a in aliases:
        if a in df.columns:
            return a
    return None


# What each position can be called. Abbreviations first, then the spelled-out
# forms some depth-chart vintages use. Fullbacks are deliberately NOT running
# backs here: they're a different fantasy animal and they'd clutter an RB board.
_POS_ALIASES = {
    "QB": ("QB",),
    "RB": ("RB", "HB"),
    "WR": ("WR",),
    "TE": ("TE",),
}
_POS_LONG = {
    "QB": ("QUARTERBACK",),
    "RB": ("RUNNING BACK", "RUNNINGBACK", "HALFBACK"),
    "WR": ("WIDE RECEIVER", "WIDERECEIVER"),
    "TE": ("TIGHT END", "TIGHTEND"),
}


def _pos_rows(df: pd.DataFrame, pos: str = "QB") -> pd.DataFrame:
    """Rows for one position, tolerant of abbreviation vs spelled-out naming."""
    col = _col(df, _POS)
    if col is None:
        # No position column found -> return EMPTY rather than everything, so we
        # never pollute the map with all positions. The other source (rosters,
        # which has 'position') still provides the players we want.
        return df.iloc[0:0]
    pos = str(pos).upper().strip()
    v = df[col].astype(str).str.upper().str.strip()
    keep = v.isin(_POS_ALIASES.get(pos, (pos,)))
    for long in _POS_LONG.get(pos, ()):
        keep = keep | v.str.startswith(long)
    return df[keep]


def build_current_map(depth_charts, rosters, pos: str = "QB") -> tuple[pd.DataFrame, list[str]]:
    """Return (map_df[gsis_id,name,team,depth_rank,is_starter], debug_lines)."""
    pos = str(pos).upper().strip()
    dbg: list[str] = []
    m: dict[str, dict] = {}

    # ---- rosters: authoritative current team ----
    if rosters is not None and not rosters.empty:
        dbg.append(f"rosters columns: {list(rosters.columns)[:30]}")
        r = _pos_rows(rosters, pos)
        gc, tc, nc = _col(r, _GSIS), _col(r, _TEAM), _col(r, _NAME)
        dbg.append(f"rosters -> gsis={gc} team={tc} name={nc} | {pos} rows={len(r)}")
        if gc and tc:
            for _, row in r.iterrows():
                g = row.get(gc)
                if pd.isna(g):
                    continue
                m[str(g)] = {"name": row.get(nc) if nc else None,
                             "team": row.get(tc), "depth_rank": float("nan"), "is_starter": None}

    # ---- depth charts: starter / rank (take the latest update per player) ----
    if depth_charts is not None and not depth_charts.empty:
        dbg.append(f"depth columns: {list(depth_charts.columns)[:30]}")
        d = _pos_rows(depth_charts, pos)
        gc, tc, nc = _col(d, _GSIS), _col(d, _TEAM), _col(d, _NAME)
        rc, tmc = _col(d, _RANK), _col(d, _TIME)
        dbg.append(f"depth -> gsis={gc} team={tc} rank={rc} time={tmc} | {pos} rows={len(d)}")
        if gc and tmc and tmc in d.columns:
            d = d.sort_values(tmc).groupby([gc], as_index=False).tail(1)  # newest per player
        if gc:
            for _, row in d.iterrows():
                g = row.get(gc)
                if pd.isna(g):
                    continue
                g = str(g)
                rank = pd.to_numeric(pd.Series([row.get(rc)]), errors="coerce").iloc[0] if rc else 1.0
                rec = m.get(g, {"name": row.get(nc) if nc else None, "team": row.get(tc) if tc else None,
                                "depth_rank": float("nan"), "is_starter": None})
                rec["depth_rank"] = rank
                rec["is_starter"] = bool(rank == 1) if pd.notna(rank) else None
                if not rec.get("team") and tc:
                    rec["team"] = row.get(tc)
                if not rec.get("name") and nc:
                    rec["name"] = row.get(nc)
                m[g] = rec

    if not m:
        dbg.append("No current roster/depth-chart data available.")
        return pd.DataFrame(columns=["gsis_id", "name", "team", "depth_rank", "is_starter"]), dbg

    out = pd.DataFrame([{"gsis_id": g, **v} for g, v in m.items()])
    n_start = int((out["is_starter"] == True).sum())  # noqa: E712
    n_norank = int(pd.to_numeric(out["depth_rank"], errors="coerce").isna().sum())
    dbg.append(f"mapped {len(out)} {pos}s; {n_start} at depth rank 1; "
               f"{n_norank} with no depth-chart rank")
    return out, dbg


def starters(map_df: pd.DataFrame, keep_depth: int = 1) -> pd.DataFrame:
    """Keep the players deep enough on the chart to matter.

    `keep_depth=1` is the quarterback rule and the default: the flagged starters
    if we have any, everyone if the depth chart told us nothing.

    `keep_depth=3` is the running-back rule: ranks 1 through 3. Players with no
    rank at all are KEPT rather than cut, because a missing depth-chart row is a
    gap in the data, not evidence the player is bad -- and the model's own
    career-games floor already removes camp bodies. The build script prints how
    many that was so it's visible instead of silent.
    """
    if map_df.empty:
        return map_df
    if keep_depth <= 1:
        if (map_df["is_starter"] == True).any():  # noqa: E712
            return map_df[map_df["is_starter"] == True].reset_index(drop=True)  # noqa: E712
        return map_df.reset_index(drop=True)
    rank = pd.to_numeric(map_df["depth_rank"], errors="coerce")
    if rank.notna().any():
        return map_df[rank.isna() | (rank <= keep_depth)].reset_index(drop=True)
    return map_df.reset_index(drop=True)
