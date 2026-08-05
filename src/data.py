"""
Data access: download NFL data from nflverse and cache it locally.

We use `nflreadpy`, the officially maintained nflverse Python package. (Its
predecessor `nfl_data_py` is deprecated as of 2025 -- do not use it.)

Design choices that make this beginner-friendly and robust:

* nflreadpy is imported *lazily* (inside functions), so every other module in
  this project works even if nflreadpy isn't installed. Only the actual data
  pull needs it.

* Each dataset is cached to `data/raw/` after the first download, so re-runs
  are instant and you're kind to nflverse's servers. Pass refresh=True to
  force a fresh download.

* nflreadpy returns **polars** DataFrames; we convert everything to **pandas**
  immediately, because pandas is what most tutorials and Stack Overflow
  answers use. You never have to think about polars.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import config


# ---------------------------------------------------------------------------
# nflreadpy access
# ---------------------------------------------------------------------------
def _lazy_nflreadpy():
    """Import nflreadpy on demand, with a friendly message if it's missing."""
    try:
        import nflreadpy  # noqa: WPS433 (intentional local import)

        return nflreadpy
    except ImportError as exc:  # pragma: no cover - depends on user's install
        raise ImportError(
            "nflreadpy is not installed. Install the project requirements "
            "first:\n\n    pip install -r requirements.txt\n\n"
            "(nflreadpy is the maintained nflverse package; the old "
            "nfl_data_py is deprecated.)"
        ) from exc


def _to_pandas(obj) -> pd.DataFrame:
    """Convert whatever nflreadpy returns (usually a polars DF) to pandas."""
    if isinstance(obj, pd.DataFrame):
        return obj
    to_pandas = getattr(obj, "to_pandas", None)
    if callable(to_pandas):
        return obj.to_pandas()
    return pd.DataFrame(obj)


def _call_loader(fn, seasons):
    """
    Call an nflreadpy load_* function, tolerating small signature differences
    between versions. Tries seasons= keyword, then positional, then no-arg.
    """
    for attempt in ("kw", "pos", "noarg"):
        try:
            if attempt == "kw":
                return fn(seasons=seasons)
            if attempt == "pos":
                return fn(seasons)
            return fn()
        except TypeError:
            continue  # signature mismatch -> try the next calling style
    return fn()  # last resort


def _filter_seasons(df: pd.DataFrame, seasons) -> pd.DataFrame:
    """Keep only requested seasons if a 'season' column is present."""
    if "season" in df.columns and seasons is not None:
        return df[df["season"].isin(list(seasons))].reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Local cache helpers
# ---------------------------------------------------------------------------
def save_df(df: pd.DataFrame, name: str, folder: Path = config.RAW_DIR) -> Path:
    """Save a DataFrame to the cache. Prefers parquet, falls back to CSV."""
    folder.mkdir(parents=True, exist_ok=True)
    parquet_path = folder / f"{name}.parquet"
    try:
        df.to_parquet(parquet_path, index=False)
        return parquet_path
    except Exception:  # noqa: BLE001 - parquet engine may be unavailable
        csv_path = folder / f"{name}.csv"
        df.to_csv(csv_path, index=False)
        return csv_path


def load_df(name: str, folder: Path = config.RAW_DIR) -> pd.DataFrame | None:
    """Load a cached DataFrame if it exists (parquet preferred), else None."""
    parquet_path = folder / f"{name}.parquet"
    csv_path = folder / f"{name}.csv"
    if parquet_path.exists():
        return pd.read_parquet(parquet_path)
    if csv_path.exists():
        return pd.read_csv(csv_path)
    return None


def _cached_pull(name: str, loader_fn, seasons, refresh: bool) -> pd.DataFrame:
    """Return cached data if present, otherwise pull, cache, and return it."""
    if not refresh:
        cached = load_df(name)
        if cached is not None:
            return cached
    nfl = _lazy_nflreadpy()
    raw = _to_pandas(_call_loader(loader_fn, seasons))
    raw = _filter_seasons(raw, seasons)
    save_df(raw, name)
    return raw


