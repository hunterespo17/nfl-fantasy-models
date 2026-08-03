"""
HTML report for the QB index-blend model.

`render(result, meta)` returns one self-contained HTML string (CSS + JS inlined,
no network, no storage). The page has two tabs:

  How it works  -- explains the model and shows the factor weighting (% of 100).
  QB Rankings   -- the board, with LIVE weight sliders: drag a factor's weight
                   and the projections + ranking recompute in the browser.

All the math is embedded per QB as 0-100 factor indices plus a calibration
(a, b); the browser computes  pts = a + b * (sum(w*index)/sum(w))  on the fly.
"""
from __future__ import annotations

import json


def render(result: dict, meta: dict) -> str:
    payload = {
        "meta": meta,
        "qbs": result.get("payload", []),
        "weights": result.get("weights", {}),
        "groups": result.get("groups", []),
        "calib": result.get("calib", {"a": 0, "b": 0.25}),
        "backtest": result.get("backtest", {}),
    }
    return _TEMPLATE.replace("__DATA_JSON__", json.dumps(payload))


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en" data-theme="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NFL QB Projection Model</title>
<style>
  :root{
    --surface-1:#fcfcfb;--plane:#f9f9f7;--ink:#0b0b0b;--ink-2:#52514e;--muted:#898781;
    --grid:#e1e0d9;--baseline:#c3c2b7;--border:rgba(11,11,11,.10);
    --pos:#2a78d6;--neg:#e34948;--accent:#256abf;--accent-soft:#cde2fb;
    --t1:#184f95;--t2:#256abf;--t3:#5598e7;--t4:#9ec5f4;
    --arch:#4a3aa7;--good:#006300;
  }
  :root[data-theme="dark"]{
    --surface-1:#1a1a19;--plane:#0d0d0d;--ink:#fff;--ink-2:#c3c2b7;--muted:#898781;
    --grid:#2c2c2a;--baseline:#383835;--border:rgba(255,255,255,.10);
    --pos:#3987e5;--neg:#e66767;--accent:#3987e5;--accent-soft:#12233b;
    --t1:#9ec5f4;--t2:#5598e7;--t3:#3987e5;--t4:#184f95;--arch:#9085e9;--good:#0ca30c;
  }
  @media(prefers-color-scheme:dark){:root[data-theme="auto"]{
    --surface-1:#1a1a19;--plane:#0d0d0d;--ink:#fff;--ink-2:#c3c2b7;--muted:#898781;
    --grid:#2c2c2a;--baseline:#383835;--border:rgba(255,255,255,.10);
    --pos:#3987e5;--neg:#e66767;--accent:#3987e5;--accent-soft:#12233b;
    --t1:#9ec5f4;--t2:#5598e7;--t3:#3987e5;--t4:#184f95;--arch:#9085e9;--good:#0ca30c;}}
  *{box-sizing:border-box}
  body{margin:0;background:var(--plane);color:var(--ink);font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.5;-webkit-font-smoothing:antialiased}
  .wrap{max-width:1060px;margin:0 auto;padding:0 20px 80px}
  header{position:sticky;top:0;z-index:5;background:var(--plane);border-bottom:1px solid var(--border);padding:16px 0 0}
  .hgrid{max-width:1060px;margin:0 auto;padding:0 20px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
  h1{font-size:19px;margin:0;font-weight:650;letter-spacing:-.01em}
  .sub{color:var(--ink-2);font-size:13px;margin:2px 0 0}
  .spacer{flex:1}
  .tabs{display:flex;gap:4px;margin:14px 0 0}
  .tab{border:0;background:transparent;color:var(--ink-2);font:inherit;font-size:14px;font-weight:550;padding:10px 14px;border-bottom:2px solid transparent;cursor:pointer}
  .tab[aria-selected="true"]{color:var(--ink);border-bottom-color:var(--accent)}
  .toggle{border:1px solid var(--border);background:var(--surface-1);color:var(--ink-2);font:inherit;font-size:12px;padding:6px 10px;border-radius:8px;cursor:pointer}
  section{display:none;padding-top:24px}section.active{display:block}
  .card{background:var(--surface-1);border:1px solid var(--border);border-radius:14px;padding:22px 24px;margin:0 0 18px}
  h2{font-size:16px;font-weight:620;margin:0 0 12px;letter-spacing:-.01em}
  h3{font-size:12px;font-weight:600;margin:0 0 8px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
  p{margin:0 0 12px;color:var(--ink-2);font-size:14.5px}p strong{color:var(--ink);font-weight:600}
  .stat{display:inline-flex;gap:8px;align-items:baseline;background:var(--plane);border:1px solid var(--border);border-radius:10px;padding:8px 14px;margin:2px 8px 2px 0}
  .stat b{font-size:18px;font-variant-numeric:tabular-nums}.stat span{font-size:12px;color:var(--muted)}
  /* weight bars */
  .wrow{display:grid;grid-template-columns:120px 1fr 46px;gap:10px 12px;align-items:center;margin:7px 0}
  .wname{font-size:13.5px;color:var(--ink);text-align:right}
  .wtrack{height:12px;border-radius:6px;background:var(--grid);overflow:hidden}
  .wfill{height:100%;border-radius:6px;background:var(--accent)}
  .wpct{font-size:13px;color:var(--ink-2);font-variant-numeric:tabular-nums;text-align:right}
  .arraw{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
  .chip{font-size:12px;padding:3px 10px;border-radius:20px;background:var(--accent-soft);color:var(--accent);font-weight:600}
  /* controls / sliders */
  .panel{display:flex;flex-wrap:wrap;gap:14px 22px;align-items:flex-start}
  .slider{width:150px}
  .slider label{display:flex;justify-content:space-between;font-size:12px;color:var(--ink-2);margin-bottom:2px}
  .slider label b{color:var(--ink);font-variant-numeric:tabular-nums}
  .slider input{width:100%}
  .btn{border:1px solid var(--border);background:var(--surface-1);color:var(--ink-2);font:inherit;font-size:12.5px;padding:6px 12px;border-radius:8px;cursor:pointer}
  .search{font:inherit;font-size:14px;padding:8px 12px;border:1px solid var(--border);border-radius:9px;background:var(--surface-1);color:var(--ink);min-width:180px}
  /* table */
  table{width:100%;border-collapse:collapse;font-size:14px}
  thead th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:600;padding:0 10px 8px;border-bottom:1px solid var(--border);white-space:nowrap}
  thead th.num{text-align:right}
  tbody td{padding:11px 10px;border-bottom:1px solid var(--border);vertical-align:middle}
  tbody tr.row{cursor:pointer}tbody tr.row:hover{background:var(--plane)}
  .rank{font-variant-numeric:tabular-nums;color:var(--muted);width:30px}
  .qb b{font-weight:600}.qb .tm{color:var(--muted);font-size:12.5px;margin-left:3px}
  .archtag{display:inline-block;font-size:11px;font-weight:600;color:#fff;background:var(--arch);border-radius:20px;padding:1px 8px;margin-left:6px}
  .move{display:inline-block;font-size:10.5px;font-weight:600;color:var(--neg);border:1px solid var(--neg);border-radius:20px;padding:0 6px;margin-left:6px}
  .bdg{display:inline-block;font-size:11px;font-weight:600;border-radius:20px;padding:1px 9px;white-space:nowrap}
  .bdg.g{background:rgba(0,120,60,.14);color:var(--good)}
  .bdg.a{background:rgba(190,130,0,.16);color:#9a6600}
  .bdg.r{background:rgba(210,60,60,.14);color:var(--neg)}
  .bdg.n{background:var(--grid);color:var(--ink-2)}
  :root[data-theme="dark"] .bdg.a{color:#e6a93a}
  .adpcell{font-variant-numeric:tabular-nums;font-weight:600}
  .vtag{font-size:10px;font-weight:700;margin-left:5px;letter-spacing:.02em}
  .vt{font-size:9.5px;font-weight:700;padding:1px 5px;border-radius:20px;margin-left:6px;letter-spacing:.03em;vertical-align:middle;white-space:nowrap}
  .vt.g{background:rgba(0,120,60,.14);color:var(--good)}
  .vt.r{background:rgba(210,60,60,.14);color:var(--neg)}
  .pfr{font-variant-numeric:tabular-nums;font-size:13px}
  th.mkt,td.mkt{border-left:1px solid var(--border)}
  td.mkt{font-weight:600;color:var(--accent);font-variant-numeric:tabular-nums}
  .whycol{max-width:180px;line-height:1.9}
  .fl{display:inline-block;font-size:10.5px;font-weight:600;border-radius:20px;padding:1px 8px;white-space:nowrap}
  .fl.g{background:rgba(0,120,60,.13);color:var(--good)}
  .fl.a{background:rgba(190,130,0,.15);color:#9a6600}
  .fl.r{background:rgba(210,60,60,.13);color:var(--neg)}
  .fl.n{background:var(--grid);color:var(--ink-2)}
  :root[data-theme="dark"] .fl.a{color:#e6a93a}
  .sortsel{font:inherit;font-size:13px;padding:6px 9px;border:1px solid var(--border);border-radius:9px;background:var(--surface-1);color:var(--ink)}
  .ov{display:grid;grid-template-columns:132px 1fr;gap:8px 14px;font-size:14px;color:var(--ink-2)}
  .ov .ovh{color:var(--ink);font-weight:600}
  .num{text-align:right;font-variant-numeric:tabular-nums}
  .bartrack{display:inline-block;width:90px;height:8px;border-radius:4px;background:var(--grid);vertical-align:middle;margin-right:8px;overflow:hidden}
  .bar{height:8px;border-radius:4px;background:var(--accent);display:block}
  .tier{display:inline-block;min-width:20px;text-align:center;font-size:12px;font-weight:600;color:#fff;padding:2px 8px;border-radius:20px}
  .caret{color:var(--muted);display:inline-block;transition:transform .15s}tr.open .caret{transform:rotate(90deg)}
  .detail td{background:var(--plane);padding:0}
  .dbox{padding:18px 20px 22px}
  .dhead{display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:12px}
  .dhead .big{font-size:22px;font-weight:650;font-variant-numeric:tabular-nums}
  .legend{font-size:12px;color:var(--ink-2);display:flex;gap:14px;margin-bottom:8px}
  .sw{display:inline-block;width:10px;height:10px;border-radius:3px;vertical-align:middle;margin-right:5px}
  .wf{display:grid;grid-template-columns:110px 34px 1fr 60px;gap:7px 10px;align-items:center}
  .wf .lab{font-size:12.5px;color:var(--ink-2);text-align:right}
  .wf .idx{font-size:11px;color:var(--muted);text-align:right;font-variant-numeric:tabular-nums}
  .wtk{position:relative;height:18px;background:linear-gradient(var(--grid),var(--grid)) center/100% 1px no-repeat}
  .wmid{position:absolute;top:0;bottom:0;left:50%;width:1px;background:var(--baseline)}
  .wb{position:absolute;top:3px;height:12px;border-radius:3px}
  .wf .v{font-size:12.5px;font-variant-numeric:tabular-nums}
  .feat{margin-top:16px}.feat table{font-size:13px}.feat td{padding:5px 10px;border-bottom:1px solid var(--border)}
  .feat .k{color:var(--ink-2)}.feat .v{text-align:right;font-variant-numeric:tabular-nums}
  .note{color:var(--muted);font-size:12.5px;margin-top:14px}
  .pill{display:inline-block;font-size:11px;font-weight:600;padding:2px 8px;border-radius:20px;margin-left:6px;background:var(--accent-soft);color:var(--accent)}
  @media(max-width:640px){.wname{width:auto}}
</style>
</head>
<body>
<header>
  <div class="hgrid">
    <div><h1>NFL QB Projection Model <span class="pill" id="seasonPill"></span></h1>
      <div class="sub" id="subline"></div></div>
    <div class="spacer"></div>
    <button class="toggle" id="themeBtn" type="button">◑ Theme</button>
  </div>
  <div class="hgrid"><div class="tabs" role="tablist">
    <button class="tab" role="tab" data-tab="overview" aria-selected="true">How it works</button>
    <button class="tab" role="tab" data-tab="rankings" aria-selected="false">QB Rankings</button>
  </div></div>
</header>

<div class="wrap">
  <section id="overview" class="active">
    <div class="card">
      <h2>What this model does</h2>
      <p>It projects each quarterback's <strong>fantasy points</strong> as a transparent blend of factors —
      <strong>who the player is</strong> and <strong>the situation he's in</strong>. Every factor is scored
      0–100 (his percentile among QBs), then combined with the weights below. Nothing is a black box: you can
      see exactly how much each factor counts, and change it on the <strong>QB Rankings</strong> tab.</p>
      <div id="btstat"></div>
    </div>
    <div class="card">
      <h2>Factor weighting</h2>
      <p>What share of the projection each factor drives, out of 100%. Talent and archetype anchor the board.
      Talent is built from each QB's <strong>last three healthy seasons</strong> (12+ games, never reaching back
      more than five years) with <strong>touchdown luck regressed out</strong>, and thin résumés are pulled toward
      the field — so a sustained elite isn't sunk by one injury year, and a small hot sample can't crown someone.
      There is deliberately <strong>no "recent form" factor</strong>.</p>
      <div id="weightBars"></div>
    </div>
    <div class="card">
      <h2>Archetypes</h2>
      <p>Each QB is bucketed by his rushing and passing value — touchdowns regressed toward what his yardage
      predicts — measured against the <strong>last five seasons</strong> of QB play. Style predicts fantasy value.
      <strong>Konami</strong> (top-20% rushing <em>and</em> top-30% passing) is deliberately exclusive: only
      genuinely game-breaking dual-threats qualify.</p>
      <div class="arraw">
        <span class="chip">Konami — elite pass + rush</span>
        <span class="chip">Rushing QB</span>
        <span class="chip">Dual-Threat</span>
        <span class="chip">Pocket Passer</span>
        <span class="chip">Game Manager</span>
        <span class="chip">Bridge / Rookie</span>
      </div>
    </div>
    <div class="card">
      <h2>Draft overlays — floor, ceiling, ADP &amp; risk</h2>
      <p>Beyond the projection, each QB gets four quick read-outs. These <strong>don't change the projection</strong> —
      they sit on top of it to help you draft:</p>
      <div class="ov">
        <div class="ovh">Floor</div><div>His bad-week baseline — the recency-weighted 25th-percentile game he turns in.
          Graded <b style="color:var(--good)">Safe</b> / <b style="color:#9a6600">Moderate</b> / <b style="color:var(--neg)">Risky</b> vs the field.</div>
        <div class="ovh">Ceiling</div><div>How often he pops: share of games over <b>25</b> and <b>30</b> points
          (recent games count more; thin samples pulled toward the field). <b>High</b> / <b>Medium</b> / <b>Low</b>.</div>
        <div class="ovh">ADP</div><div>Where he's drafted on each platform, as a QB rank — <b>Sleeper</b>, <b>ESPN</b> &amp; <b>FFC</b> (redraft) and
          <b>Underdog</b> (best-ball). The pools differ sharply — ESPN fades QBs hardest, Sleeper takes them earliest.
          The <b>Market</b> column is a neutral reference — the average of <b>Underdog</b> (best-ball) and <b>FFC</b> (season-long), spanning both formats.
          Set <b>&ldquo;Drafting on&rdquo;</b> to your platform and the <b style="color:var(--good)">▲Value</b> /
          <b style="color:var(--neg)">▼Reach</b> tag flags who your platform drafts <b>earlier or later than that Market</b> — where it's out of step.
          Leave it on <b>Consensus</b> to compare the model to the market instead; open a row for the full gap.</div>
        <div class="ovh">Risk at ADP</div><div>Whether his price is worth it: paying an early pick for a shaky floor or thin
          ceiling — or reaching past where the model ranks him — is risky. A cheap QB is low-risk by definition.</div>
      </div>
    </div>
    <div class="card">
      <h2>Using this as a draft cheat sheet</h2>
      <p>A leak-free 4-year backtest is blunt about one thing: <strong>ADP already out-ranks this model</strong> — the market
      prices in everything the model sees plus offseason news, so don't draft <em>against</em> consensus on the model's say-so
      alone. Use the board like this instead:</p>
      <div class="ov">
        <div class="ovh">ADP is the backbone</div><div>Start from the <b>Market</b> column (Underdog + FFC blended) — that's the neutral anchor. Set <b>&ldquo;Drafting on&rdquo;</b> to your platform to see who your platform prices as a value or reach <em>versus that market</em>.</div>
        <div class="ovh">Floor / Ceiling / Risk</div><div>The draft <em>context</em> a raw ADP number can't give you: how safe his week-to-week floor is, how often he pops, and whether his price is worth it.</div>
        <div class="ovh">&ldquo;Why&rdquo; flags</div><div>The transparent reasons behind a profile:
          <span class="fl g">Ascending</span> <span class="fl g">Elite rusher</span> <span class="fl g">Strong team</span>
          <span class="fl r">Weak team</span> <span class="fl r">Thin cast</span> <span class="fl a">New team</span>.
          Vegas win totals now feed the team flags (and a Vegas factor is in the blend).</div>
        <div class="ovh">The one real edge</div><div><span class="fl g">Ascending</span> (year 2–3 QBs) is the single spot the backtest found the <em>market itself</em> underrates. Treat it as a genuine lean; the other flags are for understanding, not overrides.</div>
      </div>
    </div>
    <div class="card">
      <h2>Honest limitations</h2>
      <p>NFL scoring is noisy — treat this as an <strong>edge, not gospel</strong>. Offensive-line quality and a
      brand-new coordinator's exact tendencies aren't cleanly available in free data, so they're
      <strong>proxied</strong> (sack rate, measured team tendencies). Players who just changed teams are
      <strong>flagged</strong>, and their team-based factors are shrunk toward neutral because their new spot is
      uncertain. Rookies with no NFL history aren't projected yet.</p>
    </div>
  </section>

  <section id="rankings">
    <div class="card">
      <h2>Tune the weights</h2>
      <p style="margin-bottom:14px">Drag any factor and the projections and ranking update instantly. This is the
      model's mix, in your hands.</p>
      <div class="panel" id="sliders"></div>
      <div style="margin-top:14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <button class="btn" id="reset">Reset to defaults</button>
        <label class="note" style="margin:0">Drafting on&nbsp;<select class="sortsel" id="platsel"></select></label>
        <label class="note" style="margin:0">Sort&nbsp;
          <select class="sortsel" id="sortsel">
            <option value="proj">Projection</option>
            <option value="adp">ADP (consensus)</option>
            <option value="market">Market (UD+FFC)</option>
            <option value="value">Value vs market</option>
            <option value="floor">Floor</option>
            <option value="ceiling">Ceiling</option>
            <option value="risk">Risk</option>
          </select></label>
        <input class="search" id="search" type="search" placeholder="Search a QB…" aria-label="Search">
        <span class="note" style="margin:0">Click a row for the full breakdown.</span>
      </div>
    </div>
    <div class="card" style="padding:14px 16px">
      <table id="tbl"><thead id="thead"></thead><tbody id="tbody"></tbody></table>
    </div>
    <p class="note" id="rnote"></p>
  </section>
</div>

<script>
const DATA = __DATA_JSON__;
const $=s=>document.querySelector(s);
const fmt=(n,d=1)=>(n==null||isNaN(n))?"–":Number(n).toFixed(d);
const GROUPS=DATA.groups.length?DATA.groups:Object.keys(DATA.weights);
const A=DATA.calib.a, B=DATA.calib.b;
let weights=Object.assign({}, DATA.weights);

$("#seasonPill").textContent=DATA.meta.season_label||"";
$("#subline").textContent=DATA.meta.subline||"";
$("#rnote").textContent=DATA.meta.note||"";
if(DATA.backtest && DATA.backtest.model_mae!=null){
  $("#btstat").innerHTML=`<div class="stat"><b>${fmt(DATA.backtest.model_mae,2)}</b><span>model error (MAE, pts/gm)</span></div>`+
    `<div class="stat"><b>${fmt(DATA.backtest.baseline_mae,2)}</b><span>last-year-repeats baseline</span></div>`+
    `<div class="note">Backtested on ${(DATA.backtest.seasons||[]).join(" & ")} — lower is better.</div>`;
}

document.querySelectorAll(".tab").forEach(t=>t.onclick=()=>{
  document.querySelectorAll(".tab").forEach(x=>x.setAttribute("aria-selected",x===t));
  document.querySelectorAll("section").forEach(s=>s.classList.toggle("active",s.id===t.dataset.tab));
});
const root=document.documentElement;
$("#themeBtn").onclick=()=>{const c=root.getAttribute("data-theme");
  root.setAttribute("data-theme",c==="auto"?"light":c==="light"?"dark":"auto");
  $("#themeBtn").textContent="◑ "+root.getAttribute("data-theme");};

function sumW(){return GROUPS.reduce((a,g)=>a+(weights[g]||0),0)||1;}
function composite(q){const s=sumW();return GROUPS.reduce((a,g)=>a+(weights[g]||0)*(q.indices[g]??50),0)/s;}
function projOf(q){return Math.max(0, A + B*composite(q));}

function weightBars(){
  const s=sumW();
  $("#weightBars").innerHTML=GROUPS.map(g=>{
    const pct=100*(weights[g]||0)/s;
    return `<div class="wrow"><div class="wname">${g}</div>
      <div class="wtrack"><div class="wfill" style="width:${pct.toFixed(1)}%"></div></div>
      <div class="wpct">${pct.toFixed(0)}%</div></div>`;
  }).join("");
}

function sliders(){
  $("#sliders").innerHTML=GROUPS.map(g=>{
    const s=sumW(), pct=100*(weights[g]||0)/s;
    return `<div class="slider"><label>${g} <b data-w="${g}">${pct.toFixed(0)}%</b></label>
      <input type="range" min="0" max="40" step="1" value="${weights[g]||0}" data-g="${g}"></div>`;
  }).join("");
  document.querySelectorAll('#sliders input').forEach(inp=>inp.oninput=()=>{
    weights[inp.dataset.g]=Number(inp.value); refresh();
  });
}
function syncSliderLabels(){const s=sumW();
  document.querySelectorAll('#sliders b[data-w]').forEach(b=>b.textContent=(100*(weights[b.dataset.w]||0)/s).toFixed(0)+"%");}

const REPL=11; // replacement level ~ QB12 (12-team, 1QB)
function tiers(sorted){ // gap-based on proj
  const v=sorted.map(q=>q._p); if(v.length<2){sorted.forEach(q=>q._tier=1);return;}
  const d=[];for(let i=1;i<v.length;i++)d.push(v[i-1]-v[i]);
  const mean=d.reduce((a,x)=>a+x,0)/d.length, sd=Math.sqrt(d.reduce((a,x)=>a+(x-mean)**2,0)/d.length);
  let t=1;sorted[0]._tier=1;for(let i=1;i<v.length;i++){if(d[i-1]>mean+sd)t++;sorted[i]._tier=t;}
}
function tierColor(t){return ["var(--t1)","var(--t2)","var(--t3)","var(--t4)"][Math.min((t||1)-1,3)];}

// ---- draft-overlay rendering (floor / ceiling / adp / risk) ----
const FCLS={Safe:"g",Moderate:"a",Risky:"r"};
const CCLS={High:"g",Medium:"a",Low:"r"};
const RCLS={Low:"g",Moderate:"a",High:"r"};
function bdg(t,cls){return t?`<span class="bdg ${cls||'n'}">${t}</span>`:'<span class="bdg n">–</span>';}
const PLABEL={sleeper:"Sleeper",underdog:"Underdog",espn:"ESPN",ffc:"FFC",yahoo:"Yahoo",cbs:"CBS"};
const PLATS=(DATA.qbs.length&&DATA.qbs[0].adp_platforms)?Object.keys(DATA.qbs[0].adp_platforms):[];
// "Market" = re-ranked average of Underdog (best-ball) + FFC (season-long) QB ranks.
// A neutral reference spanning both draft formats. Sleeper/ESPN are the platforms you
// draft on and check AGAINST this market; the market itself is built only from UD+FFC.
const MKT_SRC=["underdog","ffc"].filter(p=>PLATS.includes(p));
const NCOL=8+PLATS.length+(MKT_SRC.length?1:0);   // +1 for the Market column
let draftPlatform="consensus";
(function(){
  const scored=DATA.qbs.map(x=>{
    const rs=MKT_SRC.map(p=>x.adp_platforms&&x.adp_platforms[p]).filter(v=>v!=null);
    x._mktScore=rs.length?rs.reduce((a,b)=>a+b,0)/rs.length:null; return x;
  }).filter(x=>x._mktScore!=null).sort((a,b)=>a._mktScore-b._mktScore);
  scored.forEach((x,i)=>{x._market=i+1;});   // clean market QB# 1..N
})();
function pfRank(x,pf){const r=x.adp_platforms&&x.adp_platforms[pf];
  if(!r)return '<span class="pfr" style="color:var(--muted)">—</span>';
  return `<span class="pfr"${pf===draftPlatform?' style="font-weight:700;color:var(--accent)"':''}>QB${r}</span>`;}
// Value/Reach is mode-aware: "consensus" = model vs the whole market; a platform =
// that platform's price vs the MARKET column (Underdog + FFC blend). A player is a
// reach on a platform when that platform drafts him EARLIER than the market, a value
// when it lets him fall LATER — i.e. that platform is out of step with the market.
function platEdge(x){
  if(draftPlatform==="consensus")return {tag:x.value_tag,gap:x.value_gap,mode:"c"};
  const mine=x.adp_platforms&&x.adp_platforms[draftPlatform], mkt=x._market;
  if(mine==null)return {tag:null,mine:null,mkt:mkt==null?null:mkt,mode:"p"};
  if(mkt==null)return {tag:null,mine,mkt:null,mode:"p"};
  const gap=mkt-mine;   // + => platform drafts him earlier than the market => reach
  return {tag:gap>=2?"Reach":gap<=-2?"Value":null, gap, mine, mkt, mode:"p"};
}
function valueTag(x){const e=platEdge(x);if(!e||!e.tag)return '';
  return e.tag==="Value"?' <span class="vt g">▲ VALUE</span>':' <span class="vt r">▼ REACH</span>';}
// detail-panel line: how the selected platform prices him vs the market (UD+FFC blend)
function platEdgeLine(o){
  if(draftPlatform==="consensus")return "";
  const lab=PLABEL[draftPlatform]||draftPlatform, e=platEdge(o);
  if(e.mine==null)return `<div class="ovh">On ${lab}</div><div><span style="color:var(--muted)">not ranked on ${lab}</span></div>`;
  if(e.mkt==null)return `<div class="ovh">On ${lab}</div><div><b>QB${e.mine}</b> <span style="color:var(--muted)">— no market price to compare</span></div>`;
  let verdict;
  if(e.gap>=2)verdict=`<span style="color:var(--neg)">▼ ${fmt(Math.abs(e.gap),0)} spots earlier than the market — reach on ${lab}</span>`;
  else if(e.gap<=-2)verdict=`<span style="color:var(--good)">▲ ${fmt(Math.abs(e.gap),0)} spots later than the market — value on ${lab}</span>`;
  else verdict=`<span style="color:var(--muted)">in line with the market</span>`;
  return `<div class="ovh">On ${lab}</div><div><b>QB${e.mine}</b> here vs market <b>QB${e.mkt}</b> <span style="color:var(--muted)">(Underdog + FFC)</span> — ${verdict}</div>`;
}
const FLAGCLS={up:"g",down:"r",warn:"a"};
function flagChips(x){const f=x.flags||[];if(!f.length)return '<span class="mut" style="font-size:11px">—</span>';return f.map(t=>`<span class="fl ${FLAGCLS[t[0]]||'n'}">${t[1]}</span>`).join(" ");}
const PF=PLATS.map(p=>[p,PLABEL[p]||p]);
function adpBreakdown(o){return PF.map(([k,lab])=>{const r=o.adp_platforms&&o.adp_platforms[k],pk=o.adp_picks&&o.adp_picks[k];if(!r)return `<span style="color:var(--muted)">${lab} —</span>`;return `${lab} <b>QB${r}</b>${pk!=null?` <span style="color:var(--muted)">(${fmt(pk,0)})</span>`:''}`;}).join(' &nbsp;·&nbsp; ');}
function valueByPlatform(o){if(!o.value_by_platform)return "";const parts=PF.filter(([k])=>o.value_by_platform[k]!=null).map(([k,lab])=>{const g=o.value_by_platform[k];const col=g>=5?'var(--good)':g<=-5?'var(--neg)':'var(--ink-2)';return `${lab} <span style="color:${col}">${g>0?'+':''}${g}</span>`;});return parts.length?`<div style="margin-top:5px;font-size:12.5px;color:var(--muted)">Model vs platform (QB spots, + = value): ${parts.join(' &nbsp; ')}</div>`:"";}
function adpCell(x){
  if(!x.adp_label||x.adp_label==="UDFA")return '<span class="adpcell" style="color:var(--muted);font-weight:400">UDFA</span>';
  let tag="";
  if(x.value_tag==="Value")tag=' <span class="vtag" style="color:var(--good)">▲VALUE</span>';
  else if(x.value_tag==="Reach")tag=' <span class="vtag" style="color:var(--neg)">▼REACH</span>';
  return `<span class="adpcell">${x.adp_label}</span>${tag}`;
}
function valueLine(o){
  if(o.value_gap==null)return "";
  if(o.value_gap>=5)return ` · <span style="color:var(--good)">model ${o.value_gap} spots higher — value</span>`;
  if(o.value_gap<=-5)return ` · <span style="color:var(--neg)">model ${Math.abs(o.value_gap)} spots lower — reach</span>`;
  return " · in line with the model";
}
function riskWhy(o){
  if(!o.adp_pos_rank)return "undrafted — no cost, no risk";
  if(o.risk_bucket==="Low")return "cheap or safe enough that the pick can't really hurt";
  const b=[];
  if(o.floor_bucket==="Risky")b.push("shaky floor");
  if(o.ceiling_bucket==="Low")b.push("limited ceiling");
  if(o.value_gap!=null&&o.value_gap<=-5)b.push("going ahead of the model");
  return (o.risk_bucket==="High"?"expensive, with ":"some cost, with ")+(b.length?b.join(", "):"only modest upside");
}
function overlays(o){
  return `<div class="ov" style="margin:2px 0 16px">
    <div class="ovh">Draft slot (ADP)</div><div>${adpBreakdown(o)}${o._market?` &nbsp;·&nbsp; <b style="color:var(--accent)">Market QB${o._market}</b>`:''}<div style="margin-top:3px">consensus <b>${o.adp_label||"UDFA"}</b>${valueLine(o)}</div>${valueByPlatform(o)}</div>
    ${platEdgeLine(o)}
    <div class="ovh">Floor</div><div>${bdg(o.floor_bucket,FCLS[o.floor_bucket])} <span style="color:var(--muted)">bad-week baseline ≈ ${fmt(o.floor_pts,1)} pts/gm</span></div>
    <div class="ovh">Ceiling</div><div>${bdg(o.ceiling_bucket,CCLS[o.ceiling_bucket])} <span style="color:var(--muted)">${o.boom25!=null?o.boom25:"–"}% of games 25+, ${o.boom30!=null?o.boom30:"–"}% 30+</span></div>
    <div class="ovh">Risk at ADP</div><div>${bdg(o.risk_bucket,RCLS[o.risk_bucket])} <span style="color:var(--muted)">${riskWhy(o)}</span></div>
    <div class="ovh">Tier / VOR</div><div>Tier ${o._tier||"–"} <span style="color:var(--muted)">·</span> ${o._vor!=null?fmt(o._vor*17,0)+" pts over replacement (season)":"–"}</div>
  </div>`;
}
const SORD={Safe:3,Moderate:2,Risky:1,High:3,Medium:2,Low:1};
const RORD={High:3,Moderate:2,Low:1};
const pfr=(x,pf)=>(x.adp_platforms&&x.adp_platforms[pf])||999;
function sortCmp(m){
  if(PLATS.includes(m))return (a,b)=>(pfr(a,m)-pfr(b,m))||(b._p-a._p);
  return ({
  proj:(a,b)=>b._p-a._p,
  adp:(a,b)=>((a.adp_pos_rank||999)-(b.adp_pos_rank||999))||(b._p-a._p),
  market:(a,b)=>((a._market||999)-(b._market||999))||(b._p-a._p),
  value:(a,b)=>{const ga=platEdge(a).gap,gb=platEdge(b).gap;return ((gb==null?-99:gb)-(ga==null?-99:ga))||(b._p-a._p);},
  floor:(a,b)=>((SORD[b.floor_bucket]||0)-(SORD[a.floor_bucket]||0))||((b.floor_pts||0)-(a.floor_pts||0)),
  ceiling:(a,b)=>((SORD[b.ceiling_bucket]||0)-(SORD[a.ceiling_bucket]||0))||(((b.boom25||0)+(b.boom30||0))-((a.boom25||0)+(a.boom30||0))),
  risk:(a,b)=>((RORD[b.risk_bucket]||0)-(RORD[a.risk_bucket]||0))||(b._p-a._p),
})[m]||((a,b)=>b._p-a._p);}
let sortMode="proj";

function detail(q,maxAbs){
  const pts0=Math.max(0,A+B*50), s=sumW();
  const contribs=GROUPS.map(g=>({g,c:B*((weights[g]||0)/s)*((q.indices[g]??50)-50),idx:q.indices[g]??50}));
  const mA=Math.max(1,...contribs.map(x=>Math.abs(x.c)));
  const rows=contribs.map(x=>{const col=x.c>=0?"var(--pos)":"var(--neg)";
    const half=Math.max(2,Math.round(46*Math.abs(x.c)/mA));
    const st=x.c>=0?`left:50%;width:${half}%;background:${col}`:`right:50%;width:${half}%;background:${col}`;
    return `<div class="lab">${x.g}</div><div class="idx">${x.idx.toFixed(0)}</div>
      <div class="wtk"><div class="wmid"></div><div class="wb" style="${st}"></div></div>
      <div class="v" style="color:${col}">${x.c>=0?"+":""}${fmt(x.c)}</div>`;}).join("");
  const feats=Object.entries(q.signals||{}).map(([k,v])=>`<tr><td class="k">${k}</td><td class="v">${fmt(v,2)}</td></tr>`).join("");
  return `<div class="dhead"><div><h3>${q.name} — ${q.archetype||""}</h3>
      <div style="font-size:12.5px;color:var(--muted)">index 50 = league-average QB · bars are points added vs. average at the current weights</div></div>
    <div style="text-align:right"><div class="big">${fmt(q._p)}<span style="font-size:13px;color:var(--muted);font-weight:400"> pts/gm</span></div>
      <div style="font-size:12px;color:var(--muted)">avg QB ≈ ${fmt(pts0)}</div></div></div>
    ${overlays(q)}
    <div class="legend"><span><span class="sw" style="background:var(--pos)"></span>boosts</span>
      <span><span class="sw" style="background:var(--neg)"></span>lowers</span>
      <span style="color:var(--muted)">middle column = 0–100 factor index</span></div>
    <div class="wf">${rows}</div>
    ${feats?`<div class="feat"><h3>Underlying inputs</h3><table>${feats}</table></div>`:""}`;
}

function refresh(){
  const q=($("#search").value||"").trim().toLowerCase();
  const rows=DATA.qbs.map(x=>{x._p=projOf(x);return x;}).filter(x=>!q||x.name.toLowerCase().includes(q));
  const all=DATA.qbs.slice().sort((a,b)=>b._p-a._p);
  const replPts=all.length?all[Math.min(REPL,all.length-1)]._p:0;
  rows.sort(sortCmp(sortMode));
  tiers(all);
  const maxP=Math.max(...DATA.qbs.map(x=>x._p),1);
  $("#tbody").innerHTML=rows.map((x)=>{
    const rank=all.indexOf(x)+1, vor=x._p-replPts, w=Math.max(2,Math.round(90*x._p/maxP));
    x._vor=vor;
    return `<tr class="row" data-id="${x.rank}">
      <td class="rank num">${rank}</td>
      <td class="qb"><b>${x.name}</b><span class="tm">${x.team||""}</span>
        <span class="archtag">${x.archetype||""}</span>${x.mover?'<span class="move">NEW</span>':''}${valueTag(x)}</td>
      <td class="num"><span class="bartrack"><span class="bar" style="width:${w}px"></span></span>${fmt(x._p)}</td>
      ${PLATS.map(p=>`<td class="num">${pfRank(x,p)}</td>`).join("")}
      ${MKT_SRC.length?`<td class="num mkt">${x._market?('QB'+x._market):'<span style="color:var(--muted)">—</span>'}</td>`:""}
      <td>${bdg(x.floor_bucket,FCLS[x.floor_bucket])}</td>
      <td>${bdg(x.ceiling_bucket,CCLS[x.ceiling_bucket])}</td>
      <td>${bdg(x.risk_bucket,RCLS[x.risk_bucket])}</td>
      <td class="whycol">${flagChips(x)}</td>
      <td class="num"><span class="caret">▸</span></td></tr>
      <tr class="detail" data-for="${x.rank}" style="display:none"><td colspan="${NCOL}"><div class="dbox">${detail(x)}</div></td></tr>`;
  }).join("");
  document.querySelectorAll("tr.row").forEach(tr=>tr.onclick=()=>{
    const d=document.querySelector(`tr.detail[data-for="${tr.dataset.id}"]`);
    const open=d.style.display!=="none";d.style.display=open?"none":"table-row";tr.classList.toggle("open",!open);
  });
  weightBars(); syncSliderLabels();
}

function header(){
  const pf=PLATS.map(p=>`<th class="num" title="${PLABEL[p]||p} ADP, as a QB rank">${PLABEL[p]||p}</th>`).join("");
  const mkt=MKT_SRC.length?`<th class="num mkt" title="Market = average of Underdog (best-ball) + FFC (season-long) QB ranks">Market</th>`:"";
  $("#thead").innerHTML=`<tr><th class="num">#</th><th>Quarterback</th><th class="num">Proj</th>${pf}${mkt}`+
    `<th>Floor</th><th>Ceiling</th><th>Risk</th><th>Why</th><th></th></tr>`;
}
$("#search").oninput=refresh;
$("#sortsel").onchange=e=>{sortMode=e.target.value;refresh();};
// inject one "<Platform> ADP" sort option per platform, before the Floor option
(function(){const anchor=[...$("#sortsel").options].find(o=>o.value==="floor");
  PLATS.forEach(p=>{const o=document.createElement("option");o.value=p;o.textContent=(PLABEL[p]||p)+" ADP";
    $("#sortsel").insertBefore(o,anchor);});})();
$("#platsel").innerHTML='<option value="consensus">Consensus</option>'+PLATS.map(p=>`<option value="${p}">${PLABEL[p]||p}</option>`).join("");
$("#platsel").onchange=e=>{draftPlatform=e.target.value;refresh();};
$("#reset").onclick=()=>{weights=Object.assign({},DATA.weights);sliders();refresh();};
header(); sliders(); weightBars(); refresh();
</script>
</body>
</html>
"""
