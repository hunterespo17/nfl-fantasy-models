"""
The QB index-blend model.

Every factor becomes a 0-100 index (a QB's percentile among his peers, except
Archetype which is a fixed structural-upside score). The projection is an
EXPLICIT weighted average of those indices -- weights you can see and change --
calibrated to real fantasy points per game.

    projection_ppg = a + b * ( sum(weight_i * index_i) / sum(weight_i) )

What makes the "who the player is" side trustworthy:

  * Talent uses each QB's last 3 HEALTHY seasons (>= 12 games), and never
    reaches back more than 5 years -- so a long-ago season (or an injury year)
    doesn't define a player. Most recent healthy season is weighted most.
  * Touchdowns are REGRESSED toward what the player's yardage predicts, because
    TD totals are volatile year-to-year while yards are sticky. Rushing PRODUCTION
    is therefore driven by rushing YARDS, not by a lucky/unlucky TD count.
  * The Rushing factor is half production and half VOLUME (rush attempts per
    game). Attempts are a coaching decision and repeat year-to-year far better
    than yards or TDs do, which makes volume the more forecastable half of QB
    rushing -- and it is the unit every published rushing threshold uses.
  * Thin resumes are pulled toward the field: a QB with few career games has his
    talent shrunk toward the pack (sample-size regression), so a tiny hot sample
    can't crown someone.
  * Archetype is a discrete style label (Konami / Rushing / Dual-Threat /
    Pocket / Game Manager / Bridge) set from rushing & passing percentiles vs the
    last five seasons of QB play. "Konami" is deliberately exclusive.

There is intentionally no "recent form" factor -- three noisy games shouldn't
move a multi-year picture.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import archetype, availability, calibration, rankings, scoring

# --- Model constants (validated on real QB seasons) -------------------------
K_TD = 8.0          # TD regression: games needed to fully trust observed TDs
K_CAREER = 12.0     # sample-size regression: shrink strength on career games
HEALTHY_GAMES = 12  # a "healthy" season is at least this many games played
RECENCY = 5         # never reach back more than this many seasons for talent
RUSH_VOL_W = 0.5    # Rushing index: share given to attempt VOLUME vs production

# --- Will he be on the field in September? ----------------------------------
# The same treatment the running backs get, for the same reason: a draft pick
# buys a season, not a rate. A quarterback expected to miss a month is worth less
# than the identical quarterback who isn't, and until now this board could not
# see the difference. The mechanics live in src/availability.py, and the long
# note on why a stated games count is taken at FACE VALUE rather than hedged sits
# above NEWS_W in rb_blend.py -- it applies here word for word.
#
# One quarterback-specific wrinkle worth writing down. A hurt QB and a hurt RB do
# not cost you the same thing: miss six games as a back and your bench absorbs
# it, miss six as a quarterback and the one starting spot on your roster is empty
# for six weeks. Less slack behind the position, not more -- which is the
# argument for taking a QB's missed time just as seriously, not less so.
NEWS_W = 1.0
MIN_GAMES_RATIO = 0.35

# Raw signals surfaced in each QB's detail panel, with friendly labels.
SIGNALS = {
    "talent_reg": "Talent · last 3 healthy (reg fp/gm)",
    "talent_final": "Talent · after sample-size reg",
    "rush_val": "Rushing value (reg fp/gm)",
    "rush_att_pg": "Rush attempts/gm",
    "pass_val": "Passing value (reg fp/gm)",
    "career_games": "Career games",
    "age": "Age",
    "durability": "Durability (games/17)",
    "clay_rank": "Outside guide's QB rank",
    "clay_games": "Games the outside guide expects",
    "proj_games": "Games this board expects",
    "pass_rate": "Team pass rate",
    "plays_pg": "Team plays/gm",
    "implied_total_avg": "Team implied total",
    "points_pg": "Team points/gm",
    "sack_rate": "Sack rate allowed",
    "wrte_rec_yds_pg": "WR/TE yds/gm",
    "win_total": "Vegas win total",
}

# Factor -> weight (percent). These sum to 100 and are the numbers shown on the
# homepage; the user can retune them live in the report. Form has been removed;
# Vegas (forward-looking team quality) folded in.
DEFAULT_WEIGHTS = {
    "Talent": 32, "Archetype": 14, "Rushing": 14, "Vegas": 10, "Cast & OL": 10,
    "Situation": 8, "Scoring env": 6, "Availability": 6, "Matchup": 0,
}
GROUPS = list(DEFAULT_WEIGHTS.keys())


# Vegas preseason win totals (forward-looking team quality) -> data/win_totals.csv.
_WT_CACHE = None


def win_totals() -> dict:
    """{(season, team): win_total} from data/win_totals.csv (empty if missing)."""
    global _WT_CACHE
    if _WT_CACHE is None:
        from . import config
        try:
            wt = pd.read_csv(config.DATA_DIR / "win_totals.csv")
            _WT_CACHE = {(int(r.season), str(r.team)): float(r.wt) for r in wt.itertuples()}
        except Exception:
            _WT_CACHE = {}
    return _WT_CACHE


# Who actually calls the offensive plays -> data/playcallers.csv. Hand-maintained,
# because nflverse only gives us the head coach and the head coach is the play-caller
# for barely half the league (17 of 32 in 2026). See PLAYCALLER_PLAN.md.
_PC_CACHE = None


def playcallers() -> dict:
    """{(season, team): {"playcaller", "role", "tree"}} from data/playcallers.csv.

    Same swallow-everything contract as win_totals(): a hand-typed file must never
    be able to take the site down, so anything unparseable degrades to {} and the
    play-caller check quietly reads "not tracked". That is the right behaviour live
    and the wrong behaviour for a typo, which is why scripts/09_check_playcallers.py
    exists -- run it after every edit.
    """
    global _PC_CACHE
    if _PC_CACHE is None:
        from . import config
        try:
            pc = pd.read_csv(config.DATA_DIR / "playcallers.csv")
            _PC_CACHE = {
                (int(r.season), str(r.team)): {
                    "playcaller": str(r.playcaller), "role": str(r.role), "tree": str(r.tree)
                }
                for r in pc.itertuples()
            }
        except Exception:
            _PC_CACHE = {}
    return _PC_CACHE


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _num(df, name):
    if name in df.columns:
        return pd.to_numeric(df[name], errors="coerce")
    return pd.Series(np.nan, index=df.index)


def _numf(df, names):
    """First matching column as numeric, 0-filled (for summable components)."""
    for n in names:
        if n in df.columns:
            return pd.to_numeric(df[n], errors="coerce").fillna(0.0)
    return pd.Series(0.0, index=df.index)


def _first(df, names):
    for n in names:
        if n in df.columns:
            return df[n]
    return pd.Series(index=df.index, dtype="float64")


def _age_curve(age: float) -> float:
    if age is None or (isinstance(age, float) and np.isnan(age)):
        return 0.85
    if 26 <= age <= 31:
        return 1.0
    if age < 26:
        return max(0.6, 0.8 + (age - 24) * 0.06)
    return max(0.5, 1.0 - (age - 31) * 0.06)


def _birth_map(players) -> dict:
    if players is None or players.empty:
        return {}
    pid = _first(players, ["gsis_id", "player_id"]).astype(str)
    by = pd.to_datetime(_first(players, ["birth_date", "birthdate"]), errors="coerce").dt.year
    return dict(zip(pid, by))


def _pct_of(arr: np.ndarray, v: float) -> float:
    """Fraction of pool values <= v (a 0-1 percentile against a fixed pool)."""
    if v is None or (isinstance(v, float) and np.isnan(v)) or arr is None or len(arr) == 0:
        return np.nan
    return float((arr <= v).mean())


# ---------------------------------------------------------------------------
# 1. Season aggregates  (raw components + TD-regressed per-game value)
# ---------------------------------------------------------------------------
def season_aggregates(weekly: pd.DataFrame, scoring_rules: dict | None) -> pd.DataFrame:
    """Per (player_id, season) QB totals plus TD-regressed rush/pass fp per game.

    Keeps the raw components (yards, TDs, attempts, ...) so talent can be built
    from them, and adds `rush_fp_reg_pg` / `pass_fp_reg_pg` / `tot_fp_reg_pg`
    where TDs are regressed toward what yardage predicts.
    """
    w = pd.DataFrame(index=weekly.index)
    w["player_id"] = _first(weekly, ["player_id", "gsis_id"]).astype(str)
    w["player_name"] = _first(weekly, ["player_display_name", "player_name"])
    w["position"] = _first(weekly, ["position", "position_group"])
    w["team"] = _first(weekly, ["team", "recent_team"])
    w["season"] = _num(weekly, "season")
    stype = _first(weekly, ["season_type"])
    w["season_type"] = stype if stype is not None else "REG"

    w["total_fp"] = scoring.compute_fantasy_points(weekly, scoring_rules)
    w["carries"] = _numf(weekly, ["carries", "rushing_attempts"])
    w["rush_yds"] = _numf(weekly, ["rushing_yards"])
    w["rush_tds"] = _numf(weekly, ["rushing_tds"])
    w["attempts"] = _numf(weekly, ["attempts", "passing_attempts"])
    w["completions"] = _numf(weekly, ["completions"])
    w["pass_yds"] = _numf(weekly, ["passing_yards"])
    w["pass_tds"] = _numf(weekly, ["passing_tds"])
    w["interceptions"] = _numf(weekly, ["passing_interceptions", "interceptions"])

    w = w[(w["position"] == "QB") & (w["season_type"].astype(str).str.upper() == "REG")]
    w = w.dropna(subset=["player_id", "season"])

    grp = w.groupby(["player_id", "season"])
    sa = grp.agg(
        games=("total_fp", "size"),
        total_fp=("total_fp", "sum"),
        total_fp_pg=("total_fp", "mean"),
        carries=("carries", "sum"), rush_yds=("rush_yds", "sum"), rush_tds=("rush_tds", "sum"),
        attempts=("attempts", "sum"), completions=("completions", "sum"),
        pass_yds=("pass_yds", "sum"), pass_tds=("pass_tds", "sum"),
        interceptions=("interceptions", "sum"),
    ).reset_index()

    modal = grp["team"].agg(lambda s: s.mode().iat[0] if len(s.mode()) else None).rename("team")
    name = grp["player_name"].agg(lambda s: s.dropna().iloc[-1] if s.notna().any() else None).rename("player_name")
    sa = sa.merge(modal.reset_index(), on=["player_id", "season"])
    sa = sa.merge(name.reset_index(), on=["player_id", "season"])
    sa["season"] = sa["season"].astype(int)

    # League TD-per-yard rates from the recent window (the modern-era baseline
    # each QB's TDs are regressed toward).
    mx = int(sa["season"].max())
    ref = sa[(sa["season"] >= mx - RECENCY + 1) & (sa["games"] >= 8)]
    r_ty = float(ref["rush_tds"].sum()) / max(float(ref["rush_yds"].sum()), 1.0)
    p_ty = float(ref["pass_tds"].sum()) / max(float(ref["pass_yds"].sum()), 1.0)

    wt = sa["games"] / (sa["games"] + K_TD)               # trust in observed TDs
    reg_rush_td = wt * sa["rush_tds"] + (1 - wt) * sa["rush_yds"] * r_ty
    reg_pass_td = wt * sa["pass_tds"] + (1 - wt) * sa["pass_yds"] * p_ty
    g = sa["games"].replace(0, np.nan)
    sa["rush_fp_reg_pg"] = (sa["rush_yds"] * 0.1 + reg_rush_td * 6) / g
    sa["pass_fp_reg_pg"] = (sa["pass_yds"] * 0.04 + reg_pass_td * 4 - sa["interceptions"] * 2) / g
    sa["tot_fp_reg_pg"] = sa["rush_fp_reg_pg"] + sa["pass_fp_reg_pg"]
    # Rushing VOLUME, kept separate from rushing production. Attempts are the
    # unit every league-winner rushing threshold is stated in (55 / 100 over a
    # season), and per-game keeps it honest for QBs who missed time.
    sa["rush_att_pg"] = sa["carries"] / g
    return sa


def _recent_pool(sa: pd.DataFrame) -> pd.DataFrame:
    """Reference pool for archetype percentiles = last RECENCY seasons, games>=8."""
    mx = int(sa["season"].max())
    return sa[(sa["season"] >= mx - RECENCY + 1) & (sa["games"] >= 8)]


# ---------------------------------------------------------------------------
# 2. Talent bundle  (healthy + recency-capped, most-recent weighted)
# ---------------------------------------------------------------------------
def _bundle(pdf: pd.DataFrame, as_of: int) -> dict | None:
    """Talent/rush/pass value entering `as_of`, from a player's prior seasons.

    Uses the last 3 HEALTHY seasons within the recency window; falls back to any
    recent season, then to any prior season. Most recent counts most (.5/.33/.17).
    """
    prior = pdf[pdf["season"] < as_of]
    if prior.empty:
        return None
    cand = prior[prior["season"] >= as_of - RECENCY]
    healthy = cand[cand["games"] >= HEALTHY_GAMES]
    use = healthy if len(healthy) else (cand if len(cand) else prior)
    use = use.sort_values("season", ascending=False).head(3)
    if use.empty:
        return None
    wts = np.array([0.5, 0.33, 0.17][: len(use)], dtype=float)
    prior_sorted = prior.sort_values("season")
    return {
        "talent_reg": float(np.average(use["tot_fp_reg_pg"].to_numpy(), weights=wts)),
        "rush_val": float(use["rush_fp_reg_pg"].mean()),
        "rush_att_pg": float(use["rush_att_pg"].mean()) if "rush_att_pg" in use else np.nan,
        "pass_val": float(use["pass_fp_reg_pg"].mean()),
        "career_games": float(prior["games"].sum()),
        "healthy_recent": bool(len(healthy) > 0),
        "prev_ppg": float(prior_sorted["total_fp_pg"].iloc[-1]),
        "prev_games": float(prior_sorted["games"].iloc[-1]),
        # Games a season over his last three, not just last year's. This is the
        # single biggest thing separating a quarterback who got hurt from one who
        # is simply not durable, and it matters more here than anywhere else: a
        # passer who misses six weeks empties the one starting spot on your
        # roster. On seasons the fit never saw it cuts the miss from 3.67 games
        # to 3.38. Only availability.py reads it; the Availability index still
        # uses last season, so fresh news still moves a rank faster than a mean.
        "prev_games3": float(prior_sorted["games"].tail(3).mean()),
        # How big last season's job was, on a 0-to-1 scale where 1 is a full
        # starter's 32 throws a game. Only used to work out how many games he
        # plays NEXT year: a starter who missed six weeks hurt and a backup who
        # got six weeks of mop-up both show up as "played 11", and the games
        # model cannot tell them apart without this. See availability.py.
        "prev_role": float(np.clip(
            (float(prior_sorted["attempts"].iloc[-1])
             / max(float(prior_sorted["games"].iloc[-1]), 1.0)) / 32.0, 0.0, 1.0)),
        "prev_team": prior_sorted["team"].iloc[-1],
    }


def _merge_team_env(prof: pd.DataFrame, team_season: pd.DataFrame) -> pd.DataFrame:
    """Attach the CURRENT team's prior-season environment (handles movers)."""
    if team_season is None or team_season.empty:
        return prof
    ts = team_season.copy()
    ts["season"] = pd.to_numeric(ts["season"], errors="coerce")
    prof["prev_season"] = prof["season"] - 1
    prof = prof.merge(ts, left_on=["prev_season", "team"], right_on=["season", "team"],
                      how="left", suffixes=("", "_ts"))
    if "season_ts" in prof.columns:
        prof = prof.drop(columns=["season_ts"])
    return prof


