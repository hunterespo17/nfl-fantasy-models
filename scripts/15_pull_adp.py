"""
Step 15 -- Refresh data/adp.csv straight from the sites. No typing.

    py scripts\\15_pull_adp.py

WHAT IT DOES

ESPN publishes its live average draft position in a public feed. This script
reads it, turns it into the same shape data/adp.csv already uses (one row per
player, one column per site, each value that site's overall pick number), and
merges it in. Columns it did not pull are left exactly as they were -- your FFC
prices are never touched.

Sleeper and Underdog do not publish an open feed. If you ever paste one of
their boards into a text file, this script will read it:

    data\\paste_sleeper.txt
    data\\paste_underdog.txt

Any layout works as long as each line has a player name and that player's pick
number somewhere on it. "1.02 Jahmyr Gibbs RB DET", "Jahmyr Gibbs  1.5" and
"3 Jahmyr Gibbs DET 1.5" all parse. Lines it cannot read are printed, not
guessed at. If the files aren't there the script just skips them.

SAFETY

The old data/adp.csv is copied to data\\adp_backup.csv before anything is
written, and nothing is written at all unless the pull actually produced
players. A bad network day leaves your file alone.
"""
import os
import pathlib
import re
import shutil
import sys

# --- Stale-bytecode guard (important when the project lives in OneDrive) ------
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
for _pyc in _ROOT.rglob("*.pyc"):
    try:
        _pyc.unlink()
    except OSError:
        pass

import pandas as pd  # noqa: E402

from src import adp as adp_mod, config  # noqa: E402

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
SEASON = getattr(config, "UPCOMING_SEASON", 2026)
ADP_FILE = config.DATA_DIR / "adp.csv"
BACKUP_FILE = config.DATA_DIR / "adp_backup.csv"

# Which positions we keep. The file is per-position, and a kicker's ADP would
# only ever dilute the rank columns for the positions that have boards.
KEEP_POS = {"QB", "RB", "WR", "TE"}

# ESPN's own position codes.
ESPN_POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DST"}

# ESPN's read-only fantasy host. `leaguedefaults/3` is the public 10-team PPR
# default -- no league, no login. `kona_player_info` is the view that carries
# the ownership block, which is where averageDraftPosition lives.
ESPN_URL = (
    "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/"
    f"{SEASON}/segments/0/leaguedefaults/3"
)

# Without a filter header ESPN returns a few hundred players in alphabetical
# order and stops. The header is what makes it sort by draft rank and hand over
# the whole board.
ESPN_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0 Safari/537.36"),
    "Accept": "application/json",
}

# A player nobody drafts still gets a number from ESPN; it just sits at the very
# bottom. Anything past this is noise and would stretch the rank columns for no
# reason. 300 is roughly 25 rounds deep in a 12-team league.
MAX_PICK = 300.0


def _say(msg=""):
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# ESPN
# ---------------------------------------------------------------------------
def pull_espn() -> dict:
    """{(pos, normalized_name): overall_pick} from ESPN. Empty dict on failure."""
    try:
        import requests
    except ImportError:
        _say("  [skip] ESPN -- the 'requests' package isn't installed.")
        _say("         Run:  py -m pip install -r requirements.txt")
        return {}

    import json

    out, seen_pages = {}, 0
    offset, page_size = 0, 500
    while offset < 2000:
        filt = {"players": {
            "limit": page_size,
            "offset": offset,
            "sortDraftRanks": {"sortPriority": 100, "sortAsc": True,
                               "value": "PPR"},
        }}
        headers = dict(ESPN_HEADERS)
        headers["x-fantasy-filter"] = json.dumps(filt)
        try:
            r = requests.get(ESPN_URL, params={"view": "kona_player_info"},
                             headers=headers, timeout=45)
            r.raise_for_status()
            payload = r.json()
        except Exception as exc:                                # noqa: BLE001
            if offset == 0:
                _say(f"  [fail] ESPN -- {type(exc).__name__}: {exc}")
                return {}
            break                       # got some pages; keep what we have

        players = payload.get("players") or []
        if not players:
            break
        seen_pages += 1
        for row in players:
            p = row.get("player") or {}
            name = p.get("fullName")
            pos = ESPN_POS.get(p.get("defaultPositionId"))
            pick = ((p.get("ownership") or {}).get("averageDraftPosition"))
            if not name or pos not in KEEP_POS:
                continue
            try:
                pick = float(pick)
            except (TypeError, ValueError):
                continue
            if not (0 < pick <= MAX_PICK):
                continue
            out[(pos, adp_mod.norm(name))] = round(pick, 1)
        if len(players) < page_size:
            break
        offset += page_size

    if out:
        by_pos = {}
        for (pos, _), _v in out.items():
            by_pos[pos] = by_pos.get(pos, 0) + 1
        counts = ", ".join(f"{k} {by_pos[k]}" for k in sorted(by_pos))
        _say(f"  [ok]   ESPN -- {len(out)} players over {seen_pages} page(s): {counts}")
    else:
        _say("  [fail] ESPN -- reached the site but found no draft positions.")
    return out


