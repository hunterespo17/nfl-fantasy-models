"""
Step 6 -- Build the QB projection model for the UPCOMING season.

Mixes two sources, as it should:
  * CURRENT teams & starters  -> from live nflverse depth charts + rosters
    (refreshed daily, so this reflects the current offseason's moves)
  * production / talent        -> from historical games through last season

The projection is a transparent index blend with weights you retune live in the
report.

    py scripts\\06_build_qb_model.py

First run downloads play-by-play, players, depth charts, and rosters (cached after).
"""
import os
import pathlib
import shutil
import sys

# --- Stale-bytecode guard (important when the project lives in OneDrive) ------
# OneDrive syncs the __pycache__ folder to the cloud and can restore an OLD .pyc
# whose timestamp makes Python skip recompiling your updated source -- so edits
# silently don't take effect. We (1) refuse to write new .pyc files and (2) wipe
# any existing caches right here, BEFORE importing project modules, so every run
# compiles from the current source no matter what OneDrive did. We delete .pyc
# files individually (a locked file can make a whole-dir rmtree fail silently).
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

import pandas as pd  # noqa: E402

from src import (  # noqa: E402
    adp as adp_mod, calibration, config, current_roster, data, media, qb_blend,
    ratings, report, team_features,
)


def _scoring_label() -> str:
    r = config.SCORING.get("reception", 1.0)
    return {1.0: "Full PPR", 0.5: "Half PPR", 0.0: "Standard"}.get(r, f"{r}/rec")


def _refresh_site() -> None:
    """Rebuild the one-page board, so it is never a command you can forget.

    Wrapped in a catch on purpose: a problem assembling the combined page must
    not throw away the board this script just spent two minutes building.
    """
    print(f"\nThis board on its own:  {config.OUTPUT_DIR / 'qb_model.html'}")
    try:
        out, boards = report.build_site(config.OUTPUT_DIR / "boards",
                                        config.OUTPUT_DIR / "index.html")
    except Exception as exc:                                   # noqa: BLE001
        print(f"  (couldn't refresh the combined page: {exc})")
        print("   Run  py scripts\\12_build_site.py  to try again.")
        return
    if out is None:
        return
    tabs = " + ".join(m.get("pos", "?") for _, m in boards)
    print(f"\n  >>> OPEN THIS ONE:  {out}")
    print(f"      All positions on one page ({tabs}), plus the Big Board.")