# ---------------------------------------------------------------------------
# 3. Entering-season profiles (historical, for calibration + backtest)
# ---------------------------------------------------------------------------
def entering_profiles(sa: pd.DataFrame, team_season: pd.DataFrame,
                      players: pd.DataFrame | None, pool: pd.DataFrame) -> pd.DataFrame:
    """One row per (player, completed season) with talent built from prior years."""
    pool_rush = pool["rush_fp_reg_pg"].to_numpy()
    pool_pass = pool["pass_fp_reg_pg"].to_numpy()
    birth = _birth_map(players)

    rows = []
    for pid, pdf in sa.sort_values("season").groupby("player_id"):
        for _, cur in pdf.iterrows():
            season = int(cur["season"])
            b = _bundle(pdf, season)
            if b is None:
                continue
            rows.append({
                "player_id": str(pid),
                "player_name": cur["player_name"],
                "season": season,
                "team": cur["team"],
                "actual_ppg": float(cur["total_fp_pg"]),
                "age": season - birth.get(str(pid), np.nan),
                "durability": b["prev_games"] / 17.0,
                "rush_pct": _pct_of(pool_rush, b["rush_val"]),
                "pass_pct": _pct_of(pool_pass, b["pass_val"]),
                "win_total": win_totals().get((season, cur["team"])),
                **b,
            })
    prof = pd.DataFrame(rows)
    if prof.empty:
        return prof
    prof["mover"] = (prof["team"] != prof["prev_team"]) & prof["prev_team"].notna()
    return _merge_team_env(prof, team_season)


