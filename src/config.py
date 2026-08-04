"""
Central configuration for the NFL fantasy modeling project.

Everything you might reasonably want to change lives here, so you don't have
to dig through the code. Read the comments top-to-bottom to understand the
knobs you can turn.
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------
# PROJECT_ROOT is the top-level project folder (the one that contains src/,
# scripts/, data/, etc.). We build every other path relative to it so the
# project works no matter where you cloned it.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = PROJECT_ROOT / "data"            # cached data (git-ignored)
RAW_DIR = DATA_DIR / "raw"                  # untouched pulls from nflverse
PROCESSED_DIR = DATA_DIR / "processed"      # engineered features, etc.
MODELS_DIR = PROJECT_ROOT / "models"        # saved trained models (git-ignored)
OUTPUT_DIR = PROJECT_ROOT / "outputs"       # projections, rankings, charts

# Create the folders on import so scripts never fail on a missing directory.
for _d in (DATA_DIR, RAW_DIR, PROCESSED_DIR, MODELS_DIR, OUTPUT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Which seasons to work with
# ---------------------------------------------------------------------------
# nflverse has data back to 1999, but the NFL changes over time (rules, pace,
# passing rates). A recent window keeps the model relevant. Widen or narrow
# this as you like; more seasons = more training data but older patterns.
SEASONS = list(range(2018, 2026))   # 2018, 2019, ... 2025 (completed seasons with game data)
CURRENT_SEASON = 2025               # most recent COMPLETED season (historical anchor)
UPCOMING_SEASON = 2026              # the season we project; teams/starters come from
                                    # current depth charts, production from games through 2025

# ---------------------------------------------------------------------------
# Positions we model
# ---------------------------------------------------------------------------
# The offensive skill positions that score the way our scoring rules assume.
# (Kickers and team defenses score differently and use other data; they're a
# later enhancement, not part of v1.)
FANTASY_POSITIONS = ["QB", "RB", "WR", "TE"]

# ---------------------------------------------------------------------------
# Scoring settings  --  change these to match YOUR league
# ---------------------------------------------------------------------------
# Set to HALF-PPR (0.5 per reception) to match Hunter's league.
#   - For FULL PPR set "reception": 1.0
#   - For STANDARD (non-PPR) set "reception": 0.0
# See src/scoring.py for exactly how each weight is applied.
#
# This setting does more work than it looks like it does. Every fantasy point in
# the project is computed through src/scoring.py from these weights, so the RB
# expectation curve, the backtest, and replacement level all move with it. It does
# NOT change the QB board (quarterbacks don't catch passes), so the published QB
# rankings are unaffected -- only the "Half PPR" label on them changes.
SCORING = {
    "passing_yards": 0.04,    # 1 point per 25 passing yards
    "passing_td": 4.0,
    "interception": -2.0,
    "passing_2pt": 2.0,
    "rushing_yards": 0.1,     # 1 point per 10 rushing yards
    "rushing_td": 6.0,
    "rushing_2pt": 2.0,
    "reception": 0.5,         # <-- 1.0 PPR | 0.5 half-PPR | 0.0 standard
    "receiving_yards": 0.1,   # 1 point per 10 receiving yards
    "receiving_td": 6.0,
    "receiving_2pt": 2.0,
    "fumble_lost": -2.0,
}

# ---------------------------------------------------------------------------
# Feature settings
# ---------------------------------------------------------------------------
# Rolling windows (measured in games) used to summarize a player's recent
# form. e.g. 3 = "last 3 games", 10 = "last 10 games".
ROLLING_WINDOWS = [3, 5, 10]

# Only regular-season games are used for modeling by default. Set to
# ("REG", "POST") to include playoffs.
SEASON_TYPES = ("REG",)

# ---------------------------------------------------------------------------
# Draft-ranking league settings (used by src/rankings.py)
# ---------------------------------------------------------------------------
# Used to compute "replacement level" for value-over-replacement (VOR).
# These are the number of each position drafted as starters across the league.
# Defaults assume a fairly standard 12-team, 1QB league.
LEAGUE = {
    "teams": 12,
    "starters": {"QB": 1, "RB": 2, "WR": 2, "TE": 1},  # per team (FLEX handled below)
    "flex_spots": 1,        # 1 FLEX (RB/WR/TE) per team
    "games_per_season": 17,
}

# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
RANDOM_SEED = 42