# ---------------------------------------------------------------------------
# Pasted boards (Sleeper / Underdog)
# ---------------------------------------------------------------------------
# A name is two or more words of letters, apostrophes, periods and hyphens.
_NAME_RE = re.compile(r"[A-Za-z][A-Za-z'.\-]*(?:\s+[A-Za-z][A-Za-z'.\-]*)+")
_NUM_RE = re.compile(r"\d+\.\d+|\d+")
_POS_RE = re.compile(r"\b(QB|RB|WR|TE|K|DST|D/ST|DEF)\b")
_ROUND_PICK = re.compile(r"\b(\d{1,2})\.(\d{2})\b")     # 1.02  =  round.pick
_JUNK_WORDS = {"rank", "player", "team", "pos", "adp", "bye", "avg", "position",
               "overall", "name", "notes", "tier"}


def _clean_name(raw: str) -> str:
    """Strip team codes and position tags that ran into the name."""
    s = _POS_RE.sub(" ", f" {raw} ")
    s = re.sub(r"\b[A-Z]{2,3}\b", " ", s)        # NYJ, KC, SF ...
    return re.sub(r"\s+", " ", s).strip()


def parse_paste(path: pathlib.Path, label: str, teams: int = 12) -> dict:
    """{(pos, normalized_name): overall_pick} from a pasted board."""
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        _say(f"  [fail] {label} -- couldn't read {path.name}: {exc}")
        return {}

    out, bad = {}, []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.lower() in _JUNK_WORDS:
            continue
        low = line.lower()
        if sum(w in low for w in _JUNK_WORDS) >= 2:
            continue                                  # a header row

        pos_hit = _POS_RE.search(line)
        pos = pos_hit.group(1) if pos_hit else None
        pos = {"D/ST": "DST", "DEF": "DST"}.get(pos, pos)

        name_hit = _NAME_RE.search(line)
        if not name_hit:
            continue
        name = _clean_name(name_hit.group(0))
        if len(name.split()) < 2:
            bad.append(line)
            continue

        # Prefer a round.pick like 1.02; otherwise the last decimal on the line.
        rp = _ROUND_PICK.search(line)
        if rp:
            pick = (int(rp.group(1)) - 1) * teams + int(rp.group(2))
        else:
            tail = line[name_hit.end():]
            nums = [float(n) for n in _NUM_RE.findall(tail)]
            nums = [n for n in nums if 0 < n <= MAX_PICK]
            if not nums:
                bad.append(line)
                continue
            pick = nums[-1]

        if pos not in KEEP_POS:
            # No position on the line -- park it and let the merge match it to
            # whatever position that name already holds in the file.
            pos = "?"
        out[(pos, adp_mod.norm(name))] = round(float(pick), 1)

    if out:
        _say(f"  [ok]   {label} -- {len(out)} players from {path.name}")
    if bad:
        _say(f"         ({len(bad)} line(s) skipped, e.g. {bad[0][:60]!r})")
    return out


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------
def merge(existing: pd.DataFrame, pulls: dict) -> tuple[pd.DataFrame, dict]:
    """Fold {platform: {(pos, key): pick}} into the ADP table."""
    df = existing.copy()
    if df.empty:
        df = pd.DataFrame(columns=["player", "pos", *adp_mod.PLATFORMS])
    for col in ("player", "pos", *adp_mod.PLATFORMS):
        if col not in df.columns:
            df[col] = pd.NA
    df["pos"] = df["pos"].astype(str).str.upper().str.strip().replace(
        {"": "QB", "NAN": "QB", "NONE": "QB"})
    df["key"] = df["player"].map(adp_mod.norm)

    # Where does each (pos, key) live? Also a name-only index so a pasted line
    # with no position on it can still find its player.
    row_of = {(r.pos, r.key): i for i, r in df.iterrows()}
    by_name = {}
    for i, r in df.iterrows():
        by_name.setdefault(r.key, []).append(i)

    stats = {}
    for platform, picks in pulls.items():
        if not picks:
            continue
        filled = added = 0
        for (pos, key), pick in picks.items():
            idx = row_of.get((pos, key))
            if idx is None and pos == "?":
                hits = by_name.get(key) or []
                idx = hits[0] if len(hits) == 1 else None
            if idx is None:
                if pos in ("?", None) or pos not in KEEP_POS:
                    continue            # can't file it without a position
                new = {c: pd.NA for c in df.columns}
                new["player"] = key.title()
                new["pos"] = pos
                new["key"] = key
                new[platform] = pick
                df.loc[len(df)] = new
                row_of[(pos, key)] = len(df) - 1
                added += 1
            else:
                df.at[idx, platform] = pick
                filled += 1
        stats[platform] = (filled, added)
    return df, stats


