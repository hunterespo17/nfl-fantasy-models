"""
HTML report for the QB index-blend model.

`render(result, meta)` returns one self-contained HTML string (CSS + JS inlined,
no storage). It makes three kinds of network request, all optional: team logos
and player headshots from ESPN's image CDN (each has a text fallback -- team
abbreviation / initials avatar), and one small request for this page's own URL
to check whether a newer build has been published (see "freshness check" in the
script below). With no internet, all three fail quietly and the board renders
exactly as it did before any of them existed. The page has two tabs:

  How it works  -- explains the model and shows the factor weighting (% of 100).
  QB Rankings   -- the board, with LIVE weight sliders: drag a factor's weight
                   and the projections + ranking recompute in the browser.

All the math is embedded per QB as 0-100 factor indices plus a calibration
(a, b); the browser computes  pts = a + b * (sum(w*index)/sum(w))  on the fly.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone


def render(result: dict, meta: dict) -> str:
    payload = {
        "meta": meta,
        # When this file was generated, in UTC. The page prints it in the
        # viewer's own timezone and uses it to spot a stale cached copy.
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "qbs": result.get("payload", []),
        "weights": result.get("weights", {}),
        "groups": result.get("groups", []),
        "calib": result.get("calib", {"a": 0, "b": 0.25}),
        "backtest": result.get("backtest", {}),
        # ADP-expectation curve + the league-winner thresholds, so the page can
        # show what the bars are instead of asking you to trust them.
        "ratings_meta": result.get("ratings_meta", {}),
    }
    return _TEMPLATE.replace("__DATA_JSON__", json.dumps(payload))


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en" data-theme="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<!-- GitHub Pages serves this file with "cache for 10 minutes" and gives us no
     way to change that header, so a refresh straight after a rebuild can hand
     you the previous board. These ask the browser to check with the server
     every time instead of trusting its copy. Browsers honour them to varying
     degrees, which is why the script also runs a freshness check on load. -->
<meta http-equiv="Cache-Control" content="no-cache, must-revalidate, max-age=0">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>NFL QB Projection Model</title>
<style>
  :root{
    --surface-1:#fcfcfb;--plane:#f5f6f9;--ink:#0b0b0b;--ink-2:#52514e;--muted:#898781;
    --grid:#e1e0d9;--baseline:#c3c2b7;--border:rgba(11,11,11,.10);
    --pos:#2a78d6;--neg:#e34948;--accent:#256abf;--accent-soft:#cde2fb;
    --t1:#184f95;--t2:#256abf;--t3:#5598e7;--t4:#9ec5f4;
    --arch:#4a3aa7;--good:#006300;
    --brand:#123f86;--brand-2:#3a2f8f;--on-brand:#ffffff;--radius:16px;
    --shadow:0 1px 2px rgba(11,11,11,.05),0 14px 30px -18px rgba(11,11,11,.22);
  }
  :root[data-theme="dark"]{
    --surface-1:#1a1a19;--plane:#0d0d0d;--ink:#fff;--ink-2:#c3c2b7;--muted:#898781;
    --grid:#2c2c2a;--baseline:#383835;--border:rgba(255,255,255,.10);
    --pos:#3987e5;--neg:#e66767;--accent:#3987e5;--accent-soft:#12233b;
    --t1:#9ec5f4;--t2:#5598e7;--t3:#3987e5;--t4:#184f95;--arch:#9085e9;--good:#0ca30c;
    --brand:#10336e;--brand-2:#2a2170;--on-brand:#ffffff;
    --shadow:0 1px 2px rgba(0,0,0,.5),0 16px 34px -20px rgba(0,0,0,.8);
  }
  @media(prefers-color-scheme:dark){:root[data-theme="auto"]{
    --surface-1:#1a1a19;--plane:#0d0d0d;--ink:#fff;--ink-2:#c3c2b7;--muted:#898781;
    --grid:#2c2c2a;--baseline:#383835;--border:rgba(255,255,255,.10);
    --pos:#3987e5;--neg:#e66767;--accent:#3987e5;--accent-soft:#12233b;
    --t1:#9ec5f4;--t2:#5598e7;--t3:#3987e5;--t4:#184f95;--arch:#9085e9;--good:#0ca30c;
    --brand:#10336e;--brand-2:#2a2170;--on-brand:#ffffff;
    --shadow:0 1px 2px rgba(0,0,0,.5),0 16px 34px -20px rgba(0,0,0,.8);}}
  *{box-sizing:border-box}
  body{margin:0;background:var(--plane);color:var(--ink);font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.5;-webkit-font-smoothing:antialiased}
  /* The board needs ~1110px to show all 13 columns without a sideways scroll.
     Prose stays narrow (long lines are hard to read); only the board goes wide. */
  .wrap{max-width:1192px;margin:0 auto;padding:0 20px 80px}
  #overview{max-width:1000px}
  header{position:sticky;top:0;z-index:5;background:linear-gradient(105deg,var(--brand),var(--brand-2));border-bottom:0;padding:16px 0 0;box-shadow:0 4px 18px -6px rgba(0,0,0,.35)}
  .hgrid{max-width:1192px;margin:0 auto;padding:0 20px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
  h1{font-size:23px;margin:0;font-weight:800;letter-spacing:-.02em;color:var(--on-brand);text-transform:uppercase}
  .sub{color:rgba(255,255,255,.82);font-size:13px;margin:3px 0 0}
  .spacer{flex:1}
  .tabs{display:flex;gap:4px;margin:14px 0 0}
  .tab{border:0;background:transparent;color:rgba(255,255,255,.72);font:inherit;font-size:14px;font-weight:650;padding:11px 15px;border-bottom:3px solid transparent;cursor:pointer;transition:color .12s}
  .tab:hover{color:#fff}
  .tab[aria-selected="true"]{color:#fff;border-bottom-color:#fff}
  .toggle{border:1px solid rgba(255,255,255,.3);background:rgba(255,255,255,.12);color:#fff;font:inherit;font-size:12px;font-weight:600;padding:6px 11px;border-radius:8px;cursor:pointer;transition:background .12s}
  .toggle:hover{background:rgba(255,255,255,.22)}
  /* "a newer board is live" chip. Hidden unless the copy you're looking at is
     genuinely older than the one on the server — see the freshness check. */
  .fresh{position:fixed;left:50%;bottom:22px;transform:translateX(-50%) translateY(12px);z-index:40;
    display:none;align-items:center;gap:10px;background:var(--surface-1);color:var(--ink);
    border:1px solid var(--border);border-radius:999px;padding:8px 9px 8px 18px;
    box-shadow:0 2px 6px rgba(0,0,0,.10),0 18px 38px -16px rgba(0,0,0,.45);
    font-size:13.5px;font-weight:600;opacity:0;transition:opacity .18s,transform .18s}
  .fresh.show{display:flex;opacity:1;transform:translateX(-50%) translateY(0)}
  .fresh button{font:inherit;border:0;border-radius:999px;cursor:pointer;white-space:nowrap}
  .fresh .go{background:var(--accent);color:#fff;font-size:13px;font-weight:700;padding:7px 15px;flex:0 0 auto}
  .fresh .go:hover{filter:brightness(1.08)}
  .fresh .x{background:transparent;color:var(--muted);padding:5px 9px;font-size:16px;line-height:1}
  .fresh .x:hover{color:var(--ink)}
  @media(max-width:560px){.fresh{left:12px;right:12px;bottom:12px;justify-content:space-between;
    padding-left:15px;font-size:13px}
    .fresh,.fresh.show{transform:none}}
  section{display:none;padding-top:24px}section.active{display:block}
  .card{background:var(--surface-1);border:1px solid var(--border);border-radius:var(--radius);padding:22px 24px;margin:0 0 18px;box-shadow:var(--shadow)}
  h2{font-size:18px;font-weight:750;margin:0 0 12px;letter-spacing:-.015em}
  h3{font-size:12px;font-weight:700;margin:0 0 8px;color:var(--accent);text-transform:uppercase;letter-spacing:.06em}
  p{margin:0 0 12px;color:var(--ink-2);font-size:14.5px}p strong{color:var(--ink);font-weight:600}
  .stat{display:inline-flex;gap:8px;align-items:baseline;background:var(--plane);border:1px solid var(--border);border-radius:10px;padding:8px 14px;margin:2px 8px 2px 0}
  .stat b{font-size:18px;font-variant-numeric:tabular-nums}.stat span{font-size:12px;color:var(--muted)}
  /* weight bars */
  .wrow{display:grid;grid-template-columns:120px 1fr 46px;gap:10px 12px;align-items:center;margin:7px 0}
  .wname{font-size:13.5px;color:var(--ink);text-align:right}
  .wtrack{height:12px;border-radius:6px;background:var(--grid);overflow:hidden}
  .wfill{height:100%;border-radius:6px;background:linear-gradient(90deg,var(--t2),var(--accent))}
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
  thead th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--ink-2);font-weight:700;padding:2px 10px 9px;border-bottom:2px solid var(--border);white-space:nowrap}
  thead th.num{text-align:right}
  tbody td{padding:12px 10px;border-bottom:1px solid var(--border);vertical-align:middle}
  tbody tr.row{cursor:pointer;transition:background .12s}tbody tr.row:hover{background:var(--accent-soft)}
  .rank{font-variant-numeric:tabular-nums;color:var(--accent);font-weight:800;font-size:15px;width:32px}
  /* Wide table: on a narrow screen it scrolls sideways instead of overflowing the
     page. Names and badges never break mid-word — when the column gets tight the
     badges drop to a second line, which is tidy; "Jayden / Daniels" is not. */
  .tblwrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
  .qb b{font-weight:700;font-size:14.5px;white-space:nowrap}.qb .tm{color:var(--muted);font-size:12.5px;margin-left:3px;font-weight:600}
  /* team logo, with the text abbreviation as a fallback if the image can't load */
  .tmwrap{display:inline-flex;align-items:center;vertical-align:middle;margin-left:7px}
  .tmlogo{width:23px;height:23px;object-fit:contain;display:block}
  .tmwrap .tm{position:absolute;width:1px;height:1px;margin:0;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
  .tmwrap.nologo .tmlogo{display:none}
  .tmwrap.nologo .tm{position:static;width:auto;height:auto;overflow:visible;clip-path:none}
  /* dark surfaces swallow the dark-primary logos (Raiders, Steelers, Jets) — put them on a disc */
  :root[data-theme="dark"] .tmlogo,:root[data-theme="dark"] .shotteam{background:rgba(255,255,255,.92);border-radius:50%;padding:1px}
  @media(prefers-color-scheme:dark){:root[data-theme="auto"] .tmlogo,:root[data-theme="auto"] .shotteam{background:rgba(255,255,255,.92);border-radius:50%;padding:1px}}
  .archtag{display:inline-block;font-size:10.5px;font-weight:700;color:#fff;background:var(--arch);border-radius:20px;padding:2px 9px;margin-left:6px;letter-spacing:.02em;white-space:nowrap}
  .move{display:inline-block;font-size:10.5px;font-weight:600;color:var(--neg);border:1px solid var(--neg);border-radius:20px;padding:0 6px;margin-left:6px}
  .bdg{display:inline-block;font-size:11px;font-weight:700;border-radius:20px;padding:2px 10px;white-space:nowrap;letter-spacing:.01em}
  .bdg.g{background:rgba(0,120,60,.18);color:var(--good)}
  .bdg.a{background:rgba(190,130,0,.20);color:#9a6600}
  .bdg.r{background:rgba(210,60,60,.18);color:var(--neg)}
  .bdg.n{background:var(--grid);color:var(--ink-2)}
  :root[data-theme="dark"] .bdg.a{color:#e6a93a}
  .vt{font-size:9.5px;font-weight:800;padding:2px 7px;border-radius:20px;margin-left:6px;letter-spacing:.03em;vertical-align:middle;white-space:nowrap}
  .vt.g{background:rgba(0,120,60,.18);color:var(--good)}
  .vt.r{background:rgba(210,60,60,.18);color:var(--neg)}
  /* Platform ADP cells, scored against the Market column: GREEN where that site
     lets him fall 2+ QB spots LATER than the market (you get him cheaper — a
     value), RED where it drafts him 2+ spots EARLIER (you'd be paying up — a
     reach). Inside 2 spots stays plain text on purpose: only prices genuinely
     out of step with the market should catch your eye. */
  .pfr{font-variant-numeric:tabular-nums;font-size:13px}
  .pfr.val{color:var(--good);font-weight:700;background:rgba(0,120,60,.13);border-radius:7px;padding:2px 7px}
  .pfr.rch{color:var(--neg);font-weight:700;background:rgba(210,60,60,.13);border-radius:7px;padding:2px 7px}
  .pfr.e{color:var(--muted)}
  /* the platform chosen in the "Drafting on" toggle — underlined rather than
     recoloured, so the value/reach colour above still reads through it */
  .pfr.sel,.selcol{text-decoration:underline;text-decoration-color:var(--accent);
    text-decoration-thickness:2px;text-underline-offset:3px}
  .pfr.sel{font-weight:700}
  thead th.selcol{color:var(--ink)}
  th.mkt,td.mkt{border-left:1px solid var(--border)}
  th.mkt{color:var(--ink)}
  /* Market is bold wherever it appears — it's what the site columns roll up into */
  td.mkt{font-weight:800;color:var(--accent);font-variant-numeric:tabular-nums}
  .whycol{max-width:180px;line-height:1.9}
  .fl{display:inline-block;font-size:10.5px;font-weight:700;border-radius:20px;padding:2px 9px;white-space:nowrap}
  .fl.g{background:rgba(0,120,60,.16);color:var(--good)}
  .fl.a{background:rgba(190,130,0,.18);color:#9a6600}
  .fl.r{background:rgba(210,60,60,.16);color:var(--neg)}
  .fl.n{background:var(--grid);color:var(--ink-2)}
  :root[data-theme="dark"] .fl.a{color:#e6a93a}
  .sortsel{font:inherit;font-size:13px;padding:6px 9px;border:1px solid var(--border);border-radius:9px;background:var(--surface-1);color:var(--ink)}
  .ov{display:grid;grid-template-columns:132px 1fr;gap:8px 14px;font-size:14px;color:var(--ink-2)}
  .ov .ovh{color:var(--ink);font-weight:600}
  /* League-winner checklist: fixed published bars, pass/fail/not-measured. */
  .lw{display:flex;flex-direction:column;gap:3px}
  .lwr{display:grid;grid-template-columns:16px 1fr auto;gap:8px;align-items:baseline;font-size:13px}
  .lwr .lwm{font-weight:800;text-align:center}
  .lwr.y .lwm{color:var(--good)} .lwr.y .lwl{color:var(--ink);font-weight:600}
  .lwr.n .lwm{color:var(--neg)}  .lwr.n .lwl{color:var(--ink-2)}
  .lwr.u .lwm{color:var(--muted)}.lwr.u .lwl,.lwr.u .lwd{color:var(--muted)}
  .lwr .lwd{color:var(--muted);font-variant-numeric:tabular-nums;font-size:12px}
  .lwcap{margin-top:6px;font-size:11.5px;line-height:1.5;color:var(--muted)}
  /* The two Heath paths are an OR, so they get drawn as one bracketed group with
     a divider rather than as two independent rows. The box IS the argument: it
     says "one of these, not both" without needing a sentence to explain it. */
  .lwgate{display:flex;align-items:center;gap:8px;margin-bottom:7px;font-size:12.5px}
  .lwgate .gb{font-size:11px;font-weight:800;letter-spacing:.03em;text-transform:uppercase;
    padding:2px 7px;border-radius:999px;white-space:nowrap}
  .lwgate.y .gb{color:var(--good);background:color-mix(in srgb,var(--good) 13%,transparent)}
  .lwgate.n .gb{color:var(--neg);background:color-mix(in srgb,var(--neg) 13%,transparent)}
  .lwgate.u .gb{color:var(--muted);background:var(--grid)}
  .lwgate .gv{color:var(--ink-2)}
  .lwpaths{border:1px solid var(--border);border-radius:9px;padding:7px 9px;background:var(--plane)}
  .lwor{display:grid;grid-template-columns:16px 1fr;gap:8px;align-items:center;
    margin:3px 0;font-size:10.5px;font-weight:700;letter-spacing:.08em;color:var(--muted)}
  .lwor::after{content:"";height:1px;background:var(--grid)}
  .lwsub{margin:9px 0 3px;font-size:10.5px;font-weight:700;letter-spacing:.08em;
    text-transform:uppercase;color:var(--muted)}
  .num{text-align:right;font-variant-numeric:tabular-nums}
  .bartrack{display:inline-block;width:90px;height:9px;border-radius:5px;background:var(--grid);vertical-align:middle;margin-right:8px;overflow:hidden}
  .bar{height:9px;border-radius:5px;background:linear-gradient(90deg,var(--t3),var(--t2));display:block}
  .tier{display:inline-block;min-width:20px;text-align:center;font-size:12px;font-weight:600;color:#fff;padding:2px 8px;border-radius:20px}
  .caret{color:var(--muted);display:inline-block;transition:transform .15s}tr.open .caret{transform:rotate(90deg)}
  .detail td{background:var(--plane);padding:0}
  .dbox{padding:18px 20px 22px}
  .dhead{display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:12px}
  /* headshot, with an initials avatar as the fallback */
  .dhead .who{display:flex;align-items:center;gap:15px}
  .shot{position:relative;flex:0 0 auto;width:66px;height:66px;border-radius:50%;background:var(--accent-soft);border:1px solid var(--border);display:grid;place-items:center}
  .shotimg{width:100%;height:100%;border-radius:50%;object-fit:cover;object-position:center 14%;display:block}
  .shot .shotini{display:none;font-size:21px;font-weight:800;color:var(--accent);letter-spacing:.02em}
  .shot.noshot .shotimg{display:none}
  .shot.noshot .shotini{display:block}
  .shotteam{position:absolute;right:-5px;bottom:-3px;width:27px;height:27px;object-fit:contain;background:var(--surface-1);border-radius:50%;padding:2px;box-shadow:0 1px 4px rgba(0,0,0,.28)}
  /* Same avatar shrunk for the comp cards. 38px is the largest circle that still
     fits inside the three lines of text the card already had, so adding faces
     costs no height and all five comps stay on screen at once. */
  .shot.xs{width:38px;height:38px}
  .shot.xs .shotini{font-size:13px}
  .shot.xs .shotteam{right:-3px;bottom:-2px;width:17px;height:17px;padding:1px;box-shadow:0 1px 3px rgba(0,0,0,.25)}
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
  .feat table{font-size:13px}.feat td{padding:5px 10px;border-bottom:1px solid var(--border)}
  .feat .k{color:var(--ink-2)}.feat .v{text-align:right;font-variant-numeric:tabular-nums}
  /* the ADP table inside a player's panel: one column per site, Market last and
     bold. These rules sit after ".detail td" on purpose — same specificity, so
     the later one wins and the nested table keeps its own padding. */
  .adpt{width:auto;border-collapse:collapse;font-size:13px;margin:0 0 2px}
  .adpt th,.adpt td{padding:5px 13px;border-bottom:1px solid var(--border);text-align:right;white-space:nowrap;background:none}
  .adpt thead th{font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--ink-2);
    font-weight:700;padding-bottom:7px;border-bottom:2px solid var(--border)}
  .adpt .rh{text-align:left;font-weight:600;color:var(--ink-2);font-size:12.5px;
    padding-left:0;text-transform:none;letter-spacing:0}
  .adpt tbody tr:last-child th,.adpt tbody tr:last-child td{border-bottom:0}
  .adpt td{font-variant-numeric:tabular-nums;color:var(--ink)}
  .adpt .mk{border-left:1px solid var(--border);font-weight:800;color:var(--accent)}
  .adpt thead th.mk{color:var(--ink)}
  .adpt .e{color:var(--muted);font-weight:400}
  .adpt .gd{color:var(--good);font-weight:700}
  .adpt .bd{color:var(--neg);font-weight:700}
  .adpt thead th.selcol{color:var(--ink)}
  .adpcap{font-size:12px;color:var(--muted);margin-top:7px;max-width:600px;line-height:1.45}
  /* "Similar QBs" — the backup-options layer */
  .sim{margin:18px 0 2px}
  .simcap{font-size:12.5px;color:var(--muted);margin:-2px 0 9px;max-width:640px;line-height:1.45}
  .simgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(224px,1fr));gap:8px}
  /* Face on the left, the three lines of text on the right. min-width:0 on the
     text column is what lets a long name wrap instead of shoving the card wider
     than the rail. */
  .simcard{display:flex;align-items:center;gap:11px;text-align:left;font:inherit;cursor:pointer;width:100%;
    background:var(--surface-1);border:1px solid var(--border);border-radius:11px;padding:9px 12px 10px;
    transition:background .12s,border-color .12s}
  .simcard:hover{background:var(--accent-soft);border-color:var(--accent)}
  .simcard .shot{background:var(--plane)}
  .simcard:hover .shot{border-color:var(--accent)}
  .siminfo{min-width:0;flex:1 1 auto}
  .simcard .nm{display:block;font-size:13.5px;font-weight:700;color:var(--ink)}
  .simcard .nm .tm{color:var(--muted);font-size:12px;font-weight:600;margin-left:5px}
  .simcard .mt{display:block;font-size:11.5px;color:var(--ink-2);margin-top:1px;font-variant-numeric:tabular-nums}
  .simcard .cost{display:block;font-size:11.5px;font-weight:700;margin-top:3px;font-variant-numeric:tabular-nums}
  .simcard .cost.later{color:var(--good)}
  .simcard .cost.earlier{color:var(--neg)}
  .simcard .cost.same{color:var(--muted)}
  .simdots{color:var(--accent);letter-spacing:1px;margin-left:6px;font-size:10px}
  /* The panel is two columns: what you read top-to-bottom on the left, the comps
     as a rail down the right, so a replacement is always one glance from the
     price. Under 900px the rail drops underneath instead of sitting off the side
     of the horizontally-scrolling table where you'd never find it. */
  .dcols{display:grid;grid-template-columns:minmax(0,1fr) minmax(238px,290px);gap:4px 28px;align-items:start}
  .dmain,.drail{min-width:0}
  .drail .sim{margin:0}
  .drail .simgrid{grid-template-columns:1fr}
  .drail .simcap{max-width:none}
  @media(max-width:900px){.dcols{grid-template-columns:1fr}.drail{margin-top:18px}}
  /* Collapsible breakdown. Both sections start closed so a panel opens on the
     things you act on — the price and the comps — and the toggle is shared across
     players: open it once and it stays open for the rest of the session. */
  .fold{border-top:1px solid var(--border);margin-top:14px}
  .fold>summary{list-style:none;cursor:pointer;display:flex;align-items:baseline;gap:8px;
    padding:11px 8px 9px;margin:0 -8px;border-radius:8px;font-size:12px;font-weight:700;
    color:var(--accent);text-transform:uppercase;letter-spacing:.06em;user-select:none}
  .fold>summary::-webkit-details-marker{display:none}
  .fold>summary::before{content:"▸";font-size:10px;color:var(--muted);display:inline-block;
    transition:transform .15s;text-transform:none}
  .fold[open]>summary::before{transform:rotate(90deg)}
  .fold>summary:hover{background:var(--accent-soft)}
  .fold .fsub{font-weight:400;font-size:12px;color:var(--muted);text-transform:none;letter-spacing:0}
  .fbody{padding:3px 0 14px}
  .note{color:var(--muted);font-size:12.5px;margin-top:14px}
  .pill{display:inline-block;font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;margin-left:8px;background:rgba(255,255,255,.16);color:#fff;border:1px solid rgba(255,255,255,.28);letter-spacing:.02em;vertical-align:middle}
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
  <!-- Rankings first and open by default: the board is what you came for on
       draft day. "How it works" is reference material you read once. -->
  <div class="hgrid"><div class="tabs" role="tablist">
    <button class="tab" role="tab" data-tab="rankings" aria-selected="true">QB Rankings</button>
    <button class="tab" role="tab" data-tab="overview" aria-selected="false">How it works</button>
  </div></div>
</header>

<div class="wrap">
  <section id="overview">
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
        <div class="ovh">Worth the pick?</div><div>The same value question answered in <b>points</b> instead of draft slots — the unit that
          actually decides a week. Four years of QB draft prices were joined to what those QBs really averaged, giving a curve of
          <em>what a pick is worth</em>; this is his projection minus that. <b style="color:var(--good)">+5</b> a game is the league-winner
          bar and <b style="color:var(--good)">+2</b> is ordinary good value. Beating the field by two ranking spots may win you nothing;
          beating your draft slot by five points a game wins you weeks. It moves live with the weight sliders.</div>
        <div class="ovh">League-winner shape</div><div>Four yes/no reads on whether he has the <em>profile</em> that historically wins
          leagues, kept deliberately separate from the projection — &ldquo;how many points&rdquo; and &ldquo;what kind of player&rdquo; are
          different questions. Rushing volume is quoted as a <b>17-game pace</b>, so a QB who started four games on a 99-carry pace is
          credited for the pace rather than punished for the missed time. Unlike the factor bars these are <b>fixed thresholds, not
          percentiles</b> — every QB in a weak year can fail all of them.</div>
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
          Vegas win totals now feed the team flags (and a Vegas factor is in the blend).
          Two chips come from fixed league-winner bars rather than from this field's percentiles:
          <span class="fl g">+5 over ADP</span> (beating what his draft slot is worth by five points a game) and
          <span class="fl g">100+ rush pace</span> / <span class="fl r">No rush floor</span> (17-game rushing-attempt pace above 100, or below 55).</div>
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

  <section id="rankings" class="active">
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
      <div class="tblwrap"><table id="tbl"><thead id="thead"></thead><tbody id="tbody"></tbody></table></div>
    </div>
    <p class="note" id="rnote"></p>
  </section>
</div>

<div class="fresh" id="freshChip" role="status" aria-live="polite">
  <span id="freshMsg">A newer board has been published.</span>
  <button class="go" id="freshGo" type="button">Load it</button>
  <button class="x" id="freshX" type="button" aria-label="Dismiss">&times;</button>
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

/* --- build stamp + freshness check ---------------------------------------
   Two problems, one answer.

   (1) "Am I even looking at the new board?" -- the exact build time is now
       printed in the header, in your timezone, so you never have to guess.
   (2) "Why is it still the old one?" -- GitHub Pages tells your browser to
       keep this page for 10 minutes and offers no way to change that header,
       so a refresh right after a rebuild can legitimately hand you the
       previous copy. Shortly after load we ask the server for the current
       file with cache:"reload", which both skips the cache on the way out and
       replaces the stored copy on the way back -- so your NEXT refresh is
       fresh even if you ignore everything below. If the server's build stamp
       is newer than ours we also offer a one-click jump to it; the ?v= on
       that link is the guarantee, since the browser has never seen that URL
       and so cannot answer it from cache.

   It asks rather than reloading by itself on purpose: yanking the page out
   from under you mid-draft, with your weight sliders tuned, would be rude.

   Every step is guarded. Offline, opened from disk (file://), or a failed
   request all end with no chip and no error in the console. */
const BUILT = DATA.built || "";

(function stampBuildTime(){
  const d = BUILT ? new Date(BUILT) : null;
  if(!d || isNaN(d)) return;
  const sub = $("#subline");
  sub.textContent = (sub.textContent ? sub.textContent + " · " : "") + "built " +
    d.toLocaleString(undefined,{month:"short",day:"numeric",hour:"numeric",minute:"2-digit"});
  sub.title = "This page was generated " + d.toLocaleString();
})();

function freshCheck(){
  if(!BUILT || !/^https?:$/.test(location.protocol)) return;   // nothing to check against
  fetch(location.pathname, {cache:"reload"})
    .then(r => r.ok ? r.text() : null)
    .then(html => {
      if(!html) return;
      const m = html.match(/"built"\s*:\s*"([^"]+)"/);
      if(!m || m[1] === BUILT) return;                       // already current
      const theirs = new Date(m[1]), ours = new Date(BUILT);
      if(isNaN(theirs) || theirs <= ours) return;            // server isn't newer
      const chip = $("#freshChip");
      $("#freshMsg").textContent = "A newer board was published " +
        theirs.toLocaleString(undefined,{month:"short",day:"numeric",hour:"numeric",minute:"2-digit"}) + ".";
      $("#freshGo").onclick = () => location.replace(location.pathname + "?v=" + encodeURIComponent(m[1]));
      $("#freshX").onclick  = () => chip.classList.remove("show");
      chip.classList.add("show");
    })
    .catch(()=>{});
}
setTimeout(freshCheck, 1200);
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
/* How one site prices a QB against the Market column (Underdog + FFC).
   gap = market − site.  NEGATIVE: the site lets him fall LATER than the market,
   so he's cheaper there — a value. POSITIVE: the site drafts him EARLIER, so
   you'd be paying up — a reach. Two QB spots is the cutoff either way. */
function mktEdge(x,pf){
  const mine=(x.adp_platforms&&x.adp_platforms[pf])??null, mkt=x._market??null;
  if(mine==null||mkt==null)return {mine,mkt,gap:null,cls:"",word:""};
  const gap=mkt-mine;
  return {mine,mkt,gap,
    cls:gap<=-2?"val":gap>=2?"rch":"",
    word:gap<=-2?`falls ${-gap} QB spots later than the market here — value`
        :gap>=2?`goes ${gap} QB spots earlier than the market here — reach`
        :"in line with the market"};
}
function pfRank(x,pf){
  const e=mktEdge(x,pf), sel=pf===draftPlatform?" sel":"";
  if(e.mine==null)return `<span class="pfr e${sel}">—</span>`;
  return `<span class="pfr ${e.cls}${sel}"${e.word?` title="${PLABEL[pf]||pf}: ${e.word}"`:""}>QB${e.mine}</span>`;
}
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
/* --- Value in POINTS, not in draft slots --------------------------------
   exp_fpg is what a QB drafted at his price has historically been worth per
   game (fixed — it's a property of the price, not of our weights). The EDGE is
   projection minus that, so it has to be computed here: dragging a weight
   slider changes the projection, and a number baked in at build time would
   quietly go stale the moment you touched the board. */
const RMETA=DATA.ratings_meta||{};
const LWB=RMETA.lw_bars||{fpg:5,value_fpg:2,att_floor:55,att_high:100,rush_fpg:5};
const CURVE=RMETA.curve||null;
function edgeFpg(x){return x.exp_fpg==null?null:projOf(x)-x.exp_fpg;}
function edgeTag(v){return v==null?null:v>=LWB.fpg?"League winner":v>=LWB.value_fpg?"Value":v<=-LWB.value_fpg?"Pricey":null;}
function flagChips(x){
  const f=(x.flags||[]).slice(), e=edgeFpg(x);
  if(e!=null&&e>=LWB.fpg)f.unshift(["up",`+${e.toFixed(0)} over ADP`]);
  if(!f.length)return '<span class="mut" style="font-size:11px">—</span>';
  return f.slice(0,6).map(t=>`<span class="fl ${FLAGCLS[t[0]]||'n'}">${t[1]}</span>`).join(" ");
}
/* Reads as a sentence: what he's projected for, what the pick is worth, the gap. */
function valuePointsLine(o){
  const e=edgeFpg(o);
  if(e==null)return '<span style="color:var(--muted)">no draft price to score him against</span>';
  const tag=edgeTag(e), cls=e>=LWB.value_fpg?"g":e<=-LWB.value_fpg?"r":"n";
  const sign=e>0?"+":"";
  const src=o.value_fpg_src?` <span style="color:var(--muted)">(${o.value_fpg_src} price)</span>`:"";
  /* Two different sentences, because the two curves mean different things. The
     historical curve says what QBs at this price ACTUALLY did; the board fallback
     only says what this year's market implies. Saying "have averaged" about the
     fallback would claim evidence that isn't there. */
  const basis=CURVE&&CURVE.source==="board"
    ?`vs the ${fmt(o.exp_fpg,1)} this year's price curve implies at that cost`
    :`vs the ${fmt(o.exp_fpg,1)} QBs drafted around here have actually averaged`;
  return `${bdg(tag||"Fair price",cls)} <b>${sign}${fmt(e,1)} pts/gm</b>
    <span style="color:var(--muted)">— ${fmt(projOf(o),1)} projected ${basis}</span>${src}`;
}
/* The checklist is intentionally NOT folded into the projection. "Will he score
   points" and "does he have the shape that wins leagues" are different
   questions; blending them would hide the second inside the first.

   The top two rows are Heath's two paths and they are an OR, not a tally: "every
   late-round QB to make the playoffs in 45%+ of ESPN leagues since 2021 fits one
   of these two criteria." So one path is a full pass. Clearing both is not extra
   credit and clearing only one is not a partial — which is why this renders as a
   gate with a bracketed either/or group, and why the old "cleared N of 4" caption
   is gone. That count quietly punished a pocket passer in a Shanahan offense for
   missing a bar the research never asked him to clear. */
function lwChecklist(o){
  const cs=o.lw_checks||[];
  if(!cs.length)return '<span style="color:var(--muted)">—</span>';
  const row=c=>{
    const st=c.pass===true?["y","✓"]:c.pass===false?["n","✗"]:["u","·"];
    const t=c.why?` title="${String(c.why).replace(/"/g,"&quot;")}"`:"";
    return `<div class="lwr ${st[0]}"${t}><span class="lwm">${st[1]}</span>`+
      `<span class="lwl">${c.label}</span><span class="lwd">${c.detail||""}</span></div>`;
  };
  /* Fall back to flat rendering if an older payload has no groups, so a stale
     qb_data.json can't blank the panel out. */
  const paths=cs.filter(c=>c.group==="path"), sup=cs.filter(c=>c.group==="support");
  if(!paths.length)return `<div class="lw">${cs.map(row).join("")}</div>`;

  const g=o.lw_gate, via=o.lw_gate_via||[];
  const gs=g===true?["y","Clears the screen"]:g===false?["n","Misses both paths"]
                                                       :["u","Not enough data"];
  /* Don't lowercase the label: it opens on a proper noun, so "via mcshanahan
     play-caller" reads as a typo. And when he misses both, the badge has already
     said it -- a trailing "neither path" is the same sentence twice. */
  const gv=g===true
    ?(via.length>1?"via both paths":`via ${via[0]}`)
    :g===false?"":"one path couldn't be measured";
  const cap=g===false
    ?`Since 2021 every late-round QB with a 45%+ playoff rate had <b>one</b> of the two —
      100+ rush attempts or a McShanahan-tree play-caller. This profile has neither.`
    :`Either path on its own is enough; a QB needs one, not both. Stated for QBs drafted
      after Round 10, so for an early pick read it as context rather than a verdict.`;

  return `<div class="lwgate ${gs[0]}"><span class="gb">${gs[1]}</span>
      <span class="gv">${gv}</span></div>
    <div class="lwpaths">${row(paths[0])}
      <div class="lwor"><span>or</span></div>
      ${paths.slice(1).map(row).join("")}</div>`+
    (sup.length?`<div class="lwsub">Supporting</div><div class="lw">${sup.map(row).join("")}</div>`:"")+
    `<div class="lwcap">${cap} These are fixed published thresholds, not percentiles —
      a whole weak field can miss every one of them, which is the point.</div>`;
}
const PF=PLATS.map(p=>[p,PLABEL[p]||p]);
/* The draft-slot block, as one small table: a row per way of quoting the price,
   a column per site, and Market last and bold because it's the number the site
   columns roll up into. Cells carry the same green/red as the board. Every row
   below the first is conditional, so a thin ADP file still renders tidily. */
function adpTable(o){
  const sel=k=>k===draftPlatform?" selcol":"";
  const head=PF.map(([k,lab])=>`<th class="${sel(k).trim()}">${lab}</th>`).join("")+
    (MKT_SRC.length?`<th class="mk" title="Market = Underdog (best-ball) and FFC (season-long) blended, then re-ranked">Market</th>`:"");
  const mkCell=(inner,cls)=>MKT_SRC.length?`<td class="mk ${cls||""}">${inner}</td>`:"";

  const rank=`<tr><th class="rh">Drafted at</th>`+
    PF.map(([k])=>{const e=mktEdge(o,k);
      return e.mine==null?'<td class="e">—</td>'
        :`<td><span class="pfr ${e.cls}${sel(k)?" sel":""}">QB${e.mine}</span></td>`;}).join("")+
    mkCell(o._market?`QB${o._market}`:"—",o._market?"":"e")+`</tr>`;

  const pick=PF.some(([k])=>o.adp_picks&&o.adp_picks[k]!=null)
    ?`<tr><th class="rh">Overall pick</th>`+
      PF.map(([k])=>{const p=o.adp_picks&&o.adp_picks[k];
        return p==null?'<td class="e">—</td>':`<td>${fmt(p,0)}</td>`;}).join("")+
      mkCell("—","e")+`</tr>`
    :"";

  const vsMkt=(MKT_SRC.length&&o._market)
    ?`<tr><th class="rh" title="Two QB spots either way is the cutoff">vs market</th>`+
      PF.map(([k])=>{const e=mktEdge(o,k);
        if(e.gap==null)return '<td class="e">—</td>';
        if(e.gap<=-2)return `<td class="gd">${-e.gap} later</td>`;
        if(e.gap>=2)return `<td class="bd">${e.gap} earlier</td>`;
        return '<td class="e">in line</td>';}).join("")+
      mkCell("—","e")+`</tr>`
    :"";

  const vb=o.value_by_platform||null;
  const vsMod=(vb&&PF.some(([k])=>vb[k]!=null))
    ?`<tr><th class="rh" title="Where my projection ranks him against that site's price. Five QB spots either way is the cutoff — a model edge needs to be bigger than a site-to-site wobble to mean anything.">vs my model</th>`+
      PF.map(([k])=>{const g=vb[k];
        if(g==null)return '<td class="e">—</td>';
        if(g>=5)return `<td class="gd">${g} later</td>`;
        if(g<=-5)return `<td class="bd">${-g} earlier</td>`;
        return '<td class="e">in line</td>';}).join("")+
      mkCell("—","e")+`</tr>`
    :"";

  return `<table class="adpt"><thead><tr><th class="rh"></th>${head}</tr></thead>
      <tbody>${rank}${pick}${vsMkt}${vsMod}</tbody></table>
    <div class="adpcap">Market blends Underdog and FFC — one neutral price spanning best-ball and
      season-long. <b style="color:var(--good)">Green</b> means that site lets him fall <b>later</b>
      than the market, so he's cheaper there; <b style="color:var(--neg)">red</b> means it drafts him
      <b>earlier</b> and you'd be paying up.</div>`;
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
    <div class="ovh">Draft slot (ADP)</div><div>${adpTable(o)}</div>
    ${platEdgeLine(o)}
    <div class="ovh">Worth the pick?</div><div>${valuePointsLine(o)}</div>
    <div class="ovh">League-winner shape</div><div>${lwChecklist(o)}</div>
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

/* --- images -------------------------------------------------------------
   Logos and headshots come from ESPN's image CDN. Nothing here is load-bearing:
   if a request fails (offline, 404, blocked), onerror swaps in the text the
   board used to show, so the page never displays a broken image. */
const TEAM_SLUG={ARI:"ari",ATL:"atl",BAL:"bal",BUF:"buf",CAR:"car",CHI:"chi",CIN:"cin",CLE:"cle",
  DAL:"dal",DEN:"den",DET:"det",GB:"gb",HOU:"hou",IND:"ind",JAX:"jax",JAC:"jax",KC:"kc",
  LA:"lar",LAR:"lar",LAC:"lac",LV:"lv",OAK:"lv",SD:"lac",STL:"lar",MIA:"mia",MIN:"min",
  NE:"ne",NO:"no",NYG:"nyg",NYJ:"nyj",PHI:"phi",PIT:"pit",SEA:"sea",SF:"sf",TB:"tb",
  TEN:"ten",WAS:"wsh",WSH:"wsh"};
function teamLogo(t){const s=TEAM_SLUG[String(t||"").toUpperCase().trim()];
  return s?`https://a.espncdn.com/i/teamlogos/nfl/500/${s}.png`:null;}
function teamCell(t){
  t=t||"";const u=teamLogo(t);
  if(!u)return `<span class="tm">${t}</span>`;
  return `<span class="tmwrap" title="${t}"><img class="tmlogo" src="${u}" alt="" loading="lazy"`+
    ` onerror="this.parentNode.classList.add('nologo')"><span class="tm">${t}</span></span>`;}
function initials(n){return String(n||"").split(/\s+/).filter(Boolean).map(w=>w[0]).join("").slice(0,2).toUpperCase();}
/* Headshot with the team logo badged on its corner, initials when there's no
   photo. `sz` picks a size variant ("xs" for the comp cards). It emits a <span>
   rather than a <div> because one of its callers is a <button>, which may only
   contain phrasing content — .shot sets display:grid either way, so nothing
   about the rendering changes. */
function shot(q,sz){
  const lg=teamLogo(q.team);
  const badge=lg?`<img class="shotteam" src="${lg}" alt="" loading="lazy" onerror="this.remove()">`:"";
  const img=q.headshot?`<img class="shotimg" src="${q.headshot}" alt="" loading="lazy"`+
    ` onerror="this.closest('.shot').classList.add('noshot')">`:"";
  return `<span class="shot${sz?" "+sz:""}${q.headshot?"":" noshot"}">${img}`+
    `<span class="shotini">${initials(q.name)}</span>${badge}</span>`;}

/* --- "Similar QBs": the backup-options layer ------------------------------
   If he's already gone, or the price is too high, who does roughly the same
   job? Similarity blends three things, and it is recomputed every time you
   move a weight slider -- so the factors YOU care about are the factors that
   decide who counts as similar:
     * style     -- distance between the two 0-100 factor profiles, weighted by
                    the same weights driving the projection
     * output    -- how far apart the projections are (a 2 pts/gm gap is a
                    different player even when the profile shape matches)
     * archetype -- a small bonus for carrying the same label
   The ORDER is deliberately NOT "most similar first": QBs going LATER than he
   does float to the top, because a comparable QB you can still get is the
   useful answer and one already off the board is not. */
const SIM_N=5;
function costRank(x){   // what he costs right now, on the site you're drafting on
  if(draftPlatform!=="consensus"){
    const r=x.adp_platforms&&x.adp_platforms[draftPlatform];
    if(r!=null)return r;
  }
  return x._market!=null?x._market:(x.adp_pos_rank!=null?x.adp_pos_rank:null);
}
function simDist(a,b){
  const s=sumW();
  let style=0;
  GROUPS.forEach(g=>{style+=(weights[g]||0)*Math.abs((a.indices[g]??50)-(b.indices[g]??50));});
  style/=s;                                        // 0 = identical profile
  const out=Math.abs((a._p||0)-(b._p||0));         // pts/gm apart
  const same=a.archetype&&a.archetype===b.archetype;
  return style + 6*out - (same?4:0);               // 1 pt/gm ~ 6 index points
}
function similarQBs(q){
  const mine=costRank(q);
  const pool=DATA.qbs.filter(x=>x!==q&&x.indices).map(x=>{
    const c=costRank(x);
    return {x,d:simDist(q,x),cost:c,later:(mine!=null&&c!=null)?c-mine:null};
  });
  pool.sort((p,r)=>{                                // still-gettable first, then closest
    const pc=(p.later!=null&&p.later>=1)?0:1, rc=(r.later!=null&&r.later>=1)?0:1;
    return (pc-rc)||(p.d-r.d);
  });
  const top=pool.slice(0,SIM_N);
  if(!top.length)return "";
  const where=(draftPlatform!=="consensus"&&PLABEL[draftPlatform])?PLABEL[draftPlatform]:"the market";
  const cards=top.map(c=>{
    const dots=c.d<12?3:c.d<24?2:1;
    const meter=`<span class="simdots" title="${["loose match","similar","very similar"][dots-1]}">`+
      "●".repeat(dots)+"○".repeat(3-dots)+"</span>";
    const sp=n=>n===1?"spot":"spots";
    let cost,cls,tip;
    if(c.later==null){
      cost=c.cost!=null?`QB${c.cost}`:"undrafted"; cls="same"; tip="no price to compare";
    }else if(c.later>=1){
      cost=`QB${c.cost} · ${c.later} ${sp(c.later)} later`; cls="later";
      tip=`Goes ${c.later} QB ${sp(c.later)} later than ${q.name} on ${where} — you can still get him`;
    }else if(c.later<=-1){
      cost=`QB${c.cost} · ${-c.later} ${sp(-c.later)} earlier`; cls="earlier";
      tip=`Off the board ${-c.later} QB ${sp(-c.later)} before ${q.name} on ${where}`;
    }else{
      cost=`QB${c.cost} · same spot`; cls="same"; tip="drafted in the same range";
    }
    return `<button class="simcard" type="button" data-goto="${c.x.rank}" title="${tip}">
      ${shot(c.x,"xs")}<span class="siminfo">
      <span class="nm">${c.x.name}<span class="tm">${c.x.team||""}</span></span>
      <span class="mt">${c.x.archetype||"—"} · ${fmt(c.x._p)} pts/gm${meter}</span>
      <span class="cost ${cls}">${cost}</span></span></button>`;
  }).join("");
  /* The caption earns its keep but the rail is narrow, so it's kept to two lines:
     what the list is for, and the one thing that isn't obvious from the cards
     (whoever you can still get is listed first). */
  return `<div class="sim"><h3>Similar QBs</h3>
    <div class="simcap">If he's gone or too pricey. Closest on style, factor mix and output
      at your weights — anyone you can <b>still get</b> on ${where} comes first.</div>
    <div class="simgrid">${cards}</div></div>`;
}

/* One shared open/closed state for the collapsible sections. It lives out here
   rather than in the DOM because the whole table body is re-rendered on every
   slider move, which would otherwise snap them shut mid-drag. Sharing it (rather
   than keeping a flag per player) is what makes the choice stick: open "Why this
   projection" on one QB and it's open on the next one you click. */
const folds={why:false,inputs:false};
function fold(k,title,sub,body){
  return `<details class="fold" data-fold="${k}"${folds[k]?" open":""}>
      <summary>${title}<span class="fsub">${sub}</span></summary>
      <div class="fbody">${body}</div></details>`;
}

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
  return `<div class="dhead"><div class="who">${shot(q)}<div><h3>${q.name} — ${q.archetype||""}</h3>
      <div style="font-size:12.5px;color:var(--muted)">index 50 = league-average QB · bars are points added vs. average at the current weights</div></div></div>
    <div style="text-align:right"><div class="big">${fmt(q._p)}<span style="font-size:13px;color:var(--muted);font-weight:400"> pts/gm</span></div>
      <div style="font-size:12px;color:var(--muted)">avg QB ≈ ${fmt(pts0)}</div></div></div>
    <div class="dcols">
      <div class="dmain">${overlays(q)}
        ${fold("why","Why this projection",`${GROUPS.length} factors at your weights`,
          `<div class="legend"><span><span class="sw" style="background:var(--pos)"></span>boosts</span>
             <span><span class="sw" style="background:var(--neg)"></span>lowers</span>
             <span style="color:var(--muted)">middle column = 0–100 factor index</span></div>
           <div class="wf">${rows}</div>`)}
        ${feats?fold("inputs","Underlying inputs","the raw numbers behind the factors",
          `<div class="feat"><table>${feats}</table></div>`):""}</div>
      <div class="drail">${similarQBs(q)}</div>
    </div>`;
}

const qbById=id=>DATA.qbs.find(x=>String(x.rank)===String(id));

// A detail panel is built the first time it's opened, and then left alone until
// the next refresh() throws the whole tbody away. dataset.built is what stops a
// reopen from rebuilding one that's already sitting there.
function fillPanel(d){
  if(!d||d.dataset.built)return;
  const q=qbById(d.dataset.for); if(!q)return;
  d.querySelector(".dbox").innerHTML=detail(q);
  d.dataset.built="1";
  wirePanel(d);
}
function openPanel(tr,d){ if(!d)return; fillPanel(d); d.style.display="table-row"; tr.classList.add("open"); }

// Click handlers for one freshly built panel. Scoped to that panel: its siblings
// are either already wired or not built yet, so there's nothing to re-bind.
function wirePanel(root){
  // a "similar QB" card jumps to that player's row and opens him. If the search
  // box is currently hiding him, clear it first so there's something to jump to.
  root.querySelectorAll(".simcard").forEach(b=>b.onclick=ev=>{
    ev.stopPropagation();
    const id=b.dataset.goto, find=()=>document.querySelector(`tr.row[data-id="${id}"]`);
    let tr=find();
    if(!tr && $("#search").value){ $("#search").value=""; refresh(); tr=find(); }
    if(!tr)return;
    const d=document.querySelector(`tr.detail[data-for="${id}"]`);
    if(d && d.style.display==="none") openPanel(tr,d);
    tr.scrollIntoView({behavior:"smooth",block:"center"});
  });
  // The two breakdown sections share one open/closed state, so flipping one
  // applies it to every other panel as well and the choice carries to the next
  // player you click. Assigning .open when it already matches fires no event,
  // so this settles in one pass instead of ping-ponging between panels.
  root.querySelectorAll("details.fold").forEach(d=>d.addEventListener("toggle",()=>{
    const k=d.dataset.fold; if(folds[k]===d.open)return;
    folds[k]=d.open;
    document.querySelectorAll(`details.fold[data-fold="${k}"]`).forEach(o=>{o.open=d.open;});
  }));
}

function refresh(){
  const q=($("#search").value||"").trim().toLowerCase();
  const rows=DATA.qbs.map(x=>{x._p=projOf(x);return x;}).filter(x=>!q||x.name.toLowerCase().includes(q));
  const all=DATA.qbs.slice().sort((a,b)=>b._p-a._p);
  const replPts=all.length?all[Math.min(REPL,all.length-1)]._p:0;
  rows.sort(sortCmp(sortMode));
  tiers(all);
  const maxP=Math.max(...DATA.qbs.map(x=>x._p),1);
  // Which panels are open right now. The tbody is rebuilt from scratch on every
  // slider move, so without carrying this across, a panel would slam shut the
  // instant you touched a weight — exactly when you most want to watch the bars
  // and the comps re-sort under it.
  const wasOpen=new Set([...document.querySelectorAll("tr.detail")]
    .filter(d=>d.style.display!=="none").map(d=>d.dataset.for));
  $("#tbody").innerHTML=rows.map((x)=>{
    const rank=all.indexOf(x)+1, vor=x._p-replPts, w=Math.max(2,Math.round(90*x._p/maxP));
    const isOpen=wasOpen.has(String(x.rank));
    x._vor=vor;
    return `<tr class="row${isOpen?" open":""}" data-id="${x.rank}">
      <td class="rank num">${rank}</td>
      <td class="qb"><b>${x.name}</b>${teamCell(x.team)}
        <span class="archtag">${x.archetype||""}</span>${x.mover?'<span class="move">NEW</span>':''}${valueTag(x)}</td>
      <td class="num"><span class="bartrack"><span class="bar" style="width:${w}px"></span></span>${fmt(x._p)}</td>
      ${PLATS.map(p=>`<td class="num pf">${pfRank(x,p)}</td>`).join("")}
      ${MKT_SRC.length?`<td class="num mkt">${x._market?('QB'+x._market):'<span style="color:var(--muted)">—</span>'}</td>`:""}
      <td>${bdg(x.floor_bucket,FCLS[x.floor_bucket])}</td>
      <td>${bdg(x.ceiling_bucket,CCLS[x.ceiling_bucket])}</td>
      <td>${bdg(x.risk_bucket,RCLS[x.risk_bucket])}</td>
      <td class="whycol">${flagChips(x)}</td>
      <td class="num"><span class="caret">▸</span></td></tr>
      <tr class="detail" data-for="${x.rank}" style="display:${isOpen?"table-row":"none"}"><td colspan="${NCOL}"><div class="dbox"></div></td></tr>`;
  }).join("");
  document.querySelectorAll("tr.row").forEach(tr=>tr.onclick=()=>{
    const d=document.querySelector(`tr.detail[data-for="${tr.dataset.id}"]`);
    if(d.style.display!=="none"){d.style.display="none";tr.classList.remove("open");}
    else openPanel(tr,d);
  });
  weightBars(); syncSliderLabels();
  // Only the panels you actually have open get built. Dragging a slider rebuilds
  // this table on every tick, and a panel is by far the most expensive thing in
  // it — nine factor bars, an ADP table, and five comp cards each carrying a
  // headshot and a logo. Building all 32 to show one made the sliders stutter;
  // building only what's on screen keeps a drag smooth however long the board.
  // Left until last on purpose: if one panel ever failed to build, the board
  // itself is already wired and usable rather than rendered-but-dead.
  wasOpen.forEach(id=>fillPanel(document.querySelector(`tr.detail[data-for="${id}"]`)));
}

function header(){
  const pf=PLATS.map(p=>`<th class="num${p===draftPlatform?" selcol":""}" title="${PLABEL[p]||p} ADP, as a QB rank — green where he falls later than the market, red where he goes earlier">${PLABEL[p]||p}</th>`).join("");
  const mkt=MKT_SRC.length?`<th class="num mkt" title="Market = average of Underdog (best-ball) + FFC (season-long) QB ranks. The site columns are scored against this.">Market</th>`:"";
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
$("#platsel").onchange=e=>{draftPlatform=e.target.value;header();refresh();};
$("#reset").onclick=()=>{weights=Object.assign({},DATA.weights);sliders();refresh();};
header(); sliders(); weightBars(); refresh();
</script>
</body>
</html>
"""
