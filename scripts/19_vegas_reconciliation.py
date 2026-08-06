"""Top-down check: do the four boards add up to a football team?

Every board is built one player at a time. Nothing ever checked the obvious
consequence -- that a team's players, added together, describe an offence the
betting market would recognise. This does that.

    py scripts\\19_vegas_reconciliation.py

The exchange rate is measured, not assumed. For every position and every depth
k, take 2018-2025 team-seasons, add up the top k players at that position by
fantasy points per game, and fit that against the points the team actually
scored. That gives one line per (position, depth): how many fantasy points a
team's top k receivers are worth per point the team puts on the board.

Depth has to be matched or the answer is nonsense. The published boards are cut
at 100 running backs, 128 receivers and 89 tight ends, so most teams do not have
four backs or five receivers on them -- the median team carries three and four.
Summing our three backs against a four-back historical benchmark makes every
offence look broken. So each team is compared at the depth it actually has.

Writes outputs/vegas_reconciliation.csv.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src import config, data, team_features                          # noqa: E402

pd.set_option("display.width", 250)

MAXDEPTH = {"QB": 2, "RB": 5, "WR": 6, "TE": 4}
BOARD_DEPTH = {"QB": 1, "RB": 4, "WR": 5, "TE": 3}


def half_ppr(w: pd.DataFrame) -> pd.Series:
    """Weekly rows -> fantasy points under the league's own scoring."""
    S = config.SCORING
    out = pd.Series(0.0, index=w.index)
    # left: the weekly file's column, right: the key config.SCORING uses
    pairs = [
        ("passing_yards", "passing_yards"), ("passing_tds", "passing_td"),
        ("passing_interceptions", "interception"),
        ("passing_2pt_conversions", "passing_2pt"),
        ("rushing_yards", "rushing_yards"), ("rushing_tds", "rushing_td"),
        ("rushing_2pt_conversions", "rushing_2pt"),
        ("receptions", "reception"), ("receiving_yards", "receiving_yards"),
        ("receiving_tds", "receiving_td"),
        ("receiving_2pt_conversions", "receiving_2pt"),
        ("rushing_fumbles_lost", "fumble_lost"),
        ("receiving_fumbles_lost", "fumble_lost"),
        ("sack_fumbles_lost", "fumble_lost"),
    ]
    used = {k for c, k in pairs if c in w.columns and k in S}
    missing = sorted(set(S) - used)
    if missing:
        print(f"  !! scoring keys never applied: {missing}")
    for col, key in pairs:
        if col in w.columns and key in S:
            out = out + pd.to_numeric(w[col], errors="coerce").fillna(0.0) * S[key]
    return out


