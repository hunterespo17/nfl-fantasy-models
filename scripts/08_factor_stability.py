"""
Step 8 -- FACTOR STABILITY TEST.  Does each factor earn the weight it is given?

The board blends nine factors with weights I picked by judgement. Judgement is a
fine place to start and a bad place to stop, so this script measures each factor
on the two things that actually matter and then checks the answer against the
model itself.

    py scripts\\08_factor_stability.py

Three measures per factor
-------------------------
  1. PREDICTIVE   Spearman(factor entering a season, points per game IN that
                  season), computed inside each season and then averaged. This is
                  the only question that pays: does a high score here mean he
                  scores more?
  2. STABLE       Spearman(factor in year Y, same player's factor in year Y+1).
                  A factor that reshuffles every year can be predictive and still
                  be useless to forecast with, because you can't know next year's
                  value in advance.
  3. CHURN        Median absolute year-over-year change, in index points and as a
                  percent. This is the research's own metric, kept so the numbers
                  are comparable to what's published.

Then two checks on the model itself, which are what I'd actually act on:
  * LEAVE-ONE-OUT  Zero out one factor's weight, refit, re-backtest. If the error
                   gets WORSE without it, the factor is doing real work. If it
                   gets better, the factor is costing accuracy.
  * OVERLAP        Which factor pairs move together. Two factors that correlate
                   at 0.8 are mostly one factor charging double.

What this is NOT
----------------
It is not a weight optimiser. Factors overlap, so their contributions do not add
up, and tuning weights directly on a two-season backtest is how you overfit a
30-row test set. Read the table, then move weights a few points at a time in the
direction it points -- and re-run this to confirm the move helped.

Everything measured here is leak-free: profiles are built from PRIOR seasons only
(talent from earlier years, team environment from the team's previous season,
Vegas from preseason win totals), so a factor cannot score well by peeking.

Writes:
    outputs/factor_stability.csv   -- the full table, one row per factor
"""
import os
import pathlib
import shutil
import sys

# --- Stale-bytecode guard (same as scripts 06 / 07) --------------------------
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
for _pyc in _ROOT.rglob("*.pyc"):
    try:
        _pyc.unlink()
    except OSError:
        pass
for _pc in sorted(_ROOT.rglob("__pycache__"), key=lambda p: -len(p.parts)):
    try:
        _pc.rmdir()
    except OSError:
        shutil.rmtree(_pc, ignore_errors=True)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src import config, data, qb_blend, team_features  # noqa: E402

MIN_GAMES = 6       # a 1-5 game cameo is noise; don't let it grade a factor
MIN_PAIRS = 12      # below this, a correlation is a coin flip -- report "thin"


# ---------------------------------------------------------------------------
# Small stats helpers (no scipy dependency -- ranks + Pearson IS Spearman)
# ---------------------------------------------------------------------------
def spearman(a, b) -> tuple[float | None, int]:
    """Rank correlation. Returns (rho, n); rho is None when the sample is unusable."""
    a = pd.Series(list(a), dtype="float64").reset_index(drop=True)
    b = pd.Series(list(b), dtype="float64").reset_index(drop=True)
    ok = a.notna() & b.notna()
    a, b = a[ok], b[ok]
    if len(a) < 5 or a.nunique() < 3 or b.nunique() < 3:
        return None, int(len(a))
    return float(np.corrcoef(a.rank(), b.rank())[0, 1]), int(len(a))


def fmt(v, nd=2, dash="  --  ") -> str:
    return dash if v is None or (isinstance(v, float) and not np.isfinite(v)) else f"{v:+.{nd}f}"


def _bar(v, lo=-0.2, hi=0.7, width=14) -> str:
    """Tiny text gauge so the table is readable at a glance."""
    if v is None or not np.isfinite(v):
        return " " * width
    f = min(max((v - lo) / (hi - lo), 0.0), 1.0)
    n = int(round(f * width))
    return "#" * n + "." * (width - n)


# ---------------------------------------------------------------------------
def build_profiles():
    weekly = data.load_df("player_weekly_stats")
    if weekly is None:
        print("No cached data. Run scripts/01_pull_data.py first.")
        return None
    schedules = data.load_df("schedules")

    print("Loading games and players (first run downloads, then it's cached)...")
    pbp = data.get_pbp(config.SEASONS)
    players = data.get_players()
    team_season = team_features.build_team_season_features(pbp, schedules, weekly)

    sa = qb_blend.season_aggregates(weekly, config.SCORING)
    pool = qb_blend._recent_pool(sa)
    prof = qb_blend.entering_profiles(sa, team_season, players, pool)
    if prof.empty:
        print("Not enough history to grade the factors.")
        return None
    prof = qb_blend.add_indices(prof)

    # Attach how many games he actually played that season, so a 2-game cameo
    # can't grade a factor. entering_profiles carries prev_games, not this one.
    g = sa[["player_id", "season", "games"]].copy()
    g["player_id"] = g["player_id"].astype(str)
    prof["player_id"] = prof["player_id"].astype(str)
    prof = prof.merge(g, on=["player_id", "season"], how="left")
    return prof


