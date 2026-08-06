"""
Step 12 -- Put every position on one page.

    py scripts\\12_build_site.py

The position models each build on their own schedule, and each one parks its
finished board in outputs\\boards\\ when it runs. This script reads whatever is
sitting in that folder and writes ONE page, outputs\\index.html, with a tab per
position, the Big Board, the VORP Rankings, and a single How-it-works tab.

The Big Board is the draft order and the VORP Rankings are the value board it is
built out of. The difference between them is one number per position, fitted
here at build time by src\\draftboard.py, and this script prints that fit so a
bad one is visible without opening the page.

That split is the whole point. Rebuild only the running backs and the RB tab
refreshes while the quarterbacks stay exactly as they were -- and a running-back
run that blows up cannot take the quarterbacks off the site, because it never
touched their saved board.

Run this AFTER the position builds:

    py scripts\\06_build_qb_model.py
    py scripts\\11_build_rb_model.py
    py scripts\\12_build_site.py

Then open outputs\\index.html. The single-position pages (qb_model.html,
rb_model.html) are still written and still work; they are just the same board
on its own, which is handy when you only rebuilt one thing.
"""
import os
import pathlib
import shutil
import sys

# --- Stale-bytecode guard (important when the project lives in OneDrive) ------
# Same guard as the other scripts: OneDrive can restore an OLD .pyc whose
# timestamp makes Python skip recompiling your updated source, so edits silently
# don't take effect. Refuse to write .pyc files, then wipe the caches BEFORE
# importing anything from src\.
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

from src import config, report  # noqa: E402

# Draft-board order: the positions you argue about first, first. A position not
# listed here still gets a tab, it just lands on the end.
TAB_ORDER = ["QB", "RB", "WR", "TE", "K", "DST"]


def main() -> int:
    folder = config.OUTPUT_DIR / "boards"
    out, boards = report.build_site(folder, config.OUTPUT_DIR / "index.html")

    if out is None:
        print("No boards to combine.")
        print(f"  Looked in: {folder}")
        print("  Build at least one position first, then run this again:")
        print("    py scripts\\06_build_qb_model.py")
        print("    py scripts\\11_build_rb_model.py")
        return 1

    print("Built one page from these boards:")
    for result, meta in boards:
        n = len(result.get("payload", []))
        print(f"  {meta.get('pos', '??'):<4} {n:>4} players")
    print(f"\nSaved to: {out}")
    print(f"  ({out.stat().st_size:,} bytes)")
    print("Open that file in your browser. Tabs across the top: one per")
    print("position, then Big Board, then VORP Rankings, then How it works.")

    # The positional premium, echoed here because it is the one thing in the
    # build that can quietly go wrong without the page looking broken.
    try:
        from src import draftboard, report as _r
        by_pos = {}
        for result, meta in boards:
            p, b = _r._board(result, meta)
            by_pos[p] = b
        order = sorted(by_pos, key=lambda p: TAB_ORDER.index(p)
                       if p in TAB_ORDER else 99)
        print("\n" + draftboard.describe(draftboard.premiums(by_pos, order)))
    except Exception as exc:                      # never fail a build over a print
        print(f"\n  (couldn't summarise the draft-board fit: {exc})")

    stale = [meta.get("pos") for _, meta in boards
             if meta.get("season") and meta["season"] != config.UPCOMING_SEASON]
    if stale:
        print(f"\n  Heads up: {', '.join(str(s) for s in stale)} was built for a "
              f"different season than {config.UPCOMING_SEASON}. Rebuild that "
              f"position so the page is all one year.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
