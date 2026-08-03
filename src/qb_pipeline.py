"""
Turn a trained QB model + feature table into the ranked, explained payload the
HTML report consumes. Shared by scripts/06 so the logic lives in one place.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import explain, qb_features, rankings

# Human-readable labels for the handful of inputs we surface in each QB's detail.
FEATURE_LABELS = {
    "arch_pass_att_pg": "Career pass att / gm",
    "arch_rush_att_pg": "Career rush att / gm",
    "arch_ypa": "Career yards / attempt",
    "arch_fp_pg": "Career fantasy pts / gm",
    "sit_pass_rate": "Team pass rate",
    "sit_proe": "Pass rate over expected",
    "sit_plays_pg": "Team plays / gm",
    "sit_implied_total": "Vegas implied team total",
    "form_fp_roll3": "Last-3 fantasy pts / gm",
}


def latest_active_rows(qb_df: pd.DataFrame, season: int, min_games: int = 4) -> pd.DataFrame:
    """Most recent feature row for each QB who played enough in `season`."""
    active = qb_df[qb_df["season"] == season]
    counts = active.groupby("player_id").size()
    keep = counts[counts >= min_games].index
    latest = (
        qb_df[qb_df["player_id"].isin(keep)]
        .sort_values(["player_id", "season", "week"])
        .groupby("player_id")
        .tail(1)
    )
    return latest.reset_index(drop=True)


def build_board(qb_df: pd.DataFrame, model_obj, season: int) -> tuple[pd.DataFrame, list[dict]]:
    """Project, rank, and explain QBs for `season`. Returns (board_df, payload)."""
    rows = latest_active_rows(qb_df, season).copy()
    if rows.empty:
        return pd.DataFrame(), []

    # Neutralize matchup: a season-long ranking shouldn't hinge on one opponent.
    for col in qb_features.FEATURE_GROUPS["Matchup"]:
        if col in rows.columns and col in model_obj.numeric:
            rows[col] = qb_df[col].median()

    rows["proj_ppg"] = np.clip(model_obj.predict(rows), 0, None)
    attrib = explain.group_attributions(
        model_obj, rows, qb_features.FEATURE_GROUPS, reference=qb_df
    )
    attrib = attrib.assign(player_id=rows["player_id"].values)

    board = rankings.build_rankings(
        rows[["player_id", "player_name", "position", "proj_ppg"]], ppg_col="proj_ppg"
    )

    groups_present = [g for g in qb_features.FEATURE_GROUPS if g in attrib.columns]
    team_by_id = dict(zip(rows["player_id"], rows.get("team", pd.Series(index=rows.index))))
    feat_by_id = {pid: r for pid, r in zip(rows["player_id"], rows.to_dict("records"))}
    attrib_by_id = {r["player_id"]: r for r in attrib.to_dict("records")}

    payload = []
    for _, r in board.iterrows():
        pid = r["player_id"]
        a = attrib_by_id.get(pid, {})
        frow = feat_by_id.get(pid, {})
        features = {
            label: round(float(frow[col]), 2)
            for col, label in FEATURE_LABELS.items()
            if col in frow and pd.notna(frow[col])
        }
        payload.append({
            "rank": int(r["overall_rank"]),
            "name": r["player_name"],
            "team": team_by_id.get(pid, ""),
            "proj_ppg": round(float(r["proj_ppg"]), 2),
            "proj_total": round(float(r["proj_points_total"]), 1),
            "tier": int(r["tier"]),
            "vor": round(float(r["vor"]), 1),
            "baseline": round(float(a.get("baseline", np.nan)), 2),
            "groups": {g: round(float(a.get(g, 0.0)), 2) for g in groups_present},
            "features": features,
        })
    return board, payload
