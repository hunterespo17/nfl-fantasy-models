"""Turn the published projection guide into data/clay_rb_<season>.csv,
data/clay_qb_<season>.csv, data/clay_wr_<season>.csv and data/clay_te_<season>.csv.

WHEN YOU RUN THIS: once, whenever a new guide comes out. Never as part of a
normal build -- the model reads the CSV, not the PDF, so the PDF is not a
dependency of anything.

HOW YOU RUN IT: put the PDF in the data\\raw folder, then

    py scripts\\import_clay.py

If you'd rather leave the PDF where it is, hand it the path instead:

    py scripts\\import_clay.py "C:\\Users\\hunte\\Downloads\\theguide.pdf"

It needs pdftotext, which ships with Poppler. If you don't have it the script
says so and stops; nothing else in the project needs it.
"""
import csv, re, subprocess, sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import adp as A, config, data  # noqa: E402


def _find_pdf() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    hits = sorted(config.RAW_DIR.glob("*.pdf"))
    if not hits:
        sys.exit(f"No PDF given, and none found in {config.RAW_DIR}.\n"
                 f"Put the guide there, or pass its path on the command line.")
    return str(hits[-1])


PDF = _find_pdf()
OUT = config.DATA_DIR / f"clay_rb_{config.UPCOMING_SEASON}.csv"
OUT_QB = config.DATA_DIR / f"clay_qb_{config.UPCOMING_SEASON}.csv"
OUT_WR = config.DATA_DIR / f"clay_wr_{config.UPCOMING_SEASON}.csv"
OUT_TE = config.DATA_DIR / f"clay_te_{config.UPCOMING_SEASON}.csv"

