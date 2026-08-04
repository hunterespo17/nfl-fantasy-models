"""
Step 11 -- Build the RB projection model for the UPCOMING season.

Same shape as the quarterback build (scripts\\06_build_qb_model.py), with the
differences a backfield forces:

  * It keeps the top THREE backs on each depth chart, not just the starter.
    A team has one quarterback who matters and two or three backs who do, and
    the second one is often the better pick -- filtering to lead backs would
    delete exactly the players worth finding.
  * It loads snap counts. Touches tell you what a back did; snaps tell you
    whether he was on the field for the plays that hadn't happened yet.
  * There is no league-winner gate on this board yet. The running-back version
    of that screen needs contract years and expected-points share, which are
    tier 2. An empty gate is honest; a quarterback's gate applied to a back
    would not be.

    py scripts\\11_build_rb_model.py

First run downloads play-by-play, players, depth charts, rosters, and snap
counts (all cached afterward).
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

import inspect  # noqa: E402

import pandas as pd  # noqa: E402

from src import (  # noqa: E402
    adp as adp_mod, config, current_roster, data, media, rb_blend, ratings, report,
    team_features,
)

POS = "RB"
KEEP_DEPTH = 3          # RB1 / RB2 / RB3 on each depth chart


def _scoring_label() -> str:
    r = config.SCORING.get("reception", 1.0)
    return {1.0: "Full PPR", 0.5: "Half PPR", 0.0: "Standard"}.get(r, f"{r}/rec")


def main() -> None:
    # Loud check: if a stale .pyc still shadowed the new source, say so plainly
    # instead of silently producing an old-looking board.
    stale = []
    if "Backfield" not in getattr(rb_blend, "DEFAULT_WEIGHTS", {}):
        stale.append("rb_blend")
    # Added with the drafted-only points scale. Catches the half-updated case too:
    # a copy of rb_blend.py that predates that fix would make this script print a
    # scale line about a calibration it never did.
    if not hasattr(rb_blend, "MIN_CAL_ROWS"):
        stale.append("rb_blend")
    if not hasattr(ratings, "_flags"):
        stale.append("ratings")
    if "pos" not in inspect.signature(adp_mod.raw_picks).parameters:
        stale.append("adp")
    if stale:
        print("\n" + "=" * 68)
        print("[!] STALE CODE LOADED for: " + ", ".join(dict.fromkeys(stale)))
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

    # Snap share. Wrapped, because it is one factor inside one index -- worth
    # having, never worth failing the whole build over. rb_blend leaves the
    # Backfield index as pure touch share when this is missing or thin.
    snaps = None
    try:
        snaps = data.get_snap_counts(config.SEASONS)
        print(f"  snap counts: {len(snaps):,} rows")
    except Exception as exc:  # noqa: BLE001
        print(f"  [note] Snap counts unavailable ({type(exc).__name__}: {exc}). "
              "Backfield share will be based on touches alone.")

    team_season = team_features.build_team_season_features(pbp, schedules, weekly)

    # ---- current team + depth-chart mapping (with a debug dump we can verify) ----
    cmap, dbg = current_roster.build_current_map(depth, rosters, pos=POS)
    debug_path = config.OUTPUT_DIR / "current_map_debug_rb.txt"
    lines = [f"UPCOMING_SEASON = {config.UPCOMING_SEASON}", f"POSITION = {POS}",
             f"KEEP_DEPTH = {KEEP_DEPTH}", ""] + dbg + ["", f"MAPPED {POS}s:"]
    if not cmap.empty:
        show = cmap.sort_values(["team", "depth_rank"], ascending=[True, True])
        lines += show.to_string(index=False).splitlines()
    debug_path.write_text("\n".join(str(x) for x in lines), encoding="utf-8")
    print(f"  wrote mapping debug -> {debug_path}")

    if cmap.empty:
        print("\n  [!] No current depth-chart/roster data available. Falling back to LAST "
              "season's teams (these may be stale). Re-run once nflverse has current data.")
        result = rb_blend.run(weekly, team_season, players, config.SCORING,
                              config.CURRENT_SEASON, snaps=snaps)
        season_label = f"{config.CURRENT_SEASON} (stale teams — current roster data unavailable)"
    else:
        keep = current_roster.starters(cmap, keep_depth=KEEP_DEPTH)
        n_norank = int(pd.to_numeric(keep["depth_rank"], errors="coerce").isna().sum())
        print(f"  depth charts: {len(cmap)} {POS}s found, keeping {len(keep)} at rank "
              f"1-{KEEP_DEPTH}"
              + (f" (plus {n_norank} with no depth-chart rank — kept rather than cut, "
                 "since a missing row is a data gap, not a bad player)" if n_norank else ""))
        result = rb_blend.run_upcoming(
            weekly, team_season, players, keep, config.SCORING, config.UPCOMING_SEASON,
            snaps=snaps,
        )
        season_label = f"{config.UPCOMING_SEASON} outlook"

    if not result["payload"]:
        print(f"No {POS}s with enough history to project.")
        return

    cov = result.get("snap_coverage")
    if cov is not None:
        note = "" if cov >= 0.5 else "  <- under 50%, so it is NOT folded into the Backfield index"
        print(f"  snap share matched on {cov:.0%} of {POS} seasons{note}")

    # ---- descriptive draft overlays (floor / ceiling / ADP / risk) ----------
    # These do NOT change the projection or ranking; they are added on top.
    adp_df = adp_mod.load_adp()
    n_rb_adp = len(adp_mod.for_pos(adp_df, POS)) if not adp_df.empty else 0
    if n_rb_adp == 0:
        print(f"  [note] No {POS} rows in data/adp.csv — floor/ceiling shown, "
              "ADP, value and risk skipped. Add rows with pos=RB to turn those on.")
    result = ratings.attach(result, weekly, config.SCORING, adp_df, config, pos=POS)

    # ---- headshots (cosmetic only) -----------------------------------------
    # Wrapped: a picture is never worth failing a build over. If this errors or
    # finds nothing, the board just shows initials avatars instead.
    try:
        n_shots = media.attach_headshots(result["payload"], players, rosters)
        if n_shots:
            print(f"  headshots matched for {n_shots}/{len(result['payload'])} {POS}s")
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
              "Needs RB rows in data/adp_history.csv whose names match.")
    elif cv.get("source") == "board":
        print("  [note] ADP curve fell back to THIS year's prices (no RB history in "
              "data/adp_history.csv, or the names wouldn't join). It can only say "
              "'cheap for this year's market', not 'cheap versus history'.")
    else:
        print(f"  ADP expectation curve: {cv['n']} {POS} seasons over "
              f"{'-'.join(str(s) for s in (cv['seasons'][:1] + cv['seasons'][-1:]))}, "
              f"R²={cv['r2']} ({cv['missed']} drafted {POS}s never played enough to score)")

    # The points scale has to be anchored on the SAME crowd the curve was fit on,
    # or "worth the pick?" measures the gap between two crowds instead of the gap
    # between a player and his price. That failure is silent -- the board still
    # prints confident numbers -- so say which crowd was used, every run.
    _cal = result.get("calibration") or {}
    if _cal.get("anchor") == "drafted players":
        print(f"  Points scale: fit on {_cal['n_used']} drafted {POS} seasons "
              f"(of {_cal['n_all']} with scoring), the same crowd as the curve above.")
        if _cal.get("shape") == "curve":
            print(f"     Bent to the curve's shape at {len(_cal['knots'])} points, so the "
                  f"top of the board can pull away: best {POS} projects "
                  f"{_cal.get('top')}, deepest {_cal.get('floor')} per game.")
        else:
            print("     [note] One straight line — not enough drafted seasons to bend it. "
                  f"The top of the board will read a couple of points light.")
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
        # A straight line ran off the bottom into negative points and clipped a
        # dozen backs onto a shared 0.0. The bent one shouldn't, so anybody still
        # sitting there is worth a look.
        _floor = [q["name"] for q in (result.get("payload") or [])
                  if (q.get("proj_ppg") or 0) <= 0]
        if _floor:
            print(f"     {len(_floor)} at the 0.0 floor (deep backs the scale bottoms out on): "
                  + ", ".join(_floor[:8]) + (" ..." if len(_floor) > 8 else ""))
    elif _cal:
        print(f"  [note] Points scale fell back to ALL {_cal.get('n_all')} {POS}s, "
              f"including undrafted ones — only {_cal.get('n_drafted')} drafted seasons "
              f"joined by name and it needs {rb_blend.MIN_CAL_ROWS}. Early-round backs "
              "will read too cheap and late-round backs too rich.")

    # The historical ADP file is a list of NAMES, so the one way it can quietly
    # go wrong is a name that doesn't match the stats -- the curve just gets
    # fitted on fewer players and never says so. Print who dropped out. Most will
    # be real (hurt, benched, retired); a spelling difference stands out because
    # it will be someone who obviously played a full season.
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
        print("  (MAE is an average. It rewards being right about the middle of the board "
              "and says nothing about whether the league-winners got flagged.)")
    skipped = result.get("skipped_rookies", [])
    if skipped:
        print(f"  Not projected (no NFL history yet — rookies/first-timers): {', '.join(skipped[:12])}"
              + (" ..." if len(skipped) > 12 else ""))

    meta = {
        "pos": POS,
        "season": config.UPCOMING_SEASON, "season_label": season_label,
        # The report appends "built <date & time>" to this line itself, shown in
        # the reader's own timezone — so no generated-on date is needed here.
        "subline": f"RB index-blend · top {KEEP_DEPTH} on each depth chart · "
                   f"{_scoring_label()}",
        "note": f"{len(result['payload'])} backs. Teams and depth from current depth charts; "
                f"production from games through {config.CURRENT_SEASON}. A target counts as "
                f"{rb_blend.TARGET_MULT}x a carry in half-PPR.",
    }
    # See the matching note in scripts\06_build_qb_model.py: the standalone page
    # is this board alone, the saved board is the RB tab of the one-page site.
    (config.OUTPUT_DIR / "rb_model.html").write_text(report.render(result, meta), encoding="utf-8")
    report.save_board(result, meta, config.OUTPUT_DIR / "boards" / "rb.json")
    rows = [{k: q.get(k) for k in ("rank", "name", "team", "mover", "starter", "depth_rank",
                                   "proj_ppg", "proj_total", "tier", "vor",
                                   "adp_label", "value_gap", "value_tag",
                                   "exp_fpg", "value_fpg", "value_fpg_tag",
                                   "carries_pg", "targets_pg", "targets_pace", "opp_pg",
                                   "bf_share", "snap_pct", "rush_fpg", "rec_fpg",
                                   "age", "career_games", "durability",
                                   "floor_pts", "floor_bucket", "boom25", "boom30",
                                   "ceiling_bucket", "risk_bucket")} for q in result["payload"]]
    pd.DataFrame(rows).to_csv(config.OUTPUT_DIR / "rb_projections.csv", index=False)

    print("\nTop 8 (default weights):")
    for q in result["payload"][:8]:
        flag = " [NEW TEAM]" if q["mover"] else ""
        adp = q.get("adp_label", "—")
        tag = f" {q['value_tag'].upper()}" if q.get("value_tag") else ""
        bf = f"{q['bf_share']:.0%}" if q.get("bf_share") is not None else "—"
        print(f"  {q['rank']:>2}. {q['name']:<22} {q['team']:<4} {q['proj_ppg']:>5.1f} pts/gm  "
              f"bkfld {bf:<5} tch/g {str(q.get('opp_pg', '—')):<5} ADP {adp:<5} "
              f"floor:{q.get('floor_bucket', '?'):<8} ceil:{q.get('ceiling_bucket', '?'):<6} "
              f"risk:{q.get('risk_bucket', '?')}{tag}{flag}")
    print(f"\nSaved report to: {config.OUTPUT_DIR / 'rb_model.html'}")
    print("If any team or depth spot looks wrong, open current_map_debug_rb.txt and send it to me.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback as _tb
        _p = config.OUTPUT_DIR / "current_map_debug_rb.txt"
        with open(_p, "a", encoding="utf-8") as _f:
            _f.write("\n\n=== ERROR during run ===\n" + _tb.format_exc())
        print(f"\n[!] Something errored. Full traceback appended to {_p} — send me that file.")
        raise
