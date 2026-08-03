"""
Walk-forward validation of the QB model.

Freeze the model before each season, project that season with ZERO knowledge of
what happened, then compare to what actually happened. It is leak-free:

  * each QB's projection uses only seasons BEFORE the target year (the live
    model's `entering_profiles` already builds rows that way);
  * the archetype percentile pool for year T uses only seasons in [T-5, T-1];
  * the composite->points calibration is fit ONLY on seasons before T.

It reuses the exact live model (`qb_blend`) -- same factors, same weights, same
talent/archetype/rushing logic -- so it validates the real thing, not a copy.
The only stationary assumption is league-average TD-per-yard rates (used for TD
regression), which barely move year to year.

`run_backtest(...)` returns (per-QB results, per-year summary, pooled summary).
`render_html(...)` turns those into a self-contained report.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import qb_blend


def _spearman(x, y) -> float:
    x = pd.Series(np.asarray(x, dtype=float))
    y = pd.Series(np.asarray(y, dtype=float))
    ok = x.notna() & y.notna()
    if ok.sum() < 3:
        return float("nan")
    return float(np.corrcoef(x[ok].rank(), y[ok].rank())[0, 1])


def run_backtest(weekly, team_season, players, scoring, years=None, min_games=6):
    """Leak-free walk-forward. Returns (results_df, per_year_df, pooled_dict)."""
    sa = qb_blend.season_aggregates(weekly, scoring)
    seasons = sorted(int(s) for s in sa["season"].dropna().unique())
    if years is None:
        years = [s for s in seasons if (s - 1) in seasons][-5:]   # last 5 with a prior season

    rows, per_year = [], []
    for T in years:
        pool_T = sa[(sa["season"] >= T - qb_blend.RECENCY) & (sa["season"] < T) & (sa["games"] >= 8)]
        if pool_T.empty:
            continue
        prof = qb_blend.entering_profiles(sa, team_season, players, pool_T)
        if prof.empty:
            continue
        prof = qb_blend.add_indices(prof, qb_blend.DEFAULT_WEIGHTS)

        train = prof[(prof["season"] < T) & prof["actual_ppg"].notna()]
        if len(train) < 5:
            continue
        b, a = np.polyfit(train["composite"].to_numpy(), train["actual_ppg"].to_numpy(), 1)

        cur = prof[(prof["season"] == T) & (prof["career_games"] >= 8)].copy()
        if cur.empty:
            continue
        cur["pred"] = np.clip(a + b * cur["composite"], 0, None)

        gT = sa[sa["season"] == T][["player_id", "games"]].rename(columns={"games": "gT"})
        cur = cur.merge(gT, on="player_id", how="left")
        cur = cur[cur["gT"].fillna(0) >= min_games].copy()
        prev = sa[sa["season"] == T - 1][["player_id", "total_fp_pg"]].rename(columns={"total_fp_pg": "prev"})
        cur = cur.merge(prev, on="player_id", how="left")

        cur["actual"] = cur["actual_ppg"]
        cur["err"] = cur["pred"] - cur["actual"]
        cur["missed"] = (17 - cur["gT"]).clip(lower=0).round().astype(int)
        cur["pred_rank"] = cur["pred"].rank(ascending=False, method="first").astype(int)
        cur["actual_rank"] = cur["actual"].rank(ascending=False, method="first").astype(int)
        cur["year"] = T

        for _, r in cur.iterrows():
            rows.append({
                "year": T, "name": r.get("player_name"), "team": r.get("team"),
                "archetype": r.get("archetype"),
                "pred": round(float(r["pred"]), 2), "pred_rank": int(r["pred_rank"]),
                "actual": round(float(r["actual"]), 2), "actual_rank": int(r["actual_rank"]),
                "games": int(r["gT"]) if pd.notna(r["gT"]) else None,
                "missed": int(r["missed"]),
                "prev": round(float(r["prev"]), 2) if pd.notna(r["prev"]) else None,
                "err": round(float(r["err"]), 2),
            })

        bb = cur.dropna(subset=["prev"])
        per_year.append({
            "year": T, "n": int(len(cur)),
            "model_mae": float(cur["err"].abs().mean()),
            "base_mae": float((bb["prev"] - bb["actual"]).abs().mean()) if len(bb) else float("nan"),
            "model_rho": _spearman(cur["pred"], cur["actual"]),
            "base_rho": _spearman(bb["prev"], bb["actual"]) if len(bb) else float("nan"),
        })

    res = pd.DataFrame(rows)
    yr = pd.DataFrame(per_year)
    bb = res.dropna(subset=["prev"]) if len(res) else res
    pooled = {
        "n": int(len(res)),
        "years": list(yr["year"]) if len(yr) else [],
        "model_mae": float(res["err"].abs().mean()) if len(res) else float("nan"),
        "base_mae": float((bb["prev"] - bb["actual"]).abs().mean()) if len(bb) else float("nan"),
        "model_rho": _spearman(res["pred"], res["actual"]) if len(res) else float("nan"),
        "base_rho": _spearman(bb["prev"], bb["actual"]) if len(bb) else float("nan"),
    }
    # how often the model's top-12 preseason actually finished top-12
    if len(res):
        hit = res[(res["pred_rank"] <= 12)]
        pooled["top12_hitrate"] = float((hit["actual_rank"] <= 12).mean()) if len(hit) else float("nan")
        big = res[res["err"].abs() >= 5]
        pooled["big_miss_injury_share"] = float((big["missed"] >= 3).mean()) if len(big) else float("nan")
    return res, yr, pooled


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------
def _verdict(p: dict) -> str:
    mae_better = p["model_mae"] < p["base_mae"]
    rho_better = p["model_rho"] > p["base_rho"]
    mae_pct = 100 * (p["base_mae"] - p["model_mae"]) / p["base_mae"] if p["base_mae"] else 0
    parts = []
    if mae_better:
        parts.append(f"beats a naive &ldquo;repeat last year&rdquo; baseline on scoring accuracy by "
                     f"{mae_pct:.0f}% ({p['model_mae']:.2f} vs {p['base_mae']:.2f} pts/gm average error)")
    else:
        parts.append(f"is about even with the naive baseline on scoring accuracy "
                     f"({p['model_mae']:.2f} vs {p['base_mae']:.2f} pts/gm)")
    if rho_better:
        parts.append(f"and ranks QBs slightly better than it (rank-correlation {p['model_rho']:.2f} vs {p['base_rho']:.2f})")
    else:
        parts.append(f"and ranks QBs about as well as it (rank-correlation {p['model_rho']:.2f} vs {p['base_rho']:.2f})")
    inj = ""
    if p.get("big_miss_injury_share") == p.get("big_miss_injury_share"):  # not nan
        inj = (f" Of the biggest misses (5+ pts/gm off), {100*p['big_miss_injury_share']:.0f}% involved a QB who "
               f"missed 3+ games — i.e. injury, which no preseason model predicts.")
    return (f"Across {p['n']} quarterback-seasons ({'-'.join(str(y) for y in p['years'])}), the model " +
            ", ".join(parts) + "." + inj +
            " &ldquo;Repeat last year&rdquo; is a weak stand-in for real ADP consensus, so read this as a floor, "
            "not the final word on beating the market.")


def render_html(res: pd.DataFrame, yr: pd.DataFrame, pooled: dict, meta: dict | None = None) -> str:
    meta = meta or {}
    def tile(v, lab, good=None):
        col = "" if good is None else (";color:var(--good)" if good else ";color:var(--neg)")
        return f'<div class="stat"><b style="{col[1:] if col else ""}">{v}</b><span>{lab}</span></div>'
    tiles = (
        tile(f"{pooled['model_mae']:.2f}", "model error (MAE, pts/gm)", pooled["model_mae"] < pooled["base_mae"]) +
        tile(f"{pooled['base_mae']:.2f}", "&ldquo;repeat last year&rdquo; error") +
        tile(f"{pooled['model_rho']:.2f}", "model rank-corr", pooled["model_rho"] >= pooled["base_rho"]) +
        tile(f"{pooled['base_rho']:.2f}", "baseline rank-corr")
    )
    if pooled.get("top12_hitrate") == pooled.get("top12_hitrate"):
        tiles += tile(f"{100*pooled['top12_hitrate']:.0f}%", "preseason top-12 that finished top-12")

    ysum = "".join(
        f"<tr><td>{int(r.year)}</td><td class='num'>{int(r.n)}</td>"
        f"<td class='num'>{r.model_mae:.2f}</td><td class='num'>{r.base_mae:.2f}</td>"
        f"<td class='num'>{r.model_rho:.2f}</td><td class='num'>{r.base_rho:.2f}</td></tr>"
        for r in yr.itertuples()
    )

    sections = ""
    for T in (pooled["years"] or []):
        sub = res[res["year"] == T].sort_values("actual_rank")
        body = ""
        for r in sub.itertuples():
            ae = abs(r.err)
            ec = "var(--neg)" if ae >= 5 else ("var(--warn)" if ae >= 3 else "var(--good)")
            inj = f'<span class="inj">missed {r.missed}</span>' if r.missed and r.missed >= 2 else ""
            body += (
                f"<tr><td class='num'>{r.actual_rank}</td><td class='num mut'>{r.pred_rank}</td>"
                f"<td><b>{r.name}</b> <span class='mut'>{r.team or ''}</span> "
                f"<span class='arch'>{r.archetype or ''}</span>{inj}</td>"
                f"<td class='num'>{r.pred:.1f}</td><td class='num'>{r.actual:.1f}</td>"
                f"<td class='num' style='color:{ec}'>{'+' if r.err>=0 else ''}{r.err:.1f}</td></tr>"
            )
        sections += (
            f"<div class='card'><h3>{T}</h3>"
            "<table><thead><tr><th class='num'>Fin</th><th class='num'>Proj</th><th>Quarterback</th>"
            "<th class='num'>Pred</th><th class='num'>Actual</th><th class='num'>Err</th></tr></thead>"
            f"<tbody>{body}</tbody></table></div>"
        )

    return _TEMPLATE.replace("__TILES__", tiles).replace("__VERDICT__", _verdict(pooled)) \
        .replace("__YSUM__", ysum).replace("__SECTIONS__", sections) \
        .replace("__SUB__", meta.get("subline", "Walk-forward validation · full model · leak-free"))


_TEMPLATE = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>QB Model — Backtest</title>
<style>
:root{--bg:#f9f9f7;--surface:#fff;--ink:#0b0b0b;--ink2:#52514e;--mut:#898781;--bd:rgba(11,11,11,.10);
--good:#006300;--neg:#e34948;--warn:#a86a00;--accent:#256abf;--arch:#4a3aa7;--plane:#f2f2ef}
@media(prefers-color-scheme:dark){:root{--bg:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--mut:#898781;
--bd:rgba(255,255,255,.10);--good:#0ca30c;--neg:#e66767;--warn:#e6a93a;--plane:#141413}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.5}
.wrap{max-width:1000px;margin:0 auto;padding:26px 20px 80px}
h1{font-size:21px;margin:0 0 2px}.sub{color:var(--ink2);font-size:13.5px;margin:0 0 18px}
h2{font-size:16px;margin:0 0 10px}h3{font-size:14px;margin:0 0 10px;color:var(--mut);text-transform:uppercase;letter-spacing:.05em}
.card{background:var(--surface);border:1px solid var(--bd);border-radius:14px;padding:20px 22px;margin:0 0 16px}
p{color:var(--ink2);font-size:15px;margin:0 0 10px}p b{color:var(--ink)}
.stat{display:inline-flex;flex-direction:column;gap:2px;background:var(--plane);border:1px solid var(--bd);
border-radius:10px;padding:10px 16px;margin:4px 8px 4px 0}
.stat b{font-size:22px;font-variant-numeric:tabular-nums}.stat span{font-size:11.5px;color:var(--mut)}
table{width:100%;border-collapse:collapse;font-size:13.5px}
thead th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut);
font-weight:600;padding:0 9px 7px;border-bottom:1px solid var(--bd)}th.num{text-align:right}
tbody td{padding:7px 9px;border-bottom:1px solid var(--bd);vertical-align:middle}
.num{text-align:right;font-variant-numeric:tabular-nums}.mut{color:var(--mut)}
.arch{display:inline-block;font-size:10.5px;font-weight:600;color:#fff;background:var(--arch);border-radius:20px;padding:0 7px;margin-left:4px}
.inj{display:inline-block;font-size:10px;font-weight:600;color:var(--warn);border:1px solid var(--warn);border-radius:20px;padding:0 6px;margin-left:6px}
.grid{columns:2;column-gap:16px}@media(max-width:720px){.grid{columns:1}}.grid .card{break-inside:avoid}
</style></head><body><div class="wrap">
<h1>QB Model — 5-Year Backtest</h1><div class="sub">__SUB__</div>
<div class="card"><h2>How it did</h2><div>__TILES__</div>
<p style="margin-top:12px">__VERDICT__</p></div>
<div class="card"><h2>Year by year</h2>
<table><thead><tr><th class="num">Year</th><th class="num">QBs</th><th class="num">Model MAE</th>
<th class="num">Base MAE</th><th class="num">Model ρ</th><th class="num">Base ρ</th></tr></thead>
<tbody>__YSUM__</tbody></table>
<p class="sub" style="margin-top:10px">MAE = average points/gm the projection missed by (lower is better).
ρ = rank-correlation with the actual finish (higher is better). Baseline = &ldquo;repeat last year&rsquo;s PPG.&rdquo;
&ldquo;Fin&rdquo; is where he actually finished; &ldquo;Proj&rdquo; is where the model slotted him. Injury/missed-time flagged.</p></div>
<div class="grid">__SECTIONS__</div>
</div></body></html>"""