def main() -> None:
    # Loud check: if a stale .pyc still shadowed the new source, say so plainly
    # instead of silently producing an old-looking board.
    stale = []
    if "Form" in getattr(qb_blend, "DEFAULT_WEIGHTS", {"Form": 1}):
        stale.append("qb_blend")
    if not hasattr(ratings, "attach"):
        stale.append("ratings")
    if stale:
        print("\n" + "=" * 68)
        print("[!] STALE CODE LOADED for: " + ", ".join(stale))
        print("    An old cached copy is overriding the new files. Fix it with:")
        print("      1. Close this terminal window completely.")
        print("      2. Delete every '__pycache__' folder inside the project.")
        print("      3. Open a fresh terminal and run this script again.")
        print("    (If it keeps happening, the project is inside OneDrive — moving")
        print("     it to a non-synced folder like C:\\Dev\\ ends this for good.)")
        print("=" * 68 + "\n")
        return

    weekly = data.load_df("player_weekly_stats")
    if weekly is None:
        print("No cached data. Run scripts/01_pull_data.py first.")
        return
    schedules = data.load_df("schedules")

    print("Loading games, players, and CURRENT depth charts + rosters...")
    pbp = data.get_pbp(config.SEASONS)
    players = data.get_players()
    depth = data.get_depth_charts([config.UPCOMING_SEASON])
    rosters = data.get_rosters([config.UPCOMING_SEASON])

    team_season = team_features.build_team_season_features(pbp, schedules, weekly)

    # ---- current team + starter mapping (with a debug dump we can verify) ----
    cmap, dbg = current_roster.build_current_map(depth, rosters)
    debug_path = config.OUTPUT_DIR / "current_map_debug.txt"
    lines = [f"UPCOMING_SEASON = {config.UPCOMING_SEASON}", ""] + dbg + ["", "MAPPED QBs:"]
    if not cmap.empty:
        show = cmap.sort_values(["is_starter", "team"], ascending=[False, True])
        lines += show.to_string(index=False).splitlines()
    debug_path.write_text("\n".join(str(x) for x in lines), encoding="utf-8")
    print(f"  wrote mapping debug -> {debug_path}")

    if cmap.empty:
        print("\n  [!] No current depth-chart/roster data available. Falling back to LAST "
              "season's teams (these may be stale). Re-run once nflverse has current data.")
        result = qb_blend.run(weekly, team_season, players, config.SCORING, config.CURRENT_SEASON)
        season_label = f"{config.CURRENT_SEASON} (stale teams — current roster data unavailable)"
    else:
        starters = current_roster.starters(cmap)
        if not (cmap["is_starter"] == True).any():  # noqa: E712
            print("  [note] Depth-chart starter flags not found; ranking all rostered QBs.")
        result = qb_blend.run_upcoming(
            weekly, team_season, players, starters, config.SCORING, config.UPCOMING_SEASON
        )
        season_label = f"{config.UPCOMING_SEASON} outlook"

    if not result["payload"]:
        print("No QBs with enough history to project.")
        return

    # ---- descriptive draft overlays (floor / ceiling / ADP / risk) ----------
    # These do NOT change the projection or ranking; they are added on top.
    adp_df = adp_mod.load_adp()
    if adp_df.empty:
        print("  [note] No data/adp.csv found — floor/ceiling shown, ADP & risk skipped.")
    result = ratings.attach(result, weekly, config.SCORING, adp_df, config)

    # ---- headshots (cosmetic only) -----------------------------------------
    # Wrapped: a picture is never worth failing a build over. If this errors or
    # finds nothing, the board just shows initials avatars instead.
    try:
        n_shots = media.attach_headshots(result["payload"], players, rosters)
        if n_shots:
            print(f"  headshots matched for {n_shots}/{len(result['payload'])} QBs")
        else:
            print("  [note] No headshot URLs found in the nflverse tables — "
                  "the board will show initials instead.")
    except Exception as exc:  # noqa: BLE001
        print(f"  [note] Headshots skipped ({type(exc).__name__}: {exc}).")

    # The ADP-expectation curve is the backbone of the points-space value tag, so
    # say out loud what it was fit on -- a silently-degraded curve would still
    # produce confident-looking numbers.
    cv = (result.get("ratings_meta") or {}).get("curve")
    if not cv:
        print("  [note] No ADP expectation curve — 'worth the pick?' in points is skipped. "
              "Check data/adp_history.csv exists and its names match.")
    elif cv.get("source") == "board":
        print("  [note] ADP curve fell back to THIS year's prices (data/adp_history.csv "
              "missing or wouldn't join). It can only say 'cheap for this year's market'.")
    else:
        print(f"  ADP expectation curve: {cv['n']} QB seasons over "
              f"{'-'.join(str(s) for s in (cv['seasons'][:1] + cv['seasons'][-1:]))}, "
              f"R²={cv['r2']} ({cv['missed']} drafted QBs never played enough to score)")

    # The points scale has to be anchored on the SAME crowd the curve was fit on,
    # or "worth the pick?" measures the gap between two crowds instead of the gap
    # between a player and his price. That failure is silent -- the board still
    # prints confident numbers -- so say which crowd was used, every run.
    _cal = result.get("calibration") or {}
    if _cal.get("anchor") == "drafted players":
        print(f"  Points scale: fit on {_cal['n_used']} drafted QB seasons "
              f"(of {_cal['n_all']} with scoring), the same crowd as the curve above.")
        if _cal.get("shape") == "curve":
            print(f"     Bent to the curve's shape at {len(_cal['knots'])} points, so the "
                  f"top of the board can pull away: best QB projects "
                  f"{_cal.get('top')}, deepest {_cal.get('floor')} per game.")
        else:
            print("     [note] One straight line — not enough drafted seasons to bend it. "
                  "The top of the board will read a couple of points light.")
        # Both sides of "worth the pick?" are hedged; what matters is that they're
        # hedged by the SAME amount. Near zero is a fair fight. Well below zero
        # means the factors know less than the draft slot does, and the value
        # column will lean toward calling early picks overpriced.
        if _cal.get("hedge_gap") is not None:
            _hg = _cal["hedge_gap"]
            print(f"     Factors explain {_cal.get('r_composite')} vs draft slot's "
                  f"{_cal.get('r_pick')} (gap {_hg:+.3f})"
                  + ("." if abs(_hg) < 0.10 else
                     " — over 0.10 apart, so read the value column with that in mind."))
        _floor = [q["name"] for q in (result.get("payload") or [])
                  if (q.get("proj_ppg") or 0) <= 0]
        if _floor:
            print(f"     {len(_floor)} at the 0.0 floor (deep QBs the scale bottoms out on): "
                  + ", ".join(_floor[:8]) + (" ..." if len(_floor) > 8 else ""))
    elif _cal:
        print(f"  [note] Points scale fell back to ALL {_cal.get('n_all')} QBs, "
              f"including undrafted ones — only {_cal.get('n_drafted')} drafted seasons "
              f"joined by name and it needs {calibration.MIN_ROWS}. Early-round QBs "
              "will read too cheap and late-round QBs too rich.")

    # The historical ADP file is a list of NAMES, so the one way it can quietly
    # go wrong is a name that doesn't match the stats -- the curve just gets
    # fitted on fewer players and never says so. Print who dropped out.
    _missed = result.get("curve_missed") or []
    if _missed:
        print(f"  Not in the fit ({len(_missed)}) — drafted but under "
              f"{adp_mod.MIN_GAMES_HIST} games, OR the name didn't match:")
        for i in range(0, min(len(_missed), 24), 4):
            print("     " + "  |  ".join(_missed[i:i + 4]))
        if len(_missed) > 24:
            print(f"     ...and {len(_missed) - 24} more")
        print("     If someone there played a full season, it's a spelling "
              "mismatch — send me the name.")

    bt = result.get("backtest", {})
    if bt:
        print(f"\n  Backtest ({' & '.join(str(s) for s in bt['seasons'])}): "
              f"model MAE {bt['model_mae']} vs baseline {bt['baseline_mae']}")
    skipped = result.get("skipped_rookies", [])
    if skipped:
        print(f"  Not projected (no NFL history yet — rookies/first-timers): {', '.join(skipped[:12])}"
              + (" ..." if len(skipped) > 12 else ""))

    meta = {
        "pos": "QB",
        "season": config.UPCOMING_SEASON, "season_label": season_label,
        # The report appends "built <date & time>" to this line itself, shown in
        # the reader's own timezone — so no generated-on date is needed here.
        "subline": f"QB index-blend · current teams & starters via depth charts · "
                   f"{_scoring_label()}",
        "note": f"{len(result['payload'])} projected starters. Teams/starters from current depth charts; "
                f"production from games through {config.CURRENT_SEASON}.",
    }
    # Two outputs, on purpose. qb_model.html is this board on its own, which is
    # the thing to open if you only rebuilt the quarterbacks. The saved board is
    # what scripts\12_build_site.py folds into the one-page site with the other
    # positions, so a QB rebuild refreshes the QB tab and touches nothing else.
    (config.OUTPUT_DIR / "qb_model.html").write_text(report.render(result, meta), encoding="utf-8")
    report.save_board(result, meta, config.OUTPUT_DIR / "boards" / "qb.json")
    rows = [{k: q.get(k) for k in ("rank", "name", "team", "archetype", "mover", "starter",
                                   "proj_ppg", "proj_total", "tier", "vor",
                                   "adp", "adp_label", "value_gap", "value_tag",
                                   "exp_fpg", "value_fpg", "value_fpg_tag",
                                   "rush_att_pace", "rush_fpg", "lw_score",
                                   "floor_pts", "floor_bucket", "boom25", "boom30",
                                   "ceiling_bucket", "risk_bucket")} for q in result["payload"]]
    pd.DataFrame(rows).to_csv(config.OUTPUT_DIR / "qb_projections.csv", index=False)

    print("\nTop 8 (default weights):")
    for q in result["payload"][:8]:
        flag = " [NEW TEAM]" if q["mover"] else ""
        adp = q.get("adp_label", "—")
        tag = f" {q['value_tag'].upper()}" if q.get("value_tag") else ""
        print(f"  {q['rank']:>2}. {q['name']:<22} {q['team']:<4} {q['proj_ppg']:>5.1f} pts/gm  "
              f"{q['archetype']:<13} ADP {adp:<5} floor:{q.get('floor_bucket','?'):<8} "
              f"ceil:{q.get('ceiling_bucket','?'):<6} risk:{q.get('risk_bucket','?')}{tag}{flag}")
    _refresh_site()
    print("If any team/starter looks wrong, open current_map_debug.txt and send it to me.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback as _tb
        _p = config.OUTPUT_DIR / "current_map_debug.txt"
        with open(_p, "a", encoding="utf-8") as _f:
            _f.write("\n\n=== ERROR during run ===\n" + _tb.format_exc())
        print(f"\n[!] Something errored. Full traceback appended to {_p} — send me that file.")
        raise