# ---------------------------------------------------------------------------
# Public dataset getters
# ---------------------------------------------------------------------------
def get_player_weekly_stats(seasons=None, refresh: bool = False) -> pd.DataFrame:
    """Weekly player box-score stats -- the backbone of fantasy modeling."""
    seasons = seasons or config.SEASONS
    return _cached_pull(
        "player_weekly_stats",
        lambda seasons: _lazy_nflreadpy().load_player_stats(seasons=seasons),
        seasons,
        refresh,
    )


def get_schedules(seasons=None, refresh: bool = False) -> pd.DataFrame:
    """Game schedules & results (opponent, home/away, kickoff, scores)."""
    seasons = seasons or config.SEASONS
    return _cached_pull(
        "schedules",
        lambda seasons: _lazy_nflreadpy().load_schedules(seasons=seasons),
        seasons,
        refresh,
    )


def get_snap_counts(seasons=None, refresh: bool = False) -> pd.DataFrame:
    """Offensive snap counts & snap share -- a strong usage signal."""
    seasons = seasons or config.SEASONS
    return _cached_pull(
        "snap_counts",
        lambda seasons: _lazy_nflreadpy().load_snap_counts(seasons=seasons),
        seasons,
        refresh,
    )


# Play-by-play has ~380 columns; we only need a handful for team tendencies.
# Keeping just these keeps the cache small and memory use low.
_PBP_COLUMNS = [
    "season", "week", "posteam", "defteam", "play_type",
    "pass", "rush", "sack", "xpass", "pass_oe", "epa", "down", "wp",
]


def get_pbp(seasons=None, refresh: bool = False) -> pd.DataFrame:
    """
    Play-by-play, slimmed to the columns needed for team tendencies.

    Pulled one season at a time (each season is large) and trimmed immediately,
    so peak memory stays modest even on a laptop.
    """
    seasons = seasons or config.SEASONS
    if not refresh:
        cached = load_df("pbp_slim")
        if cached is not None:
            return cached

    nfl = _lazy_nflreadpy()
    frames = []
    for year in seasons:
        raw = _to_pandas(_call_loader(nfl.load_pbp, [year]))
        keep = [c for c in _PBP_COLUMNS if c in raw.columns]
        frames.append(raw[keep].copy())
        print(f"  pbp {year}: {len(raw):,} plays -> kept {len(keep)} cols")
        del raw
    slim = pd.concat(frames, ignore_index=True)
    save_df(slim, "pbp_slim")
    return slim


def get_ff_opportunity(seasons=None, refresh: bool = False) -> pd.DataFrame | None:
    """
    Expected fantasy points ('opportunity') data -- optional but very useful.

    This dataset occasionally changes shape between versions, so we treat it
    as optional: if it can't be loaded, we return None and the rest of the
    pipeline carries on without it.
    """
    seasons = seasons or config.SEASONS
    try:
        return _cached_pull(
            "ff_opportunity",
            lambda seasons: _lazy_nflreadpy().load_ff_opportunity(seasons=seasons),
            seasons,
            refresh,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] Could not load ff_opportunity ({exc}). Skipping it.")
        return None


def get_rosters_weekly(seasons=None, refresh: bool = False) -> pd.DataFrame | None:
    """Weekly rosters (position, team, status). Optional helper dataset."""
    seasons = seasons or config.SEASONS
    try:
        return _cached_pull(
            "rosters_weekly",
            lambda seasons: _lazy_nflreadpy().load_rosters_weekly(seasons=seasons),
            seasons,
            refresh,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] Could not load rosters_weekly ({exc}). Skipping it.")
        return None


def get_players(refresh: bool = False) -> pd.DataFrame | None:
    """Player bio table (birth date, position, etc.) -- used for age."""
    try:
        if not refresh:
            cached = load_df("players")
            if cached is not None:
                return cached
        nfl = _lazy_nflreadpy()
        players = _to_pandas(nfl.load_players())
        save_df(players, "players")
        return players
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] Could not load players ({exc}). Age features will be skipped.")
        return None


