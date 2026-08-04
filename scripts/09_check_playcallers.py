"""Sanity-check data/playcallers.csv before it reaches the board.

Why this exists: the loader in src/qb_blend.py swallows errors and returns {} on
anything it can't parse -- which is the right behaviour for a live site (a broken
hand-typed file should never take the page down), but it also means a typo turns
the play-caller check silently OFF instead of loudly failing. That is exactly the
kind of mistake you only notice in November.

So: run this after every edit. It takes a second and it is the only thing standing
between "TB" fat-fingered as "TP" and a checklist box that quietly reads
"not tracked yet" all season.

    python scripts/09_check_playcallers.py

Exits non-zero if anything is wrong, so it can go in a GitHub Action later.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config  # noqa: E402

VALID_TREES = {"mcshanahan", "other"}
VALID_ROLES = {"HC", "OC"}
COLUMNS = ["season", "team", "playcaller", "role", "tree"]


def main() -> int:
    path = config.DATA_DIR / "playcallers.csv"
    if not path.exists():
        print(f"MISSING  {path}")
        return 1

    pc = pd.read_csv(path)
    problems: list[str] = []

    missing_cols = [c for c in COLUMNS if c not in pc.columns]
    if missing_cols:
        print(f"FAIL  missing columns: {', '.join(missing_cols)}")
        return 1

    # The team vocabulary is not invented here -- it is whatever win_totals.csv
    # already uses, because both files get joined to the same `team` column in
    # entering_profiles(). A code that works in one must work in the other.
    wt = pd.read_csv(config.DATA_DIR / "win_totals.csv")

    for season, grp in pc.groupby("season"):
        season = int(season)
        want = set(wt[wt["season"] == season]["team"])
        have = set(grp["team"])
        if not want:
            problems.append(f"{season}: no win_totals rows to check team codes against")
            continue
        if have - want:
            problems.append(f"{season}: unknown team codes {sorted(have - want)}")
        if want - have:
            problems.append(f"{season}: no play-caller for {sorted(want - have)}")
        dupes = grp["team"][grp["team"].duplicated()].tolist()
        if dupes:
            problems.append(f"{season}: duplicated teams {sorted(set(dupes))}")

    bad_tree = sorted(set(pc["tree"].dropna()) - VALID_TREES)
    if bad_tree:
        problems.append(f"tree must be one of {sorted(VALID_TREES)}; found {bad_tree}")
    bad_role = sorted(set(pc["role"].dropna()) - VALID_ROLES)
    if bad_role:
        problems.append(f"role must be one of {sorted(VALID_ROLES)}; found {bad_role}")
    blank = pc[pc["playcaller"].isna() | (pc["playcaller"].astype(str).str.strip() == "")]
    if len(blank):
        problems.append(f"{len(blank)} row(s) with a blank playcaller")

    for problem in problems:
        print(f"FAIL  {problem}")
    if problems:
        return 1

    print(f"OK    {len(pc)} rows, seasons {pc['season'].min()}-{pc['season'].max()}")
    for season, grp in pc.groupby("season"):
        n = int((grp["tree"] == "mcshanahan").sum())
        print(f"      {int(season)}: {n}/{len(grp)} McShanahan-tree ({n / len(grp):.0%} of offenses)")
    # Year-over-year churn, which is the number that justifies the whole
    # maintenance cadence: if this is ever much above ~8, re-read the plan.
    seasons = sorted(pc["season"].unique())
    for a, b in zip(seasons, seasons[1:]):
        prev = pc[pc["season"] == a].set_index("team")["playcaller"]
        cur = pc[pc["season"] == b].set_index("team")["playcaller"]
        both = prev.index.intersection(cur.index)
        changed = [t for t in both if prev[t] != cur[t]]
        print(f"      {int(a)} -> {int(b)}: {len(changed)} changed "
              f"({', '.join(sorted(changed)) if changed else 'none'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