# ---------------------------------------------------------------------------
# 4. Indices + composite
# ---------------------------------------------------------------------------
def add_indices(prof: pd.DataFrame, weights: dict | None = None) -> pd.DataFrame:
    weights = weights or DEFAULT_WEIGHTS
    p = prof.copy()

    # What we expect to get out of him THIS year. Upcoming season only, so a 2026
    # injury report can never leak backwards into a backtest scored on 2019.
    p = availability.attach(p, "QB", NEWS_W, MIN_GAMES_RATIO)

    # Sample-size regression: shrink talent toward each season-cohort's mean by
    # how thin the career is (few games -> pulled to the pack).
    pool_mean = p.groupby("season")["talent_reg"].transform("mean")
    cg = pd.to_numeric(p["career_games"], errors="coerce").fillna(0.0)
    wc = cg / (cg + K_CAREER)
    p["talent_final"] = wc * p["talent_reg"] + (1 - wc) * pool_mean
    p["reg_shrink"] = (1 - wc)          # 0 = fully trusted, 1 = fully to the mean

    # Archetype from rushing/passing percentiles (vs the recent pool) + career games.
    p["archetype"] = [
        archetype.bucket(rp, pp, g)
        for rp, pp, g in zip(p["rush_pct"], p["pass_pct"], p["career_games"])
    ]
    p["Archetype"] = archetype.upside_index(p["archetype"]).values

    def pct(col):
        if col not in p.columns:
            return pd.Series(np.nan, index=p.index)
        return p.groupby("season")[col].transform(lambda s: s.rank(pct=True) * 100)

    p["Talent"] = pct("talent_final")
    # Rushing = production + VOLUME. Attempts are a coaching decision and repeat
    # year to year much better than rushing yards or TDs do, so volume is the
    # forecastable half; production keeps goal-line and big-play value in view.
    _rush_prod = pct("rush_val")
    _rush_vol = pct("rush_att_pg")
    if _rush_vol.notna().any():
        p["Rushing"] = (1 - RUSH_VOL_W) * _rush_prod + RUSH_VOL_W * _rush_vol.fillna(_rush_prod)
    else:
        p["Rushing"] = _rush_prod        # older cache without carries: production only
    p["Situation"] = pd.concat([pct("pass_rate"), pct("proe"), pct("plays_pg")], axis=1).mean(axis=1)
    p["Scoring env"] = pd.concat([pct("implied_total_avg"), pct("points_pg")], axis=1).mean(axis=1)
    p["Vegas"] = pct("win_total")            # forward-looking team quality (preseason win total)
    if "sack_rate" in p.columns:
        p["neg_sack"] = -p["sack_rate"]
    p["Cast & OL"] = pd.concat([pct("wrte_rec_yds_pg"), pct("neg_sack")], axis=1).mean(axis=1)
    # Age curve and last year's durability, times what we hear about this year.
    # The injury costs him twice on purpose and both charges are small: once here
    # (6 of 100 weight, so a month missed is worth well under a point of
    # composite) and once through proj_games below, which is where the real
    # markdown happens. This one is the "and he's a health risk generally" nudge;
    # that one is the arithmetic of a shorter season.
    p["Availability"] = [
        _age_curve(a) * (d if pd.notna(d) else 0.8) * 100 * gr
        for a, d, gr in zip(p["age"], p["durability"], p["games_ratio"])
    ]
    p["Matchup"] = 50.0

    # Movers: shrink team-based factors toward neutral (their new spot is uncertain).
    for col in ["Situation", "Scoring env", "Cast & OL"]:
        m = p["mover"] == True  # noqa: E712
        p.loc[m, col] = 0.6 * p.loc[m, col] + 0.4 * 50

    for gcol in GROUPS:
        p[gcol] = pd.to_numeric(p.get(gcol), errors="coerce").fillna(50.0)

    p["composite"] = composite(p, weights)
    return p


