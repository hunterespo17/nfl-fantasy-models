"""
Step 0 -- Check your setup.

Run this first. It confirms Python and the required packages are installed,
shows where data will be cached, and does one tiny live download to prove the
connection to nflverse works.

    python scripts/00_check_setup.py
"""
import os
import pathlib
import sys

# polars (pulled in by nflreadpy) misfires its CPU feature check under x86-64
# emulation on ARM machines ("unknown feature flag: 'sse3'"). Skipping the
# check is safe -- the emulator runs the code fine. Must be set before the
# nflreadpy import below. Harmless on other platforms.
os.environ.setdefault("POLARS_SKIP_CPU_CHECK", "1")

# Make the project importable when running "python scripts/00_check_setup.py".
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


def main() -> None:
    print("=" * 64)
    print("NFL fantasy models -- setup check")
    print("=" * 64)

    print(f"Python: {sys.version.split()[0]}")
    if sys.version_info < (3, 10):
        print("  [!] Python 3.10+ recommended. Consider upgrading.")

    print("\nChecking required packages...")
    ok = True
    for pkg in ["pandas", "numpy", "sklearn", "matplotlib", "joblib"]:
        try:
            module = __import__(pkg)
            print(f"  [ok] {pkg:<12} {getattr(module, '__version__', '?')}")
        except ImportError:
            ok = False
            print(f"  [MISSING] {pkg} -- run: pip install -r requirements.txt")

    try:
        import nflreadpy
        print(f"  [ok] nflreadpy    {getattr(nflreadpy, '__version__', '?')}")
    except ImportError:
        ok = False
        print("  [MISSING] nflreadpy -- run: pip install -r requirements.txt")

    from src import config
    print(f"\nData will be cached in: {config.DATA_DIR}")
    print(f"Models will be saved in: {config.MODELS_DIR}")
    print(f"Seasons configured:      {config.SEASONS[0]}-{config.SEASONS[-1]}")

    if not ok:
        print("\nFix the missing packages above, then re-run this check.")
        return

    print("\nTrying one small live download (schedules for the current season)...")
    try:
        from src import data
        sched = data.get_schedules([config.CURRENT_SEASON], refresh=True)
        print(f"  [ok] Downloaded {len(sched):,} rows. nflverse connection works!")
    except Exception as exc:  # noqa: BLE001
        print(f"  [!] Download failed: {exc}")
        print("      Check your internet connection and try again.")
        return

    print("\nAll set. Next: python scripts/01_pull_data.py")


if __name__ == "__main__":
    main()
