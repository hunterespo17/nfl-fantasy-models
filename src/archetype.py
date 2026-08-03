"""
QB archetype buckets -- a discrete, interpretable label for "what kind of QB."

A QB is bucketed by his RUSHING-yards fantasy value and PASSING fantasy value
(both regressed for TD variance), each expressed as a percentile against the
last five seasons of QB play. The thresholds are deliberately exclusive so
"Konami" stays limited to genuinely game-breaking dual-threats.

  Konami (100)        -- rushing top 20% AND passing top 30% (the cheat code)
  Rushing QB (80)     -- rushing top 20%, passing not elite
  Dual-Threat (70)    -- both above the pack (>= ~50th pct)
  Pocket Passer (60)  -- passing-driven, little rushing
  Bridge/Rookie (48)  -- under 10 career games
  Game Manager (42)   -- low value both ways
"""
from __future__ import annotations

import math

import pandas as pd

ARCHETYPE_UPSIDE = {
    "Konami": 100, "Rushing QB": 80, "Dual-Threat": 70,
    "Pocket Passer": 60, "Bridge/Rookie": 48, "Game Manager": 42,
}
BUCKETS = list(ARCHETYPE_UPSIDE)

# Locked defaults (20% rush / 30% pass) -> exclusive Konami.
RUSH_CUT = 0.80
PASS_CUT = 0.70


def bucket(rush_pct: float, pass_pct: float, career_games: float,
           rush_cut: float = RUSH_CUT, pass_cut: float = PASS_CUT) -> str:
    """Assign a bucket from rushing/passing percentiles (0-1) and career games."""
    if career_games is None or (isinstance(career_games, float) and math.isnan(career_games)) or career_games < 10:
        return "Bridge/Rookie"
    rp = 0.5 if rush_pct is None or (isinstance(rush_pct, float) and math.isnan(rush_pct)) else rush_pct
    pp = 0.5 if pass_pct is None or (isinstance(pass_pct, float) and math.isnan(pass_pct)) else pass_pct
    if rp >= rush_cut and pp >= pass_cut:
        return "Konami"
    if rp >= rush_cut:
        return "Rushing QB"
    if rp >= 0.50 and pp >= 0.50:
        return "Dual-Threat"
    if pp >= 0.60:
        return "Pocket Passer"
    return "Game Manager"


def upside_index(buckets: pd.Series) -> pd.Series:
    return buckets.map(ARCHETYPE_UPSIDE).fillna(50).rename("Archetype")
