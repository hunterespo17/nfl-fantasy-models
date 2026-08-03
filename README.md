# NFL Fantasy Football Prediction Models

A clean, beginner-friendly Python project for building **NFL fantasy football**
prediction models. It does two things:

1. **Weekly player projections** — predict how many fantasy points a player will
   score in an upcoming week.
2. **Season / draft rankings** — turn those projections into a ranked, tiered
   draft board with value-over-replacement (VOR).

It runs entirely on **free** public data from [nflverse](https://nflverse.nflverse.com/)
(no API keys, no scraping, no paid services) via the officially maintained
[`nflreadpy`](https://nflreadpy.nflverse.com/) package.

> New to this? Read `ROADMAP.md` next — it explains the *why* behind each step
> and the concepts (in plain English) that make fantasy models work.

---

## What you need first

- **Python 3.10 or newer.** Check with `python --version` (on Windows you may
  need to type `py --version`). If you don't have it, install from
  [python.org](https://www.python.org/downloads/).
- About 5 minutes and an internet connection for the first data download.

No prior machine-learning experience required.

---

## Quick start

Open a terminal **in this project folder**, then run these one at a time.

```bash
# 1. (Recommended) create an isolated environment so this project's packages
#    don't clash with anything else on your computer.
python -m venv .venv
# Activate it:
#   Windows (PowerShell):   .venv\Scripts\Activate.ps1
#   Windows (cmd):          .venv\Scripts\activate.bat
#   macOS / Linux:          source .venv/bin/activate

# 2. Install the required packages.
pip install -r requirements.txt

# 3. Check everything is working (also does one tiny live download).
python scripts/00_check_setup.py

# 4. Run the pipeline, in order:
python scripts/01_pull_data.py        # download & cache the data
python scripts/02_build_features.py   # engineer leak-free features
python scripts/03_train_weekly.py     # train the weekly projection model
python scripts/04_backtest.py         # measure accuracy vs a baseline
python scripts/05_rank_players.py     # build a draft board
```

Outputs (a draft board CSV, backtest predictions, and a calibration chart)
land in the `outputs/` folder.

**Want to confirm the code works before downloading anything?**
Run `python scripts/run_selftest.py` — it exercises the whole pipeline on
fake data in a couple of seconds.

---

## Project structure

```
nfl-fantasy-models/
├── README.md            ← you are here
├── ROADMAP.md           ← the plan + concepts explained
├── requirements.txt     ← the packages to install
│
├── src/                 ← the reusable code ("library")
│   ├── config.py        ← ALL your settings: seasons, scoring, league setup
│   ├── data.py          ← download & cache nflverse data
│   ├── scoring.py       ← box-score stats  →  fantasy points (your rules)
│   ├── features.py      ← build leak-free features (the careful part)
│   ├── model.py         ← baseline + gradient-boosting predictors
│   ├── evaluate.py      ← walk-forward backtesting & accuracy metrics
│   └── rankings.py      ← season/draft rankings with VOR + tiers
│
├── scripts/             ← the things you actually RUN, numbered in order
│   ├── 00_check_setup.py
│   ├── 01_pull_data.py
│   ├── 02_build_features.py
│   ├── 03_train_weekly.py
│   ├── 04_backtest.py
│   ├── 05_rank_players.py
│   └── run_selftest.py  ← verify the pipeline on synthetic data
│
├── data/                ← cached downloads & features   (auto-created, git-ignored)
├── models/              ← saved trained models          (auto-created, git-ignored)
└── outputs/             ← rankings, predictions, charts  (auto-created, git-ignored)
```

The idea: **`src/` is the toolbox, `scripts/` are the buttons you press.** Read a
script top-to-bottom and it tells you exactly which tools it uses.

---

## Make it match YOUR league

Open `src/config.py` and edit the `SCORING` dictionary. The default is full PPR
(1 point per reception). The one line you're most likely to change:

```python
"reception": 1.0,   # 1.0 = PPR   |   0.5 = half-PPR   |   0.0 = standard
```

You can change every scoring value there (passing TD points, yardage rates,
etc.), plus which `SEASONS` to use and your league size for draft rankings
(`LEAGUE`). Re-run from `scripts/02_build_features.py` onward after changes.

---

## Notes for Windows on ARM (your machine)

This project deliberately uses only mainstream packages (pandas, numpy,
scikit-learn, matplotlib) and **avoids** XGBoost/LightGBM, which can be painful
to install on Windows/ARM. Everything here has prebuilt wheels for your platform.

If `pip install -r requirements.txt` ever fails on a single package, upgrade pip
first (`python -m pip install --upgrade pip`) and try again. If `nflreadpy`'s
dependency `pyarrow` is the sticking point, the project automatically falls back
to caching data as CSV, so you can keep going.

---

## Troubleshooting

- **`ModuleNotFoundError: No module named 'src'`** — run scripts from the
  project's top folder, e.g. `python scripts/01_pull_data.py` (not from inside
  `scripts/`).
- **`nflreadpy is not installed`** — you skipped `pip install -r requirements.txt`
  (or your virtual environment isn't activated).
- **A download failed** — re-run the script; nflverse data is cached, so it
  resumes. Add `--refresh` to `01_pull_data.py` to force fresh downloads.
- **Everything is slow the first time** — that's the initial download and
  feature build. Later runs use the local cache and are fast.

---

## Data & credit

All data comes from the **nflverse** project and is loaded with **nflreadpy**.
Please star/support their work: https://github.com/nflverse. (The older
`nfl_data_py` package is **deprecated** — this project uses its maintained
successor, `nflreadpy`.)