def main() -> None:
    weekly = data.get_player_weekly_stats(config.SEASONS)
    pbp = data.get_pbp(config.SEASONS)
    sched = data.get_schedules(config.SEASONS)
    ts = team_features.build_team_season_features(pbp, sched, weekly)

    # ---- 1. history: fantasy points per team point, per position per depth ----
    w = weekly.copy()
    w["fp"] = half_ppr(w)
    w = w[w["position"].isin(MAXDEPTH)]
    ps = (w.groupby(["season", "team", "position", "player_id"], as_index=False)
          .agg(fp=("fp", "sum"), g=("week", "nunique")))
    ps = ps[ps["g"] >= 1]
    ps["ppg"] = ps["fp"] / ps["g"]

    rows = []
    for (season, team), grp in ps.groupby(["season", "team"]):
        d = {"season": int(season), "team": team}
        for pos, kmax in MAXDEPTH.items():
            sub = (grp[grp["position"] == pos]
                   .sort_values("fp", ascending=False)["ppg"].tolist())
            run = 0.0
            for k in range(1, kmax + 1):
                run += float(sub[k - 1]) if k <= len(sub) else 0.0
                d[f"{pos}{k}"] = run
        rows.append(d)
    hist = pd.DataFrame(rows)

    # what the team actually scored, per game
    tcol = [c for c in ("points_for_pg", "pts_pg", "points_pg", "ppg_scored")
            if c in ts.columns]
    if tcol:
        real = ts[["season", "team", tcol[0]]].rename(
            columns={tcol[0]: "team_pts_pg"})
    else:
        a = sched[["season", "home_team", "home_score"]].rename(
            columns={"home_team": "team", "home_score": "pts"})
        b = sched[["season", "away_team", "away_score"]].rename(
            columns={"away_team": "team", "away_score": "pts"})
        real = (pd.concat([a, b], ignore_index=True).dropna(subset=["pts"])
                .groupby(["season", "team"], as_index=False)["pts"].mean()
                .rename(columns={"pts": "team_pts_pg"}))
    hist = hist.merge(real, on=["season", "team"], how="left").dropna(
        subset=["team_pts_pg"])

    fits = {}
    for pos, kmax in MAXDEPTH.items():
        for k in range(1, kmax + 1):
            c = f"{pos}{k}"
            fits[c] = np.polyfit(hist["team_pts_pg"], hist[c], 1)

    full = sum(hist[f"{p}{k}"] for p, k in BOARD_DEPTH.items())
    r = float(hist["team_pts_pg"].corr(full))
    print(f"=== history: {len(hist)} team-seasons, {hist['season'].min()}-"
          f"{hist['season'].max()} ===")
    print(f"  at full board depth (1QB/4RB/5WR/3TE) a team's skill players are "
          f"worth {r:+.4f} correlation with the points it scores")
    print(f"  their combined ppg: median {full.median():.1f}  "
          f"p10 {full.quantile(.10):.1f}  p90 {full.quantile(.90):.1f}")
    print("  fantasy points added by each extra body, per team point scored:")
    for pos, kmax in MAXDEPTH.items():
        s = "  ".join(f"{k}:{fits[f'{pos}{k}'][0]:.3f}" for k in range(1, kmax + 1))
        print(f"    {pos}  {s}")

    # ---- 2. the upcoming boards -------------------------------------------
    board = []
    for pos in ("qb", "rb", "wr", "te"):
        path = f"outputs/boards/{pos}.json"
        if not os.path.exists(path):
            print(f"\n!! {path} missing -- build the boards first")
            return
        with open(path) as fh:
            d = json.load(fh)
        pay = pd.DataFrame(d["result"]["payload"])
        pay["position"] = pos.upper()
        board.append(pay[["position", "name", "team", "proj_ppg"]])
    board = pd.concat(board, ignore_index=True)
    board["proj_ppg"] = pd.to_numeric(board["proj_ppg"], errors="coerce")
    board = board.dropna(subset=["proj_ppg", "team"])

    rows = []
    for team, grp in board.groupby("team"):
        d = {"team": team}
        tot = 0.0
        for pos, kmax in BOARD_DEPTH.items():
            sub = (grp[grp["position"] == pos]
                   .sort_values("proj_ppg", ascending=False).head(kmax))
            d[pos] = float(sub["proj_ppg"].sum())
            d[f"n{pos}"] = int(len(sub))
            tot += d[pos]
        d["skill_ppg"] = tot
        rows.append(d)
    proj = pd.DataFrame(rows)

    iseas = config.UPCOMING_SEASON
    imp = (ts[ts["season"] == iseas][["team", "implied_total_avg"]]
           .drop_duplicates("team"))
    if imp.empty or imp["implied_total_avg"].isna().all():
        iseas = config.CURRENT_SEASON
        imp = (ts[ts["season"] == iseas][["team", "implied_total_avg"]]
               .drop_duplicates("team"))
    proj = proj.merge(imp, on="team", how="left")

    # each team is priced at the depth it actually carries on the board
    def expect(row):
        e = 0.0
        for pos, kmax in BOARD_DEPTH.items():
            k = int(min(max(row[f"n{pos}"], 1), MAXDEPTH[pos]))
            a, b = fits[f"{pos}{k}"]
            e += a * row["implied_total_avg"] + b
        return e

    proj["expected"] = proj.apply(expect, axis=1)
    proj["gap"] = proj["skill_ppg"] - proj["expected"]
    proj["gap_pct"] = 100.0 * proj["gap"] / proj["expected"]
    proj = proj.sort_values("gap")

    rr = float(proj["implied_total_avg"].rank().corr(proj["skill_ppg"].rank()))
    print(f"\n=== {config.UPCOMING_SEASON} boards vs Vegas, n={len(proj)} teams "
          f"(implied totals from {iseas}) ===")
    print(f"  bodies carried per team: RB median {proj['nRB'].median():.0f} of 4, "
          f"WR {proj['nWR'].median():.0f} of 5, TE {proj['nTE'].median():.0f} of 3")
    print(f"  our team totals track the implied totals at rho {rr:+.4f}")
    if "implied_total_avg" in ts.columns:
        hb = hist.merge(
            ts[["season", "team", "implied_total_avg"]].drop_duplicates(
                ["season", "team"]), on=["season", "team"], how="left")
        hb["full"] = sum(hb[f"{p}{k}"] for p, k in BOARD_DEPTH.items())
        hb = hb.dropna(subset=["implied_total_avg"])
        if len(hb) > 50:
            hr = float(hb["implied_total_avg"].rank().corr(hb["full"].rank()))
            per = hb.groupby("season").apply(
                lambda g: g["implied_total_avg"].rank().corr(g["full"].rank()))
            print(f"  for reference, real teams tracked their OWN implied total "
                  f"at rho {hr:+.4f} (n={len(hb)})")
            print("  per season: " + "  ".join(f"{int(s)} {v:+.2f}"
                                               for s, v in per.items()))
    print(f"  ours     median {proj['skill_ppg'].median():.1f}  "
          f"min {proj['skill_ppg'].min():.1f}  max {proj['skill_ppg'].max():.1f}")
    print(f"  expected median {proj['expected'].median():.1f}  "
          f"min {proj['expected'].min():.1f}  max {proj['expected'].max():.1f}")
    print(f"  mean absolute gap {proj['gap'].abs().mean():.2f} ppg "
          f"({proj['gap_pct'].abs().mean():.1f}%)")

    for lab, sub in (("LOWEST", proj.head(8)),
                     ("HIGHEST", proj.tail(8).iloc[::-1])):
        print(f"\n  --- we are {lab} against what Vegas implies ---")
        for _, x in sub.iterrows():
            print(f"    {x['team']:3s} ours {x['skill_ppg']:5.1f} vs "
                  f"{x['expected']:5.1f} ({x['gap']:+5.1f}, {x['gap_pct']:+5.1f}%)"
                  f"  implied {x['implied_total_avg']:.1f}  "
                  f"QB {x['QB']:4.1f} RB {x['RB']:4.1f}({x['nRB']:.0f}) "
                  f"WR {x['WR']:4.1f}({x['nWR']:.0f}) "
                  f"TE {x['TE']:4.1f}({x['nTE']:.0f})")

    print("\n  --- position groups, ours vs the historical median team ---")
    for pos, kmax in BOARD_DEPTH.items():
        med = int(proj[f"n{pos}"].median())
        h = hist[f"{pos}{med}"]
        print(f"    {pos} (top {med})  ours median {proj[pos].median():6.2f}  "
              f"history median {h.median():6.2f}  "
              f"(history p10 {h.quantile(.10):.2f} p90 {h.quantile(.90):.2f})")

    os.makedirs("outputs", exist_ok=True)
    proj.to_csv("outputs/vegas_reconciliation.csv", index=False)
    print("\n  wrote outputs/vegas_reconciliation.csv")


if __name__ == "__main__":
    main()
