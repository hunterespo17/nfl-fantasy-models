"""
The RB index-blend model.

Same machine as the QB model: every factor becomes a 0-100 index (a back's
percentile among his peers), and the projection is an EXPLICIT weighted average
of those indices -- weights you can see and change -- calibrated to real fantasy
points per game.

    projection_ppg = a + b * ( sum(weight_i * index_i) / sum(weight_i) )

What's different about running backs, and why:

  * OPPORTUNITY IS THE PRODUCT. A quarterback's job is safe; a running back's
    job is the whole question. So the two biggest things here after raw scoring
    are Volume (how many touches he gets) and Backfield (what share of his own
    team's back-touches he takes). Those are the numbers that repeat.
  * A TARGET IS WORTH MORE THAN A CARRY. In half PPR a target is worth about
    1.8 carries (see TARGET_MULT below for the arithmetic), so "touches" are
    counted weighted, not raw. A back with 12 carries and 5 targets is a bigger
    asset than one with 20 carries and none, and raw touch counts say the
    opposite.
  * BACKS AGE EARLY. The age curve peaks at 22-25 and falls off a cliff after
    26. That isn't a hunch -- 85% of league-winning RB seasons came from backs
    27 or younger, average 25.1.
  * SHORTER MEMORY. RECENCY is 4 seasons, not the QB model's 5, and a healthy
    season is 10 games instead of 12. Backfields turn over fast and backs miss
    more time; a 2021 workload should not be shaping a 2026 projection.
  * TOUCHDOWNS ARE REGRESSED HARDER (K_TD = 10 vs the QB model's 8). Goal-line
    work moves around between seasons more than yardage does, so a back who
    vultured 14 scores is pulled further back toward what his yards predict.

Movers are handled the way the QB model handles them: a back who changed teams
has his team-based factors -- AND his backfield share -- pulled toward neutral,
because last year's share on last year's depth chart says very little about the
job he's walking into.

There is deliberately no archetype bucket, no league-winner screen and no
hand-maintained backfield file in here. Those are the next tier; this file is
only the free, measurable stuff.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import calibration, rankings, scoring

# --- Model constants --------------------------------------------------------
K_TD = 10.0         # TD regression: games needed to fully trust observed TDs
K_CAREER = 10.0     # sample-size regression: shrink strength on career games
HEALTHY_GAMES = 10  # a "healthy" RB season is at least this many games
RECENCY = 4         # never reach back more than this many seasons for talent
REC_VOL_W = 0.5     # Receiving index: share given to target VOLUME vs production
MIN_CAREER_GAMES = 6    # below this we don't have enough to project a back
MIN_CAL_ROWS = calibration.MIN_ROWS   # kept as an alias; the real one lives there

# How many carries one target is worth, in THIS league's scoring.
#
#   a carry   ~ 4.3 yds x 0.1            + 0.031 TD/att x 6      ~ 0.61 pts
#   a target  ~ 0.64 catch x 0.5 (PPR pt) + 5.9 yds x 0.1 + TD   ~ 1.11 pts
#                                                          ratio ~ 1.8
#
# The same arithmetic in FULL PPR gives 2.45, which lands on the 2.55 figure
# Fantasy Points published -- that agreement is why we trust the half-PPR number.
# It is derived from the scoring settings, so if you ever switch back to full
# PPR this constant needs to move to about 2.5.
TARGET_MULT = 1.8

# Raw signals surfaced in each back's detail panel, with friendly labels.
SIGNALS = {
    "talent_reg": "Talent · last healthy yrs (reg fp/gm)",
    "talent_final": "Talent · after sample-size reg",
    "rush_val": "Rushing value (reg fp/gm)",
    "rec_val": "Receiving value (reg fp/gm)",
    "carries_pg": "Carries/gm",
    "targets_pg": "Targets/gm",
    "opp_pg": "Weighted touches/gm",
    "bf_share": "Backfield share (of team RB work)",
    "bf_carry_share": "Share of team RB carries",
    "bf_target_share": "Share of team RB targets",
    "snap_pct": "Snap share",
    "ypc": "Yards per carry",
    "ypt": "Yards per target",
    "career_games": "Career games",
    "age": "Age",
    "durability": "Durability (games/17)",
    "plays_pg": "Team plays/gm",
    "pass_rate": "Team pass rate",
    "implied_total_avg": "Team implied total",
    "points_pg": "Team points/gm",
    "win_total": "Vegas win total",
}

# Factor -> weight (percent). These sum to 100 and are retunable live in the
# report. Talent is what the calibration hangs on; Volume and Backfield are the
# two that actually forecast, which is why together they outweigh it.
DEFAULT_WEIGHTS = {
    "Talent": 26,       # TD-regressed total fp/gm over his last healthy seasons
    "Volume": 18,       # weighted touches per game (a target counts as 1.8)
    "Receiving": 14,    # targets + receiving production (the half-PPR premium)
    "Backfield": 12,    # his share of his own team's RB work
    "Vegas": 10,        # preseason win total + implied team total
    "Availability": 10, # age curve x durability
    "Efficiency": 6,    # yards per carry & yards per target
    "Situation": 4,     # team pace & run lean
    "Matchup": 0,
}
GROUPS = list(DEFAULT_WEIGHTS.keys())

# Reuse the QB model's file loaders rather than keeping two copies of them --
# win totals and play-callers are league-wide facts, not position-specific.
from .qb_blend import (  # noqa: E402
    _birth_map, _first, _num, _numf, _pct_of, playcallers, win_totals,
)

__all__ = [
    "DEFAULT_WEIGHTS", "GROUPS", "SIGNALS", "TARGET_MULT",
    "season_aggregates", "entering_profiles", "add_indices", "composite",
    "calibrate", "backtest", "run", "run_upcoming", "build_upcoming",
    "win_totals", "playcallers",
]


def _age_curve(age: float) -> float:
    """RB aging: flat through 25, then down hard. 26 is the hinge, not 31.

    Returns a 0-1 multiplier on Availability. The numbers come from the shape of
    league-winning RB seasons -- average age 25.1, 85% of them 27 or younger --
    so a 29-year-old back has to be genuinely excellent everywhere else to rank
    where a 24-year-old ranks on merit.
    """
    if age is None or (isinstance(age, float) and np.isnan(age)):
        return 0.85
    if 22 <= age <= 25:
        return 1.0
    if age < 22:
        return 0.95     # young is fine; unproven is handled by sample-size regression
    return max(0.35, 1.0 - (age - 25) * 0.09)


# ---------------------------------------------------------------------------
# 1. Season aggregates  (raw components + TD-regressed per-game value)
# ---------------------------------------------------------------------------
def _backfield_shares(w: pd.DataFrame) -> pd.DataFrame:
    """Each back's share of HIS OWN TEAM's running-back work, per season.

    Computed off weekly rows, so a back who was traded contributes to whichever
    team he was actually playing for that week. The share is then reported for
    the team he played the most games for -- a mid-season trade therefore reads
    as a partial share, which is the honest answer rather than a made-up one.

    Denominator is every RB on the roster, so this is "backfield competition"
    and "backfield share" in a single number: 0.75 means he took three quarters
    of the backfield's work, which necessarily means nobody else did.
    """
    cols = ["player_id", "season", "bf_carry_share", "bf_target_share", "bf_share"]
    if w.empty:
        return pd.DataFrame(columns=cols)

    # Team-season totals across all backs.
    team = w.groupby(["season", "team"], dropna=True).agg(
        t_car=("carries", "sum"), t_tgt=("targets", "sum")
    ).reset_index()

    # Player totals per team (so trades split correctly), plus games for tiebreak.
    ply = w.groupby(["player_id", "season", "team"], dropna=True).agg(
        p_car=("carries", "sum"), p_tgt=("targets", "sum"), p_gm=("carries", "size")
    ).reset_index()

    m = ply.merge(team, on=["season", "team"], how="left")
    m["bf_carry_share"] = m["p_car"] / m["t_car"].replace(0, np.nan)
    m["bf_target_share"] = m["p_tgt"] / m["t_tgt"].replace(0, np.nan)
    # One blended share, weighted the same way touches are weighted everywhere
    # else in this file, so the pass-catching back isn't punished for the fact
    # that his team runs the ball with someone else.
    p_opp = m["p_car"] + TARGET_MULT * m["p_tgt"]
    t_opp = (m["t_car"] + TARGET_MULT * m["t_tgt"]).replace(0, np.nan)
    m["bf_share"] = p_opp / t_opp

    # Keep the team he actually played for most that season.
    m = m.sort_values(["player_id", "season", "p_gm"], ascending=[True, True, False])
    m = m.groupby(["player_id", "season"], as_index=False).head(1)
    return m[cols]


def season_aggregates(weekly: pd.DataFrame, scoring_rules: dict | None,
                      snaps: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per (player_id, season) RB totals plus TD-regressed rush/rec fp per game.

    Keeps the raw components so the factors can be built from them, and adds
    `rush_fp_reg_pg` / `rec_fp_reg_pg` / `tot_fp_reg_pg` where touchdowns are
    regressed toward what the yardage predicts.

    `snaps` is optional. When it's supplied and joins cleanly it adds a snap
    share column; when it doesn't, everything else still works and snap share is
    simply absent. It is never allowed to break a build.
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
    w["targets"] = _numf(weekly, ["targets"])
    w["receptions"] = _numf(weekly, ["receptions"])
    w["rec_yds"] = _numf(weekly, ["receiving_yards"])
    w["rec_tds"] = _numf(weekly, ["receiving_tds"])

    w = w[(w["position"] == "RB") & (w["season_type"].astype(str).str.upper() == "REG")]
    w = w.dropna(subset=["player_id", "season"])
    if w.empty:
        return pd.DataFrame(columns=["player_id", "season"])
    w["season"] = w["season"].astype(int)

    shares = _backfield_shares(w)

    grp = w.groupby(["player_id", "season"])
    sa = grp.agg(
        games=("total_fp", "size"),
        total_fp=("total_fp", "sum"),
        total_fp_pg=("total_fp", "mean"),
        carries=("carries", "sum"), rush_yds=("rush_yds", "sum"), rush_tds=("rush_tds", "sum"),
        targets=("targets", "sum"), receptions=("receptions", "sum"),
        rec_yds=("rec_yds", "sum"), rec_tds=("rec_tds", "sum"),
    ).reset_index()

    modal = grp["team"].agg(lambda s: s.mode().iat[0] if len(s.mode()) else None).rename("team")
    name = grp["player_name"].agg(
        lambda s: s.dropna().iloc[-1] if s.notna().any() else None).rename("player_name")
    sa = sa.merge(modal.reset_index(), on=["player_id", "season"])
    sa = sa.merge(name.reset_index(), on=["player_id", "season"])
    sa = sa.merge(shares, on=["player_id", "season"], how="left")

    # League TD-per-yard rates from the recent window (the baseline each back's
    # TDs are regressed toward). Rushing and receiving get their own rates
    # because a receiving yard is far less likely to end in the end zone.
    mx = int(sa["season"].max())
    ref = sa[(sa["season"] >= mx - RECENCY + 1) & (sa["games"] >= 8)]
    if ref.empty:
        ref = sa
    r_ty = float(ref["rush_tds"].sum()) / max(float(ref["rush_yds"].sum()), 1.0)
    c_ty = float(ref["rec_tds"].sum()) / max(float(ref["rec_yds"].sum()), 1.0)

    wt = sa["games"] / (sa["games"] + K_TD)               # trust in observed TDs
    reg_rush_td = wt * sa["rush_tds"] + (1 - wt) * sa["rush_yds"] * r_ty
    reg_rec_td = wt * sa["rec_tds"] + (1 - wt) * sa["rec_yds"] * c_ty

    g = sa["games"].replace(0, np.nan)
    rules = scoring_rules or {}
    ppr = float(rules.get("reception", 0.5))
    sa["rush_fp_reg_pg"] = (sa["rush_yds"] * 0.1 + reg_rush_td * 6) / g
    sa["rec_fp_reg_pg"] = (sa["rec_yds"] * 0.1 + sa["receptions"] * ppr + reg_rec_td * 6) / g
    sa["tot_fp_reg_pg"] = sa["rush_fp_reg_pg"] + sa["rec_fp_reg_pg"]

    # Opportunity. Carries and targets separately (they behave differently) and
    # blended into one weighted-touch number, which is the single best one-line
    # summary of an RB's fantasy job.
    sa["carries_pg"] = sa["carries"] / g
    sa["targets_pg"] = sa["targets"] / g
    sa["opp_pg"] = sa["carries_pg"] + TARGET_MULT * sa["targets_pg"]
    sa["ypc"] = sa["rush_yds"] / sa["carries"].replace(0, np.nan)
    sa["ypt"] = sa["rec_yds"] / sa["targets"].replace(0, np.nan)

    sa = _attach_snaps(sa, snaps)
    return sa


def _attach_snaps(sa: pd.DataFrame, snaps: pd.DataFrame | None) -> pd.DataFrame:
    """Optional snap-share column, joined on normalized name + season + team.

    nflverse's snap-count table is keyed by Pro-Football-Reference IDs, not the
    GSIS IDs everything else here uses, so the join has to go through names. That
    is a genuinely fragile join, which is why the whole thing is wrapped: if it
    matches nothing, or the table's shape changed, the model carries on without
    it rather than failing or -- worse -- silently filling zeros.

    Coverage is reported by `snap_coverage()` so the build script can print it
    instead of leaving it to be discovered later.
    """
    sa["snap_pct"] = np.nan
    if snaps is None or getattr(snaps, "empty", True):
        return sa
    try:
        from .adp import norm
        s = snaps.copy()
        pos = _first(s, ["position"])
        if pos is not None and pos.notna().any():
            s = s[pos.astype(str).str.upper() == "RB"]
        pct = _first(s, ["offense_pct", "off_pct", "offense_snap_pct"])
        if pct is None or not pct.notna().any():
            return sa
        src_id = _first(s, ["pfr_player_id", "pfr_id", "player_id"])
        j = pd.DataFrame({
            "season": pd.to_numeric(_first(s, ["season"]), errors="coerce"),
            "nkey": _first(s, ["player", "player_name", "full_name"]).map(norm),
            "pct": pd.to_numeric(pct, errors="coerce"),
            "src": (src_id.astype(str) if src_id is not None else ""),
        }).dropna(subset=["season", "nkey"])
        if j.empty:
            return sa
        j["season"] = j["season"].astype(int)

        # Two different backs whose names normalize to the same key would get
        # averaged together into a number that is wrong for both of them, and
        # nothing downstream would ever look suspicious. Drop those keys instead:
        # a missing snap share is handled everywhere; a quietly wrong one isn't.
        if (j["src"] != "").any():
            amb = j.groupby(["season", "nkey"])["src"].nunique()
            bad = set(amb[amb > 1].index)
            if bad:
                j = j[~j.set_index(["season", "nkey"]).index.isin(bad)]
                if j.empty:
                    return sa

        # Snap counts are per game; a season's snap share is the mean of them.
        j = j.groupby(["season", "nkey"], as_index=False)["pct"].mean()
        # nflverse reports this as 0-1 in some years and 0-100 in others.
        if float(j["pct"].max()) <= 1.5:
            j["pct"] = j["pct"] * 100.0
        sa["nkey"] = sa["player_name"].map(norm)
        sa = sa.drop(columns=["snap_pct"]).merge(
            j.rename(columns={"pct": "snap_pct"}), on=["season", "nkey"], how="left")
        sa = sa.drop(columns=["nkey"])
    except Exception:      # noqa: BLE001 -- a cosmetic signal must never fail a build
        if "snap_pct" not in sa.columns:
            sa["snap_pct"] = np.nan
    return sa


def snap_coverage(sa: pd.DataFrame) -> float:
    """Fraction of RB seasons that actually got a snap share (0.0 - 1.0)."""
    if sa is None or sa.empty or "snap_pct" not in sa.columns:
        return 0.0
    return float(sa["snap_pct"].notna().mean())


def _recent_pool(sa: pd.DataFrame) -> pd.DataFrame:
    """Reference pool for cross-season percentiles = last RECENCY seasons, games>=8."""
    if sa is None or sa.empty:
        return sa
    mx = int(sa["season"].max())
    pool = sa[(sa["season"] >= mx - RECENCY + 1) & (sa["games"] >= 8)]
    return pool if not pool.empty else sa


# ---------------------------------------------------------------------------
# 2. Talent bundle  (healthy + recency-capped, most-recent weighted)
# ---------------------------------------------------------------------------
_BUNDLE_MEANS = ["rush_fp_reg_pg", "rec_fp_reg_pg", "carries_pg", "targets_pg",
                 "opp_pg", "bf_share", "bf_carry_share", "bf_target_share",
                 "snap_pct", "ypc", "ypt"]


def _bundle(pdf: pd.DataFrame, as_of: int) -> dict | None:
    """What a back brings into `as_of`, built only from his prior seasons.

    Uses his last 3 HEALTHY seasons inside the recency window; falls back to any
    recent season, then to any prior season at all. The most recent one counts
    most, and more steeply than the QB model does it (.6/.27/.13 vs .5/.33/.17)
    because a back's job changes faster than a quarterback's.
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
    wts = np.array([0.6, 0.27, 0.13][: len(use)], dtype=float)

    out = {"talent_reg": float(np.average(use["tot_fp_reg_pg"].to_numpy(), weights=wts))}
    for col in _BUNDLE_MEANS:
        if col in use.columns:
            v = pd.to_numeric(use[col], errors="coerce").dropna()
            out[col.replace("_fp_reg_pg", "_val")] = float(v.mean()) if len(v) else np.nan
        else:
            out[col.replace("_fp_reg_pg", "_val")] = np.nan

    prior_sorted = prior.sort_values("season")
    out.update({
        "career_games": float(prior["games"].sum()),
        "healthy_recent": bool(len(healthy) > 0),
        "prev_ppg": float(prior_sorted["total_fp_pg"].iloc[-1]),
        "prev_games": float(prior_sorted["games"].iloc[-1]),
        "prev_team": prior_sorted["team"].iloc[-1],
    })
    return out


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
    """One row per (back, completed season) with everything built from prior years."""
    if sa is None or sa.empty:
        return pd.DataFrame()
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

    # Sample-size regression: shrink talent toward each season-cohort's mean by
    # how thin the career is. Backs produce sooner than quarterbacks do, so the
    # shrink is gentler here (K_CAREER 10 vs 12) -- but a six-game hot streak
    # still can't crown anyone.
    pool_mean = p.groupby("season")["talent_reg"].transform("mean")
    cg = pd.to_numeric(p["career_games"], errors="coerce").fillna(0.0)
    wc = cg / (cg + K_CAREER)
    p["talent_final"] = wc * p["talent_reg"] + (1 - wc) * pool_mean
    p["reg_shrink"] = (1 - wc)          # 0 = fully trusted, 1 = fully to the mean

    def pct(col):
        if col not in p.columns:
            return pd.Series(np.nan, index=p.index)
        return p.groupby("season")[col].transform(lambda s: s.rank(pct=True) * 100)

    p["Talent"] = pct("talent_final")

    # Volume: weighted touches per game. One number, and the most repeatable
    # thing a running back has.
    p["Volume"] = pct("opp_pg")

    # Receiving: half target VOLUME, half receiving PRODUCTION -- the same split
    # the QB model uses for rushing, and for the same reason. Targets are a
    # coaching decision and repeat; receiving yards and scores wobble.
    _rec_prod = pct("rec_val")
    _rec_vol = pct("targets_pg")
    if _rec_vol.notna().any():
        p["Receiving"] = (1 - REC_VOL_W) * _rec_prod + REC_VOL_W * _rec_vol.fillna(_rec_prod)
    else:
        p["Receiving"] = _rec_prod

    # Backfield: his share of his own team's back-work. Snap share is folded in
    # only where it actually joined, so a missing snap table quietly leaves this
    # as pure touch share instead of dragging half the field to the middle.
    _share = pct("bf_share")
    _snap = pct("snap_pct")
    if _snap.notna().sum() >= max(10, int(0.5 * len(p))):
        p["Backfield"] = pd.concat([_share, _snap.fillna(_share)], axis=1).mean(axis=1)
    else:
        p["Backfield"] = _share

    p["Efficiency"] = pd.concat([pct("ypc"), pct("ypt")], axis=1).mean(axis=1)
    p["Vegas"] = pd.concat([pct("win_total"), pct("implied_total_avg")], axis=1).mean(axis=1)
    # Situation for a back is pace plus run lean -- more snaps and more handoffs.
    # Note the sign flip against the QB model: a pass-happy offense helps a
    # quarterback and (mostly) hurts a runner, so pass rate enters negated.
    if "pass_rate" in p.columns:
        p["neg_pass"] = -pd.to_numeric(p["pass_rate"], errors="coerce")
    p["Situation"] = pd.concat([pct("plays_pg"), pct("neg_pass")], axis=1).mean(axis=1)
    p["Availability"] = [
        _age_curve(a) * (d if pd.notna(d) else 0.8) * 100
        for a, d in zip(p["age"], p["durability"])
    ]
    p["Matchup"] = 50.0

    # Movers: shrink team-based factors toward neutral. BACKFIELD IS IN THIS
    # LIST and it isn't in the QB model's -- a back's share of last year's
    # backfield tells you almost nothing about the depth chart he just joined,
    # and leaving it un-shrunk is how a change-of-scenery back ends up ranked on
    # a job he no longer has.
    for col in ["Situation", "Vegas", "Backfield"]:
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