def get_depth_charts(seasons=None, refresh: bool = False) -> pd.DataFrame | None:
    """
    Depth charts (current team + starter/rank). nflverse refreshes these daily,
    so the upcoming season reflects this offseason's moves. From 2025 on, rows
    carry an update timestamp instead of a week.
    """
    seasons = seasons or [config.UPCOMING_SEASON]
    try:
        if not refresh:
            cached = load_df("depth_charts")
            if cached is not None:
                return cached
        nfl = _lazy_nflreadpy()
        dc = _to_pandas(_call_loader(nfl.load_depth_charts, seasons))
        dc = _filter_seasons(dc, seasons)
        save_df(dc, "depth_charts")
        return dc
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] Could not load depth charts ({exc}).")
        return None


# Entering-season depth-chart history, kept under its OWN cache name.
#
# get_depth_charts() above stores whatever seasons it last pulled under the
# single name "depth_charts". The RB pipeline asks it for the upcoming season
# first, so anything that later asked it for history would just get 2026 back.
# This function has a separate cache file and a separate shape, which keeps the
# two from stepping on each other.
_DEPTH_HIST_NAME = "rb_depth_by_season"
# Running backs only. Fullbacks were in here and it was quietly wrong: the depth
# file numbers each position group on its own, so every team's FB1 arrived
# looking like a starting running back. 96 of 458 "starters" in the history were
# fullbacks -- backs like Patrick Ricard, who scores about 2 points a game.
_BACKFIELD_POS = {"RB", "HB"}


def _coalesce(df: pd.DataFrame, *names) -> pd.Series | None:
    """First non-null value across whichever of these columns exist."""
    out = None
    for name in names:
        if name not in df.columns:
            continue
        col = df[name]
        out = col if out is None else out.where(out.notna(), col)
    return out


def _normalize_depth(dc: pd.DataFrame) -> pd.DataFrame | None:
    """
    Fold both depth-chart layouts into one table and keep only the snapshot
    taken BEFORE the season started.

    nflverse changed the file in 2025. Through 2024 a row is a week
    (`club_code`, `week`, `depth_team`); from 2025 it is a dated snapshot
    (`team`, `dt`, `pos_rank`). Mixing the two in one frame leaves both sets of
    columns present with holes, so every field here is coalesced rather than
    picked.

    Returns: season, team, gsis_id, position, depth.
    """
    if dc is None or dc.empty:
        return None
    d = dc.copy()

    team = _coalesce(d, "team", "club_code")
    pos = _coalesce(d, "position", "pos_abb")
    depth = _coalesce(d, "depth", "depth_team", "pos_rank")
    pid = _coalesce(d, "gsis_id", "player_id")
    if team is None or pos is None or depth is None or pid is None:
        return None

    stamp = pd.to_datetime(d["dt"], errors="coerce") if "dt" in d.columns else None
    season = _coalesce(d, "season")
    if season is not None:
        season = pd.to_numeric(season, errors="coerce")
    if stamp is not None:
        # A depth chart dated January belongs to the season that started the
        # previous August, so the season only rolls over in the spring.
        from_stamp = stamp.dt.year - (stamp.dt.month < 3).astype("Int64")
        season = from_stamp if season is None else season.where(season.notna(), from_stamp)
    if season is None:
        return None

    # "How early in the season is this row?" -- the week number on the old
    # layout, the timestamp on the new one, made comparable as one number. We
    # only ever compare within a season, and a season is entirely one layout.
    when = pd.Series([float("nan")] * len(d), index=d.index, dtype=float)
    if "week" in d.columns:
        when = pd.to_numeric(d["week"], errors="coerce").astype(float)
    if stamp is not None:
        secs = (stamp - pd.Timestamp("1970-01-01")).dt.total_seconds()
        when = when.where(when.notna(), secs)

    out = pd.DataFrame({
        "season": season,
        "team": team.astype(str).str.upper(),
        "gsis_id": pid.astype(str),
        "position": pos.astype(str).str.upper(),
        "depth": pd.to_numeric(depth, errors="coerce"),
        "_when": when.fillna(0.0),
    })
    out = out[out["position"].isin(_BACKFIELD_POS)]
    out = out.dropna(subset=["season", "depth"])
    out = out[out["gsis_id"].str.len() > 3]
    if out.empty:
        return None
    out["season"] = out["season"].astype(int)
    earliest = out.groupby("season")["_when"].transform("min")
    out = out[out["_when"] == earliest].drop(columns="_when")
    out["depth"] = out["depth"].astype(int)
    out = (out.sort_values(["season", "team", "depth"])
              .drop_duplicates(["season", "team", "gsis_id"])
              .reset_index(drop=True))

    # Renumber 1..N inside each backfield now that the fullbacks are gone --
    # otherwise dropping an FB1 leaves the real starter sitting at 2. Dense
    # ranking on purpose: through 2024 the file lists package-specific spots, so
    # 25-28 teams a year show two backs tied at 1. Two men listed as the starter
    # stay tied at 1 and the next back is 2, which is what the chart says.
    out["depth"] = (out.groupby(["season", "team"])["depth"]
                       .rank(method="dense").astype(int))
    return out.sort_values(["season", "team", "depth"]).reset_index(drop=True)