def composite(p: pd.DataFrame, weights: dict) -> pd.Series:
    total_w = sum(weights.values()) or 1
    acc = pd.Series(0.0, index=p.index)
    for gcol, w in weights.items():
        acc = acc + w * p[gcol]
    return acc / total_w


def calibrate(p: pd.DataFrame, info: dict | None = None) -> tuple[float, float]:
    """Map composite -> points per game. See src/calibration.py for the why.

    This used to be a plain least-squares line across every QB who ever took a
    snap. It carried the same two bugs the RB board had: the points were anchored
    on a different crowd of players than the ADP curve they get subtracted from,
    and the fitted line told QBs apart LESS well than their draft slot alone
    does. Both are fixed in that one shared file so the two boards cannot drift.
    """
    return calibration.fit(p, pos="QB", info=info)


def backtest(p: pd.DataFrame) -> dict:
    """Fit on earlier seasons, score the two most recent, vs a prior-year baseline."""
    seasons = sorted(int(s) for s in p["season"].dropna().unique())
    if len(seasons) < 3:
        return {}
    test = seasons[-2:]
    tr = p[(~p["season"].isin(test)) & p["actual_ppg"].notna()]
    if len(tr) < 5:
        return {}
    b, a = np.polyfit(tr["composite"], tr["actual_ppg"], 1)
    te = p[p["season"].isin(test) & p["actual_ppg"].notna()].copy()
    te["pred"] = a + b * te["composite"]
    mae_model = float(np.mean(np.abs(te["pred"] - te["actual_ppg"])))
    base = te.dropna(subset=["prev_ppg"])
    mae_base = float(np.mean(np.abs(base["prev_ppg"] - base["actual_ppg"]))) if len(base) else float("nan")
    return {"seasons": test, "model_mae": round(mae_model, 2), "baseline_mae": round(mae_base, 2)}


