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
BOOM1, BOOM2 = 25.0, 30.0   # the two "huge game" thresholds
K_SHRINK = 10.0       # sample-size shrink strength (in recency-weighted games)
REPL_RANK = 12        # QB12 ~ replacement in a 12-team, 1QB league

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
def _game_fp(weekly: pd.DataFrame, rules: dict | None) -> pd.DataFrame:
    pos = _first(weekly, ["position", "position_group"]).astype(str).str.upper()
    st = _first(weekly, ["season_type"])
    m = (pos == "QB")
    if st is not None and st.notna().any():
        m = m & (st.astype(str).str.upper() == "REG")
    w = weekly[m]
    fp = scoring.compute_fantasy_points(w, rules).to_numpy()
    pid = _first(w, ["player_id", "gsis_id"]).astype(str).to_numpy()
    sea = pd.to_numeric(_first(w, ["season"]), errors="coerce").to_numpy()
    out = pd.DataFrame({"player_id": pid, "season": sea, "fp": fp})
    return out.dropna(subset=["season"])


def _actual_ppg_by_season(weekly: pd.DataFrame, rules: dict | None) -> dict:
    """{(season, normalized_name): actual REG-season fantasy pts/gm} for QBs.

    Keyed by NAME rather than player_id on purpose: the historical ADP file is a
    hand-kept list of names with no nflverse ids in it, and `adp.norm` is the
    same normalizer the live ADP join already uses.
    """
    pos = _first(weekly, ["position", "position_group"]).astype(str).str.upper()
    st = _first(weekly, ["season_type"])
    m = (pos == "QB")
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


def raw_metrics(gl: pd.DataFrame, latest: int) -> dict:
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
            "boom1": float(wt[fp >= BOOM1].sum() / n),
            "boom2": float(wt[fp >= BOOM2].sum() / n),
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
# main entry
# ---------------------------------------------------------------------------
def attach(result: dict, weekly: pd.DataFrame, scoring_rules: dict | None,
           adp_df: pd.DataFrame, cfg) -> dict:
    payload = result.get("payload", [])
    if not payload:
        return result

    gl = _game_fp(weekly, scoring_rules)
    latest = int(gl["season"].max()) if not gl.empty else int(getattr(cfg, "CURRENT_SEASON", 2025))
    raw = raw_metrics(gl, latest)

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

    # ADP -> per-platform QB ranks + a consensus anchor (drives value/risk).
    pranks = adp_mod.platform_qb_ranks(adp_df)
    crank, _cscore = adp_mod.consensus_ranks(adp_df, pranks)
    picks = adp_mod.raw_picks(adp_df)
    for q in payload:
        k = adp_mod.norm(q["name"])
        q["adp_platforms"] = {pf: pranks[pf].get(k) for pf in adp_mod.PLATFORMS}   # QB# per platform
        q["adp_picks"] = picks.get(k, {pf: None for pf in adp_mod.PLATFORMS})       # raw overall pick
        q["adp_pos_rank"] = int(crank[k]) if k in crank else None                   # consensus QB#
        q["adp_label"] = f"QB{q['adp_pos_rank']}" if q["adp_pos_rank"] else "UDFA"
        q["value_by_platform"] = {pf: (pranks[pf][k] - q["rank"])                   # +: falls past model
                                  for pf in adp_mod.PLATFORMS if k in pranks.get(pf, {})}

    # pool-relative floor & ceiling buckets
    _tertile(payload, "floor_pts", ["Risky", "Moderate", "Safe"], "floor_bucket")
    _tertile(payload, "_cscore", ["Low", "Medium", "High"], "ceiling_bucket")

    # risk at ADP
    _pctl(payload, "floor_pts", "_fpct")
    _pctl(payload, "_cscore", "_cpct")
    for q in payload:
        apr = q.get("adp_pos_rank")
        if not apr:
            q["risk_bucket"] = "Low"
            q["value_gap"] = None
            q["value_tag"] = None
            q["_risk"] = 0.0
            continue
        cost = min(max((REPL_RANK - apr) / (REPL_RANK - 1), 0.0), 1.0)   # QB1~1, QB12+~0
        downside = 1 - q["_fpct"]        # weak floor
        no_upside = 1 - q["_cpct"]       # thin ceiling (a high ceiling forgives a lot)
        reach = min(max((q["rank"] - apr) / 8.0, 0.0), 1.0)             # going ahead of the model
        # A premium pick is risky when it's shaky (weak floor AND/OR no ceiling to
        # justify it) or a reach past the model. High ceiling meaningfully offsets.
        q["_risk"] = cost * (0.40 * downside + 0.25 * no_upside + 0.35 * reach)
        vg = apr - q["rank"]                     # +: falls past where model ranks him = value
        q["value_gap"] = int(vg)
        q["value_tag"] = "Value" if vg >= 5 else ("Reach" if vg <= -5 else None)

    _risk_buckets(payload)

    for q in payload:                            # drop internal temporaries
        for t in ("_cscore", "_games", "_fpct", "_cpct", "_risk"):
            q.pop(t, None)

    # ---- VALUE IN POINTS, not in draft slots -------------------------------
    # The rank-space gap above says "he falls past where we rank him". This says
    # "he beats what his draft slot is historically worth, by N points a game" --
    # which is the version that decides a season.
    curve = adp_mod.fit_expectation_curve(
        adp_mod.load_adp_history(), _actual_ppg_by_season(weekly, scoring_rules)
    )
    if not curve:
        # No history file (or it wouldn't join): fall back to the shape of THIS
        # year's market. Weaker -- it can only say "cheap for this year's price
        # curve" -- so the report labels it differently.
        bp = [(p, q["proj_ppg"]) for q in payload
              for p, _src in [_curve_pick(q)] if p is not None and q.get("proj_ppg") is not None]
        curve = adp_mod.fit_curve_from_board([p for p, _ in bp], [v for _, v in bp]) if bp else {}

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

    # ---- League-winner checklist -------------------------------------------
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
    for q in payload:
        ix = q.get("indices", {})
        cg, age = q.get("career_games"), q.get("age")
        f = []
        if cg is not None and 10 <= cg <= 40:
            f.append(["up", "Ascending"])        # the one profile the market underrates
        if ix.get("Rushing", 50) >= 72:
            f.append(["up", "Elite rusher"])
        # League-winner reads, from the checklist above. "Elite rusher" is a
        # percentile (best of THIS field); these are absolute bars, so a whole
        # weak field can miss them and a whole strong one can clear them.
        # NOTE: the "+N over ADP" chip is deliberately NOT added here. It depends
        # on the projection, and the projection moves live when the reader drags
        # a weight slider -- so the report builds that chip in the browser from
        # the current weights. Everything below is weight-independent and safe
        # to bake in.
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
        if age is not None and age >= 34:
            f.append(["down", f"Age {age}"])
        q["flags"] = f[:6]

    result["ratings_meta"] = {
        "adp_source": adp_mod.source_label(adp_df),
        "boom": [int(BOOM1), int(BOOM2)],
        "n_with_adp": sum(1 for q in payload if q.get("adp_pos_rank")),
        "curve": curve or None,
        "lw_bars": {"fpg": LW_FPG_EDGE, "value_fpg": VAL_FPG_EDGE,
                    "att_floor": RUSH_ATT_FLOOR, "att_high": RUSH_ATT_HIGH,
                    "rush_fpg": RUSH_FPG_HIGH},
    }
    return result