# Clay's team codes -> the ones nflreadpy uses.
TEAM = {"ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}
# Clay's spellings -> the ones the player file uses. Keys are already
# normalised, so the suffix is gone by the time we look one up.
ALIAS = {"ken walker": "kenneth walker", "kenneth gainwell": "kenny gainwell",
         "kyle t williams": "kyle williams",      # the 2025 rookie, not the 2010 one
         "chigoziem okonkwo": "chig okonkwo"}

ROW = re.compile(
    r"^(.+?)\s{2,}([A-Z]{2,3})\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(-?\d+)\s+(\d+)"
    r"\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)%\s+(\d+)%\s*$")

# Quarterback rows: name, team, then rank / points / games / twelve stat columns.
# Same shape as the RB pattern, minus the two share percentages on the end.
QB_ROW = re.compile(
    r"^(.+?)\s{2,}([A-Z]{2,3})\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)"
    r"\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$")


def pages(pdf):
    try:
        txt = subprocess.run(["pdftotext", "-layout", pdf, "-"],
                             capture_output=True, text=True, check=True).stdout
    except FileNotFoundError:
        sys.exit("pdftotext isn't installed. It comes with Poppler:\n"
                 "  winget install oschwartz10612.Poppler\n"
                 "Then open a new window and run this again.")
    return txt.split("\f")


def parse(pdf):
    out = []
    for pg in pages(pdf):
        if not pg.lstrip().startswith("Running Back Projections"):
            continue
        for line in pg.splitlines():
            m = ROW.match(line.strip())
            if not m:
                continue
            g = m.groups()
            out.append({
                "name": g[0].strip(), "team": TEAM.get(g[1], g[1]),
                "clay_rank": int(g[2]), "clay_ppr": int(g[3]), "clay_games": int(g[4]),
                "carries": int(g[5]), "rush_yds": int(g[6]), "rush_td": int(g[7]),
                "targets": int(g[8]), "rec": int(g[9]),
                "rec_yds": int(g[10]), "rec_td": int(g[11]),
            })
    return pd.DataFrame(out)


def parse_qb(pgs):
    out = []
    for pg in pgs:
        if not pg.lstrip().startswith("Quarterback Projections"):
            continue
        for line in pg.splitlines():
            m = QB_ROW.match(line.strip())
            if not m:
                continue
            g = m.groups()
            out.append({
                "name": g[0].strip(), "team": TEAM.get(g[1], g[1]),
                "clay_rank": int(g[2]), "clay_ppr": int(g[3]), "clay_games": int(g[4]),
                "pass_att": int(g[5]), "comp": int(g[6]), "pass_yds": int(g[7]),
                "pass_td": int(g[8]), "ints": int(g[9]), "sacks": int(g[10]),
                "carries": int(g[11]), "rush_yds": int(g[12]), "rush_td": int(g[13]),
            })
    return pd.DataFrame(out)


def parse_skill(pgs, heading):
    """Read any of the skill-position tables -- they all share one column layout.

    Receivers and tight ends print the same fourteen columns as running backs,
    so the row pattern is reused rather than duplicated. Clay's own Car% and
    Targ% come along for the ride purely as a cross-check on the share maths.
    """
    out = []
    for pg in pgs:
        if not pg.lstrip().startswith(heading):
            continue
        for line in pg.splitlines():
            m = ROW.match(line.strip())
            if not m:
                continue
            g = m.groups()
            out.append({
                "name": g[0].strip(), "team": TEAM.get(g[1], g[1]),
                "clay_rank": int(g[2]), "clay_ppr": int(g[3]), "clay_games": int(g[4]),
                "carries": int(g[5]), "rush_yds": int(g[6]), "rush_td": int(g[7]),
                "targets": int(g[8]), "rec": int(g[9]),
                "rec_yds": int(g[10]), "rec_td": int(g[11]),
                "clay_carry_pct": int(g[12]) / 100.0,
                "clay_targ_pct": int(g[13]) / 100.0,
            })
    return pd.DataFrame(out)


def _receiving_files(players, pgs):
    """Write the receiver and tight-end files.

    Target share here means share of the WHOLE passing game, not share of one
    position group -- so the denominator is every target the guide hands out on
    that team, backs and tight ends included. Taking it off the receiver table
    alone would inflate every wideout by roughly a third.
    """
    tables = {h: parse_skill(pgs, h) for h in
              ("Wide Receiver Projections", "Tight End Projections",
               "Running Back Projections")}
    wr, te, rb = tables["Wide Receiver Projections"], \
        tables["Tight End Projections"], tables["Running Back Projections"]
    if wr.empty:
        print("\nno receiver page found -- skipping the WR file")
        return

    everyone = pd.concat([d for d in (wr, te, rb) if not d.empty], ignore_index=True)
    team_targets = everyone.groupby("team")["targets"].sum()

    idmap = _idmap(players, ["WR", "TE"])
    # Two-way players are filed under their defensive position -- Travis Hunter
    # reads CB. Anyone the receiver map misses gets a second look against every
    # position, and the fallback is printed so a real bad match can't hide.
    anypos = _idmap(players, sorted(
        players.get("position", players.get("position_group")).astype(str).str.upper().unique()))
    cols = ["player_id", "name", "team", "clay_rank", "clay_ppr", "clay_games",
            "carries", "rush_yds", "rush_td", "targets", "rec", "rec_yds", "rec_td",
            "clay_target_share", "clay_targ_pct", "clay_yards_share"]

    team_yards = everyone.groupby("team")["rec_yds"].sum()
    for df, label, path in ((wr, "receivers", OUT_WR), (te, "tight ends", OUT_TE)):
        if df.empty:
            continue
        print(f"\nparsed {len(df)} {label}")
        df["key"] = df["name"].map(lambda n: ALIAS.get(A.norm(n), A.norm(n)))
        df["player_id"] = df["key"].map(idmap)
        late = df["player_id"].isna() & df["key"].isin(anypos)
        if late.any():
            print("  found off the receiver list (two-way or mis-filed position): "
                  + ", ".join(df.loc[late, "name"]))
            df.loc[late, "player_id"] = df.loc[late, "key"].map(anypos)
        print(f"matched {df['player_id'].notna().sum()} of {len(df)} to a player id")
        miss = df[df["player_id"].isna()]
        if len(miss):
            print("  unmatched:", ", ".join(f"{r['name']} ({r.team}, {r.clay_rank})"
                                            for _, r in miss.iterrows()))
        df["clay_target_share"] = (df["targets"] / df["team"].map(team_targets)).round(4)
        df["clay_yards_share"] = (df["rec_yds"] / df["team"].map(team_yards)).round(4)
        path.parent.mkdir(parents=True, exist_ok=True)
        df[cols].to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)
        print(f"wrote {path}  ({len(df)} rows)")

        # Clay rounds his own percentage to a whole point, so agreement inside
        # one point is the most the check can ask for. A bigger gap would mean
        # the denominator is wrong -- a missing position table, most likely.
        gap = (df["clay_target_share"] - df["clay_targ_pct"]).abs()
        print(f"  share check vs Clay's printed %: worst gap {gap.max():.3f}, "
              f"{(gap <= 0.011).mean():.0%} inside a rounding point")

        short = df[df["clay_games"] < 17].sort_values("clay_rank")
        print(f"  {label} the guide does not give a full season:"
              if len(short) else f"  every one of the {label} is down for a full season")
        for _, r in short.iterrows():
            print(f"    {r.clay_rank:<4d} {r['name']:24s} {r.team:4s} {r.clay_games} games")