def grade(prof: pd.DataFrame) -> pd.DataFrame:
    graded = prof[(prof["games"].fillna(0) >= MIN_GAMES) & prof["actual_ppg"].notna()].copy()

    rows = []
    for gcol in qb_blend.GROUPS:
        # --- 1. predictive: within-season, then averaged by sample size --------
        # Within-season because the indices are percentiles inside a season cohort
        # and league scoring drifts; pooling across years would mix those in.
        parts, weights_, pooled_a, pooled_b = [], [], [], []
        for _s, sub in graded.groupby("season"):
            rho, n = spearman(sub[gcol], sub["actual_ppg"])
            if rho is not None:
                parts.append(rho)
                weights_.append(n)
            pooled_a.extend(sub[gcol].tolist())
            pooled_b.extend(sub["actual_ppg"].tolist())
        pred = float(np.average(parts, weights=weights_)) if parts else None
        pred_n = int(sum(weights_))
        pooled, _ = spearman(pooled_a, pooled_b)

        # --- 2/3. stability + churn: same player, consecutive seasons ----------
        cur, nxt, pct_ch, pt_ch = [], [], [], []
        for _pid, pdf in prof.sort_values("season").groupby("player_id"):
            recs = pdf[["season", gcol]].dropna().to_records(index=False)
            by_season = {int(s): float(v) for s, v in recs}
            for s, v in by_season.items():
                w = by_season.get(s + 1)
                if w is None:
                    continue
                cur.append(v)
                nxt.append(w)
                pt_ch.append(abs(w - v))
                if abs(v) > 1e-9:
                    pct_ch.append(abs(w - v) / abs(v) * 100.0)
        stab, stab_n = spearman(cur, nxt)

        rows.append({
            "factor": gcol,
            "weight": qb_blend.DEFAULT_WEIGHTS[gcol],
            "predictive": pred,
            "predictive_pooled": pooled,
            "pred_n": pred_n,
            "stable": stab,
            "stable_n": stab_n,
            "churn_pts": float(np.median(pt_ch)) if pt_ch else None,
            "churn_pct": float(np.median(pct_ch)) if pct_ch else None,
        })
    return pd.DataFrame(rows)


def leave_one_out(prof: pd.DataFrame) -> dict:
    """Re-backtest with each factor's weight set to 0. Returns {factor: delta_MAE}.

    Positive delta = the model got WORSE without the factor = it is pulling weight.
    composite() divides by the weight total, so zeroing one factor automatically
    re-normalises the rest -- no manual rescaling needed.
    """
    base_bt = qb_blend.backtest(prof)
    if not base_bt:
        return {}
    out = {"_base": base_bt}
    for gcol, w in qb_blend.DEFAULT_WEIGHTS.items():
        if w == 0:
            out[gcol] = None        # already off; nothing to remove
            continue
        wts = dict(qb_blend.DEFAULT_WEIGHTS, **{gcol: 0})
        p2 = prof.copy()
        p2["composite"] = qb_blend.composite(p2, wts)
        bt = qb_blend.backtest(p2)
        out[gcol] = round(bt["model_mae"] - base_bt["model_mae"], 3) if bt else None
    return out


def overlap(prof: pd.DataFrame, top=6) -> list[tuple[str, str, float]]:
    live = [g for g in qb_blend.GROUPS if prof[g].nunique() > 2]
    pairs = []
    for i, x in enumerate(live):
        for y in live[i + 1:]:
            rho, n = spearman(prof[x], prof[y])
            if rho is not None and n >= MIN_PAIRS:
                pairs.append((x, y, rho))
    return sorted(pairs, key=lambda t: -abs(t[2]))[:top]


