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
    adp as adp_mod, config, current_roster, data, media, qb_blend, ratings, report,
    team_features,
)


def _scoring_label() -> str:
    r = config.SCORING.get("reception", 1.0)
    return {1.0: "Full PPR", 0.5: "Half PPR", 0.0: "Standard"}.get(r, f"{r}/rec")


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

    bt = result.get("backtest", {})
    if bt:
        print(f"\n  Backtest ({' & '.join(str(s) for s in bt['seasons'])}): "
              f"model MAE {bt['model_mae']} vs baseline {bt['baseline_mae']}")
    skipped = result.get("skipped_rookies", [])
    if skipped:
        print(f"  Not projected (no NFL history yet — rookies/first-timers): {', '.join(skipped[:12])}"
              + (" ..." if len(skipped) > 12 else ""))

    meta = {
        "season": config.UPCOMING_SEASON, "season_label": season_label,
        # The report appends "built <date & time>" to this line itself, shown in
        # the reader's own timezone — so no generated-on date is needed here.
        "subline": f"QB index-blend · current teams & starters via depth charts · "
                   f"{_scoring_label()}",
        "note": f"{len(result['payload'])} projected starters. Teams/starters from current depth charts; "
                f"production from games through {config.CURRENT_SEASON}.",
    }
    (config.OUTPUT_DIR / "qb_model.html").write_text(report.render(result, meta), encoding="utf-8")
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
    print(f"\nSaved report to: {config.OUTPUT_DIR / 'qb_model.html'}")
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