def report_coverage(df: pd.DataFrame) -> None:
    _say()
    _say("  Coverage now, by position:")
    head = "    " + "pos".ljust(6) + "rows".rjust(6)
    head += "".join(adp_mod.PLATFORM_LABEL[p].rjust(10) for p in adp_mod.PLATFORMS)
    _say(head)
    for pos in sorted(df["pos"].dropna().unique()):
        sub = df[df["pos"] == pos]
        line = "    " + str(pos).ljust(6) + str(len(sub)).rjust(6)
        for p in adp_mod.PLATFORMS:
            n = int(pd.to_numeric(sub[p], errors="coerce").notna().sum())
            line += (str(n) if n else "-").rjust(10)
        _say(line)


def main() -> int:
    _say()
    _say("=" * 62)
    _say(f"  Refreshing draft prices for {SEASON}")
    _say("=" * 62)
    _say()

    before = adp_mod.load_adp()
    if before.empty:
        _say(f"  [note] {ADP_FILE} is missing or empty -- starting a new one.")
    else:
        _say(f"  Read {len(before)} existing rows from data\\adp.csv")
    _say()

    pulls = {
        "espn": pull_espn(),
        "sleeper": parse_paste(config.DATA_DIR / "paste_sleeper.txt", "Sleeper"),
        "underdog": parse_paste(config.DATA_DIR / "paste_underdog.txt", "Underdog"),
    }
    for name, path in (("Sleeper", "paste_sleeper.txt"),
                       ("Underdog", "paste_underdog.txt")):
        if not (config.DATA_DIR / path).exists():
            _say(f"  [skip] {name} -- no data\\{path} to read (that's fine).")

    if not any(pulls.values()):
        _say()
        _say("  Nothing came back, so data\\adp.csv was left exactly as it was.")
        _say("  Send Claude everything above and he'll fix the puller.")
        return 1

    merged, stats = merge(before, pulls)
    _say()
    for platform, (filled, added) in stats.items():
        lab = adp_mod.PLATFORM_LABEL.get(platform, platform)
        _say(f"  {lab}: updated {filled} player(s), added {added} new row(s)")

    # Back up, then write.
    if ADP_FILE.exists():
        shutil.copy2(ADP_FILE, BACKUP_FILE)
        _say(f"\n  Previous file saved as data\\{BACKUP_FILE.name}")

    out = merged[["player", "pos", *adp_mod.PLATFORMS]].copy()
    out = out.sort_values(["pos", *adp_mod.PLATFORMS], na_position="last")
    ADP_FILE.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(ADP_FILE, index=False)
    _say(f"  Wrote {len(out)} rows to data\\adp.csv")

    report_coverage(out)
    _say()
    _say("  Done. Now double-click BUILD MY BOARD to rebuild with the new prices.")
    _say()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