# ---------------------------------------------------------------------------
def main() -> None:
    if "Form" in getattr(qb_blend, "DEFAULT_WEIGHTS", {"Form": 1}):
        print("\n[!] STALE CODE LOADED. Close the terminal, delete every __pycache__ "
              "folder, and re-run.\n")
        return

    prof = build_profiles()
    if prof is None:
        return

    seasons = sorted(int(s) for s in prof["season"].dropna().unique())
    graded_n = int(((prof["games"].fillna(0) >= MIN_GAMES) & prof["actual_ppg"].notna()).sum())
    print(f"\n{len(prof)} QB-seasons built ({seasons[0]}-{seasons[-1]}); "
          f"{graded_n} played {MIN_GAMES}+ games and are used for grading.")

    tab = grade(prof)
    loo = leave_one_out(prof)
    base = loo.get("_base") or {}

    # ---- the table ---------------------------------------------------------
    print("\n" + "=" * 92)
    print("FACTOR SCORECARD")
    print("=" * 92)
    print(f"{'factor':<13}{'wt':>4}{'predictive':>12}  {'':<14} {'stable':>8}  {'':<14}"
          f"{'churn':>8}{'dMAE':>8}")
    print(f"{'':<13}{'':>4}{'(rho vs ppg)':>12}  {'':<14} {'(Y->Y+1)':>8}  {'':<14}"
          f"{'(pts)':>8}{'w/o it':>8}")
    print("-" * 92)
    for r in tab.sort_values("weight", ascending=False).itertuples():
        d = loo.get(r.factor)
        print(f"{r.factor:<13}{r.weight:>4}{fmt(r.predictive):>12}  {_bar(r.predictive):<14} "
              f"{fmt(r.stable):>8}  {_bar(r.stable):<14}"
              f"{('  --  ' if r.churn_pts is None else f'{r.churn_pts:6.1f}'):>8}"
              f"{('   --  ' if d is None else f'{d:+.3f}'):>8}")
    print("-" * 92)
    if base:
        print(f"baseline: model MAE {base['model_mae']} vs prev-year {base['baseline_mae']} "
              f"on {' & '.join(str(s) for s in base['seasons'])}")
    print("dMAE = points/gm of error ADDED when that factor is switched off. "
          "Positive = it's earning its keep.")

    # ---- quadrant read -----------------------------------------------------
    live = tab[tab["predictive"].notna() & tab["stable"].notna()]
    if len(live) >= 4:
        pm, sm = live["predictive"].median(), live["stable"].median()
        print("\n" + "=" * 92)
        print(f"QUADRANTS  (split at this run's medians: predictive {pm:+.2f}, stable {sm:+.2f})")
        print("=" * 92)
        buckets = {
            "LEAN ON IT      predictive AND stable": (True, True),
            "SMOOTH IT       predictive but jumpy -- multi-year average it": (True, False),
            "CHEAP BALLAST   stable but not predictive -- carrying it costs little, "
            "gains little": (False, True),
            "SUSPECT         neither -- candidate to cut or rebuild": (False, False),
        }
        for label, (wp, ws) in buckets.items():
            names = [r.factor for r in live.itertuples()
                     if (r.predictive >= pm) == wp and (r.stable >= sm) == ws]
            print(f"  {label}\n      {', '.join(names) if names else '(none)'}")
        print("\nThese are RELATIVE to each other, not absolute pass/fail: the median split "
              "\nguarantees roughly half the factors land on each side even in a good model.")

    # ---- overlap -----------------------------------------------------------
    ov = overlap(prof)
    if ov:
        print("\n" + "=" * 92)
        print("MOST OVERLAPPING FACTOR PAIRS  (two factors at 0.8 are mostly one factor "
              "charging twice)")
        print("=" * 92)
        for x, y, rho in ov:
            print(f"  {rho:+.2f}   {x} <-> {y}")

    # ---- what to actually do ----------------------------------------------
    print("\n" + "=" * 92)
    print("READ IT LIKE THIS")
    print("=" * 92)
    print("  * dMAE is the decisive column -- it is measured on the real model, not on a")
    print("    correlation in isolation. Predictive+stable but dMAE ~ 0 usually means the")
    print("    factor is redundant with a bigger one (check the overlap list).")
    print("  * Move weights a few points at a time and RE-RUN. A weight change that doesn't")
    print("    move dMAE or the backtest is a change you can't defend.")
    print("  * Small samples lie. Anything with n under ~40 is a hint, not a finding.")
    print("  * Matchup sits at weight 0 by design, so it has no dMAE to report.")

    out = config.OUTPUT_DIR / "factor_stability.csv"
    tab["delta_mae_without"] = tab["factor"].map(lambda f: loo.get(f))
    tab.round(4).to_csv(out, index=False)
    print(f"\nSaved the full table to: {out}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback as _tb
        _p = config.OUTPUT_DIR / "factor_stability_error.txt"
        _p.write_text(_tb.format_exc(), encoding="utf-8")
        print(f"\n[!] Something errored. Full traceback written to {_p} — send me that file.")
        raise