# ---------------------------------------------------------------------------
# 5. Payload assembly (shared by both entry points)
# ---------------------------------------------------------------------------
def _empty(weights: dict, extra: dict | None = None) -> dict:
    out = {"payload": [], "calib": {"a": 0.0, "b": 0.25}, "backtest": {},
           "weights": weights, "groups": [g for g in GROUPS if weights[g] > 0]}
    if extra:
        out.update(extra)
    return out


def _assemble(cur: pd.DataFrame, a: float, b: float, bt: dict, weights: dict,
              extra: dict | None = None) -> dict:
    cur = cur.copy()
    # The bends, when calibration managed to fit them. They live inside `extra`
    # because both callers already hand their calibration detail through there.
    # No bends -> apply() is the same straight line this always was.
    knots = ((extra or {}).get("calibration") or {}).get("knots") or []
    cur["proj_ppg"] = calibration.apply(cur["composite"], a, b, knots)
    cur["position"] = "QB"
    # Rank on the SEASON, not the rate. proj_ppg is what he scores in a game he
    # plays; proj_ppg * proj_games is what the pick is actually worth. They are
    # the same number for everyone healthy, which is nearly everyone.
    if "proj_games" not in cur.columns:
        cur["proj_games"] = 17.0
    cur["proj_games"] = pd.to_numeric(cur["proj_games"], errors="coerce").fillna(17.0).clip(1.0, 17.0)
    board = rankings.build_rankings(
        cur[["player_id", "player_name", "position", "proj_ppg", "proj_games"]],
        ppg_col="proj_ppg", games_col="proj_games",
    )
    by_id = {r["player_id"]: r for r in cur.to_dict("records")}
    payload = []
    for _, r in board.iterrows():
        row = by_id.get(r["player_id"], {})
        payload.append({
            "rank": int(r["overall_rank"]),
            "player_id": str(r["player_id"]),
            "name": r["player_name"],
            "team": row.get("team", ""),
            "archetype": row.get("archetype", ""),
            "mover": bool(row.get("mover", False)),
            "starter": bool(row.get("is_starter")) if row.get("is_starter") is not None else None,
            "proj_ppg": round(float(r["proj_ppg"]), 2),
            "proj_total": round(float(r["proj_points_total"]), 1),
            "tier": int(r["tier"]),
            "vor": round(float(r["vor"]), 1),
            "career_games": (round(float(row["career_games"])) if pd.notna(row.get("career_games")) else None),
            "age": (round(float(row["age"])) if pd.notna(row.get("age")) else None),
            # How much of the season we expect to get, why, and where an outside
            # guide has him. The page reads all three straight off the row.
            "games": round(float(row.get("proj_games", 17.0)), 1),
            "games_note": (str(row.get("games_note") or "") or None),
            "clay_rank": (int(row["clay_rank"]) if pd.notna(row.get("clay_rank")) else None),
            # Explicit numeric fields (not just SIGNALS, which is label-keyed) so
            # ratings.py can test the published rushing thresholds directly.
            # "pace" = per-game extrapolated to a 17-game season, which is how the
            # thresholds are stated and keeps QBs who missed time honest.
            "rush_att_pg": (round(float(row["rush_att_pg"]), 2)
                            if pd.notna(row.get("rush_att_pg")) else None),
            "rush_att_pace": (round(float(row["rush_att_pg"]) * 17.0)
                              if pd.notna(row.get("rush_att_pg")) else None),
            "rush_fpg": (round(float(row["rush_val"]), 2)
                         if pd.notna(row.get("rush_val")) else None),
            "indices": {g: round(float(row.get(g, 50.0)), 1) for g in GROUPS},
            "signals": {label: round(float(row[col]), 2) for col, label in SIGNALS.items()
                        if col in row and pd.notna(row.get(col))},
        })
    # The page recomputes every projection itself whenever a slider moves, so it
    # needs the bends, not just the line. Same numbers, same order, both sides.
    out = {"payload": payload,
           "calib": {"a": round(a, 3), "b": round(b, 4), "knots": knots},
           "backtest": bt,
           "weights": weights, "groups": [g for g in GROUPS if weights[g] > 0]}
    if extra:
        out.update(extra)
    return out


