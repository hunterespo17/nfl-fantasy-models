"""
Descriptive DRAFT OVERLAYS for the QB board: floor, ceiling, ADP value, risk.

These do NOT feed the projection -- the index-blend projection and ranking are
left exactly as they are. They are separate, interpretable buckets layered on
top of each already-ranked QB:

  Floor    -- a bad-week baseline: the recency-weighted 25th-percentile game he
              turns in. Bucketed Safe / Moderate / Risky vs the field.
  Ceiling  -- how often he explodes: recency-weighted rate of 25+ and 30+ point
              games (shrunk toward the field for small samples). Bucketed
              High / Medium / Low.
  ADP      -- current cross-site consensus draft slot, expressed as QB#.
  Risk     -- how risky he is AT that ADP: are you paying an early pick for a
              shaky floor / thin ceiling, or reaching past where the model
              ranks him? Cheap QBs are low-risk almost by definition.
  Value    -- the same question in POINTS rather than in draft slots: his
              projection minus what a pick at his price has historically been
              worth (see the ADP expectation curve in src/adp.py). Falling two
              ranking spots past the market may be worth nothing; beating your
              draft slot by five points a game is what wins leagues.
  LW check -- published league-winner thresholds, structured the way the
              research states them: two ALTERNATIVE paths (100+ rush attempt
              pace OR a McShanahan-tree play-caller), either of which alone
              clears the screen, plus two supporting rushing bars. Deliberately
              a checklist and NOT another weighted factor: "how many points will
              he score" and "does he have the shape that wins leagues" are
              different questions, and folding the second into the first hides
              it. See the block comment above the checklist for the sourcing.

All buckets are pool-relative (graded against this year's projected starters).
`attach(result, ...)` mutates the payload in place and returns it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import adp as adp_mod
from . import qb_blend
from . import scoring

RECENCY = 5           # only the last N seasons of games count (matches talent)
DECAY = 0.82          # per-year recency decay on game weights
BOOM1, BOOM2 = 25.0, 30.0   # the two "huge game" thresholds (QB defaults)
K_SHRINK = 10.0       # sample-size shrink strength (in recency-weighted games)
REPL_RANK = 12        # QB12 ~ replacement in a 12-team, 1QB league

# --- What changes from one position to the next -----------------------------
# Everything else in this file is position-neutral. These five knobs are not,
# and hard-coding the quarterback values would quietly mis-grade a back:
#
#   boom       A 25-point game is a big QB week. For a half-PPR back it is a
#              monster -- backs score less, so the bar comes down with them.
#              Set from the scoring format, not from taste: an RB1 averages
#              roughly 15-16 pts/gm in half PPR against a QB1's 20-22.
#   repl       Replacement level. Read from config.LEAGUE at runtime where we
#              can (RB30 in a 12-team league with a flex), with these as the
#              fallback if that lookup ever fails.
#   reach      How many ranking spots of "reach" counts as a full one. There are
#              32 startable quarterbacks and eighty-odd draftable backs, so five
#              spots means much less on an RB board than on a QB board.
#   gap_bar    Same idea for the Value/Reach label in rank space.
#   old_age    When age becomes a red flag. 34 for QBs. For backs it's 28 --
#              85% of league-winning RB seasons came from players 27 or younger.
POS_SETTINGS = {
    "QB": {"boom": (25.0, 30.0), "repl": 12, "reach": 8.0, "gap_bar": 5, "old_age": 34},
    "RB": {"boom": (20.0, 25.0), "repl": 30, "reach": 16.0, "gap_bar": 10, "old_age": 28},
    "WR": {"boom": (20.0, 25.0), "repl": 36, "reach": 16.0, "gap_bar": 10, "old_age": 31},
    "TE": {"boom": (15.0, 20.0), "repl": 12, "reach": 8.0, "gap_bar": 5, "old_age": 33},
}


def _settings(pos: str) -> dict:
    """Position knobs, with replacement level read from the live league config."""
    s = dict(POS_SETTINGS.get(str(pos).upper(), POS_SETTINGS["QB"]))
    try:
        from . import rankings
        r = rankings.replacement_ranks().get(str(pos).upper())
        if r:
            s["repl"] = int(r)
    except Exception:      # noqa: BLE001 -- fall back to the table above
        pass
    return s

# --- League-winner thresholds ----------------------------------------------
# Every number below is quoted from the research, not invented here:
#   +5.0 pts/gm over ADP expectation ... the league-winner bar
#   +2.0 pts/gm over ADP expectation ... the ordinary "good value" bar
#   55 rush attempts (paced to 17 games) ... the floor; under it the rushing
#        cushion that makes QBs league-winners basically isn't there
#   100 rush attempts (paced) ......... elite designed-and-scramble usage
#   5.0 rushing pts/gm ................ the production side of the same idea
# Attempts are PACED (per-game x 17) because that is how the research states
# them -- it credits a QB who was on a 99-attempt pace over four starts instead
# of scoring him as if he'd carried 12 times all year.
LW_FPG_EDGE = 5.0
VAL_FPG_EDGE = 2.0
RUSH_ATT_FLOOR = 55
RUSH_ATT_HIGH = 100
RUSH_FPG_HIGH = 5.0
MCSHANAHAN = "mcshanahan"    # the one `tree` value in data/playcallers.csv we act on
# The negative side (-2.0) is OUR symmetric mirror of the +2.0 value bar, not a
# number from the research. It only ever drives a soft "pricey" label.
OVERPRICED_FPG = -2.0


def _first(df, names):
    for n in names:
        if n in df.columns:
            return df[n]
    return pd.Series(index=df.index, dtype="float64")


# ---------------------------------------------------------------------------
# per-game history -> raw floor / boom metrics
# ---------------------------------------------------------------------------
def _game_fp(weekly: pd.DataFrame, rules: dict | None, pos: str = "QB") -> pd.DataFrame:
    pcol = _first(weekly, ["position", "position_group"]).astype(str).str.upper()
    st = _first(weekly, ["season_type"])
    m = (pcol == str(pos).upper())
    if st is not None and st.notna().any():
        m = m & (st.astype(str).str.upper() == "REG")
    w = weekly[m]
    fp = scoring.compute_fantasy_points(w, rules).to_numpy()
    pid = _first(w, ["player_id", "gsis_id"]).astype(str).to_numpy()
    sea = pd.to_numeric(_first(w, ["season"]), errors="coerce").to_numpy()
    out = pd.DataFrame({"player_id": pid, "season": sea, "fp": fp})
    return out.dropna(subset=["season"])


def _actual_ppg_by_season(weekly: pd.DataFrame, rules: dict | None,
                          pos: str = "QB") -> dict:
    """{(season, normalized_name): actual REG-season fantasy pts/gm} for ONE position.

    Keyed by NAME rather than player_id on purpose: the historical ADP file is a
    hand-kept list of names with no nflverse ids in it, and `adp.norm` is the
    same normalizer the live ADP join already uses.

    `pos` matters more than it looks: this is what the expectation curve is fit
    against, and pooling positions here would fit one curve to two completely
    different scoring distributions.
    """
    pcol = _first(weekly, ["position", "position_group"]).astype(str).str.upper()
    st = _first(weekly, ["season_type"])
    m = (pcol == str(pos).upper())
    if st is not None and st.notna().any():
        m = m & (st.astype(str).str.upper() == "REG")
    w = weekly[m]
    if w.empty:
        return {}
    d = pd.DataFrame({
        "name": _first(w, ["player_display_name", "player_name"]).astype(str).to_numpy(),
        "season": pd.to_numeric(_first(w, ["season"]), errors="coerce").to_numpy(),
        "fp": scoring.compute_fantasy_points(w, rules).to_numpy(),
    }).dropna(subset=["season", "fp"])
    if d.empty:
        return {}
    d["key"] = d["name"].map(adp_mod.norm)
    d = d[d["key"] != ""]
    g = d.groupby([d["season"].astype(int), d["key"]])["fp"].agg(["mean", "size"])
    return {(int(s), k): float(row["mean"])
            for (s, k), row in g.iterrows()
            if row["size"] >= adp_mod.MIN_GAMES_HIST}


def _curve_pick(q: dict):
    """Which raw overall pick to score a QB at, and where it came from.

    FFC first, because the historical curve is fit on FFC ADP -- comparing an
    FFC-shaped curve to an FFC-shaped pick is the apples-to-apples version. If a
    QB has no FFC price (FFC only publishes a top-N), fall back to the mean of
    whatever other platforms do list him.
    """
    picks = q.get("adp_picks") or {}
    ffc = picks.get("ffc")
    if ffc is not None:
        return float(ffc), "FFC"
    others = [float(v) for pf, v in picks.items() if pf != "ffc" and v is not None]
    if others:
        return sum(others) / len(others), "cross-site avg"
    return None, None


def _wpctile(vals: np.ndarray, wts: np.ndarray, q: float) -> float:
    """Weighted percentile q (0-1) of vals."""
    vals = np.asarray(vals, dtype=float)
    wts = np.asarray(wts, dtype=float)
    if len(vals) == 0:
        return np.nan
    o = np.argsort(vals)
    v, w = vals[o], wts[o]
    tot = w.sum()
    if tot <= 0:
        return float(np.median(v))
    cw = (np.cumsum(w) - 0.5 * w) / tot
    return float(np.interp(q, cw, v))


def raw_metrics(gl: pd.DataFrame, latest: int,
                boom1: float = BOOM1, boom2: float = BOOM2) -> dict:
    """player_id -> {floor_raw, boom1, boom2, n_eff} from recency-weighted games."""
    out = {}
    for pid, d in gl.groupby("player_id"):
        d = d[d["season"] >= latest - RECENCY + 1]
        if d.empty:
            continue
        fp = d["fp"].to_numpy(dtype=float)
        wt = DECAY ** (latest - d["season"].to_numpy(dtype=float))
        n = float(wt.sum())
        if n <= 0:
            continue
        out[pid] = {
            "floor_raw": _wpctile(fp, wt, 0.25),
            "boom1": float(wt[fp >= boom1].sum() / n),
            "boom2": float(wt[fp >= boom2].sum() / n),
            "n_eff": n,
        }
    return out


# ---------------------------------------------------------------------------
# bucketing helpers (pool-relative tertiles)
# ---------------------------------------------------------------------------
def _pctl(payload, key, out_key):
    xs = np.sort(np.array([q[key] for q in payload if q.get(key) is not None], dtype=float))
    for q in payload:
        v = q.get(key)
        q[out_key] = float((xs <= v).mean()) if (v is not None and len(xs)) else 0.5


def _tertile(payload, key, labels_low_to_high, out_key):
    vals = np.array([q[key] for q in payload if q.get(key) is not None], dtype=float)
    if len(vals) == 0:
        for q in payload:
            q[out_key] = labels_low_to_high[1]
        return
    lo, hi = np.quantile(vals, [1 / 3, 2 / 3])
    for q in payload:
        v = q.get(key)
        if v is None:
            q[out_key] = labels_low_to_high[1]
        elif v >= hi:
            q[out_key] = labels_low_to_high[2]
        elif v >= lo:
            q[out_key] = labels_low_to_high[1]
        else:
            q[out_key] = labels_low_to_high[0]


def _risk_buckets(payload):
    scores = np.array([q["_risk"] for q in payload], dtype=float)
    pos = scores[scores > 0.05]
    if len(pos) == 0:
        for q in payload:
            q["risk_bucket"] = "Low"
        return
    hi = np.quantile(pos, 0.67)
    mid = np.quantile(pos, 0.34)
    for q in payload:
        s = q["_risk"]
        if s <= 0.05:
            q["risk_bucket"] = "Low"
        elif s >= hi:
            q["risk_bucket"] = "High"
        elif s >= mid:
            q["risk_bucket"] = "Moderate"
        else:
            q["risk_bucket"] = "Low"


# ---------------------------------------------------------------------------
# cheat-sheet flags
# ---------------------------------------------------------------------------
# Short, tone-coded reasons shown on each card: why this player, in six words.
#
# These are DELIBERATELY position-specific. "Elite rusher" is the highest praise
# you can give a quarterback and a description of the job for a running back, so
# a shared flag list would say nothing about either. Each branch below reads only
# the indices its own model actually produces.
#
# One rule holds across both: nothing here may depend on proj_ppg. The reader
# drags weight sliders and the projection moves underneath these flags, so any
# "+N over ADP" style chip is built in the browser instead. Everything baked in
# here is weight-independent.
def _flags(payload: list, pos: str, S: dict) -> None:
    """Attach q['flags'] -- a list of [tone, text], tone in up/down/warn."""
    pos = str(pos).upper()
    old_age = S.get("old_age", 34)

    for q in payload:
        ix = q.get("indices", {})
        cg, age = q.get("career_games"), q.get("age")
        f = []

        if pos == "RB":
            # Built as two lists, good news and bad, so that trimming to six can't
            # starve the warnings. A back with six flattering chips and a torn ACL
            # would otherwise show six flattering chips.
            up, dn = [], []

            # ROLE FIRST. Everything else is a tiebreaker next to how much of the
            # backfield a player actually owns, so these lead the chip row.
            bf = q.get("bf_share")
            if bf is not None and bf >= 0.65:
                up.append(["up", "Bellcow"])
            elif bf is not None and bf <= 0.35:
                dn.append(["down", "Committee"])
            # Receiving work. 79 targets is the average of Heath's top-20
            # league-winning backs; it's an absolute bar, not a percentile.
            tp = q.get("targets_pace")
            if tp is not None and tp >= 79:
                up.append(["up", f"{int(tp)}-target pace"])
            elif tp is not None and tp <= 30:
                dn.append(["down", "No pass game role"])
            snap = q.get("snap_pct")
            if snap is not None and snap >= 65:
                up.append(["up", "Every-down snaps"])

            # AGE AND CAREER STAGE. The strongest single filter in the research:
            # the average league-winning back was 25.1, and 85% of those seasons
            # came from players 27 or younger.
            #
            # The two age chips are worded differently on purpose. The old-age one
            # names the number because the number is the alarm; the young one names
            # the quality, because "Age 25" in green beside "Age 29" in red is two
            # chips that look identical and mean opposite things.
            if age is not None and age <= 25:
                up.append(["up", "Prime age"])
            # Ascending: still cheap, still climbing. Roughly the first two years
            # of games, which is where the rookie-contract edge lives.
            if cg is not None and 10 <= cg <= 40:
                up.append(["up", "Ascending"])
            if age is not None and age >= old_age:
                dn.append(["down", f"Age {age}"])

            # TEAM AND EFFICIENCY -- real, but they move a back less than his role.
            veg = ix.get("Vegas", 50)
            if veg >= 70:
                up.append(["up", "Winning offense"])
            elif veg <= 32:
                dn.append(["down", "Weak team"])
            eff = ix.get("Efficiency", 50)
            if eff >= 75:
                up.append(["up", "Efficient"])
            elif eff <= 25:
                dn.append(["down", "Inefficient"])

            # HIS AVAILABILITY RECORD. Three seasons of games plus the size of
            # last year's job, NOT the Availability index -- that index is age
            # times durability, so reading it here would flag every healthy older
            # back as hurt and double-count the age chip above.
            #
            # This chip carries real weight now, because it is the ONLY place a
            # thin injury history shows up. Every back on this board is projected
            # for a full seventeen games; a man who has never once come close to
            # that is a full-season projection with a warning on it, and this is
            # the warning. See src/availability.py for why it works that way.
            hurt = q.get("avail_risk")
            if hurt is not None and hurt >= 0.60:
                dn.append(["warn", "Rarely makes it through a year"])
            elif hurt is not None and hurt >= 0.35:
                dn.append(["warn", "Misses games most years"])
            if q.get("mover"):
                dn.append(["warn", "New team"])

            # Somebody has REPORTED something about him THIS year, which is a
            # completely different claim from the history above: one says a body
            # like his tends to break, this one says he is hurt right now. It is
            # the only thing that moves his games count, so it goes to the front
            # of the down list -- when it's true it's the most important thing on
            # the row. Name the injury when we know it; "coming off an ACL" tells
            # you more than "only 11 games" ever could.
            gm, inj = q.get("games"), q.get("injury")
            if q.get("games_note") and gm is not None:
                txt = (f"{inj}, ~{round(float(gm))} games" if inj
                       else f"Only {round(float(gm))} games")
                dn.insert(0, ["warn", txt])
            if q.get("rookie"):
                dn.insert(0, ["warn", "Rookie -- no NFL games"])

            # Three of each guaranteed, then backfill from whichever side has more
            # left to say.
            f = up[:3] + dn[:3]
            for extra in up[3:] + dn[3:]:
                if len(f) >= 6:
                    break
                f.append(extra)
            q["flags"] = f
            continue

        # ---- quarterbacks (unchanged) ----
        if cg is not None and 10 <= cg <= 40:
            f.append(["up", "Ascending"])        # the one profile the market underrates
        if ix.get("Rushing", 50) >= 72:
            f.append(["up", "Elite rusher"])
        # League-winner reads, from the checklist above. "Elite rusher" is a
        # percentile (best of THIS field); these are absolute bars, so a whole
        # weak field can miss them and a whole strong one can clear them.
        pace = q.get("rush_att_pace")
        if pace is not None and pace >= RUSH_ATT_HIGH:
            f.append(["up", f"{RUSH_ATT_HIGH}+ rush pace"])
        elif pace is not None and pace < RUSH_ATT_FLOOR:
            f.append(["down", "No rush floor"])
        veg = ix.get("Vegas", 50)
        if veg >= 70:
            f.append(["up", "Strong team"])
        elif veg <= 32:
            f.append(["down", "Weak team"])
        cast = ix.get("Cast & OL", 50)
        if cast >= 70:
            f.append(["up", "Loaded cast"])
        elif cast <= 32:
            f.append(["down", "Thin cast"])
        if q.get("mover"):
            f.append(["warn", "New team"])
        if age is not None and age >= old_age:
            f.append(["down", f"Age {age}"])

        # HIS AVAILABILITY RECORD -- three seasons of games plus the size of last
        # year's job. This matters more at quarterback than anywhere else on the
        # board: you start one of them, so a passer who misses six weeks doesn't
        # cost you a share of a backfield, he empties the position.
        #
        # It goes near the front because it is now the ONLY place a thin injury
        # history appears. Burrow and Daniels are projected for a full seventeen
        # games like everybody else -- correctly, since nobody has reported a
        # thing about either of them -- and this is what stops that reading as a
        # clean bill of health. See src/availability.py.
        hurt = q.get("avail_risk")
        if hurt is not None and hurt >= 0.60:
            f.insert(0, ["warn", "Rarely makes it through a year"])
        elif hurt is not None and hurt >= 0.35:
            f.insert(0, ["warn", "Misses games most years"])

        # Somebody has REPORTED something about him THIS year -- a different
        # claim from the history above, and the only one that moves his games
        # count. Front of the row so a busy card can't trim it off. Name the
        # injury when we know it, because "coming off an ACL" carries more than a
        # bare number does.
        gm, inj = q.get("games"), q.get("injury")
        if q.get("games_note") and gm is not None:
            f.insert(0, ["warn", (f"{inj}, ~{round(float(gm))} games" if inj
                                  else f"Only {round(float(gm))} games")])
        q["flags"] = f[:6]


# ---------------------------------------------------------------------------
# main entry
# ---------------------------------------------------------------------------
def attach(result: dict, weekly: pd.DataFrame, scoring_rules: dict | None,
           adp_df: pd.DataFrame, cfg, pos: str = "QB") -> dict:
    payload = result.get("payload", [])
    if not payload:
        return result
    pos = str(pos).upper().strip()
    S = _settings(pos)
    boom1, boom2 = S["boom"]
    repl_rank = S["repl"]

    gl = _game_fp(weekly, scoring_rules, pos)
    latest = int(gl["season"].max()) if not gl.empty else int(getattr(cfg, "CURRENT_SEASON", 2025))
    raw = raw_metrics(gl, latest, boom1, boom2)

    have = [raw[q["player_id"]] for q in payload if q.get("player_id") in raw]
    pool_floor = float(np.median([r["floor_raw"] for r in have])) if have else 12.0
    pool_b1 = float(np.mean([r["boom1"] for r in have])) if have else 0.10
    pool_b2 = float(np.mean([r["boom2"] for r in have])) if have else 0.03

    # floor + ceiling, sample-size shrunk toward the field
    for q in payload:
        r = raw.get(q.get("player_id"))
        if r:
            n = r["n_eff"]
            s = n / (n + K_SHRINK)
            b1 = s * r["boom1"] + (1 - s) * pool_b1
            b2 = s * r["boom2"] + (1 - s) * pool_b2
            q["floor_pts"] = round(s * r["floor_raw"] + (1 - s) * pool_floor, 1)
            q["boom25"] = round(100 * b1)
            q["boom30"] = round(100 * b2)
            q["_cscore"] = b1 + b2           # 30+ games count double (also >=25)
            q["_games"] = round(n, 1)
        else:
            q["floor_pts"] = round(pool_floor, 1)
            q["boom25"] = round(100 * pool_b1)
            q["boom30"] = round(100 * pool_b2)
            q["_cscore"] = pool_b1 + pool_b2
            q["_games"] = 0.0

    # ADP -> per-platform positional ranks + a consensus anchor (drives value/risk).
    pranks = adp_mod.platform_pos_ranks(adp_df, pos)
    crank, _cscore = adp_mod.consensus_ranks(adp_df, pranks, pos)
    picks = adp_mod.raw_picks(adp_df, pos)
    # Only the sites that actually price THIS position. It used to walk the full
    # PLATFORMS list, which put a key on every player for every site the project
    # has ever read -- and the board draws one column per key it finds. The RB
    # file carries FFC only, so that emitted three columns of nothing but dashes
    # and read as "ADP is broken on this board" when the data was simply absent.
    # Same list platform_pos_ranks itself ranked, in the same order.
    plats = adp_mod.has_platforms(adp_mod.for_pos(adp_df, pos))
    for q in payload:
        k = adp_mod.norm(q["name"])
        # .get(pf, {}) and not pranks[pf]: a platform can carry data for the
        # position and still not rank this particular player.
        q["adp_platforms"] = {pf: pranks.get(pf, {}).get(k)                        # pos# per platform
                              for pf in plats}
        _pk = picks.get(k, {})
        q["adp_picks"] = {pf: _pk.get(pf) for pf in plats}                          # raw overall pick
        q["adp_pos_rank"] = int(crank[k]) if k in crank else None                   # consensus pos#
        q["adp_label"] = f"{pos}{q['adp_pos_rank']}" if q["adp_pos_rank"] else "UDFA"
        q["value_by_platform"] = {pf: (pranks[pf][k] - q["rank"])                   # +: falls past model
                                  for pf in plats if k in pranks.get(pf, {})}

    # ---- FLOOR IS A SEASON, NOT A GAME ------------------------------------
    # `floor_pts` is a bad WEEK -- the 25th-percentile game he turns in. That is
    # the right number to print, and the wrong one to bucket on by itself, because
    # the other way a season goes wrong is that he is not out there. Every player
    # is projected for a full seventeen now (see src/availability.py), so a thin
    # availability record has to show up somewhere or it vanishes entirely, and
    # the floor is exactly where it belongs: it is the definition of a floor.
    #
    # So the BUCKET reads a bad week discounted by how long a body like his
    # normally lasts, while the printed floor stays the honest per-game number.
    # A quarterback whose last three seasons say ten games keeps his projection
    # and reads Risky, which is the whole point of the split.
    for q in payload:
        fp = q.get("floor_pts")
        ag = q.get("avail_games")
        q["_fseason"] = (None if fp is None else
                         float(fp) * (min(float(ag), 17.0) / 17.0 if ag else 1.0))

    # pool-relative floor & ceiling buckets
    _tertile(payload, "_fseason", ["Risky", "Moderate", "Safe"], "floor_bucket")
    _tertile(payload, "_cscore", ["Low", "Medium", "High"], "ceiling_bucket")

    # risk at ADP
    _pctl(payload, "_fseason", "_fpct")
    _pctl(payload, "_cscore", "_cpct")
    for q in payload:
        apr = q.get("adp_pos_rank")
        if not apr:
            q["risk_bucket"] = "Low"
            q["value_gap"] = None
            q["value_tag"] = None
            q["_risk"] = 0.0
            continue
        cost = min(max((repl_rank - apr) / max(repl_rank - 1, 1), 0.0), 1.0)  # 1st~1, replacement~0
        downside = 1 - q["_fpct"]        # weak floor
        no_upside = 1 - q["_cpct"]       # thin ceiling (a high ceiling forgives a lot)
        reach = min(max((q["rank"] - apr) / S["reach"], 0.0), 1.0)       # going ahead of the model
        # Availability gets its own term rather than only leaking in through the
        # floor above, because it is a different failure. A weak floor means his
        # bad weeks are bad; this means there may not be a week at all. It is the
        # column that carries a player's injury history now that his projection
        # no longer does, so it is weighted to be felt -- a quarterback the fit
        # says lasts ten games gives up about a quarter of the available risk
        # score before anything else is counted.
        hurt = float(q.get("avail_risk") or 0.0)
        # A premium pick is risky when it's shaky (weak floor AND/OR no ceiling to
        # justify it), a reach past the model, or unlikely to be on the field.
        # High ceiling meaningfully offsets. Cheap picks stay low-risk by
        # definition -- you cannot be hurt by a pick you did not spend.
        q["_risk"] = cost * (0.30 * downside + 0.19 * no_upside
                             + 0.26 * reach + 0.25 * hurt)
        vg = apr - q["rank"]                     # +: falls past where model ranks him = value
        q["value_gap"] = int(vg)
        bar = S["gap_bar"]
        q["value_tag"] = "Value" if vg >= bar else ("Reach" if vg <= -bar else None)

    _risk_buckets(payload)

    for q in payload:                            # drop internal temporaries
        for t in ("_cscore", "_games", "_fpct", "_cpct", "_risk", "_fseason"):
            q.pop(t, None)

    # ---- VALUE IN POINTS, not in draft slots -------------------------------
    # The rank-space gap above says "he falls past where we rank him". This says
    # "he beats what his draft slot is historically worth, by N points a game" --
    # which is the version that decides a season.
    curve = adp_mod.fit_expectation_curve(
        adp_mod.load_adp_history(), _actual_ppg_by_season(weekly, scoring_rules, pos), pos
    )
    if not curve:
        # No history file (or it wouldn't join): fall back to the shape of THIS
        # year's market. Weaker -- it can only say "cheap for this year's price
        # curve" -- so the report labels it differently.
        bp = [(p, q["proj_ppg"]) for q in payload
              for p, _src in [_curve_pick(q)] if p is not None and q.get("proj_ppg") is not None]
        curve = adp_mod.fit_curve_from_board([p for p, _ in bp], [v for _, v in bp]) if bp else {}

    # Who was in the historical ADP file but never found in the stats. Lifted OFF
    # the curve so it stays a build-time diagnostic and never ships to the page,
    # but kept on the result so the build script can print it -- a name that
    # silently fails to join is the one failure mode this whole join has.
    result["curve_missed"] = curve.pop("missed_names", []) if curve else []

    for q in payload:
        pick, src = _curve_pick(q)
        exp = adp_mod.expected_fpg(pick, curve)
        if exp is None or q.get("proj_ppg") is None:
            q["exp_fpg"] = q["value_fpg"] = q["value_fpg_tag"] = q["value_fpg_src"] = None
            continue
        edge = float(q["proj_ppg"]) - exp
        q["exp_fpg"] = round(exp, 1)
        q["value_fpg"] = round(edge, 1)
        q["value_fpg_src"] = src
        q["value_fpg_tag"] = ("League winner" if edge >= LW_FPG_EDGE
                              else "Value" if edge >= VAL_FPG_EDGE
                              else "Pricey" if edge <= OVERPRICED_FPG else None)

    # ---- League-winner checklist (QUARTERBACKS ONLY) -----------------------
    # Every threshold below is a quarterback threshold. The running-back version
    # of this screen -- first four seasons in the league or already a previous
    # league-winner, plus the archetype curve -- needs the contract and XFP-share
    # data that tier 2 brings in, so for now an RB board simply carries no gate
    # rather than being graded against bars that were never about backs.
    if pos != "QB":
        for q in payload:
            q["lw_gate"] = None
            q["lw_gate_via"] = []
            q["lw_checks"] = []
            q["lw_score"] = 0
            q["lw_max"] = 0
        _flags(payload, pos, S)
        result["ratings_meta"] = {
            "adp_source": adp_mod.source_label(adp_df, pos),
            "pos": pos,
            "boom": [int(boom1), int(boom2)],
            "repl_rank": int(repl_rank),
            "teams": int(getattr(cfg, "LEAGUE", {}).get("teams", 12) or 12),  # see note below
            "n_with_adp": sum(1 for q in payload if q.get("adp_pos_rank")),
            "curve": curve or None,
            "lw_bars": {"fpg": LW_FPG_EDGE, "value_fpg": VAL_FPG_EDGE},
        }
        return result

    # Published thresholds, not vibes. Deliberately a CHECKLIST and not another
    # weighted factor: it answers "does he have the shape that wins leagues",
    # which is a different question from "how many points will he score" and
    # shouldn't be blended into it.
    #
    # STRUCTURE MATTERS HERE. The first two rows are Ryan Heath's two paths, and
    # he states them as a DISJUNCTION, verbatim: "There are still exactly two
    # paths to success in drafting a QB after Round 10: have 100+ rush attempts;
    # play for a 'McShanahan' tree playcaller. Every late-round QB to make the
    # playoffs in 45%+ of ESPN leagues since 2021 fits one of these two criteria."
    #
    # So they are a SCREEN, not a score. A pocket passer in a Shanahan offense
    # clears it outright; he is not half-qualified, and counting "1 of 4" at him
    # would invent a penalty the research does not contain. Clearing both paths
    # is not extra credit either -- Heath's claim is that one is enough. The two
    # remaining rows are supporting rushing evidence from elsewhere in the piece
    # and are marked as such, so the renderer can keep them visually subordinate.
    #
    # Scope caveat, carried into the UI: the screen is stated for QBs drafted
    # AFTER ROUND 10. It is not a law about every QB, and it isn't applied as a
    # filter -- for an early-round QB it is context, not a verdict.
    season = int(getattr(cfg, "UPCOMING_SEASON", latest + 1))
    playcallers = qb_blend.playcallers()
    for q in payload:
        pace, rfpg = q.get("rush_att_pace"), q.get("rush_fpg")
        pc = playcallers.get((season, q.get("team")))
        mcs = (pc["tree"] == MCSHANAHAN) if pc else None
        checks = [{
            "label": f"{RUSH_ATT_HIGH}+ rush att pace",
            "pass": (pace >= RUSH_ATT_HIGH) if pace is not None else None,
            "detail": (f"{pace:.0f} paced" if pace is not None else "no rushing history"),
            "why": "Elite designed-and-scramble usage — the volume tier league winners live in.",
            "group": "path",
        }, {
            "label": "McShanahan play-caller",
            "pass": mcs,
            "detail": (f"{pc['playcaller']} ({pc['role']})" if pc else "not tracked"),
            "why": ("Drafted QBs in the Shanahan/McVay tree beat their ADP expectation by "
                    f"{LW_FPG_EDGE:.0f}+ pts/gm 22.2% of the time, vs 6.5% everywhere else."),
            "group": "path",
        }, {
            "label": f"{RUSH_ATT_FLOOR}+ rush att pace",
            "pass": (pace >= RUSH_ATT_FLOOR) if pace is not None else None,
            "detail": (f"{pace:.0f} paced" if pace is not None else "—"),
            "why": "Under this there's no rushing cushion — passing alone has to carry him.",
            "group": "support",
        }, {
            "label": f"{RUSH_FPG_HIGH:.0f}+ rushing pts/gm",
            "pass": (rfpg >= RUSH_FPG_HIGH) if rfpg is not None else None,
            "detail": (f"{rfpg:.1f} pts/gm" if rfpg is not None else "—"),
            "why": "The production side of the same edge: points he scores without throwing.",
            "group": "support",
        }]
        paths = [c for c in checks if c["group"] == "path"]
        # None means "we couldn't measure it", which is NOT the same as False. A QB
        # only fails the screen when both paths were actually measured and both said
        # no; if either is unknown he stays unknown rather than being condemned on
        # missing data.
        q["lw_gate"] = (True if any(c["pass"] is True for c in paths)
                        else False if all(c["pass"] is False for c in paths) else None)
        q["lw_gate_via"] = [c["label"] for c in paths if c["pass"] is True]
        q["lw_checks"] = checks
        # Kept for continuity, but the UI leads with the gate: once the rows are a
        # disjunction plus supporting evidence, a flat "N of 4" is not a meaningful
        # summary of them.
        q["lw_score"] = sum(1 for c in checks if c["pass"] is True)
        q["lw_max"] = sum(1 for c in checks if c["pass"] is not None)

    # cheat-sheet "why" flags -- transparent, factor-based reasons, tone-coded.
    _flags(payload, pos, S)

    result["ratings_meta"] = {
        "adp_source": adp_mod.source_label(adp_df, pos),
        "pos": pos,
        "boom": [int(boom1), int(boom2)],
        "repl_rank": int(repl_rank),
        # League size, published separately from repl_rank on purpose. For a 1-QB
        # league the two happen to match (12 teams -> QB12) and the report used to
        # back league size out of the replacement rank. That coincidence does not
        # survive contact with running backs, where replacement is RB30 in the same
        # 12-team league, so the page reads the real number from here.
        "teams": int(getattr(cfg, "LEAGUE", {}).get("teams", 12) or 12),
        "n_with_adp": sum(1 for q in payload if q.get("adp_pos_rank")),
        "curve": curve or None,
        "lw_bars": {"fpg": LW_FPG_EDGE, "value_fpg": VAL_FPG_EDGE,
                    "att_floor": RUSH_ATT_FLOOR, "att_high": RUSH_ATT_HIGH,
                    "rush_fpg": RUSH_FPG_HIGH},
    }
    return result