def _idmap(players, wanted):
    """{normalized name: gsis id} for the positions in `wanted`."""
    pl = players.copy()
    pos = pl.get("position", pl.get("position_group"))
    pl = pl[pos.astype(str).str.upper().isin(wanted)]
    pl["key"] = pl["display_name"].map(A.norm) if "display_name" in pl.columns \
        else pl["player_name"].map(A.norm)
    # Several retired players share a name with an active one. gsis ids are
    # issued in order, so the newest row wins -- the guide only projects players
    # who are currently on a roster.
    pl = pl[pl["gsis_id"].astype(str).str.startswith("00-")].sort_values("gsis_id")
    return dict(zip(pl["key"], pl["gsis_id"]))


def main_qb(players):
    df = parse_qb(pages(PDF))
    print(f"\nparsed {len(df)} quarterbacks")
    if df.empty:
        print("  no quarterback page found -- skipping the QB file")
        return
    idmap = _idmap(players, ["QB"])
    df["key"] = df["name"].map(lambda n: ALIAS.get(A.norm(n), A.norm(n)))
    df["player_id"] = df["key"].map(idmap)
    print(f"matched {df['player_id'].notna().sum()} of {len(df)} to a player id")
    miss = df[df["player_id"].isna()]
    if len(miss):
        print("  unmatched:", ", ".join(f"{r['name']} ({r.team}, QB{r.clay_rank})"
                                        for _, r in miss.iterrows()))
    cols = ["player_id", "name", "team", "clay_rank", "clay_ppr", "clay_games",
            "pass_att", "comp", "pass_yds", "pass_td", "ints", "sacks",
            "carries", "rush_yds", "rush_td"]
    df[cols].to_csv(OUT_QB, index=False, quoting=csv.QUOTE_MINIMAL)
    print(f"wrote {OUT_QB}  ({len(df)} rows)")
    short = df[df["clay_games"] < 17].sort_values("clay_rank")
    print("quarterbacks the guide does not give a full season:"
          if len(short) else "every quarterback is down for a full season")
    for _, r in short.iterrows():
        print(f"  QB{r.clay_rank:<4d} {r['name']:24s} {r.team:4s} {r.clay_games} games")


def main():
    df = parse(PDF)
    print(f"parsed {len(df)} running backs")

    players = data.get_players()
    pl = players.copy()
    pos = pl.get("position", pl.get("position_group"))
    pl = pl[pos.astype(str).str.upper().isin(["RB", "FB", "HB"])]
    pl["key"] = pl["display_name"].map(A.norm) if "display_name" in pl.columns \
        else pl["player_name"].map(A.norm)
    # Several retired backs share a name with an active one. gsis ids are issued
    # in order, so the newest row wins -- Clay is only projecting current players.
    pl = pl[pl["gsis_id"].astype(str).str.startswith("00-")].sort_values("gsis_id")
    idmap = dict(zip(pl["key"], pl["gsis_id"]))

    df["key"] = df["name"].map(lambda n: ALIAS.get(A.norm(n), A.norm(n)))
    df["player_id"] = df["key"].map(idmap)
    miss = df[df["player_id"].isna()]
    print(f"matched {df['player_id'].notna().sum()} of {len(df)} to a player id")
    if len(miss):
        print("  unmatched:", ", ".join(f"{r['name']} ({r.team}, RB{r.clay_rank})"
                                        for _, r in miss.iterrows()))

    # His share of his own backfield, straight out of Clay's numbers.
    for c, s in (("carries", "clay_carry_share"), ("targets", "clay_target_share")):
        tot = df.groupby("team")[c].transform("sum")
        df[s] = (df[c] / tot.where(tot > 0)).round(4)

    cols = ["player_id", "name", "team", "clay_rank", "clay_ppr", "clay_games",
            "carries", "rush_yds", "rush_td", "targets", "rec", "rec_yds", "rec_td",
            "clay_carry_share", "clay_target_share"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df[cols].to_csv(OUT, index=False, quoting=csv.QUOTE_MINIMAL)
    print(f"wrote {OUT}  ({len(df)} rows)")
    print("\nbacks Clay does not give a full season:")
    for _, r in df[df["clay_games"] < 17].sort_values("clay_rank").iterrows():
        print(f"  RB{r.clay_rank:<4d} {r['name']:24s} {r.team:4s} {r.clay_games} games")

    main_qb(players)
    _receiving_files(players, pages(PDF))


if __name__ == "__main__":
    main()
