"""
Step 7 -- Walk-forward BACKTEST of the QB model (last 5 seasons).

Freezes the model before each season, projects it with no knowledge of what
happened, and compares to the real results. Leak-free, uses the full live model.

    py scripts\\07_backtest_qb.py

Writes:
    outputs/qb_backtest.html  -- readable report (open in a browser)
    outputs/qb_backtest.csv   -- every QB-season: predicted vs actual, games, missed
"""
import os
import pathlib
import shutil
import sys
from datetime import date

# --- Stale-bytecode guard (same as script 06) --------------------------------
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

from src import backtest, config, data, qb_blend, team_features  # noqa: E402


def main() -> None:
    if "Form" in getattr(qb_blend, "DEFAULT_WEIGHTS", {"Form": 1}) or not hasattr(backtest, "run_backtest"):
        print("\n[!] STALE CODE LOADED. Close the terminal, delete every __pycache__ folder, and re-run.\n")
        return

    weekly = data.load_df("player_weekly_stats")
    if weekly is None:
        print("No cached data. Run scripts/01_pull_data.py first.")
        return
    schedules = data.load_df("schedules")

    print("Loading games and players for the backtest...")
    pbp = data.get_pbp(config.SEASONS)
    players = data.get_players()
    team_season = team_features.build_team_season_features(pbp, schedules, weekly)

    print("Running walk-forward (this freezes the model before each season)...")
    res, yr, pooled = backtest.run_backtest(weekly, team_season, players, config.SCORING)
    if res.empty:
        print("Not enough history to backtest.")
        return

    res.to_csv(config.OUTPUT_DIR / "qb_backtest.csv", index=False)
    meta = {"subline": f"Walk-forward validation · full model · leak-free · generated {date.today().isoformat()}"}
    (config.OUTPUT_DIR / "qb_backtest.html").write_text(backtest.render_html(res, yr, pooled, meta), encoding="utf-8")

    print("\n  Year  QBs  ModelMAE  BaseMAE  ModelRho  BaseRho")
    for r in yr.itertuples():
        print(f"  {int(r.year)}   {int(r.n):>3}    {r.model_mae:>6.2f}   {r.base_mae:>6.2f}    "
              f"{r.model_rho:>5.2f}    {r.base_rho:>5.2f}")
    print(f"\n  POOLED ({len(res)} QB-seasons): model MAE {pooled['model_mae']:.2f} vs baseline "
          f"{pooled['base_mae']:.2f} | rank-corr {pooled['model_rho']:.2f} vs {pooled['base_rho']:.2f}")
    if pooled.get("top12_hitrate") == pooled.get("top12_hitrate"):
        print(f"  Preseason top-12 that actually finished top-12: {100*pooled['top12_hitrate']:.0f}%")
    print(f"\nSaved report -> {config.OUTPUT_DIR / 'qb_backtest.html'}")
    print(f"Saved data   -> {config.OUTPUT_DIR / 'qb_backtest.csv'}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback as _tb
        _p = config.OUTPUT_DIR / "current_map_debug.txt"
        with open(_p, "a", encoding="utf-8") as _f:
            _f.write("\n\n=== ERROR during backtest ===\n" + _tb.format_exc())
        print(f"\n[!] Errored. Traceback appended to {_p} — send me that file.")
        raise