def _drafted_keys(pos: str = "RB") -> set:
    """Kept only so older test scripts that import it keep running."""
    return set(calibration.drafted_picks(pos))


def calibrate(p: pd.DataFrame, pos: str = "RB",
              info: dict | None = None) -> tuple[float, float]:
    """Map composite -> points per game. See src/calibration.py for the why.

    Two bugs lived here and both are now fixed in that one shared file, because
    the QB board had exactly the same two: the points were anchored on a
    different crowd of players than the ADP curve they get compared against, and
    the fitted line spread players out LESS than their draft slot alone does.
    """
    return calibration.fit(p, pos=pos, info=info)


def backtest(p: pd.DataFrame) -> dict:
    """Fit on earlier seasons, score the two most recent, vs a prior-year baseline.

    Worth reading with the same caution the QB board deserves: this is a MEAN
    error. It rewards being roughly right about the middle of the field and is
    almost blind to whether the model found the one back who won a league. That
    is the wrong question for RBs specifically, and it's why the plan has a
    separate historical "would this have flagged the right backs" check later.
    """
    seasons = sorted(int(s) for s in p["season"].dropna().unique())
    if len(seasons) < 3:
        return {}
    test = seasons[-2:]
    tr = p[(~p["season"].isin(test)) & p["actual_ppg"].notna()]
    if len(tr) < 5:
        return {}
    b, a = np.polyfit(tr["composite"], tr["actual_ppg"], 1)
    te = p[p["season"].isin(test) & p["actual_ppg"].notna()].copy()
    if te.empty:
        return {}
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