# ---------------------------------------------------------------------------
# 6. Entry point A -- historical projection (fallback when no current roster)
# ---------------------------------------------------------------------------
def run(weekly, team_season, players, scoring_rules, season, weights=None) -> dict:
    weights = weights or DEFAULT_WEIGHTS
    sa = season_aggregates(weekly, scoring_rules)
    pool = _recent_pool(sa)
    prof = entering_profiles(sa, team_season, players, pool)
    if prof.empty:
        return _empty(weights)
    prof = add_indices(prof, weights)
    cal: dict = {}
    a, b = calibrate(prof, info=cal)
    # backtest keeps its own plain least-squares fit on purpose, so its error
    # score stays comparable to every run from before this change.
    bt = backtest(prof)
    cur = prof[(prof["season"] == season) & (prof["career_games"] >= 8)].copy()
    if cur.empty:
        return _empty(weights)
    return _assemble(cur, a, b, bt, weights, {"calibration": cal})


# ---------------------------------------------------------------------------
# 7. Entry point B -- upcoming season, driven by the CURRENT roster/depth chart
# ---------------------------------------------------------------------------
def build_upcoming(sa, team_season, players, current_map, season, pool) -> tuple[pd.DataFrame, list[str]]:
    """One profile row per current QB: current team + historical production."""
    pool_rush = pool["rush_fp_reg_pg"].to_numpy()
    pool_pass = pool["pass_fp_reg_pg"].to_numpy()
    birth = _birth_map(players)
    by_pid = {str(pid): pdf for pid, pdf in sa.groupby("player_id")}

    rows, skipped = [], []
    for _, cm in current_map.iterrows():
        pid = str(cm["gsis_id"])
        pdf = by_pid.get(pid)
        b = _bundle(pdf, season) if pdf is not None else None
        if b is None:
            if cm.get("name"):
                skipped.append(str(cm["name"]))
            continue
        name = cm.get("name")
        if not name and pdf is not None:
            name = pdf.sort_values("season")["player_name"].iloc[-1]
        rows.append({
            "player_id": pid,
            "player_name": name or pid,
            "season": season,
            "team": cm.get("team"),
            "actual_ppg": np.nan,
            "age": season - birth.get(pid, np.nan),
            "durability": b["prev_games"] / 17.0,
            "rush_pct": _pct_of(pool_rush, b["rush_val"]),
            "pass_pct": _pct_of(pool_pass, b["pass_val"]),
            "win_total": win_totals().get((season, cm.get("team"))),
            "is_starter": cm.get("is_starter"),
            "depth_rank": cm.get("depth_rank"),
            **b,
        })
    prof = pd.DataFrame(rows)
    if prof.empty:
        return prof, skipped
    prof["mover"] = (prof["team"] != prof["prev_team"]) & prof["prev_team"].notna()
    return _merge_team_env(prof, team_season), skipped


def run_upcoming(weekly, team_season, players, current_map, scoring_rules, season, weights=None) -> dict:
    """Project the UPCOMING season using current teams/starters + historical production."""
    weights = weights or DEFAULT_WEIGHTS
    sa = season_aggregates(weekly, scoring_rules)
    pool = _recent_pool(sa)
    hist = entering_profiles(sa, team_season, players, pool)          # calibration/backtest
    up, skipped = build_upcoming(sa, team_season, players, current_map, season, pool)
    if up.empty:
        return _empty(weights, {"skipped_rookies": skipped})

    allp = pd.concat([hist, up], ignore_index=True, sort=False)
    allp = add_indices(allp, weights)
    cal: dict = {}
    a, b = calibrate(allp, info=cal)
    # See run() above: the backtest deliberately keeps the old fit.
    bt = backtest(allp)

    cur = allp[(allp["season"] == season) & (allp["career_games"] >= 8)].copy()
    if cur.empty:
        return _empty(weights, {"skipped_rookies": skipped})
    return _assemble(cur, a, b, bt, weights,
                     {"skipped_rookies": skipped, "calibration": cal})