def get_depth_history(seasons=None, refresh: bool = False) -> pd.DataFrame | None:
    """
    Where every back sat on the depth chart ENTERING each season we model.

    Entering, not mid-season, on purpose: a Week 12 depth chart already knows
    who got hurt and who won the job, which is exactly the thing we are trying
    to predict. Taking the first chart of the year keeps the factor honest.

    Columns: season, team, gsis_id, position, depth. Returns None if the pull
    fails, and the model treats that as "no depth information" rather than
    falling over.
    """
    seasons = list(seasons or config.SEASONS)
    if not refresh:
        cached = load_df(_DEPTH_HIST_NAME)
        if cached is not None:
            return _normalize_depth(cached)
    try:
        nfl = _lazy_nflreadpy()
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] Could not load depth-chart history ({exc}).")
        return None

    frames = []
    for season in seasons:
        # One season at a time so we can stamp the season ourselves -- the
        # 2025+ files don't carry a season column at all.
        try:
            raw = _to_pandas(_call_loader(nfl.load_depth_charts, [season]))
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] depth charts {season} unavailable ({exc}).")
            continue
        if raw is None or raw.empty:
            continue
        raw = raw.copy()
        if "season" not in raw.columns:
            raw["season"] = season
        frames.append(raw)
    if not frames:
        return None
    out = _normalize_depth(pd.concat(frames, ignore_index=True, sort=False))
    if out is not None and not out.empty:
        save_df(out, _DEPTH_HIST_NAME)
    return out


def get_rosters(seasons=None, refresh: bool = False) -> pd.DataFrame | None:
    """Seasonal rosters (current team per player). Updated daily year-round."""
    seasons = seasons or [config.UPCOMING_SEASON]
    try:
        if not refresh:
            cached = load_df("rosters")
            if cached is not None:
                return cached
        nfl = _lazy_nflreadpy()
        ros = _to_pandas(_call_loader(nfl.load_rosters, seasons))
        ros = _filter_seasons(ros, seasons)
        save_df(ros, "rosters")
        return ros
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] Could not load rosters ({exc}).")
        return None


def pull_all(seasons=None, refresh: bool = False) -> dict[str, pd.DataFrame]:
    """Download (or load from cache) every dataset the pipeline uses."""
    seasons = seasons or config.SEASONS
    datasets = {
        "player_weekly_stats": get_player_weekly_stats(seasons, refresh),
        "schedules": get_schedules(seasons, refresh),
        "snap_counts": get_snap_counts(seasons, refresh),
    }
    opp = get_ff_opportunity(seasons, refresh)
    if opp is not None:
        datasets["ff_opportunity"] = opp
    return datasets