def _r(row, key, nd=2):
    """Round a payload value, or None when it isn't there."""
    v = row.get(key)
    if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v):
        return None
    return round(float(v), nd)


def _assemble(cur: pd.DataFrame, a: float, b: float, bt: dict, weights: dict,
              extra: dict | None = None) -> dict:
    cur = cur.copy()
    # The bends, when calibration managed to fit them. They live inside `extra`
    # because both callers already hand their calibration detail through there.
    # No bends -> apply() is the same straight line this always was.
    knots = ((extra or {}).get("calibration") or {}).get("knots") or []
    cur["proj_ppg"] = calibration.apply(cur["composite"], a, b, knots)
    cur["position"] = "RB"
    board = rankings.build_rankings(
        cur[["player_id", "player_name", "position", "proj_ppg"]], ppg_col="proj_ppg"
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
            "archetype": "",          # tier 2 (XFP-share buckets); blank keeps the UI happy
            "mover": bool(row.get("mover", False)),
            "starter": bool(row.get("is_starter")) if row.get("is_starter") is not None else None,
            "depth_rank": (int(row["depth_rank"]) if pd.notna(row.get("depth_rank")) else None),
            "proj_ppg": round(float(r["proj_ppg"]), 2),
            "proj_total": round(float(r["proj_points_total"]), 1),
            "tier": int(r["tier"]),
            "vor": round(float(r["vor"]), 1),
            "career_games": (round(float(row["career_games"]))
                             if pd.notna(row.get("career_games")) else None),
            "age": (round(float(row["age"])) if pd.notna(row.get("age")) else None),
            # Explicit numeric fields, so ratings.py and the report can test
            # published thresholds directly instead of parsing labels.
            "carries_pg": _r(row, "carries_pg"),
            "targets_pg": _r(row, "targets_pg"),
            "targets_pace": (round(float(row["targets_pg"]) * 17.0)
                             if pd.notna(row.get("targets_pg")) else None),
            "opp_pg": _r(row, "opp_pg"),
            "bf_share": _r(row, "bf_share", 3),
            "snap_pct": _r(row, "snap_pct", 1),
            "rush_fpg": _r(row, "rush_val"),
            "rec_fpg": _r(row, "rec_val"),
            # Games played per 17. Published on its own and not folded into the
            # Availability index, because that index is age x durability -- a
            # perfectly healthy 30-year-old scores low on it, and a flag that
            # said "injury history" off that number would be inventing one.
            "durability": _r(row, "durability", 2),
            "indices": {g: round(float(row.get(g, 50.0)), 1) for g in GROUPS},
            "signals": {label: round(float(row[col]), 3 if "share" in col else 2)
                        for col, label in SIGNALS.items()
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
def run(weekly, team_season, players, scoring_rules, season, weights=None,
        snaps=None) -> dict:
    weights = weights or DEFAULT_WEIGHTS
    sa = season_aggregates(weekly, scoring_rules, snaps)
    if sa.empty:
        return _empty(weights)
    prof = entering_profiles(sa, team_season, players, _recent_pool(sa))
    if prof.empty:
        return _empty(weights)
    prof = add_indices(prof, weights)
    cal: dict = {}
    a, b = calibrate(prof, info=cal)
    # backtest() deliberately keeps its own all-backs fit. It exists to answer
    # "does the composite predict better than last year's points?", which is a
    # question about ordering, and its number stays comparable to every previous
    # run that way. The calibration above only decides what SCALE those ordered
    # projections print in.
    bt = backtest(prof)
    cur = prof[(prof["season"] == season) & (prof["career_games"] >= MIN_CAREER_GAMES)].copy()
    if cur.empty:
        return _empty(weights)
    return _assemble(cur, a, b, bt, weights, {"calibration": cal})


# ---------------------------------------------------------------------------
# 7. Entry point B -- upcoming season, driven by the CURRENT roster/depth chart
# ---------------------------------------------------------------------------
def build_upcoming(sa, team_season, players, current_map, season,
                   pool) -> tuple[pd.DataFrame, list[str]]:
    """One profile row per current RB: current team + historical production."""
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


def run_upcoming(weekly, team_season, players, current_map, scoring_rules, season,
                 weights=None, snaps=None) -> dict:
    """Project the UPCOMING season using current teams/depth charts + history."""
    weights = weights or DEFAULT_WEIGHTS
    sa = season_aggregates(weekly, scoring_rules, snaps)
    if sa.empty:
        return _empty(weights, {"skipped_rookies": []})
    pool = _recent_pool(sa)
    hist = entering_profiles(sa, team_season, players, pool)          # calibration/backtest
    up, skipped = build_upcoming(sa, team_season, players, current_map, season, pool)
    if up.empty:
        return _empty(weights, {"skipped_rookies": skipped})

    allp = pd.concat([hist, up], ignore_index=True, sort=False)
    allp = add_indices(allp, weights)
    cal: dict = {}
    a, b = calibrate(allp, info=cal)
    # See run() above: the backtest keeps the all-backs fit on purpose so its
    # score still means the same thing it meant last run.
    bt = backtest(allp)

    cur = allp[(allp["season"] == season)
               & (allp["career_games"] >= MIN_CAREER_GAMES)].copy()
    if cur.empty:
        return _empty(weights, {"skipped_rookies": skipped})
    return _assemble(cur, a, b, bt, weights,
                     {"skipped_rookies": skipped,
                      "snap_coverage": round(snap_coverage(sa), 3),
                      "calibration": cal})
