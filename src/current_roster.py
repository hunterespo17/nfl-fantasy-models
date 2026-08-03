"""
Map each QB to his CURRENT team and starter status from live depth charts +
rosters (nflverse refreshes both daily, so this reflects the current offseason).

This is the "current mapping" half of the model: production/talent comes from
historical games, but *which team a QB is on now* and *whether he's the starter*
must come from today's depth chart -- not last year's game logs.

Depth-chart columns changed in the 2025+ nflverse format, and this runs on the
user's machine where we can't see the exact schema in advance, so column lookups
are defensive and we emit a debug summary of what was actually found.
"""
from __future__ import annotations

import pandas as pd

# pos_abb is the QB abbreviation in nflverse's 2025+ depth-chart format; it must
# be tried before group columns like pos_grp ("OFF"). Order matters.
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


def _qb_rows(df: pd.DataFrame) -> pd.DataFrame:
    pos = _col(df, _POS)
    if pos is None:
        # No position column found -> return EMPTY rather than everything, so we
        # never pollute the map with all positions. The other source (rosters,
        # which has 'position') still provides QBs.
        return df.iloc[0:0]
    v = df[pos].astype(str).str.upper().str.strip()
    return df[(v == "QB") | v.str.startswith("QUARTERBACK")]


def build_current_map(depth_charts, rosters) -> tuple[pd.DataFrame, list[str]]:
    """Return (map_df[gsis_id,name,team,depth_rank,is_starter], debug_lines)."""
    dbg: list[str] = []
    m: dict[str, dict] = {}

    # ---- rosters: authoritative current team ----
    if rosters is not None and not rosters.empty:
        dbg.append(f"rosters columns: {list(rosters.columns)[:30]}")
        r = _qb_rows(rosters)
        gc, tc, nc = _col(r, _GSIS), _col(r, _TEAM), _col(r, _NAME)
        dbg.append(f"rosters -> gsis={gc} team={tc} name={nc} | QB rows={len(r)}")
        if gc and tc:
            for _, row in r.iterrows():
                g = row.get(gc)
                if pd.isna(g):
                    continue
                m[str(g)] = {"name": row.get(nc) if nc else None,
                             "team": row.get(tc), "depth_rank": float("nan"), "is_starter": None}

    # ---- depth charts: starter / rank (take the latest update per QB) ----
    if depth_charts is not None and not depth_charts.empty:
        dbg.append(f"depth columns: {list(depth_charts.columns)[:30]}")
        d = _qb_rows(depth_charts)
        gc, tc, nc = _col(d, _GSIS), _col(d, _TEAM), _col(d, _NAME)
        rc, tmc = _col(d, _RANK), _col(d, _TIME)
        dbg.append(f"depth -> gsis={gc} team={tc} rank={rc} time={tmc} | QB rows={len(d)}")
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
    dbg.append(f"mapped {len(out)} QBs; {n_start} flagged as starters (depth rank 1)")
    return out, dbg


def starters(map_df: pd.DataFrame) -> pd.DataFrame:
    """Starters only if we have depth info; otherwise everyone (caller warns)."""
    if map_df.empty:
        return map_df
    if (map_df["is_starter"] == True).any():  # noqa: E712
        return map_df[map_df["is_starter"] == True].reset_index(drop=True)  # noqa: E712
    return map_df.reset_index(drop=True)
