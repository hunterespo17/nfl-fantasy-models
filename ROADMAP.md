# Project Roadmap & Concepts

This document is the *plan* and the *why*. The README tells you how to run
things; this tells you what's happening under the hood, the ideas that make
fantasy models actually work, and where to take the project next.

---

## The big picture

Almost every fantasy prediction task is built on one core engine: **predict a
player's fantasy points for an upcoming game.** Weekly lineup decisions use it
directly. Season/draft rankings are just those weekly predictions aggregated
across a season and compared across positions. Even DFS and betting props (not
in this v1, but easy to add later) sit on top of the same engine.

So we build that engine well, and everything else follows.

The pipeline has five stages, each a file you can understand on its own:

```
   raw data          fantasy pts        features           model            outputs
  (nflverse)   →    (your scoring)  →  (leak-free)   →  (baseline+GBR)  →  projections
   data.py          scoring.py         features.py       model.py          rankings.py
                                                          evaluate.py
```

---

## The five stages, explained

### 1. Data (`src/data.py`)
We pull free nflverse data with `nflreadpy`: weekly player box scores, game
schedules, snap counts, and expected-fantasy-points ("opportunity") data.
Everything is cached locally after the first download, so you only wait once.

**Concept — why nflverse:** it's the community-standard, well-maintained,
completely free source for NFL data. No API keys, no scraping, no terms-of-service
worries. (Its Python package `nfl_data_py` was **deprecated** in 2025 in favor of
`nflreadpy`, which is what we use.)

### 2. Scoring (`src/scoring.py`)
We convert raw stats (yards, TDs, receptions…) into fantasy points using *your*
league's rules, defined in `config.py`. Doing this ourselves — rather than using
a pre-computed column — means the number the model learns to predict always
matches your league (half-PPR, custom TE premium, whatever you run).

### 3. Features (`src/features.py`) — the part that matters most
A "feature" is an input the model learns from. Our features describe what we knew
**before** each game: recent scoring form (last 3/5/10 games), recent usage
(targets, carries, snap share), the opponent defense's tendency to give up points
to that position, home/away, and games played to date.

**Concept — data leakage (read this twice).** The single biggest mistake in
sports modeling is letting information from the game you're predicting sneak into
the inputs. If you accidentally include this week's targets when predicting this
week's points, your model looks brilliant in testing and then fails for real,
because on Sunday morning you *don't have* this week's stats yet. Every feature in
this project is **lagged** — shifted so the current game is excluded — which is
why a player's very first career game correctly has blank recent-form features.
The self-test explicitly checks this.

### 4. Model + baseline (`src/model.py`)
Two predictors, always compared:

- **Baseline:** "predict roughly what they've averaged lately." Dumb on purpose.
  In fantasy, recent-form averages are genuinely hard to beat, so this is the bar.
- **Gradient boosting** (scikit-learn's `HistGradientBoostingRegressor`): a strong
  tabular model that handles missing values natively and installs everywhere.

**Concept — always beat a baseline.** A model's raw accuracy is meaningless
without a reference point. "MAE of 4.5 fantasy points" only matters relative to
what simple guessing achieves. If the fancy model can't beat recent-form, it isn't
earning its complexity.

### 5. Evaluation & rankings (`src/evaluate.py`, `src/rankings.py`)
- **Backtesting (`evaluate.py`)** uses *walk-forward* validation: to score a
  season, we train only on earlier seasons — never the future. A random
  train/test split would leak future knowledge and lie to you.
- **Rankings (`rankings.py`)** turn projections into a draft board using two
  ideas:
  - **Value Over Replacement (VOR):** a player is worth what he gives you *above
    the freely-available replacement* at his position. This is why elite RBs
    outrank higher-scoring QBs — QB is deep, RB is scarce. VOR puts every
    position on one comparable scale.
  - **Tiers:** group similar-value players so you can see the "cliffs" on draft
    day and plan around them.

---

## Where we are

**v1 is complete and tested end-to-end.** You can pull data, build features,
train a model that beats the baseline, backtest it, and generate a tiered draft
board. That's a real, working foundation.

The v1 draft projection (in `scripts/05`) is intentionally simple: last season's
points-per-game. It's honest and runnable today, and it's the first thing to
upgrade (see below).

---

## What to build next (roughly in priority order)

Each item is a self-contained improvement. Do them in any order, but this
sequence gives the most accuracy-per-effort.

**A. Smarter projections (biggest bang for the buck)**
- Regress to the mean: a 20-ppg season on 6 games shouldn't project as 20.
  Blend a player's average with the positional average, weighted by sample size.
- Blend with the market: `nflreadpy.load_ff_rankings()` gives FantasyPros expert
  consensus. Averaging your model with the market is a well-known accuracy win.
- Project rest-of-season by running the trained weekly model forward game by game
  and summing, instead of using last year's ppg.

**B. Better features**
- Vegas lines: a team's implied point total is one of the strongest single
  predictors of fantasy output. (Add a betting-odds source.)
- Target share, air yards, and red-zone usage — richer "opportunity" signals
  than raw targets. Much of this is in `load_ff_opportunity()` and play-by-play.
- Injury / practice-report status via `load_injuries()`.
- Weather for outdoor games; offensive-line quality; team pace.

**C. Better modeling**
- Train separate models per position (a QB and a WR score in very different ways).
- Predict a *range*, not just a number: quantile regression gives each player a
  floor and ceiling — invaluable for start/sit and DFS.
- Tune hyperparameters and add within-season walk-forward backtesting (predict
  week by week, not just season by season).
- Try XGBoost or LightGBM once you're comfortable (often a small accuracy bump).

**D. New applications (the same engine, new outputs)**
- DFS lineup optimizer (salary cap + projections + ownership).
- Player-prop edges (compare projections to sportsbook lines).
- A weekly automation that refreshes data and emails you start/sit advice.

**E. Coverage**
- Add kickers and team defense/special teams (different data, different scoring).
- Rookie projections (draft capital, college production, athletic testing).

---

## Helpful references

- nflverse data & guides: https://nflverse.nflverse.com/
- `nflreadpy` docs (all the `load_*` functions): https://nflreadpy.nflverse.com/
- scikit-learn user guide (the modeling library): https://scikit-learn.org/stable/
- A gentle intro to gradient boosting: search "HistGradientBoostingRegressor
  scikit-learn" — the official docs page is beginner-readable.

---

## A note on expectations

NFL fantasy scoring is genuinely noisy — even the best public models land in the
~4–6 points mean-absolute-error range for weekly projections, because a tipped
pass or a goal-line vulture can swing a game. The goal isn't to predict perfectly;
it's to be **a little better than the field, consistently.** Small, honest edges
— applied across a whole season of lineup and draft decisions — are how you win.
