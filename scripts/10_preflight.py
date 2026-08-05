#!/usr/bin/env python3
"""Run this before you push. It answers one question: is what's on disk actually
the wired-up version, or did a file get missed on the way over?

This exists because the newest piece fails SILENTLY. The play-caller loader swallows
every error and returns {}, so a missing or misspelled data/playcallers.csv doesn't
crash anything -- the box just quietly reads "not tracked" for all 32 teams, which
looks like a modelling choice rather than a missing file. Section [4] guards the same
class of problem one layer down: the hand-maintained CSVs are the only inputs that
can't be re-pulled from nflverse, so an ignore rule that swallows them (a future
`data/` or `*.csv` line) would break the deployed site while everything still works
on your machine.

Static checks only -- no nflreadpy, no network, no parquet. It runs in a second on a
plain checkout, so there's no reason not to run it every time.

    python scripts/10_preflight.py

Exit code is 0 if it's safe to push, 1 if it isn't.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OK, BAD = [], []


def ck(name: str, passed: bool, info: str = "") -> bool:
    (OK if passed else BAD).append(name)
    print(f"  {'ok  ' if passed else 'MISS'}  {name}{'  -- ' + info if info else ''}")
    return passed


# Each file, and a string that only exists in the version you want. Checking for a
# marker rather than just existence is the point: an older copy of report.py is a
# file that exists, opens fine, and renders the previous panel.
EXPECT = {
    "src/qb_blend.py": [
        ("def playcallers(", "play-caller loader"),
        ("rush_att_pg", "rush-attempt volume signal"),
    ],
    "src/ratings.py": [
        ("from . import qb_blend", "imports the loader"),
        ("lw_gate", "either/or screen"),
        ("MCSHANAHAN", "the tree value it acts on"),
        ("exp_fpg", "points-space value"),
    ],
    "src/report.py": [
        ("function lwChecklist", "checklist renderer"),
        ("lwpaths", "the bracketed either/or box"),
        ("lwgate", "the verdict badge"),
    ],
    "src/adp.py": [("load_adp_history", "historical ADP reader")],
    "scripts/06_build_qb_model.py": [("adp_history.csv", "feeds history to the curve")],
    "scripts/08_factor_stability.py": [],
    "scripts/09_check_playcallers.py": [],
    "data/adp_history.csv": [],
    "data/playcallers.csv": [("mcshanahan", "the tree column is populated")],
    # NO TEXT MARKERS HERE ON PURPOSE. This used to grep .gitignore for the exact
    # lines "!data/playcallers.csv" and "!data/adp_history.csv", which is asking
    # the wrong question in the wrong place. The file un-ignores the whole folder
    # with one wildcard -- "data/*" then "!data/*.csv" -- so both files ARE
    # committed and neither literal string appears, and preflight was printing
    # two failures and "DO NOT PUSH YET" over a board that was fine to push.
    # Section [4] below already answers this properly by asking git itself, which
    # is the only thing whose opinion on what git ignores actually counts.
    ".gitignore": [],
}


def main() -> int:
    print(f"\nPreflight on {ROOT}\n")

    print("[1] The files, and whether they're the new versions")
    for rel, markers in EXPECT.items():
        p = ROOT / rel
        if not ck(f"{rel} is here", p.exists()):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for token, what in markers:
            ck(f"    ...and has {what}", token in text, f"looking for {token!r}")

    print("\n[2] The play-caller file actually loads")
    try:
        from src import qb_blend

        pcs = qb_blend.playcallers()
        rows_2026 = {k: v for k, v in pcs.items() if k[0] == 2026}
        ck("the loader returns rows, not an empty dict", bool(pcs), f"{len(pcs)} rows")
        ck("2026 covers all 32 teams", len(rows_2026) == 32, f"{len(rows_2026)} teams")
        sf = pcs.get((2026, "SF"))
        ck("a known team resolves", bool(sf), str(sf))
        mcs = sum(1 for v in rows_2026.values() if v["tree"] == "mcshanahan")
        share = 100 * mcs / len(rows_2026) if rows_2026 else 0
        # The article says McShanahan play-callers run 44% of offenses. Landing far
        # off that means the tree column drifted, not that the league changed.
        ck("the McShanahan share matches the article's 44%", 38 <= share <= 50,
           f"{mcs}/{len(rows_2026)} = {share:.1f}%")
    except Exception as e:                                        # noqa: BLE001
        ck("the loader imports and runs", False, f"{type(e).__name__}: {e}")

    print("\n[3] The full validator")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "09_check_playcallers.py")],
                       capture_output=True, text=True)
    ck("scripts/09_check_playcallers.py passes", r.returncode == 0,
       (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else "")

    print("\n[4] Git will actually carry the data files")
    # Today .gitignore only excludes data/raw and data/processed, so these four are
    # safe and the "!" lines below them are belt-and-braces. This check is here for
    # the day that changes: add `data/` or `*.csv` and the files stay on your disk,
    # the model keeps working locally, and the deployed site has never seen them.
    try:
        # Establish there IS a repo first. Outside one, check-ignore exits 128, and
        # "non-zero means not ignored" would have turned every check in this section
        # into a free pass -- a green light that means nothing.
        inside = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                                cwd=ROOT, capture_output=True, text=True)
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            print("  (not a git checkout -- skipping; this section is advisory)")
        else:
            for rel in ("data/playcallers.csv", "data/adp_history.csv", "data/adp.csv",
                        "data/win_totals.csv"):
                g = subprocess.run(["git", "check-ignore", "-q", rel],
                                   cwd=ROOT, capture_output=True)
                # 0 = ignored, 1 = not ignored, anything else = git itself failed.
                ck(f"{rel} is not ignored by git", g.returncode == 1,
                   "" if g.returncode == 1 else
                   "git would silently leave it out of the push" if g.returncode == 0
                   else f"git check-ignore exited {g.returncode}")
            st = subprocess.run(["git", "status", "--short"], cwd=ROOT,
                                capture_output=True, text=True)
            changed = [l for l in st.stdout.splitlines() if l.strip()]
            print(f"\n  {len(changed)} file(s) with uncommitted changes:")
            for line in changed[:40]:
                print(f"    {line}")
    except FileNotFoundError:
        print("  (git not on PATH -- skipping; this section is advisory)")

    print("\n" + "=" * 64)
    if BAD:
        print(f"  {len(OK)} ok, {len(BAD)} problem(s) -- DO NOT PUSH YET\n")
        for n in BAD:
            print(f"    - {n}")
        print("\n  Each line above names the file to re-copy. Re-run this after.")
        return 1
    print(f"  {len(OK)} checks passed -- safe to push")
    return 0


raise SystemExit(main())
