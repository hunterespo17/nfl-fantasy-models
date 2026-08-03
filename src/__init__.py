"""
NFL fantasy football modeling package.

Modules
-------
config    : all tunable settings (seasons, scoring, paths, league setup)
data      : download & cache nflverse data via nflreadpy
scoring   : turn raw box-score stats into fantasy points for any ruleset
features  : build leak-free features for weekly projection models
model     : baseline + gradient-boosting weekly point predictors
evaluate  : walk-forward backtesting and accuracy metrics
rankings  : season-long / draft rankings with value-over-replacement
"""

__all__ = [
    "config",
    "data",
    "scoring",
    "features",
    "model",
    "evaluate",
    "rankings",
]

# ---------------------------------------------------------------------------
# Windows-on-ARM / emulated-CPU fix
# ---------------------------------------------------------------------------
# `polars` (a dependency of nflreadpy) runs a CPU feature-flag check when it is
# imported. On an ARM machine running the Intel build of Python under emulation,
# that check misfires and raises: RuntimeError: unknown feature flag: 'sse3'.
# The check only exists to print a friendlier error; the emulator runs polars'
# code correctly. Setting this environment variable skips the check. It is set
# BEFORE polars is ever imported (this package is imported before nflreadpy),
# and it is harmless on every other platform.
import os as _os

_os.environ.setdefault("POLARS_SKIP_CPU_CHECK", "1")
