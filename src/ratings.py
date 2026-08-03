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

All buckets are pool-relative (graded against this year's projected starters).
`attach(result, ...)` mutates the payload in place and returns it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import adp as adp_mod
from . import scoring

RECENCY = 5           # only the last N seasons of games count (matches talent)
DECAY = 0.82          # per-year recency decay on game weights
BOOM1, BOOM2 = 25.0, 30.0   # the two "huge game" thresholds
K_SHRINK = 10.0       # sample-size shrink strength (in recency-weighted games)
REPL_RANK = 12        # QB12 ~ replacement in a 12-team, 1QB league


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

    # cheat-sheet "why" flags -- transparent, factor-based reasons, tone-coded.
    for q in payload:
        ix = q.get("indices", {})
        cg, age = q.get("career_games"), q.get("age")
        f = []
        if cg is not None and 10 <= cg <= 40:
            f.append(["up", "Ascending"])        # the one profile the market underrates
        if ix.get("Rushing", 50) >= 72:
            f.append(["up", "Elite rusher"])
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
        q["flags"] = f[:5]

    result["ratings_meta"] = {
        "adp_source": adp_mod.source_label(adp_df),
        "boom": [int(BOOM1), int(BOOM2)],
        "n_with_adp": sum(1 for q in payload if q.get("adp_pos_rank")),
    }
    return result
