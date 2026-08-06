"""
HTML report for the index-blend models. One template, one page, every position.

`render_site(boards, meta)` returns one self-contained HTML string (CSS + JS
inlined, no storage) holding EVERY position's board. `render(result, meta)` is
the one-board call it grew out of and still works: it wraps its argument and
hands it to render_site, so an old caller gets a page with a single position tab
on it and nothing else changes.

It makes three kinds of network request, all optional: team logos and player
headshots from ESPN's image CDN (each has a text fallback -- team abbreviation /
initials avatar), and one small request for this page's own URL to check whether
a newer build has been published (see "freshness check" in the script below).
With no internet, all three fail quietly and the board renders exactly as it did
before any of them existed.

The tab bar is built in the browser from the boards actually present:

  QB Rankings / RB Rankings / ...  -- one per position, in the order given.
  Big Board                        -- everybody at once, ranked on points over
                                      replacement, because 17 pts/gm means
                                      something different at each position.
  How it works                     -- ONE shared tab. It explains whichever
                                      position you're looking at and carries its
                                      own position switcher, rather than each
                                      board shipping a near-identical copy.

All the math is embedded per player as 0-100 factor indices plus a calibration
(a, b, and optional knots); the browser computes the points from the weights
live, per board, so every board keeps its own sliders and its own scale.

POSITION
--------
Nothing position-specific is baked into the HTML text any more -- with several
boards in one file there is no single position to bake. Two mechanisms remain:

  1. Per-board values read out of SITE.boards[pos] in the script (POS, POSLONG,
     POSPL, the calibration, the weights, the platform list...). Everything that
     used to be a page-level constant is now recomputed by loadBoard().
  2. `data-pos` attributes on whole blocks that only make sense for one position
     -- the archetype chips, and Heath's two-path league-winner screen, which is
     a claim about quarterbacks and is left off every other board on purpose.
     The show/hide pass re-runs on every board switch.

The per-board payload key is still "qbs" for every position. It is the wrong
name now, but it is load-bearing in about forty places in the script and
renaming it would buy nothing a reader of this comment doesn't already know.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

# Position words for the labels. Anything not listed falls back to the bare
# abbreviation, which reads fine everywhere it's used ("Search a K...").
_POS_WORDS = {
    "QB": ("Quarterback", "quarterback", "quarterbacks"),
    "RB": ("Running back", "running back", "running backs"),
    "WR": ("Wide receiver", "wide receiver", "wide receivers"),
    "TE": ("Tight end", "tight end", "tight ends"),
}
# The order tabs appear in when the caller doesn't pin one. Draft-board order:
# the positions you argue about first, first.
_POS_ORDER = ["QB", "RB", "WR", "TE", "K", "DST"]


def _board(result: dict, meta: dict) -> tuple[str, dict]:
    """One position's slice of the page payload."""
    pos = str(meta.get("pos") or "QB").upper().strip() or "QB"
    long, lower, plural = _POS_WORDS.get(pos, (pos, pos, pos + "s"))
    return pos, {
        "pos": pos,
        "long": long, "lower": lower, "plural": plural,
        "meta": meta,
        "qbs": result.get("payload", []),
        "weights": result.get("weights", {}),
        "groups": result.get("groups", []),
        "calib": result.get("calib", {"a": 0, "b": 0.25}),
        "backtest": result.get("backtest", {}),
        # ADP-expectation curve + the league-winner thresholds, so the page can
        # show what the bars are instead of asking you to trust them.
        "ratings_meta": result.get("ratings_meta", {}),
    }


def render_site(boards, meta: dict | None = None) -> str:
    """One page, every board.

    `boards` is a list of (result, meta) pairs -- the same two arguments the
    single-board render() takes -- one per position. `meta` is the page's own
    metadata (title, season label); when it's omitted the first board's meta
    stands in, which is what makes render() a one-line wrapper.
    """
    pairs = [_board(r, m) for r, m in boards]
    if not pairs:
        raise ValueError("render_site needs at least one board")

    by_pos = {}
    for pos, b in pairs:
        by_pos[pos] = b                      # last one wins on a duplicate
    # Caller's order is respected; anything it didn't rank falls back to the
    # standard draft-board order, and anything unheard-of goes on the end.
    given = [p for p, _ in pairs]
    order = sorted(dict.fromkeys(given),
                   key=lambda p: (_POS_ORDER.index(p) if p in _POS_ORDER else 99, p))

    site_meta = dict(meta or pairs[0][1]["meta"])
    payload = {
        "meta": site_meta,
        # When this file was generated, in UTC. The page prints it in the
        # viewer's own timezone and uses it to spot a stale cached copy.
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "order": order,
        "boards": by_pos,
        # What the betting market expects each team to score, for the team
        # filter's comparison strip. Imported here rather than at the top of the
        # file on purpose: this module's job is to turn a finished board into
        # HTML, and it should stay renderable when nothing else in src/ will
        # import -- a caller holding a saved board and no data folder still gets
        # a page, just without the outside yardstick on it.
        "team_env": _team_env(),
    }
    # Data last, and by a token no player name can contain: the JSON carries
    # names and free text, and any string replacement run after it is injected
    # could reach inside the data. There is nothing left to replace afterwards.
    return _TEMPLATE.replace("__DATA_JSON__", json.dumps(payload))


def _team_env() -> dict:
    """The market's implied points per team, or an empty block if unavailable.

    Deliberately swallows everything. The comparison strip is a nicety bolted
    onto a page that has to render either way, so a missing schedule file, a
    renamed column or a broken import costs you the strip and not the board.
    """
    try:
        from . import team_env
        return team_env.for_site()
    except Exception:
        return {}


def render(result: dict, meta: dict) -> str:
    """Back-compat: one position, one page. Same page, one tab on it."""
    return render_site([(result, meta)], meta)


# The parts of a build the page actually reads. A result also carries console
# material -- skipped rookies, debug frames -- which has no business on disk in
# a file whose only job is to be re-read by the site builder.
_BOARD_KEYS = ("payload", "weights", "groups", "calib", "backtest", "ratings_meta")


def save_board(result: dict, meta: dict, path) -> Path:
    """Park one finished board on disk so the combined page can pick it up.

    Each position is built by its own script, and rebuilding one should not
    force a rebuild of the others -- a running-back run that fails must not be
    able to take the quarterbacks off the site. So each build saves its own
    board here, and the site builder assembles the page from whatever it finds.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pos = str(meta.get("pos") or "QB").upper().strip() or "QB"
    body = {
        "pos": pos,
        "meta": meta,
        "result": {k: result[k] for k in _BOARD_KEYS if k in result},
        "saved": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def build_site(folder, out_path):
    """Fold every saved board into one page. Returns (path, boards).

    Called by each position build as its last act, so the one-page site is never
    a step you can forget. Returns (None, []) when there is nothing saved yet
    rather than writing an empty page.
    """
    boards = load_boards(folder)
    if not boards:
        return None, []
    boards.sort(key=lambda pair: (_POS_ORDER.index(pair[1]["pos"])
                                  if pair[1].get("pos") in _POS_ORDER else 99,
                                  pair[1].get("pos", "")))
    # The page's heading comes from whichever position leads the tabs, so the
    # title doesn't change depending on which board happened to build last.
    page_meta = {k: v for k, v in boards[0][1].items() if k != "pos"}
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_site(boards, page_meta), encoding="utf-8")
    return out, boards


def load_boards(folder) -> list[tuple[dict, dict]]:
    """Every saved board in a folder, in the shape render_site() wants.

    A file that is missing, half-written or not a board is skipped rather than
    raised on: one corrupt file should cost you that position, not the page.
    """
    out = []
    for p in sorted(Path(folder).glob("*.json")):
        try:
            body = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(body, dict) and isinstance(body.get("result"), dict) \
                and body["result"].get("payload"):
            meta = dict(body.get("meta") or {})
            meta.setdefault("pos", body.get("pos", "QB"))
            out.append((body["result"], meta))
    return out


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
<title>NFL Fantasy Projection Models</title>
<style>
  :root{
    --surface-1:#fcfcfb;--plane:#f5f6f9;--ink:#0b0b0b;--ink-2:#52514e;--muted:#898781;
    --grid:#e1e0d9;--baseline:#c3c2b7;--border:rgba(11,11,11,.10);
    --pos:#2a78d6;--neg:#e34948;--accent:#256abf;--accent-soft:#cde2fb;
    --t1:#184f95;--t2:#256abf;--t3:#5598e7;--t4:#9ec5f4;
    /* The tier ramp is its own thing, eight steps of ONE hue running dark to
       light. Tier is an ordinal -- 3 is further down the board than 2 -- so it
       gets a sequential ramp, not a set of unrelated colours; the four --t
       variables above are two gradients' endpoints and stop at four, which is
       short when a board runs to eleven tiers. Past eight everybody shares the
       last step: eleven blues nobody can tell apart is not information, and the
       tier NUMBER is printed on the divider anyway. */
    --tg1:#123f7a;--tg2:#184f95;--tg3:#1f5faf;--tg4:#256abf;
    --tg5:#3d84d6;--tg6:#5598e7;--tg7:#7aaeee;--tg8:#9ec5f4;
    --arch:#4a3aa7;--good:#006300;
    --brand:#123f86;--brand-2:#3a2f8f;--on-brand:#ffffff;--radius:16px;
    --shadow:0 1px 2px rgba(11,11,11,.05),0 14px 30px -18px rgba(11,11,11,.22);
  }
  :root[data-theme="dark"]{
    --surface-1:#1a1a19;--plane:#0d0d0d;--ink:#fff;--ink-2:#c3c2b7;--muted:#898781;
    --grid:#2c2c2a;--baseline:#383835;--border:rgba(255,255,255,.10);
    --pos:#3987e5;--neg:#e66767;--accent:#3987e5;--accent-soft:#12233b;
    --t1:#9ec5f4;--t2:#5598e7;--t3:#3987e5;--t4:#184f95;--arch:#9085e9;--good:#0ca30c;
    /* Same ramp, run the other way. A dark page needs tier 1 to be the LIGHT
       end -- the darkest blue is the one that disappears into #0d0d0d, and the
       tier you most need to see is the top one. */
    --tg1:#c3dcf8;--tg2:#9ec5f4;--tg3:#7aaeee;--tg4:#5598e7;
    --tg5:#3d84d6;--tg6:#2f76cc;--tg7:#256abf;--tg8:#1d5aa4;
    --brand:#10336e;--brand-2:#2a2170;--on-brand:#ffffff;
    --shadow:0 1px 2px rgba(0,0,0,.5),0 16px 34px -20px rgba(0,0,0,.8);
  }
  @media(prefers-color-scheme:dark){:root[data-theme="auto"]{
    --surface-1:#1a1a19;--plane:#0d0d0d;--ink:#fff;--ink-2:#c3c2b7;--muted:#898781;
    --grid:#2c2c2a;--baseline:#383835;--border:rgba(255,255,255,.10);
    --pos:#3987e5;--neg:#e66767;--accent:#3987e5;--accent-soft:#12233b;
    --t1:#9ec5f4;--t2:#5598e7;--t3:#3987e5;--t4:#184f95;--arch:#9085e9;--good:#0ca30c;
    --tg1:#c3dcf8;--tg2:#9ec5f4;--tg3:#7aaeee;--tg4:#5598e7;
    --tg5:#3d84d6;--tg6:#2f76cc;--tg7:#256abf;--tg8:#1d5aa4;
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
  /* The position toggle sets .hidden on whole blocks, and several of them carry a
     class with an explicit display (.ov is a grid). An author rule beats the
     browser's own [hidden]{display:none}, so without !important those blocks stay
     visible and an RB board would show the quarterback explainer underneath the
     running-back one. */
  [hidden]{display:none !important}
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
  /* League-winner filter. Non-matching QBs are dimmed and sorted underneath rather
     than removed: mid-draft, the row you suddenly need is exactly the one a real
     filter would have hidden. Hovering brings a dimmed row most of the way back so
     it stays readable when you go looking for a name that just got called. */
  tbody tr.row.dim>td{opacity:.36;transition:opacity .12s}
  tbody tr.row.dim:hover>td{opacity:.8}
  /* A labelled row rather than a heavier border. Every row already has a rule under
     it, so a 2px version of the same line reads as noise instead of as a boundary --
     and the boundary is the one thing on a filtered board you shouldn't have to infer. */
  tbody tr.lwsep>td{border-top:2px solid var(--accent);padding:8px 10px 7px;font-size:11px;
    text-transform:uppercase;letter-spacing:.05em;font-weight:700;color:var(--ink-2);background:var(--plane)}
  .lwcount{margin:0!important;font-variant-numeric:tabular-nums}
  .lwcount b{color:var(--ink);font-weight:700}
  /* --- the team strip ---------------------------------------------------
     Four numbers across the top, then the whole offence laid out by position.
     The numbers are deliberately plain text on the page background rather than
     tiles-with-borders: this sits directly above a dense table and a second
     boxed thing right there competes with the board for the eye. */
  .teamstrip{padding:16px 18px}
  .tshead{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:4px}
  .tshead h3{margin:0;font-size:17px;letter-spacing:-.01em}
  .tsnums{display:flex;flex-wrap:wrap;gap:10px 30px;margin:12px 0 4px}
  .tsnum{min-width:112px}
  .tsnum .v{font-size:22px;font-weight:800;letter-spacing:-.02em;font-variant-numeric:tabular-nums;line-height:1.15}
  .tsnum .k{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--ink-2);font-weight:700}
  .tsnum .s{font-size:11.5px;color:var(--muted)}
  .tsnum .v.over{color:var(--neg)}.tsnum .v.under{color:var(--good)}
  .tsbar{height:6px;border-radius:4px;background:var(--plane);overflow:hidden;margin:10px 0 2px;position:relative}
  .tsbar i{position:absolute;top:0;bottom:0;left:0;border-radius:4px;background:var(--accent)}
  .tsbar u{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--ink);opacity:.7}
  .tsgrid{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}
  .tspos{flex:1 1 190px;min-width:170px;border:1px solid var(--border);border-radius:10px;padding:9px 11px;background:var(--surface-1)}
  .tspos h4{margin:0 0 7px;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--ink-2)}
  .tsrow{display:flex;justify-content:space-between;gap:8px;font-size:13px;padding:3px 0;align-items:baseline}
  .tsrow.here{font-weight:700}
  .tsrow .n{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .tsrow .p{font-variant-numeric:tabular-nums;color:var(--ink-2);white-space:nowrap}
  .tsrow .p b{color:var(--ink)}
  .tsnone{font-size:12.5px;color:var(--muted)}
  .tswarn{font-size:12px;color:var(--muted);margin-top:12px;line-height:1.5}
  .rank{font-variant-numeric:tabular-nums;color:var(--accent);font-weight:800;font-size:15px;width:32px}
  /* A rank inside a big tier is still printed -- you need to know roughly where a
     man goes -- but it is not a verdict, and it was dressed like one. Bold accent
     numerals down 51 rows say "the board is sure #71 beats #72", and the board
     has been measured and is not sure: inside a tier it is a coin toss. So a rank
     with a real claim behind it keeps the accent, and one that is mostly a
     position on a list recedes to ordinary text. Nothing is hidden; the emphasis
     just stops overstating. */
  .rank.soft{color:var(--ink-2);font-weight:600}
  /* The tier rail. Three pixels down the left edge of every rank cell, one hue,
     stepping darker-to-lighter as you go down the board. Divider rows leave the
     screen as soon as you scroll; this doesn't, so you can always see which
     block you're reading and where it ends. */
  #tbody td.rank{border-left:3px solid transparent}
  /* Tier dividers, built like the round dividers on the Big Board below. A full
     row rather than a heavier rule, because the label is the point: the board's
     honest claim is "these N are one group", and a line can't say N. */
  tr.tiersep td{background:var(--plane);color:var(--ink-2);font-size:11.5px;font-weight:700;
    letter-spacing:.05em;text-transform:uppercase;padding:8px 12px 7px;border-top:1px solid var(--baseline)}
  tr.tiersep .tn{color:var(--ink);font-weight:800}
  tr.tiersep .tsw{display:inline-block;width:22px;height:8px;border-radius:3px;margin-right:10px;vertical-align:1px}
  tr.tiersep .tnote{text-transform:none;letter-spacing:0;font-weight:500;color:var(--muted)}
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

  /* --- segmented position switcher -------------------------------------
     Used twice: to pick which model "How it works" is describing, and to
     filter the big board down to one position. Same control, so the two
     read as the same idea. */
  .seg{display:inline-flex;gap:2px;padding:3px;border-radius:11px;background:var(--plane);
    border:1px solid var(--border)}
  .seg button{appearance:none;border:0;background:transparent;color:var(--ink-2);cursor:pointer;
    font:inherit;font-size:12px;font-weight:700;letter-spacing:.02em;padding:5px 13px;
    border-radius:8px;transition:background .12s,color .12s}
  .seg button:hover{color:var(--ink)}
  .seg button[aria-pressed="true"],.seg button[aria-selected="true"]{
    background:var(--accent);color:#fff}
  .ovpick{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:14px 18px}
  .ovpick .note{margin:0}

  /* --- big board -------------------------------------------------------- */
  /* The position chip is the big board's whole orientation: without it every
     row is just a name, and which scarcity you're buying is the question the
     board exists to answer. Coloured per position so a run of one shows up as
     a block of colour rather than something you have to read for. */
  .pc{display:inline-block;font-size:10px;font-weight:800;letter-spacing:.06em;padding:2px 7px;
    border-radius:6px;color:#fff;margin-right:8px;min-width:26px;text-align:center;vertical-align:1px}
  .pc.QB{background:#184f95}.pc.RB{background:#0f6b46}.pc.WR{background:#8a4b12}
  .pc.TE{background:#6b2f8a}.pc.K,.pc.DST{background:#52514e}
  #bigtbl .vor{font-variant-numeric:tabular-nums;font-weight:700}
  #bigtbl .vor.neg{color:var(--muted);font-weight:400}
  #bigtbl td.rd{color:var(--muted);font-size:12px;white-space:nowrap}
  /* Round dividers. On a cross-position board the useful unit isn't the tier,
     it's "am I still in round 3" -- so the rounds get ruled off. */
  tr.rdsep td{background:var(--plane);color:var(--ink-2);font-size:11.5px;font-weight:700;
    letter-spacing:.06em;text-transform:uppercase;padding:7px 12px;border-top:1px solid var(--baseline)}
  /* Long-standing gap: .mut was already being written into cells for "there is
     no number here" and had no rule, so a dash meant to recede read as data. */
  .mut{color:var(--muted)}
  @media(max-width:640px){.wname{width:auto}}
</style>
</head>
<body>
<header>
  <div class="hgrid">
    <div><h1 id="pageTitle">NFL Projection Models <span class="pill" id="seasonPill"></span></h1>
      <div class="sub" id="subline"></div></div>
    <div class="spacer"></div>
    <!-- There used to be a cross-link here to the other position's board, back
         when each position was its own file. They're tabs in this one now, so
         the link has nowhere to point. meta.sibling is ignored on purpose --
         a build script still setting it does no harm. -->
    <button class="toggle" id="themeBtn" type="button">◑ Theme</button>
  </div>
  <!-- Built in the browser from the boards this file actually carries: one tab
       per position, then the combined Big Board, then a single "How it works".
       Rankings first and open by default -- the board is what you came for on
       draft day; "How it works" is reference material you read once. -->
  <div class="hgrid"><div class="tabs" role="tablist" id="tabs"></div></div>
</header>

<div class="wrap">
  <section id="overview">
    <!-- One "How it works" for the whole site. Each board's copy is written into
         the same cards behind data-pos attributes and only one set is ever
         visible, so this switcher is what turns two near-identical explainer
         tabs into one. It moves the active board too, so coming back out of
         here lands you on the position you were just reading about. -->
    <div class="card ovpick" id="ovpickCard">
      <span class="note" style="margin:0">Reading the</span>
      <div class="seg" id="ovpos" role="tablist"></div>
      <span class="note" style="margin:0">model.</span>
    </div>
    <div class="card">
      <h2>What this model does</h2>
      <p data-pos="QB">It projects each quarterback's <strong>fantasy points</strong> as a transparent blend of factors —
      <strong>who the player is</strong> and <strong>the situation he's in</strong>. Every factor is scored
      0–100 (his percentile among QBs), then combined with the weights below. Nothing is a black box: you can
      see exactly how much each factor counts, and change it on the <strong>QB Rankings</strong> tab.</p>
      <p data-pos="RB">It projects each running back's <strong>fantasy points per game</strong> as a transparent blend of
      factors — <strong>who the player is</strong> and <strong>the backfield he's in</strong>. Every factor is scored
      0–100 (his percentile among the backs on this board), then combined with the weights below. Nothing is a black
      box: you can see exactly how much each factor counts, and change it on the <strong>RB Rankings</strong> tab.
      The scoring setting it's using is printed under the title at the top of the page.</p>
      <p data-pos="WR">It projects each receiver's <strong>fantasy points per game</strong> as a transparent blend of
      factors — <strong>who the player is</strong> and, far more than at any other position, <strong>how much of his
      offence runs through him</strong>. Every factor is scored 0–100 and combined with the weights below, and you can
      change any of them on the <strong>WR Rankings</strong> tab. One thing works differently here and it's worth
      knowing: the upcoming season isn't ranked against itself. A season nobody has played is a shorter list than a
      finished one — about 130 receivers off a depth chart against 180 to 200 who actually played — and a shorter list
      can't reach as high a percentile, so every receiver would quietly score low. Each of this year's numbers is
      placed into the last three finished seasons instead, and the three placements averaged.</p>
      <p data-pos="TE">It projects each tight end's <strong>fantasy points per game</strong> the same way the receiver board
      does — the same factors, the same 0–100 scoring, the same three-season placement for a year nobody has played, and the
      same sliders on the <strong>TE Rankings</strong> tab. What changed is every number inside, because they were re-fitted
      on <strong>1,028 tight end seasons from 2018 to 2025</strong> rather than borrowed. The position is different enough
      that borrowing would have been wrong: the average starting tight end sees <strong>five targets a game</strong>, roughly
      half a starting receiver's, so bars set on receivers land in the wrong place here almost every time. Where a number
      moved, the page says what moved it.</p>
      <div id="btstat"></div>
    </div>
    <div class="card">
      <h2>Factor weighting</h2>
      <p data-pos="QB">What share of the projection each factor drives, out of 100%. Talent and archetype anchor the board.
      Talent is built from each QB's <strong>last three healthy seasons</strong> (12+ games, never reaching back
      more than five years) with <strong>touchdown luck regressed out</strong>, and thin résumés are pulled toward
      the field — so a sustained elite isn't sunk by one injury year, and a small hot sample can't crown someone.
      There is deliberately <strong>no "recent form" factor</strong>.</p>
      <p data-pos="RB">What share of the projection each factor drives, out of 100%. <strong>Talent and volume</strong> anchor
      the board. Talent is built from each back's recent seasons with <strong>touchdown luck regressed out</strong> —
      short-yardage scores are the noisiest thing a running back does, and a back who found the end zone eleven times
      once is not eleven-touchdown good. Thin résumés are pulled toward the field, so a 40-carry rookie can't leapfrog
      the board on one good month.</p>
      <p data-pos="RB"><strong>Receiving is weighted heavily on purpose.</strong> A target is worth far more than a carry
      in any points-per-catch format, so backs who stay on the field for third down have a weekly floor the pure runners
      never get. That, plus <strong>backfield share</strong>, is most of what separates a useful back from a handcuff.</p>
      <p data-pos="WR">What share of the projection each factor drives, out of 100%. <strong>The job is most of the
      answer here.</strong> Volume, Opportunity and Role are 44 of the 100 weights between them, because a receiver
      cannot score points he never gets thrown. Volume is his share of the targets; Opportunity adds how far downfield
      those targets go, so a receiver running deep routes gets credit a raw count misses; Role is how often he's on the
      field at all.</p>
      <p data-pos="WR"><strong>Efficiency is deliberately held to 11.</strong> Yards and first downs per route separate
      two receivers who have the same job — they don't invent a job for someone who doesn't have one, and a great
      per-route number on forty routes is mostly noise. <strong>Vegas is 14</strong>, higher than the backs' board at 10,
      because a team's implied point total tracks its receivers' scoring nearly twice as closely as its backs'. Touchdowns
      are regressed to what the volume predicts before they count at all.</p>
      <p data-pos="TE">What share of the projection each factor drives, out of 100%. <strong>The job is even more of the
      answer here than at receiver</strong> — Volume, Opportunity and Role are 47 of the 100 weights. A tight end's share of
      his team's targets predicts next season better than anything else he does, and the two efficiency measures are the
      weakest link in the table, so the board is built on how much work he gets.</p>
      <p data-pos="TE"><strong>Vegas is 9, not the receivers' 14.</strong> A team's implied point total tracks its tight end
      room at <strong>+0.31</strong>, against <strong>+0.54</strong> for its receivers — a bit over half the strength, so a
      bit over half the weight. It also arrives by a different road: a good offence lifts a tight end mainly through
      <strong>touchdowns</strong> (+0.41) rather than targets (+0.10). His slice of the pie barely widens; the pie gets
      bigger. <strong>Efficiency is 11</strong>, same as receiver, but the two halves are reversed — yards per route is the
      better measure here and first downs per route the junior partner, where at receiver it's the other way round.</p>
      <div id="weightBars"></div>
    </div>
    <div class="card" data-pos="QB">
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
      <p data-pos="QB">Beyond the projection, each QB gets four quick read-outs. These <strong>don't change the projection</strong> —
      they sit on top of it to help you draft:</p>
      <p data-pos="RB">Beyond the projection, each back gets a few quick read-outs. These <strong>don't change the projection</strong> —
      they sit on top of it to help you draft:</p>
      <p data-pos="WR">Beyond the projection, each receiver gets a few quick read-outs. These <strong>don't change the projection</strong> —
      they sit on top of it to help you draft:</p>
      <p data-pos="TE">Beyond the projection, each tight end gets a few quick read-outs. These <strong>don't change the projection</strong> —
      they sit on top of it to help you draft:</p>
      <div class="ov" data-pos="TE">
        <div class="ovh">Floor</div><div>His bad-week baseline — the recency-weighted 25th-percentile game he turns in.
          Graded <b style="color:var(--good)">Safe</b> / <b style="color:#9a6600">Moderate</b> / <b style="color:var(--neg)">Risky</b> vs the field.
          Read this one carefully at tight end: outside the top few, a <em>good</em> floor here is a game you'd have benched
          at any other position, so the grade is relative to the tight ends and nothing else.</div>
        <div class="ovh">Ceiling</div><div>How often he pops: share of games over <b>20</b> and <b>25</b> points
          (recent games count more; thin samples pulled toward the field). <b>High</b> / <b>Medium</b> / <b>Low</b>. Very few
          tight ends ever clear these bars, which is exactly why the ones who do are worth paying for.</div>
        <div class="ovh">ADP</div><div>Where he's drafted on each platform, as a <b>TE rank</b> — <b>Sleeper</b>, <b>ESPN</b> &amp; <b>FFC</b> (redraft) and
          <b>Underdog</b> (best-ball). A site only gets a column if it actually prices tight ends in your file. The <b>Market</b> column
          is a neutral reference: the sites blended and re-ranked, preferring <b>Underdog</b> and <b>FFC</b>, the two you don't draft on.
          When the platform you're drafting on is part of that blend it's taken back out before he's graded, so no site is measured
          against a market containing itself. Set <b>&ldquo;Drafting on&rdquo;</b> to your platform and the
          <b style="color:var(--good)">▲Value</b> / <b style="color:var(--neg)">▼Reach</b> tag flags who your platform drafts
          <b>earlier or later than that Market</b>.</div>
        <div class="ovh">Risk at ADP</div><div>Whether his price is worth it: paying an early pick for a shaky floor or thin
          ceiling — or reaching past where the model ranks him — is risky. A late tight end is low-risk by definition.</div>
        <div class="ovh">Worth the pick?</div><div>The same value question answered in <b>points</b> instead of draft slots — his
          projection minus what a pick at his price has historically returned. It moves live with the weight sliders.</div>
        <div class="ovh">A ceiling on the projection</div><div>No tight end is projected above roughly <b>2.0 points per expected
          target</b>, plus a point. It binds on <b>24 of 829</b> historical seasons — mostly Taysom Hill, who is a tight end only
          on paper, plus a handful of genuinely huge touchdown years. At the other end it stops a tight end on two expected
          targets a game from being projected into a startable week on rate stats alone.</div>
      </div>
      <div class="ov" data-pos="WR">
        <div class="ovh">Floor</div><div>His bad-week baseline — the recency-weighted 25th-percentile game he turns in.
          Graded <b style="color:var(--good)">Safe</b> / <b style="color:#9a6600">Moderate</b> / <b style="color:var(--neg)">Risky</b> vs the field.
          Receiver is the position where floor and ceiling come apart hardest: a deep threat and a slot receiver can average
          the same points and give you completely different weeks.</div>
        <div class="ovh">Ceiling</div><div>How often he pops: share of games over <b>20</b> and <b>25</b> points
          (recent games count more; thin samples pulled toward the field). <b>High</b> / <b>Medium</b> / <b>Low</b>.</div>
        <div class="ovh">ADP</div><div>Where he's drafted on each platform, as a <b>WR rank</b> — <b>Sleeper</b>, <b>ESPN</b> &amp; <b>FFC</b> (redraft) and
          <b>Underdog</b> (best-ball). A site only gets a column if it actually prices receivers in your file. The <b>Market</b> column
          is a neutral reference: the sites blended and re-ranked, preferring <b>Underdog</b> and <b>FFC</b>, the two you don't draft on.
          When the platform you're drafting on is part of that blend it's taken back out before he's graded, so no site is measured
          against a market containing itself. Set <b>&ldquo;Drafting on&rdquo;</b> to your platform and the
          <b style="color:var(--good)">▲Value</b> / <b style="color:var(--neg)">▼Reach</b> tag flags who your platform drafts
          <b>earlier or later than that Market</b>.</div>
        <div class="ovh">Risk at ADP</div><div>Whether his price is worth it: paying an early pick for a shaky floor or thin
          ceiling — or reaching past where the model ranks him — is risky. A late receiver is low-risk by definition.</div>
        <div class="ovh">Worth the pick?</div><div>The same value question answered in <b>points</b> instead of draft slots. Five years
          of receiver draft prices were joined to what receivers at those prices really averaged — <b>288 seasons, 2020–2024</b> — giving
          a curve of <em>what a pick is worth</em>; this is his projection minus that. It moves live with the weight sliders.</div>
        <div class="ovh">A ceiling on the projection</div><div>No receiver is projected above roughly <b>1.9 points per expected
          target</b>, plus a point. That bar binds on two very different groups and is meant to: a handful of genuinely elite
          receivers whose per-target rate the model would otherwise run away with, and the bottom of the board, where a receiver
          on two expected targets a game cannot be projected into a startable week no matter how good his rate stats look.</div>
      </div>
      <div class="ov" data-pos="RB">
        <div class="ovh">Floor</div><div>His bad-week baseline — the recency-weighted 25th-percentile game he turns in.
          Graded <b style="color:var(--good)">Safe</b> / <b style="color:#9a6600">Moderate</b> / <b style="color:var(--neg)">Risky</b> vs the field.
          For a running back this is mostly a receiving question: the backs who catch passes still score on the days the
          run game gets stuffed.</div>
        <div class="ovh">Ceiling</div><div>How often he pops: share of games over <b>20</b> and <b>25</b> points
          (recent games count more; thin samples pulled toward the field). <b>High</b> / <b>Medium</b> / <b>Low</b>.
          The bars are lower than the quarterback board's on purpose — a 25-point game is a routine week for a starting
          QB and a genuinely big one for a back.</div>
        <div class="ovh">ADP</div><div>Where he's drafted on each platform, as an <b>RB rank</b> — <b>Sleeper</b>, <b>ESPN</b> &amp; <b>FFC</b> (redraft) and
          <b>Underdog</b> (best-ball). A site only gets a column if it actually prices backs in your file, so this board may show fewer
          than four. The <b>Market</b> column is a neutral reference: the sites blended and re-ranked — it prefers <b>Underdog</b> and
          <b>FFC</b>, the two you don't draft on, and widens to the rest only when those two don't both price backs. When the platform
          you're drafting on is itself part of that blend, it's taken back out before he's graded against it, so no site is ever
          measured against a market containing itself.
          Set <b>&ldquo;Drafting on&rdquo;</b> to your platform and the <b style="color:var(--good)">▲Value</b> /
          <b style="color:var(--neg)">▼Reach</b> tag flags who your platform drafts <b>earlier or later than that Market</b>.
          Leave it on <b>Consensus</b> to compare the model to the market instead; open a row for the full gap.</div>
        <div class="ovh">Risk at ADP</div><div>Whether his price is worth it: paying an early pick for a shaky floor or thin
          ceiling — or reaching past where the model ranks him — is risky. A late back is low-risk by definition, because
          you haven't spent anything to find out.</div>
        <div class="ovh">Worth the pick?</div><div>The same value question answered in <b>points</b> instead of draft slots. Past
          draft prices were joined to what backs at those prices really averaged, giving a curve of <em>what a pick is worth</em>;
          this is his projection minus that. <b style="color:var(--good)">+5</b> a game is the bar Heath's league-winning backs
          cleared and <b style="color:var(--good)">+2</b> is ordinary good value. Those two bars were measured in <b>full PPR</b> —
          in half-PPR they're a shade generous, so treat them as round numbers rather than a line in the sand.
          It moves live with the weight sliders.</div>
        <div class="ovh">No league-winner screen yet</div><div>The quarterback board carries Heath's two-path screen. The
          running-back version of that research — first four years in the league, contract status, and how much of the
          offense's expected points a back earns through the air — needs data this build doesn't load yet, so
          <b>this board deliberately shows no gate at all</b> rather than grading backs against bars that were written
          about quarterbacks.</div>
      </div>
      <div class="ov" data-pos="QB">
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
      <p data-pos="QB">A leak-free 4-year backtest is blunt about one thing: <strong>ADP already out-ranks this model</strong> — the market
      prices in everything the model sees plus offseason news, so don't draft <em>against</em> consensus on the model's say-so
      alone. Use the board like this instead:</p>
      <p data-pos="RB">The same rule holds here as on the quarterback board: <strong>the market is smart</strong>. It prices in
      everything the model sees plus training-camp news, so don't draft <em>against</em> consensus on the model's say-so alone.
      Use the board like this instead:</p>
      <p data-pos="WR">Same rule here as on the other two boards: <strong>the market is smart</strong>. It prices in
      everything the model sees plus camp news, so don't draft <em>against</em> consensus on the model's say-so alone.
      Use the board like this instead:</p>
      <p data-pos="TE">Same rule here as on the other three boards: <strong>the market is smart</strong>. It prices in
      everything the model sees plus camp news, so don't draft <em>against</em> consensus on the model's say-so alone.
      Use the board like this instead:</p>
      <div class="ov" data-pos="TE">
        <div class="ovh">ADP is the backbone</div><div>Start from the <b>Market</b> column — that's the neutral anchor. Set
          <b>&ldquo;Drafting on&rdquo;</b> to your platform to see who your platform prices as a value or reach <em>versus that market</em>.</div>
        <div class="ovh">Routes before everything</div><div>Same first question as the receiver board, different bar. A tight end
          who runs a route on <b>65%+</b> of his team's dropbacks averaged <b>7.0 points a game the following season</b> against
          <b>3.5</b> for everyone else — and <b>20.7%</b> of them went on to a 10-point season against <b>1.3%</b> of the rest.
          The receivers' 75% bar would have been the wrong screen here: the median tight end who plays a full season runs
          <b>50%</b> of the routes, so three quarters is a bar the position mostly doesn't clear. 65% was picked because it's
          where the separation is widest without the group shrinking to a handful.</div>
        <div class="ovh">Then the chains</div><div><span class="fl g">Moves the chains</span> is the same first-down-per-route
          badge, re-fitted again. The receivers' <b>0.095</b> is above the ninetieth percentile at tight end, so on our numbers it
          would flag almost nobody. At <b>0.065</b> over at least <b>200 routes</b> it catches 71 of 395 qualifying seasons, worth
          <b>8.0 points a game the next season against 4.2</b>, with <b>28.2%</b> reaching 10+ against 3.7%. Like the receivers'
          version it's a badge and not a factor, and for the same reason: nearly all of the edge sits at the top — among tight ends
          already scoring 5–8 points a game it's worth <b>+0.07</b>, and only above 11 does it become worth <b>+2.97</b>.</div>
        <div class="ovh">Where he sits in the room</div><div>Same blend as the receiver board: <b>where the team lists him in
          August</b> against <b>where he actually ranked in routes last year</b>, leaning on last year in proportion to how much of
          it he played, and only <b>15%</b> if he changed teams. Depth is read three deep here rather than four — the fourth tight
          end on a roster runs <b>19%</b> of the routes for a <b>3.5%</b> target share, which is not a fantasy player in any
          format.</div>
        <div class="ovh">Career window</div><div><span class="fl g">Career window</span> means <b>years three to seven</b>, two
          years longer than the receivers'. This was measured rather than assumed: a tight end's own year-over-year change in points
          per game is still flat in years six (<b>-0.05</b>) and seven (<b>-0.18</b>) and doesn't properly turn until year eight
          (<b>-0.89</b>), and the two highest top-12-finish rates on the whole table are years six and seven at <b>16.4%</b> and
          <b>15.5%</b>. Docking a sixth-year tight end the way the receiver board does would have been backwards.</div>
        <div class="ovh">No crowded-room flag — on purpose</div><div>The receiver board flags crowded rooms. This one doesn't,
          because the effect isn't there. Over <b>254</b> starting-tight-end seasons, how many routes the second tight end ran has
          essentially <b>no relationship</b> to what the first one scored (<b>r=+0.004</b>), and the starters actually averaged
          <em>more</em> when the man behind them played a lot. A two-tight-end offence is usually a team that likes throwing to
          tight ends.</div>
        <div class="ovh">What's missing</div><div><b>Route share is estimated</b>, not charted — and that proxy is shakier here
          than at receiver, because a tight end can be on the field all day as a blocker and the box score never says so. There's
          also <b>no 2025 draft-price data</b> on any platform, so the ADP fit skips that year entirely.</div>
      </div>
      <div class="ov" data-pos="WR">
        <div class="ovh">ADP is the backbone</div><div>Start from the <b>Market</b> column — that's the neutral anchor. Set
          <b>&ldquo;Drafting on&rdquo;</b> to your platform to see who your platform prices as a value or reach <em>versus that market</em>.</div>
        <div class="ovh">Routes before everything</div><div>The first thing to read on any receiver is <b>how often he's on the
          field</b>. A receiver who runs a route on <b>75%+</b> of his team's dropbacks averaged <b>9.9 points a game the following
          season</b>; everyone else averaged <b>4.8</b>. That one line separates the board better than any talent measure in it, which is
          why <span class="fl g">Full-time routes</span> leads the chip row and <span class="fl r">Part-time role</span> is a real warning.</div>
        <div class="ovh">Then the chains</div><div><span class="fl g">Moves the chains</span> is Heath's first-down-per-route badge.
          He states it at <b>0.115</b> on charted routes; ours are estimated from snap share, a different-sized denominator, so on our
          numbers 0.115 flags three receivers out of 128 — a needle, not a screen. Re-fitted on 855 historical seasons the bar lands at
          <b>0.095</b>: roughly the top tenth of receivers, worth <b>12.2 points a game the next season against 6.3</b>, with 58% of them
          reaching a startable 12+. It's a badge and not a factor on purpose — the edge sits almost entirely at the top of the board.</div>
        <div class="ovh">Where he sits in the room</div><div>The depth chart is in here, but it is not the whole vote. Entering a
          season there are two readings of a receiver's spot: <b>where the team lists him in August</b>, and <b>where he actually ranked
          in routes last year</b>. The model averages them, and how far it leans on last year depends on how much of last year he played
          — a full 17 games on the same team is worth <b>75%</b> of the vote, thirteen games about half, nine or fewer only <b>30%</b>,
          and a receiver who <b>changed teams</b> just <b>15%</b>, because his ranking was in somebody else's room. Playing hurt is the
          reason this matters: a number one who missed six weeks ranks like a number two without ever having lost the job. The blend
          applies to the season ahead only — a finished season has no chart to argue with, so there the tape is the whole answer.</div>
        <div class="ovh">Which way the job is moving</div><div><span class="fl g">Role growing</span> and
          <span class="fl g">Targets trending up</span> are the model reading a two-year slope, not a single season. At this position
          last year's target share is the single best guess at this year's, so the direction it's moving is most of what's left.</div>
        <div class="ovh">Career window</div><div><span class="fl g">Career window</span> means years three to five, where receiver
          production peaks. It's later than the running backs' window and much later than the market usually assumes — a receiver's
          third year is not "already broken out," it's the year to buy.</div>
        <div class="ovh">Crowded rooms</div><div><span class="fl r">Crowded room</span> flags the six offences with the most contested
          target trees. <b>Nothing is deducted for it</b> — a crowded room is already priced into a receiver's target share, and
          subtracting it twice would double-count. It's there so you know why two similar projections might draft very differently.</div>
        <div class="ovh">What's missing</div><div><b>Route share is estimated</b>, not charted — snap share times team dropbacks. It's a
          good proxy and it isn't the real thing. There's also <b>no 2025 draft-price data</b> on any platform, so the ADP fit skips that
          year entirely.</div>
      </div>
      <div class="ov" data-pos="RB">
        <div class="ovh">ADP is the backbone</div><div>Start from the <b>Market</b> column (Underdog + FFC blended) — that's the neutral
          anchor. Set <b>&ldquo;Drafting on&rdquo;</b> to your platform to see who your platform prices as a value or reach <em>versus that market</em>.</div>
        <div class="ovh">Role beats talent</div><div>The first thing to read on any back is <b>how much of the backfield he owns</b>.
          A good player splitting carries three ways scores like a bench player; an ordinary one with the job to himself scores
          like a starter. That's why <span class="fl g">Bellcow</span> and <span class="fl r">Committee</span> lead the chip row.</div>
        <div class="ovh">Then receiving work</div><div><span class="fl g">79-target pace</span> is an absolute bar, not a percentile:
          79 is what Heath's twenty best league-winning back seasons averaged in targets. <span class="fl r">No pass game role</span>
          is the other end — a two-down back whose season dies the moment his team falls behind.</div>
        <div class="ovh">Age is the hard one</div><div>The average league-winning back was <b>25</b>, and 85% of those seasons came from
          players 27 or younger. <span class="fl g">Prime age</span> means 25 or under; a red <span class="fl r">Age 29</span> chip is
          the model telling you the history is against him even when the projection isn't.</div>
        <div class="ovh">Floor / Ceiling / Risk</div><div>The draft <em>context</em> a raw ADP number can't give you: how safe his
          week-to-week floor is, how often he pops, and whether his price is worth it.</div>
        <div class="ovh">What's missing</div><div>This build doesn't yet know about contract year, goal-line carries, or how explosive
          a back's runs are. It also has <b>no rookie projections</b> — a back with no NFL games has nothing to measure. Both of
          those are real gaps, not rounding errors, so don't read a missing rookie as a low ranking.</div>
      </div>
      <div class="ov" data-pos="QB">
        <div class="ovh">ADP is the backbone</div><div>Start from the <b>Market</b> column (Underdog + FFC blended) — that's the neutral anchor. Set <b>&ldquo;Drafting on&rdquo;</b> to your platform to see who your platform prices as a value or reach <em>versus that market</em>.</div>
        <div class="ovh">Floor / Ceiling / Risk</div><div>The draft <em>context</em> a raw ADP number can't give you: how safe his week-to-week floor is, how often he pops, and whether his price is worth it.</div>
        <div class="ovh">&ldquo;Why&rdquo; flags</div><div>The transparent reasons behind a profile:
          <span class="fl g">Ascending</span> <span class="fl g">Elite rusher</span> <span class="fl g">Strong team</span>
          <span class="fl r">Weak team</span> <span class="fl r">Thin cast</span> <span class="fl a">New team</span>.
          Vegas win totals now feed the team flags (and a Vegas factor is in the blend).
          Two chips come from fixed league-winner bars rather than from this field's percentiles:
          <span class="fl g">+5 over ADP</span> (beating what his draft slot is worth by five points a game) and
          <span class="fl g">100+ rush pace</span> / <span class="fl r">No rush floor</span> (17-game rushing-attempt pace above 100, or below 55).</div>
        <div class="ovh">The &ldquo;League winners&rdquo; filter</div><div>Heath's finding is that every late-round QB to make the playoffs in 45%+ of ESPN leagues since 2021 either ran 100+ times or played for a McShanahan-tree play-caller — <em>one of the two, not both</em>.
          It's a claim about <b>cheap</b> quarterbacks, which is why <b>&ldquo;Late-round winners&rdquo;</b> is the setting that matches the research: it's the two paths <em>plus</em> a draft cost after Round 10.
          Run against the whole board (&ldquo;any round&rdquo;) it hands you Josh Allen and Jayden Daniels — true, and no help, because you already knew.
          Nothing is ever removed: QBs that don't fit are greyed out and moved below a labelled line, so the guy you suddenly need when your target gets sniped is still right there.</div>
        <div class="ovh">The one real edge</div><div><span class="fl g">Ascending</span> (year 2–3 QBs) is the single spot the backtest found the <em>market itself</em> underrates. Treat it as a genuine lean; the other flags are for understanding, not overrides.</div>
      </div>
    </div>
    <div class="card">
      <h2>Honest limitations</h2>
      <p data-pos="QB">NFL scoring is noisy — treat this as an <strong>edge, not gospel</strong>. Offensive-line quality and a
      brand-new coordinator's exact tendencies aren't cleanly available in free data, so they're
      <strong>proxied</strong> (sack rate, measured team tendencies). Players who just changed teams are
      <strong>flagged</strong>, and their team-based factors are shrunk toward neutral because their new spot is
      uncertain. Rookies with no NFL history aren't projected yet.</p>
      <p data-pos="RB">Running back is the noisiest position in fantasy football, and this is a <strong>first version</strong> —
      treat it as an edge, not gospel. Three things to keep in mind. <strong>Backfield share is measured from last year</strong>,
      so a rookie drafted in April or a free agent who just signed will look wrong until the season starts.
      <strong>Offensive-line quality is proxied</strong>, not measured, because it isn't cleanly available in free data.
      And a back who <strong>changed teams</strong> is flagged, with his team-based factors pulled toward neutral, because
      nobody knows what his new role is yet. Rookies with no NFL games aren't projected at all.</p>
      <p data-pos="WR">Four things to keep in mind. <strong>Route share is estimated, not charted</strong> — it's snap share
      times how often the team drops back, which is close but not the real number, and it's the reason Heath's first-down bar
      had to be re-fitted rather than copied. <strong>Route share and snap share are treated as the same thing</strong>, which
      is true for most receivers and wrong for the ones used as blockers. <strong>Rookies are on the board</strong> — unlike the
      running-back model — but a rookie has no NFL games to measure, so his row leans heavily on where he was drafted and on
      Mike Clay's projection, and is flagged as such. And a receiver who <strong>changed teams</strong> has his team-based
      factors pulled toward neutral, because his new target share is a guess.</p>
      <p data-pos="TE">Everything on the receiver list applies here, and one thing applies harder. <strong>Route share is
      estimated from snap share</strong>, and at tight end that proxy is at its weakest: a blocking tight end can play every
      snap of a game and never be a candidate to catch anything, and nothing in free data separates him from a receiving tight
      end who played the same snaps. Read a high route share on a low-target player as a warning that the estimate is doing
      badly, not as a hidden opportunity. Beyond that: <strong>rookies are on the board</strong> but lean on draft position and
      Mike Clay's projection rather than on NFL games, a tight end who <strong>changed teams</strong> has his team factors pulled
      toward neutral, and <strong>replacement level is the 12th tight end</strong> — one starter per team, no flex share — which
      is the standard setting for a league like yours and is worth knowing if you play in one that starts more.</p>
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
        <!-- The board filter. Its label, its options, the rule each one applies and
             both of its captions come from LWDEF in the script below, keyed by
             position: Heath's two-path screen at quarterback, his route gate and
             first-down badge at receiver. A board with no entry there hides this
             control rather than offering settings that all return nothing. -->
        <label class="note" style="margin:0" id="lwwrap" hidden><span id="lwlab"></span>&nbsp;
          <select class="sortsel" id="lwsel" title="A screen applied to the board. Nothing is hidden — non-matches are dimmed and sorted below the line."></select></label>
        <!-- The team filter. Unlike every other control here it deliberately
             SURVIVES a tab switch, because its whole purpose is to be carried
             from one position to the next: pick Buffalo, then walk QB → RB → WR
             → TE and you are looking at one offence being shared out. This one
             really does hide the rest of the league — dimming 400 players to
             look at eleven is not a filter, it's a haystack. -->
        <label class="note" style="margin:0">Team&nbsp;
          <select class="sortsel" id="teamsel" title="Narrow the board to one team. The choice follows you across position tabs."></select></label>
        <input class="search" id="search" type="search" placeholder="Search…" aria-label="Search">
        <span class="note" style="margin:0">Click a row for the full breakdown.</span>
      </div>
      <p class="note lwcount" id="lwcount" style="margin-top:10px"></p>
    </div>
    <!-- The team strip. Only drawn when a team is picked, and it reads across
         ALL FOUR boards, not just the tab you're on, because "does this offence
         add up" is not a question you can answer one position at a time. -->
    <div class="card teamstrip" id="teamstrip" hidden></div>
    <div class="card" style="padding:14px 16px">
      <div class="tblwrap"><table id="tbl"><thead id="thead"></thead><tbody id="tbody"></tbody></table></div>
    </div>
    <p class="note" id="rnote"></p>
  </section>

  <!-- The combined board. Everyone from every position in one ranking. -->
  <section id="big">
    <div class="card">
      <h2>One board, every position</h2>
      <p>Ranked on <strong>points over replacement</strong> — how much a player beats the
      best guy you could have had for nothing at his own position. That comparison, and not
      raw points, is what makes positions comparable: 17 points a game is a middling
      quarterback and a top-three running back, so ranking on the projection alone would
      hand you the first eight rounds of quarterbacks.</p>
      <p class="note" id="bigrepl" style="margin-top:10px"></p>
      <div style="margin-top:14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <label class="note" style="margin:0">Sort&nbsp;
          <select class="sortsel" id="bigsort">
            <option value="vor">Value over replacement</option>
            <option value="proj">Raw projection</option>
            <option value="adp">Where the market takes him</option>
            <option value="edge">Biggest gap vs the market</option>
          </select></label>
        <div class="seg" id="bigpos" role="group"></div>
        <input class="search" id="bigsearch" type="search" placeholder="Search…" aria-label="Search the big board">
        <span class="note" style="margin:0">Click a row to open him on his own board.</span>
      </div>
    </div>
    <div class="card" style="padding:14px 16px">
      <div class="tblwrap"><table id="bigtbl"><thead id="bighead"></thead><tbody id="bigbody"></tbody></table></div>
    </div>
    <p class="note" id="bignote"></p>
  </section>
</div>

<div class="fresh" id="freshChip" role="status" aria-live="polite">
  <span id="freshMsg">A newer board has been published.</span>
  <button class="go" id="freshGo" type="button">Load it</button>
  <button class="x" id="freshX" type="button" aria-label="Dismiss">&times;</button>
</div>

<script>
/* SITE holds every board; DATA is whichever one you're looking at. Splitting it
   that way is what let several positions move into one file without touching the
   forty-odd places below that read DATA.qbs -- they still read "the board", it
   just isn't the only one in the room any more. Everything derived from DATA is
   `let` and gets recomputed by loadBoard(), because a page-level constant is
   exactly the thing that goes quietly stale when the board underneath it
   changes. */
const SITE = __DATA_JSON__;
const $=s=>document.querySelector(s);
const fmt=(n,d=1)=>(n==null||isNaN(n))?"–":Number(n).toFixed(d);
const ORDER=(SITE.order&&SITE.order.length)?SITE.order.slice():Object.keys(SITE.boards||{});
const POSPL_MAP={QB:"QBs",RB:"RBs",WR:"WRs",TE:"TEs"};

/* Which position this board is. Everywhere below that used to write a literal
   "QB" in front of a rank number writes POS, so an RB board says RB12 and not
   QB12. */
let POS=ORDER[0]||"QB";
let DATA=SITE.boards[POS];
let POSLONG=POS, POSPL=POS+"s";
let GROUPS=[], A=0, B=0.25, KN=[];
let weights={};

/* One set of slider weights per board, kept for the life of the page. Tuning the
   QB board, flipping to the RB board and flipping back used to hand you the
   defaults again -- which on a draft-day page is the same as losing the work. */
const WSTATE={};
function weightsFor(pos){
  if(!WSTATE[pos])WSTATE[pos]=Object.assign({},SITE.boards[pos].weights);
  return WSTATE[pos];
}

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
const BUILT = SITE.built || "";

/* Worked out once and then pasted onto whichever board's subline is showing.
   It used to append itself to the subline on load, which with several boards
   sharing that line would have wiped the stamp the first time you switched. */
let BUILT_LABEL="", BUILT_TITLE="";
(function stampBuildTime(){
  const d = BUILT ? new Date(BUILT) : null;
  if(!d || isNaN(d)) return;
  BUILT_LABEL = "built " +
    d.toLocaleString(undefined,{month:"short",day:"numeric",hour:"numeric",minute:"2-digit"});
  BUILT_TITLE = "This page was generated " + d.toLocaleString();
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
function backtestStat(){
  /* Two numbers, not one. Error says how close the points are; rank says
     whether the board is in the right ORDER, which is the thing you draft off.
     Both are scored on the players a draft actually reaches -- score a points
     scale built for drafted players against every third-stringer who ever ran a
     route and "last year he scored nothing" wins without knowing anything. */
  const bt=DATA.backtest; if(!bt||bt.model_mae==null){$("#btstat").innerHTML="";return;}
  const win=bt.model_mae<bt.baseline_mae, rwin=bt.model_rho!=null&&bt.baseline_rho!=null&&bt.model_rho>bt.baseline_rho;
  let h=`<div class="stat"><b>${fmt(bt.model_mae,2)}</b><span>model error (MAE, pts/gm)</span></div>`+
        `<div class="stat"><b>${fmt(bt.baseline_mae,2)}</b><span>last-year-repeats baseline</span></div>`;
  if(bt.model_rho!=null) h+=`<div class="stat"><b>${fmt(bt.model_rho,3)}</b><span>rank agreement with the real season</span></div>`+
        `<div class="stat"><b>${fmt(bt.baseline_rho,3)}</b><span>same, for last-year-repeats</span></div>`;
  h+=`<div class="note">Each season predicted using only the seasons before it — `+
     `${(bt.seasons||[]).join(", ")}${bt.n?`, ${bt.n} ${bt.population||"player"} seasons`:""}. `+
     `Lower error is better, higher rank agreement is better. `+
     `The model ${win?"beats":"loses to"} the baseline on error and ${rwin?"beats":"loses to"} it on order.</div>`;
  $("#btstat").innerHTML=h;
}

/* --- tabs ----------------------------------------------------------------
   A tab is one of three things: a position (swap the board underneath the
   rankings section), the combined board, or the shared explainer. The position
   tabs all point at the SAME section -- there is one rankings table on the page
   and loadBoard() refills it -- which is why the panel is tracked separately
   from the board. */
let activeTab="rankings";
function buildTabs(){
  const t=$("#tabs");
  t.innerHTML=ORDER.map(p=>
      `<button class="tab" role="tab" data-tab="rankings" data-board="${p}">${p} Rankings</button>`).join("")+
    (ORDER.length>1
      ? `<button class="tab" role="tab" data-tab="big" title="Every position in one ranking, on points over replacement">Big Board</button>`
      : "")+
    `<button class="tab" role="tab" data-tab="overview">How it works</button>`;
  t.querySelectorAll(".tab").forEach(b=>b.onclick=()=>{
    if(b.dataset.board&&b.dataset.board!==POS)loadBoard(b.dataset.board);
    showTab(b.dataset.tab);
  });
}
function showTab(name){
  activeTab=name;
  document.querySelectorAll("#tabs .tab").forEach(b=>b.setAttribute("aria-selected",
    String(b.dataset.tab===name && (!b.dataset.board || b.dataset.board===POS))));
  document.querySelectorAll(".wrap>section").forEach(s=>s.classList.toggle("active",s.id===name));
  if(name==="big")bigRefresh();
}
const root=document.documentElement;
$("#themeBtn").onclick=()=>{const c=root.getAttribute("data-theme");
  root.setAttribute("data-theme",c==="auto"?"light":c==="light"?"dark":"auto");
  $("#themeBtn").textContent="◑ "+root.getAttribute("data-theme");};

function sumW(){return GROUPS.reduce((a,g)=>a+(weights[g]||0),0)||1;}
function composite(q){const s=sumW();return GROUPS.reduce((a,g)=>a+(weights[g]||0)*(q.indices[g]??50),0)/s;}
/* Index score -> points per game. A straight line when there are no bends;
   otherwise the bent scale calibration.py fitted, straight between each pair of
   bends. Past either end it keeps going rather than flattening off, so an
   unusually high or low score still moves the number.
   This has to stay identical to apply() in src/calibration.py -- there is a
   test that projects the same board both ways and compares. In particular the
   TOP end is damped there and has to be damped here: above the last bend there
   is nobody, and the slope up there was read off the two thinnest, luckiest
   points in the fit while also being the steepest slope on the curve. Run it out
   unchecked and the top three backs walk away from RB4 by six points -- a step
   no real season has produced (median RB3->RB4 since 2018 is 0.6, largest 2.3).
   So past the top bend the slope is the average across the top third of the
   bends rather than the final pair, halved. Still monotone: nobody reorders,
   the top of the board just stops running away from the rest of it.

   Takes its scale as arguments rather than reading the page globals, because the
   Big Board has to price a quarterback and a running back in the same pass and
   each position was fitted its own bend. ptsAt() below is this function pointed
   at whichever board you're looking at. */
const HI_DAMP=0.5;
function ptsAtK(c,kn,a,b){
  const n=kn.length;
  if(n<2) return Math.max(0, a + b*c);
  if(c<=kn[0][0]){const s=(kn[1][1]-kn[0][1])/(kn[1][0]-kn[0][0]);
                  return Math.max(0, kn[0][1]+s*(c-kn[0][0]));}
  if(c>=kn[n-1][0]){
    const j=Math.max(0, n-Math.max(2, Math.floor(n/3)));
    let s=(kn[n-1][0]>kn[j][0])?(kn[n-1][1]-kn[j][1])/(kn[n-1][0]-kn[j][0]):0;
    if(!isFinite(s)||s<=0) s=(kn[n-1][1]-kn[n-2][1])/(kn[n-1][0]-kn[n-2][0]);
    return Math.max(0, kn[n-1][1]+s*HI_DAMP*(c-kn[n-1][0]));}
  let i=1; while(i<n-1 && kn[i][0]<c) i++;
  const x0=kn[i-1][0], y0=kn[i-1][1], x1=kn[i][0], y1=kn[i][1];
  return Math.max(0, y0+(y1-y0)*(c-x0)/(x1-x0));
}
function ptsAt(c){return ptsAtK(c,KN,A,B);}
/* Points per index point right where this player sits. On a bent scale that
   changes along the board, so the contribution bars read the local one instead
   of one slope for everybody. */
function slopeAt(c){return (ptsAt(c+0.5)-ptsAt(c-0.5));}
/* A workload ceiling, when the board published one. Running backs carry it:
   the scale above is a percentile map, so it hands a third-stringer the same
   floor it hands a starter, and a player can't score points he never had the
   ball for. `ceil` is CEIL_BASE + CEIL_SLOPE x expected touches, computed in
   src/rb_blend.py -- this only has to enforce it, and it has to enforce it here
   rather than trusting the stored projection because every slider move
   re-projects the whole board from the composite. */
function capped(p,q){return (q&&q.ceil!=null)?Math.min(p,q.ceil):p;}
function projOf(q){return capped(ptsAt(composite(q)),q);}

/* --- availability ---------------------------------------------------------
   projOf is a RATE: what he scores in a game he plays. A draft board is a
   season, so a back expected to miss a month is worth less than his rate says
   even though his rate hasn't changed. `games` comes from the model -- 17 for
   everyone there's no news about, less for anyone there is -- and a board that
   doesn't publish it at all (a WR or TE board built before this existed) has to
   read as a full season, or every back would sink against every quarterback on
   the combined board for no reason at all. */
function availOf(q){const g=q&&q.games; return g==null?1:Math.max(0.2,Math.min(1,g/17));}
/* The weeks he misses are NOT worth nothing. You start somebody else, and this
   board already prices somebody else at every position -- he is the free agent
   the Over-replacement column measures everyone against. So a back down for six
   weeks loses the gap between him and that guy, not six whole games. Charging
   the missing weeks at zero is what drops a real top-twenty back below a
   fullback: correct arithmetic, wrong question.
   Capped at his own rate, so missing games can never help anybody. */
function replRate(pos){
  const qs=((SITE.boards[pos]||{}).qbs)||[];
  if(!qs.length) return 0;
  const ctx=ctxFor(pos);
  const rates=qs.map(x=>rateIn(x,ctx)).sort((a,b)=>b-a);
  return rates[Math.min(replIndex(pos),rates.length-1)];
}
/* ...but nor are they worth FULL replacement, and pretending they are is how a
   man missing a third of the season moves one single spot. You hold his bench
   slot for six weeks; he misses the START, when the pool is whatever eleven
   other people left behind; a return date only ever slips later, never earlier;
   and he comes back on a snap count, so his first fortnight isn't his rate
   either. Two thirds is the honest split. Must match MISSED_WEEK_VALUE in
   src/rankings.py -- that one ranks the printed CSV, this one ranks the page,
   and they have to agree. */
const MISSED_WEEK_VALUE=0.65;
/* Only ever runs for somebody who is actually missing time -- one or two rows
   on a hundred-row board -- so walking the board to find replacement is cheap. */
function blendAvail(rate,q,pos){
  const a=availOf(q);
  return a>=1?rate:rate*a+Math.min(replRate(pos),rate)*(1-a)*MISSED_WEEK_VALUE;
}
/* What the board sorts on: the rate, discounted for the games we don't expect
   to get, with those games credited at a bit under replacement. Same units as
   projOf, so replacement level, VOR and the tier gaps all keep meaning exactly
   what they meant before this existed. */
function valOf(q){return blendAvail(projOf(q),q,POS);}

/* --- pricing a player on a board that isn't the one on screen -------------
   Same arithmetic as composite()/projOf(), with the board handed in instead of
   read off the page. The Big Board needs it: every position keeps its own
   weights, its own factor list and its own scale, and all of them have to be
   priced at once. Slider positions are honoured -- ctxFor reads the same
   per-board weights the sliders write to, so tuning the RB board moves the
   backs on the combined board too. */
function ctxFor(pos){
  const bd=SITE.boards[pos]||{}, cal=bd.calib||{a:0,b:0.25};
  const gs=(bd.groups&&bd.groups.length)?bd.groups:Object.keys(bd.weights||{});
  return {pos, bd, w:weightsFor(pos), gs, a:cal.a??0, b:cal.b??0.25, kn:cal.knots||[]};
}
/* His rate on a board that isn't the one on screen, before availability. */
function rateIn(x,ctx){
  const s=ctx.gs.reduce((t,g)=>t+(ctx.w[g]||0),0)||1;
  const c=ctx.gs.reduce((t,g)=>t+(ctx.w[g]||0)*(x.indices[g]??50),0)/s;
  return capped(ptsAtK(c,ctx.kn,ctx.a,ctx.b),x);
}
function projIn(x,ctx){return blendAvail(rateIn(x,ctx),x,ctx.pos);}

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

/* Replacement level, as a 0-based index into the board sorted by projection.
   ratings_meta.repl_rank is the RANK of the first unstartable player -- QB12 in a
   12-team 1-QB league, RB30 in the same league once you count two starters plus
   half the flex spots -- so the index is one less. The 11 is only a fallback for
   a board built before ratings started publishing it. */
let REPL=11;
/* League size comes from the config now. It used to be REPL+1, which is right for
   quarterbacks by coincidence and badly wrong for every other position. */
let TEAMS=12;
let RD10=120;   // pick 120: the last pick of Round 10, which is where Heath's screen starts
function replIndex(pos){   // 0-based index of the first unstartable player
  const rm=(SITE.boards[pos]||{}).ratings_meta||{};
  return Math.max(0,(rm.repl_rank||12)-1);
}
/* How far apart two projections must be before the order between them means
   anything, in points per game. Measured, not chosen: across 2022-24, every pair
   of drafted players inside a season, sorted by how far apart the board had
   them. Under 1.25 the higher-projected man outscores the lower one 48-61% of
   the time with no trend -- a coin toss. From 1.25 up it climbs every step and
   never comes back: 64%, 70%, 74%, 79%, 82%, 85%, 93%. Holds on 4,537 receiver
   pairs and 3,079 back pairs. Must match TIER_RESOLUTION_PPG in
   src/rankings.py -- that one tiers the printed CSV, this one tiers the page. */
const TIER_RESOLUTION=1.25;
/* A tier is as wide as the model can see and no wider, so it closes when a
   player falls a full resolution below the TOP of it -- not when the gap to the
   man directly above him is big. The old rule measured single adjacent gaps
   against mean + 1 sd of every gap on the board, and that threshold is set by
   the cliffs at the top, so the top eight each became their own tier while 104
   of 128 receivers fell into one block. That shape came from the list, not the
   data. Capping the span instead makes the promise the useful one: same tier
   means the ranking between them is decoration, and the flat middle of the board
   is allowed to look as flat as it actually is. */
/* tier number -> {n, hi, lo}: how many are in it and the top and bottom of the
   band. Rebuilt by tiers() on every slider move, because moving a weight moves
   the boundaries -- a tier is a fact about the current board, not a label
   stamped on a player once. */
let TIERINFO={};
function tiers(sorted){
  TIERINFO={};
  const v=sorted.map(q=>q._v??q._p);
  if(v.length<2){sorted.forEach(q=>q._tier=1);
    if(v.length)TIERINFO[1]={n:1,hi:v[0],lo:v[0]};return;}
  let t=1,top=v[0];sorted[0]._tier=1;
  for(let i=1;i<v.length;i++){
    if(!Number.isFinite(top))top=v[i];
    if(Number.isFinite(v[i])&&top-v[i]>TIER_RESOLUTION){t++;top=v[i];}
    sorted[i]._tier=t;
  }
  sorted.forEach((q,i)=>{
    const e=TIERINFO[q._tier]||(TIERINFO[q._tier]={n:0,hi:null,lo:null});
    e.n++;
    if(Number.isFinite(v[i])){if(e.hi==null)e.hi=v[i];e.lo=v[i];}
  });
}
/* Eight steps and then everybody shares the last one. See --tg1..--tg8: the
   ramp is one hue so the colour reads as "further down", and it stops at eight
   because a ninth blue is not a ninth thing anybody can see. */
function tierColor(t){return "var(--tg"+Math.min(Math.max(t||1,1),8)+")";}
/* The label on a tier divider. It says the one thing the tier is FOR: how many
   men the model has decided it cannot tell apart, and the band they sit in. The
   coin-toss line only goes on the big ones -- on a two-man tier the ranking
   between them is a coin toss too, but nobody needed telling. */
/* "1 quarterbacks" and "1 QB" are both wrong in a sentence made of words. The
   plural is the only long form the payload carries, so the singular comes off
   the end of it -- quarterbacks, running backs, wide receivers and tight ends
   all lose one letter and read right. */
const posWord=n=>n===1?POSPL.replace(/s$/,""):POSPL;
function tierSep(t){
  const i=TIERINFO[t]; if(!i)return "Tier "+t;
  const band=(i.hi==null||i.lo==null) ? ""
    : " · "+(i.n===1||fmt(i.hi)===fmt(i.lo)
        ? fmt(i.hi) : fmt(i.hi)+"–"+fmt(i.lo))+" a game";
  const note=i.n>=5
    ? ` <span class="tnote">— too close to separate; the order inside is a coin toss</span>` : "";
  return `<span class="tsw" style="background:${tierColor(t)}"></span>`+
    `<span class="tn">Tier ${t}</span> · ${i.n} ${posWord(i.n)}${band}${note}`;
}

// ---- draft-overlay rendering (floor / ceiling / adp / risk) ----
const FCLS={Safe:"g",Moderate:"a",Risky:"r"};
const CCLS={High:"g",Medium:"a",Low:"r"};
const RCLS={Low:"g",Moderate:"a",High:"r"};
function bdg(t,cls){return t?`<span class="bdg ${cls||'n'}">${t}</span>`:'<span class="bdg n">–</span>';}
const PLABEL={sleeper:"Sleeper",underdog:"Underdog",espn:"ESPN",ffc:"FFC",yahoo:"Yahoo",cbs:"CBS"};
/* The sites behind the Market column, in words. The page used to write
   "Underdog + FFC" into a dozen captions and tooltips, which is true on the
   quarterback board and a lie on any board where one of the two carries no
   prices -- and there is now more than one board. */
function mktWords(){return MKT_SRC.map(p=>PLABEL[p]||p).join(" and ")||"no site";}
/* Which sites price THIS position. src/ratings.py only emits a slot for a site
   that actually carries numbers for the position, so a running-back file with
   FFC prices and nothing else draws one ADP column and not four, three of them
   full of dashes. */
let PLATS=[];
// "Market" = re-ranked average of the neutral sites' ranks — Underdog (best-ball)
// + FFC (season-long) wherever both price the position, since those are the two
// you don't draft on. Which sites end up in it is decided per position, down in
// resetBoard, because the file is not evenly filled across positions.
let MKT_SRC=[];
/* With only ONE market source the Market column is a re-rank of that one site --
   the same numbers twice, side by side, and a "vs market" row that can only ever
   say "in line". So the column is drawn when there's something to blend and the
   site column speaks for itself when there isn't. _market is still computed
   either way: value, sorting and the comp cards all price against it. */
let SHOW_MKT=false;
let NCOL=10;
let draftPlatform="consensus";
function computeMarket(){
  DATA.qbs.forEach(x=>{x._mktScore=null;x._market=null;x._mktLOO={};});
  const rankBy=(srcs,assign)=>{
    if(!srcs.length)return;
    DATA.qbs.map(x=>{
      const rs=srcs.map(p=>x.adp_platforms&&x.adp_platforms[p]).filter(v=>v!=null);
      return {x:x,s:rs.length?rs.reduce((a,b)=>a+b,0)/rs.length:null};
    }).filter(o=>o.s!=null).sort((a,b)=>a.s-b.s)
      .forEach((o,i)=>assign(o.x,i+1,o.s));
  };
  rankBy(MKT_SRC,(x,r,s)=>{x._market=r;x._mktScore=s;});   // clean market pos# 1..N
  /* A site that helps BUILD the market can't be honestly graded against it — it
     would be measured partly against itself and every gap would read smaller
     than it really is. So each site inside the blend gets its own market with
     that site left out. Sites outside the blend use the plain market. This only
     bites when a position is priced by few enough sites that a platform you
     actually draft on has to be one of them — which is exactly the case where
     the flattery would go unnoticed. */
  if(MKT_SRC.length>1)MKT_SRC.forEach(pf=>{
    rankBy(MKT_SRC.filter(p=>p!==pf),(x,r)=>{x._mktLOO[pf]=r;});
  });
}
/* The market price to judge ONE site against: leave-one-out when that site is in
   the blend, the plain market when it isn't. null means there is no market price
   for him that doesn't already contain this site — said plainly rather than
   papered over with the self-including number. */
function mktFor(x,pf){
  if(MKT_SRC.indexOf(pf)>=0)return (x._mktLOO&&x._mktLOO[pf]!=null)?x._mktLOO[pf]:null;
  return x._market!=null?x._market:null;
}
/* How one site prices a player against the Market column.
   gap = market − site.  NEGATIVE: the site lets him fall LATER than the market,
   so he's cheaper there — a value. POSITIVE: the site drafts him EARLIER, so
   you'd be paying up — a reach. Two spots is the cutoff either way. */
function mktEdge(x,pf){
  const mine=(x.adp_platforms&&x.adp_platforms[pf])??null, mkt=mktFor(x,pf);
  if(mine==null||mkt==null)return {mine,mkt,gap:null,cls:"",word:""};
  const gap=mkt-mine;
  return {mine,mkt,gap,
    cls:gap<=-2?"val":gap>=2?"rch":"",
    word:gap<=-2?`falls ${-gap} ${POS} spots later than the market here — value`
        :gap>=2?`goes ${gap} ${POS} spots earlier than the market here — reach`
        :"in line with the market"};
}
function pfRank(x,pf){
  const e=mktEdge(x,pf), sel=pf===draftPlatform?" sel":"";
  if(e.mine==null)return `<span class="pfr e${sel}">—</span>`;
  return `<span class="pfr ${e.cls}${sel}"${e.word?` title="${PLABEL[pf]||pf}: ${e.word}"`:""}>${POS}${e.mine}</span>`;
}
// Value/Reach is mode-aware: "consensus" = model vs the whole market; a platform =
// that platform's price vs the market, with that platform left out of the market.
// A player is a reach on a platform when that platform drafts him EARLIER than the
// market, a value when it lets him fall LATER — i.e. that platform is out of step.
function platEdge(x){
  if(draftPlatform==="consensus")return {tag:x.value_tag,gap:x.value_gap,mode:"c"};
  const mine=x.adp_platforms&&x.adp_platforms[draftPlatform], mkt=mktFor(x,draftPlatform);
  if(mine==null)return {tag:null,mine:null,mkt:mkt==null?null:mkt,mode:"p"};
  if(mkt==null)return {tag:null,mine,mkt:null,mode:"p"};
  const gap=mkt-mine;   // + => platform drafts him earlier than the market => reach
  return {tag:gap>=2?"Reach":gap<=-2?"Value":null, gap, mine, mkt, mode:"p"};
}
function valueTag(x){const e=platEdge(x);if(!e||!e.tag)return '';
  return e.tag==="Value"?' <span class="vt g">▲ VALUE</span>':' <span class="vt r">▼ REACH</span>';}
// detail-panel line: how the selected platform prices him vs the market it isn't in
function platEdgeLine(o){
  if(draftPlatform==="consensus")return "";
  const lab=PLABEL[draftPlatform]||draftPlatform, e=platEdge(o);
  if(e.mine==null)return `<div class="ovh">On ${lab}</div><div><span style="color:var(--muted)">not ranked on ${lab}</span></div>`;
  if(e.mkt==null)return `<div class="ovh">On ${lab}</div><div><b>${POS}${e.mine}</b> <span style="color:var(--muted)">— no market price to compare</span></div>`;
  let verdict;
  if(e.gap>=2)verdict=`<span style="color:var(--neg)">▼ ${fmt(Math.abs(e.gap),0)} spots earlier than the market — reach on ${lab}</span>`;
  else if(e.gap<=-2)verdict=`<span style="color:var(--good)">▲ ${fmt(Math.abs(e.gap),0)} spots later than the market — value on ${lab}</span>`;
  else verdict=`<span style="color:var(--muted)">in line with the market</span>`;
  const src=MKT_SRC.filter(p=>p!==draftPlatform).map(p=>PLABEL[p]||p).join(" + ")||"no other site";
  return `<div class="ovh">On ${lab}</div><div><b>${POS}${e.mine}</b> here vs market <b>${POS}${e.mkt}</b> <span style="color:var(--muted)">(${src})</span> — ${verdict}</div>`;
}
const FLAGCLS={up:"g",down:"r",warn:"a"};
/* --- Value in POINTS, not in draft slots --------------------------------
   exp_fpg is what a QB drafted at his price has historically been worth per
   game (fixed — it's a property of the price, not of our weights). The EDGE is
   projection minus that, so it has to be computed here: dragging a weight
   slider changes the projection, and a number baked in at build time would
   quietly go stale the moment you touched the board. */
let RMETA={};
let LWB={fpg:5,value_fpg:2,att_floor:55,att_high:100,rush_fpg:5};
let CURVE=null;
/* The two "big game" bars the boom rates were measured against. They are position
   thresholds, not percentiles: 25 and 30 for a quarterback, 20 and 25 for a back,
   because a 25-point game means something different at each spot. The page used to
   print "25+" and "30+" as literal text, which would have mislabelled every number
   in the RB ceiling column. */
let BOOM=[25,30];
/* The short label under a player's name. On the quarterback board that's his
   archetype ("Konami", "Pocket Passer"), which is the single most useful thing
   you can say about a QB in two words. Running backs have no archetype bucket in
   this build -- rb_blend ships an empty string on purpose -- so the equivalent
   two-word summary is how much of the backfield he owns, which is the thing that
   actually decides his week. Falls back to an em dash when neither exists. */
function styleLabel(x){
  if(x.archetype)return x.archetype;
  if(POS==="RB"&&x.bf_share!=null)return `${Math.round(x.bf_share*100)}% of backfield`;
  return "";
}
/* valOf, not projOf, and the difference matters exactly once: on a back the
   market has already marked down for an injury. His PRICE is cheap because of
   the knee, so scoring his undiscounted rate against that cheap price would
   hand him a "League winner" chip for being hurt -- on the same row where we
   just dropped him fifteen spots for it. What the pick is worth is the rate
   times the season we expect to get. Everybody healthy is unaffected. */
function edgeFpg(x){return x.exp_fpg==null?null:valOf(x)-x.exp_fpg;}
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
    :`vs the ${fmt(o.exp_fpg,1)} ${POSPL} drafted around here have actually averaged`;
  /* Print the same number the edge was computed from, or the sentence stops
     adding up. On everyone healthy that IS the projection; on a back we expect
     to miss time it's the projection after the discount, and the parenthetical
     says so rather than leaving him looking mis-rounded. */
  const v=valOf(o), p=projOf(o);
  const adj=Math.abs(v-p)>=0.05
    ?` <span style="color:var(--muted)">(${fmt(p,1)} in the games he plays)</span>`:"";
  return `${bdg(tag||"Fair price",cls)} <b>${sign}${fmt(e,1)} pts/gm</b>
    <span style="color:var(--muted)">— ${fmt(v,1)} projected ${basis}</span>${adj}${src}`;
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
let PF=[];
/* The draft-slot block, as one small table: a row per way of quoting the price,
   a column per site, and Market last and bold because it's the number the site
   columns roll up into. Cells carry the same green/red as the board. Every row
   below the first is conditional, so a thin ADP file still renders tidily. */
function adpTable(o){
  const sel=k=>k===draftPlatform?" selcol":"";
  const head=PF.map(([k,lab])=>`<th class="${sel(k).trim()}">${lab}</th>`).join("")+
    (SHOW_MKT?`<th class="mk" title="Market = ${mktWords()} blended, then re-ranked">Market</th>`:"");
  const mkCell=(inner,cls)=>SHOW_MKT?`<td class="mk ${cls||""}">${inner}</td>`:"";

  const rank=`<tr><th class="rh">Drafted at</th>`+
    PF.map(([k])=>{const e=mktEdge(o,k);
      return e.mine==null?'<td class="e">—</td>'
        :`<td><span class="pfr ${e.cls}${sel(k)?" sel":""}">${POS}${e.mine}</span></td>`;}).join("")+
    mkCell(o._market?`${POS}${o._market}`:"—",o._market?"":"e")+`</tr>`;

  const pick=PF.some(([k])=>o.adp_picks&&o.adp_picks[k]!=null)
    ?`<tr><th class="rh">Overall pick</th>`+
      PF.map(([k])=>{const p=o.adp_picks&&o.adp_picks[k];
        return p==null?'<td class="e">—</td>':`<td>${fmt(p,0)}</td>`;}).join("")+
      mkCell("—","e")+`</tr>`
    :"";

  const vsMkt=(SHOW_MKT&&o._market)
    ?`<tr><th class="rh" title="Two ${POS} spots either way is the cutoff">vs market</th>`+
      PF.map(([k])=>{const e=mktEdge(o,k);
        if(e.gap==null)return '<td class="e">—</td>';
        if(e.gap<=-2)return `<td class="gd">${-e.gap} later</td>`;
        if(e.gap>=2)return `<td class="bd">${e.gap} earlier</td>`;
        return '<td class="e">in line</td>';}).join("")+
      mkCell("—","e")+`</tr>`
    :"";

  const vb=o.value_by_platform||null;
  const vsMod=(vb&&PF.some(([k])=>vb[k]!=null))
    ?`<tr><th class="rh" title="Where my projection ranks him against that site's price. Five ${POS} spots either way is the cutoff — a model edge needs to be bigger than a site-to-site wobble to mean anything.">vs my model</th>`+
      PF.map(([k])=>{const g=vb[k];
        if(g==null)return '<td class="e">—</td>';
        if(g>=5)return `<td class="gd">${g} later</td>`;
        if(g<=-5)return `<td class="bd">${-g} earlier</td>`;
        return '<td class="e">in line</td>';}).join("")+
      mkCell("—","e")+`</tr>`
    :"";

  const cap=SHOW_MKT
    ? `Market blends ${mktWords()}, re-ranked — one reference price instead of four opinions.
       ${MKT_SRC.indexOf(draftPlatform)>=0
         ? `Your platform is part of that blend, so it's taken back out before the comparison —
            otherwise it would be graded against itself and every gap would read too small. `
         : ""}<b style="color:var(--good)">Green</b> means that site lets him fall <b>later</b> than the
       market, so he's cheaper there; <b style="color:var(--neg)">red</b> means it drafts him
       <b>earlier</b> and you'd be paying up.`
    : MKT_SRC.length
      ? `${mktWords()} is the only site in this file pricing ${POSPL}, so it <i>is</i> the market —
         there is nothing to blend it against and a second column would repeat it. Add another
         site's ${POS} ADP and the comparison columns come back on their own.`
      : `No site in this file prices ${POSPL}, so there is no draft cost to score him against.`;
  return `<table class="adpt"><thead><tr><th class="rh"></th>${head}</tr></thead>
      <tbody>${rank}${pick}${vsMkt}${vsMod}</tbody></table>
    <div class="adpcap">${cap}</div>`;
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
/* --- How much of the season do we think we get? ---------------------------
   Three separate things, and they only appear when there's something to say:
   how many of the 17 the board is paying for and why, whether he's a rookie
   with no NFL games behind the number, and where an outside guide has him.
   That last one is a sanity check, not an input -- if this board and a
   published guide disagree by thirty spots on a back, one of us is wrong and
   you should want to know before you spend a pick. */
function gamesLine(o){
  const g=o.games, out=[];
  if(g!=null&&g<16.5){
    const why=o.games_note?` <span style="color:var(--muted)">— ${o.games_note}</span>`:"";
    out.push(`<div class="ovh">Games we expect</div><div><b>${fmt(g,1)} of 17</b>${why}
      <div style="color:var(--muted);margin-top:2px">His per-game number is unchanged. He's ranked lower because a
      pick buys a season, and we don't expect to get all of this one.</div></div>`);
  }
  if(o.rookie){
    out.push(`<div class="ovh">Rookie</div><div><span style="color:var(--muted)">No NFL games behind him yet, so he's
      ranked on the size of his job plus an outside projection rather than on a box score. Treat the number as a
      placeholder with a real job attached, not as a read on the player.</span></div>`);
  }
  if(o.clay_rank!=null){
    const mine=o._rank||null;
    const d=mine?Math.abs(mine-o.clay_rank):null;
    const verdict=d==null?"":d<=8?" — in line with this board"
      :` — <span style="color:var(--neg)">${d} spots off this board</span>`;
    out.push(`<div class="ovh">Outside guide</div><div>${POS}${o.clay_rank}${verdict}</div>`);
  }
  return out.join("");
}
/* "Tier 9" on its own is a number with no claim attached. The panel is where
   somebody stops to ask what it means, so it says it: how many men are in the
   tier and how far apart the top and bottom of it are. */
function tierLine(o){
  const t=o._tier,i=TIERINFO[t];
  if(!t)return "Tier –";
  if(!i)return "Tier "+t;
  return `<span style="display:inline-block;width:14px;height:8px;border-radius:3px;`+
    `background:${tierColor(t)};margin-right:6px;vertical-align:1px"></span>Tier ${t} `+
    `<span style="color:var(--muted)">(${i.n===1?"alone in it":i.n+" "+POSPL+" the model can't separate"})</span>`;
}
function overlays(o){
  return `<div class="ov" style="margin:2px 0 16px">
    <div class="ovh">Draft slot (ADP)</div><div>${adpTable(o)}</div>
    ${gamesLine(o)}
    ${platEdgeLine(o)}
    <div class="ovh">Worth the pick?</div><div>${valuePointsLine(o)}</div>
    ${(o.lw_checks&&o.lw_checks.length)
      ? `<div class="ovh">League-winner shape</div><div>${lwChecklist(o)}</div>` : ""}
    <div class="ovh">Floor</div><div>${bdg(o.floor_bucket,FCLS[o.floor_bucket])} <span style="color:var(--muted)">bad-week baseline ≈ ${fmt(o.floor_pts,1)} pts/gm</span></div>
    <div class="ovh">Ceiling</div><div>${bdg(o.ceiling_bucket,CCLS[o.ceiling_bucket])} <span style="color:var(--muted)">${o.boom25!=null?o.boom25:"–"}% of games ${BOOM[0]}+, ${o.boom30!=null?o.boom30:"–"}% ${BOOM[1]}+</span></div>
    <div class="ovh">Risk at ADP</div><div>${bdg(o.risk_bucket,RCLS[o.risk_bucket])} <span style="color:var(--muted)">${riskWhy(o)}</span></div>
    <div class="ovh">Tier / VOR</div><div>${tierLine(o)} <span style="color:var(--muted)">·</span> ${o._vor!=null?fmt(o._vor*17,0)+" pts over replacement (season)":"–"}</div>
  </div>`;
}
const SORD={Safe:3,Moderate:2,Risky:1,High:3,Medium:2,Low:1};
const RORD={High:3,Moderate:2,Low:1};
const pfr=(x,pf)=>(x.adp_platforms&&x.adp_platforms[pf])||999;
function sortCmp(m){
  /* Every one of these ends up comparing _v, not _p -- the value the board is
     ranked on, so the order you're looking at always agrees with the rank
     numbers beside it. The Proj column still prints the RATE, which is why a
     back expected to miss time can show a bigger number than the man above
     him; his row says how many games we expect. */
  if(PLATS.includes(m))return (a,b)=>(pfr(a,m)-pfr(b,m))||(b._v-a._v);
  return ({
  proj:(a,b)=>b._v-a._v,
  adp:(a,b)=>((a.adp_pos_rank||999)-(b.adp_pos_rank||999))||(b._v-a._v),
  market:(a,b)=>((a._market||999)-(b._market||999))||(b._v-a._v),
  value:(a,b)=>{const ga=platEdge(a).gap,gb=platEdge(b).gap;return ((gb==null?-99:gb)-(ga==null?-99:ga))||(b._v-a._v);},
  floor:(a,b)=>((SORD[b.floor_bucket]||0)-(SORD[a.floor_bucket]||0))||((b.floor_pts||0)-(a.floor_pts||0)),
  ceiling:(a,b)=>((SORD[b.ceiling_bucket]||0)-(SORD[a.ceiling_bucket]||0))||(((b.boom25||0)+(b.boom30||0))-((a.boom25||0)+(a.boom30||0))),
  risk:(a,b)=>((RORD[b.risk_bucket]||0)-(RORD[a.risk_bucket]||0))||(b._v-a._v),
})[m]||((a,b)=>b._v-a._v);}
let sortMode="proj";

/* --- the league-winner filter --------------------------------------------
   Heath's two paths are a screen for LATE quarterbacks: every late-round QB to make
   the playoffs in 45%+ of ESPN leagues since 2021 fits one of them, and he states it
   for picks after Round 10. Run against Josh Allen it is trivially true and tells you
   nothing you didn't know, so "late" is the mode that actually matches the research
   and the rest are here to answer narrower questions.

   The path modes stay round-agnostic on purpose. "Which of these guys is in a
   Shanahan offense" is a different question from "who's a late flier", and folding
   the round into both would leave no way to ask the first one. */
let lwMode="all";
/* Overall pick number, on whichever platform you're drafting on -- and the average of
   the sites that price him when you're on Consensus. Overall pick rather than QB rank
   because "Round 10" is a claim about the pick, and QB18 goes in a different round
   depending on how the rest of the board falls. */
function pickOf(x){
  const ps=x.adp_picks||{};
  if(draftPlatform!=="consensus"&&ps[draftPlatform]!=null)return ps[draftPlatform];
  const v=PLATS.map(p=>ps[p]).filter(n=>n!=null);
  return v.length?v.reduce((a,b)=>a+b,0)/v.length:null;
}
const viaHas=(x,re)=>(x.lw_gate_via||[]).some(s=>re.test(s));
/* The verdict on ONE named check, whichever group it's in. viaHas above only
   ever sees the PATHS, because lw_gate_via is the list of paths a player
   cleared — which is right for "how did he qualify" and useless for the support
   rows, which never decide the gate and so never appear there. This reads the
   checklist itself and hands back true / false / null, so a support row can be
   filtered on without ever being able to promote a player through the gate.
   Null matters: an unmeasured check is neither a pass nor a fail, so === true
   and === false are both false for it and he lands below the line either way. */
const chkOf=(x,re)=>{const c=(x.lw_checks||[]).find(c=>re.test(c.label));
  return c?c.pass:null;};
/* One reader for both receiving boards. The tight-end payload writes its chips
   under te_flags rather than wr_flags so the two can never be confused upstream,
   but the KEYS INSIDE are deliberately identical — gate75, fd_badge, prime,
   crowded — so everything downstream of this line stays position-blind. Note
   that gate75 on a tight end means the 65% gate, not 75%: the name is wire
   format, the threshold lives in the model. The tight-end board never sets
   crowded (a second tight end in the room turned out not to cost the first one
   anything, r=+0.004 on route share), so no TE option reads it. */
const wrf=x=>x.wr_flags||x.te_flags||{};

/* Everything the filter needs, per position, in one table: the label on the
   control, the options it offers, the rule each option applies, the sentence
   that counts the matches, and the sentence written on the divider. Adding a
   filter to a new board is one entry here and nothing else — the control, the
   dimming, the divider and the count below are all position-blind.

   The captions are FUNCTIONS, not strings. Round 10 is TEAMS×10 picks in and
   the league size is read off the board, so a string built once at load would
   keep quoting the first board's league size after you switched boards. */
const LWDEF={
  QB:{label:"League winners",
    opts:[["all","All QBs"],
          ["late","Late-round winners (after Rd 10)"],
          ["any","Clears a path — any round"],
          ["rush","— via rushing (100+ att)"],
          ["pc","— via McShanahan play-caller"],
          ["miss","Misses both paths"]],
    /* An unpriced QB has no round, so he cannot be shown to be late. He stays on
       the board dimmed rather than passing on data we don't have — the same rule
       the gate itself uses, where unmeasured is never a pass or a fail. */
    match:{late:x=>{const p=pickOf(x);return x.lw_gate===true&&p!=null&&p>RD10;},
           any: x=>x.lw_gate===true,
           rush:x=>viaHas(x,/rush/i),
           pc:  x=>viaHas(x,/play-?caller/i),
           // Measured on BOTH paths and failing both. "Not enough data" is not a miss.
           miss:x=>x.lw_gate===false},
    note:{late:()=>`clear one of the two paths and go after pick ${RD10} — Round 10 in a ${TEAMS}-team league, which is the range Heath's finding is stated for`,
          any: ()=>"clear one of the two paths, at any draft cost",
          rush:()=>"clear the rushing path (100+ carry pace)",
          pc:  ()=>"play for a McShanahan-tree play-caller",
          miss:()=>"were measured on both paths and cleared neither"},
    sep:{late:()=>`Below the line — go inside pick ${RD10}, clear neither path, or aren't priced`,
         any: ()=>"Below the line — clear neither path, or aren't measured on both",
         rush:()=>"Below the line — not on a 100+ carry pace",
         pc:  ()=>"Below the line — not a McShanahan-tree play-caller",
         miss:()=>"Below the line — clear at least one path, or aren't measured on both"}},

  /* The running-back screen, and the one board where the PRICE lives inside the
     gate instead of beside it. The quarterback board offers "late-round winners"
     as a separate option because there the round is an extra filter on top of a
     screen that stands on its own. Here it is not an extra — it is the finding.

     Measured over 272 drafted back-seasons, 2020-2024:

       cheap alone (after pick 60)            n=148   +0.23 pts/gm   p=0.36
       played half the snaps, alone           n=125   +0.36          p=0.28
       3+ targets a game, alone               n=121   +0.23          p=0.36
       half the snaps, AMONG cheap backs      n=35    +1.39          p=0.05
       half the snaps, AMONG expensive backs  n=90    -0.21          p=0.59

     Neither half is worth anything by itself. Together and only together they
     are worth over a point a game, and on an early-round back the same facts are
     slightly NEGATIVE, because the market has already charged you for them. So
     there is no "any round" option here — it would be a screen we measured and
     found to be nothing. An early-round back reading "misses both paths" is the
     screen working: it is saying you are paying for the role, not finding it.

     BACKTESTED, and it survived two things that kill most findings.

     (1) A DIFFERENT PRICE SOURCE. Everything above is FFC prices. Rebuilt end to
     end on FantasyPros ECR -- a deeper list, ~145 backs a year against FFC's ~55
     -- the same screen on the same seasons gains +0.82 pts/gm, p=0.095, hitting
     15.9% against 12.1%. Real, and about two thirds as strong. Some of the edge
     was FFC's shallower list, not the screen. Varying the expectation curve
     (full-sample vs walk-forward) and the depth cut changed nothing at all.

     (2) A SEASON NOTHING HERE HAD SEEN. 2025, priced by a curve fitted only on
     2020-2024: gain +1.07, hit 18.8% against 10.0% (p=0.202, n=56 -- one season
     is thin). All five seasons 2021-2025 gain, +0.49/+0.58/+0.93/+0.92/+1.07.

     What it is NOT is a guarantee. Of the sixteen backs the screen picked in
     2025, three won leagues (Etienne, Javonte Williams, Dowdle) and four were
     disasters (Najee Harris 3 games, Ekeler 2, Jerome Ford, Brian Robinson). The
     screen moves the CHANCE of a hit from about one in ten to about one in five.
     It does not tell you which one.

     A note on how a short season is scored, because it decides the whole result:
     a back who plays under 8 games is scored as a full miss (-expected), not
     dropped. An earlier version of this backtest dropped them, which deletes
     every injury bust from BOTH sides of the comparison, and the effect vanished
     -- for exactly that reason, not a real one. Busting is half of what this
     screen is about, so busts have to stay in. */
  RB:{label:"League winners",
    opts:[["all","All RBs"],
          ["any","Clears a path (cheap + a real role)"],
          ["snap","— cheap and already playing"],
          ["pass","— cheap and catching passes"],
          ["full","Played a full season last year"],
          ["short","Coming off a short season"],
          ["miss","Misses both paths"]],
    match:{any:  x=>x.lw_gate===true,
           snap: x=>viaHas(x,/already playing/i),
           pass: x=>viaHas(x,/catching/i),
           /* Support row, both directions. A back with no prior season at all —
              every rookie — is null on this and matches neither, which is the
              honest answer rather than a flattering or a damning one. */
           full: x=>chkOf(x,/games last year/i)===true,
           short:x=>chkOf(x,/games last year/i)===false,
           miss: x=>x.lw_gate===false},
    note:{any:  ()=>"are priced after pick 60 AND already had a real role last season — 17.2% of them beat their price by 4+ points a game, against 10.3% of everyone else. It held on 2025, a season it was never fitted on: 18.8% against 10.0%",
          snap: ()=>"go after pick 60 and played half their team's snaps last season — 17.1% hit, against 9.7% of the other cheap backs",
          pass: ()=>"go after pick 60 and caught 3+ targets a game last season — 16.3% against 9.5%. Pass work is the part of a back's role that survives a change of starter",
          full: ()=>"played 12 or more games last season — 13.8% hit against 7.7% for everyone else, the one durability signal that held up across four of five years",
          short:()=>"played 11 games or fewer last season — they hit at 5.8% against 13.2%. It doesn't decide the screen, it colours it",
          miss: ()=>"were measured on both paths and cleared neither — which for an early-round back mostly means you're paying for the role rather than finding it"},
    sep:{any:  ()=>"Below the line — priced inside pick 60, no proven role, or no prior season to judge",
         snap: ()=>"Below the line — inside pick 60, under half the snaps, or no snap history",
         pass: ()=>"Below the line — inside pick 60, under 3 targets a game, or no target history",
         full: ()=>"Below the line — 11 games or fewer last season, or no prior season",
         short:()=>"Below the line — played 12+ games last season, or no prior season",
         miss: ()=>"Below the line — clear at least one path, or aren't measured on both"}},

  /* The receiver screens. Two of Heath's, plus the two facts about a receiver
     that the market prices and the model deliberately does not: which career
     year he is in, and whether his room is crowded. A receiver with no measured
     route share has neither screen decided, so he is never a match and never a
     miss — same treatment the quarterback gate gives an unmeasured passer. */
  WR:{label:"Screen",
    opts:[["all","All WRs"],
          ["gate","Runs 75%+ of the routes"],
          ["fd","Moves the chains (1D per route)"],
          ["both","Clears both screens"],
          ["window","In the career window (yrs 3–5)"],
          ["crowded","In a crowded receiver room"],
          ["miss","Clears neither screen"]],
    match:{gate:  x=>wrf(x).gate75===true,
           fd:    x=>wrf(x).fd_badge===true,
           both:  x=>wrf(x).gate75===true&&wrf(x).fd_badge===true,
           window:x=>wrf(x).prime===true,
           crowded:x=>wrf(x).crowded===true,
           miss:  x=>x.route_share!=null&&wrf(x).gate75===false&&wrf(x).fd_badge===false},
    note:{gate:  ()=>"run a route on 75%+ of their team's dropbacks, which was worth 9.9 points a game the following season against 4.8",
          fd:    ()=>"earn a first down on 9.5%+ of their routes — Heath's badge, re-fitted to our route estimate — worth 12.2 points a game next season against 6.3",
          both:  ()=>"clear the route gate AND the first-down badge",
          window:()=>"are in years three to five, where receiver production peaks",
          crowded:()=>"play in one of the six rooms the market treats as crowded (nothing is deducted for it — see How it works)",
          miss:  ()=>"were measured on both screens and cleared neither"},
    sep:{gate:  ()=>"Below the line — under 75% of the routes, or no measured route share",
         fd:    ()=>"Below the line — under a 0.095 first-down rate, or too few routes to judge",
         both:  ()=>"Below the line — clear at most one of the two screens",
         window:()=>"Below the line — first or second year, or year six and beyond",
         crowded:()=>"Below the line — not in one of the six rooms",
         miss:  ()=>"Below the line — clear at least one screen, or aren't measured on both"}},

  /* The tight-end screens. Same two ideas as the receivers', re-fitted, because
     the same thresholds would have caught almost nobody — three quarters of the
     routes is a bar the median tight end misses by twenty points, and a 9.5%
     first-down rate is above the ninetieth percentile here. So the gate is 65%
     and the badge is 6.5%, both picked off our own eight seasons.

     There is no crowded-room option, and its absence is a finding rather than an
     omission. A tight end's scoring barely moves with how much work the man
     behind him gets (r=+0.004 against the TE2's route share over 254 seasons),
     so there is nothing to screen for. The receivers' board keeps its version
     because the market prices crowding there; here the market doesn't either.

     The career window runs later too — years three to seven rather than three to
     five. Tight ends don't fall off until year eight.

     This board carries a SECOND family of screens, in its own group below: the
     league-winner paths, fitted the same way the running-back ones were, on 142
     drafted tight-end seasons from 2020 to 2025 against a 2-point edge bar.

       played 80%+ of the snaps      n=41   +1.27 pts/gm   p=0.004   22.0% vs 9.9%
       owns 75%+ of his TEs' work    n=43   +0.74          p=0.057   18.6% vs 11.1%
       either path                   n=59   +1.18          p=0.002   20.3% vs 8.4%
       measured, clears neither      n=76   -1.56                     6.6% vs 21.2%

     Unlike the running backs, price is NOT inside these gates — the tight-end
     effect is a main effect and it survives at every price, so folding the round
     in would only shrink the sample. Read alongside the route screens above: the
     route gate asks whether he is on the field for the passing game, and these
     ask whether the position group on his team is really just him.

     One caveat the reader is owed, and it is in How it works too: our own board
     shares the market's blind spot here. Tight ends clearing the snap path beat
     OUR projection by 1.7 points a game more than the rest, so this filter is
     currently finding players the board itself is ranking too low. */
  TE:{label:"Screen",
    opts:[["all","All TEs"],
          ["gate","Runs 65%+ of the routes","Route screens"],
          ["fd","Moves the chains (1D per route)","Route screens"],
          ["both","Clears both screens","Route screens"],
          ["window","In the career window (yrs 3–7)","Route screens"],
          ["miss","Clears neither screen","Route screens"],
          ["lw","Clears a path","League winners"],
          ["lwsnap","— plays 80%+ of the snaps","League winners"],
          ["lwown","— owns his tight end room","League winners"],
          ["lwdraft","Was a 1st- or 2nd-round NFL pick","League winners"],
          ["lwmiss","Misses both paths","League winners"]],
    match:{gate:  x=>wrf(x).gate75===true,
           fd:    x=>wrf(x).fd_badge===true,
           both:  x=>wrf(x).gate75===true&&wrf(x).fd_badge===true,
           window:x=>wrf(x).prime===true,
           miss:  x=>x.route_share!=null&&wrf(x).gate75===false&&wrf(x).fd_badge===false,
           lw:    x=>x.lw_gate===true,
           lwsnap:x=>viaHas(x,/snaps/i),
           lwown: x=>viaHas(x,/room/i),
           lwdraft:x=>chkOf(x,/NFL pick/i)===true,
           lwmiss:x=>x.lw_gate===false},
    note:{gate:  ()=>"run a route on 65%+ of their team's dropbacks, which was worth 7.0 points a game the following season against 3.5 — and 20.7% of them went on to a 10-point season against 1.3% of the rest",
          fd:    ()=>"earn a first down on 6.5%+ of their routes, over at least 200 routes — worth 8.0 points a game next season against 4.2, and 28.2% reached 10 points a game against 3.7%",
          both:  ()=>"clear the route gate AND the first-down badge",
          window:()=>"are in years three to seven, which is where tight end production holds up — the drop doesn't arrive until year eight",
          miss:  ()=>"were measured on both screens and cleared neither",
          lw:    ()=>"already played 80% of the snaps last season, or already owned their tight end room — 20.3% of them beat their draft price by 2+ points a game, against 8.4% of everyone else",
          lwsnap:()=>"played 80%+ of their team's offensive snaps last season — 22.0% hit against 9.9%, the strongest single screen on any of the four boards (p=0.004 over six seasons)",
          lwown: ()=>"took 75%+ of the expected points going to their own team's tight ends last season — 18.6% against 11.1%",
          lwdraft:()=>"were a first- or second-round NFL pick — 15.0% against 11.3%. Supporting evidence only; it never decides the screen",
          lwmiss:()=>"were measured on both paths and cleared neither — a group that missed its price by 1.6 points a game and hit 6.6% of the time against 21.2%"},
    sep:{gate:  ()=>"Below the line — under 65% of the routes, or no measured route share",
         fd:    ()=>"Below the line — under a 0.065 first-down rate, or under 200 routes to judge it on",
         both:  ()=>"Below the line — clear at most one of the two screens",
         window:()=>"Below the line — first or second year, or year eight and beyond",
         miss:  ()=>"Below the line — clear at least one screen, or aren't measured on both",
         lw:    ()=>"Below the line — under 80% of the snaps and under 75% of their room, or no prior season to measure",
         lwsnap:()=>"Below the line — under 80% of the snaps last season, or no snap history",
         lwown: ()=>"Below the line — under 75% of their tight end room, or no prior season",
         lwdraft:()=>"Below the line — drafted in round three or later, or undrafted",
         lwmiss:()=>"Below the line — clear at least one path, or aren't measured on both"}},
};
function lwDef(){return LWDEF[POS]||null;}
function lwMatch(x){const d=lwDef(); if(!d)return true;
  const f=d.match[lwMode]; return f?!!f(x):true;}
function lwNote(m){const d=lwDef(),f=d&&d.note[m]; return f?f():"";}
/* What the rows BELOW the line have in common — the negation of the mode, spelled
   out rather than left as "the others". On a board where nothing is removed, the
   line is the only thing telling you which half you're reading. */
function lwSep(m){const d=lwDef(),f=d&&d.sep[m]; return f?f():"";}
/* Built fresh on every board switch, because the options are per-position and a
   leftover "via rushing" setting on the receiver board would match nobody. */
function rebuildFilter(){
  const d=lwDef(),wrap=$("#lwwrap"),sel=$("#lwsel");
  wrap.hidden=!d;
  if(!d){sel.innerHTML="";return;}
  $("#lwlab").textContent=d.label;
  /* An option is [value, text] or [value, text, group]. Only the tight-end board
     uses the third slot, because it is the only one carrying two unrelated
     families of screen — routes and league winners — and a flat list of eleven
     would read as one muddled screen. Boards without groups render exactly as
     they always did. */
  let html="",grp=null;
  for(const o of d.opts){
    const g=o[2]||null;
    if(g!==grp){if(grp)html+="</optgroup>";grp=g;if(g)html+=`<optgroup label="${g}">`;}
    html+=`<option value="${o[0]}">${o[1]}</option>`;
  }
  if(grp)html+="</optgroup>";
  sel.innerHTML=html;
  /* A mode carried over from another board may not exist here; fall back to
     showing everyone rather than silently matching nobody. */
  if(!d.match[lwMode]&&lwMode!=="all")lwMode="all";
  sel.value=lwMode;
}

/* ==========================================================================
   THE TEAM FILTER

   Every other control on this page asks a question about a player. This one
   asks a question about an offence: there is only one ball, and a board that
   ranks men independently can hand out more of it than exists. Filtering to a
   team and reading the four positions together is the only way to see that.

   Two decisions worth stating, because both are the opposite of what the
   league-winner screen does:

     * The team choice SURVIVES a tab switch. Pick Buffalo and walk QB → RB →
       WR → TE and you are watching one offence get shared out. Resetting it
       per tab would destroy the only thing it's for.
     * It genuinely HIDES the rest of the league instead of dimming it. Dimming
       is right for a screen you might want to overrule mid-draft; it is wrong
       for "show me the Bills," where the other 400 rows are not context, they
       are the haystack.
   ------------------------------------------------------------------------ */
let teamMode="all";
const TENV=SITE.team_env||{};

/* Every team that appears anywhere on any board, not just this one. A receiver
   board with nobody from Cleveland on it should still offer Cleveland — you get
   an honest empty result and the strip telling you why, which is information,
   rather than an option that silently isn't there. */
function allTeams(){
  const s=new Set();
  for(const p of ORDER)((SITE.boards[p]||{}).qbs||[]).forEach(x=>{if(x.team)s.add(x.team);});
  return [...s].sort();
}
function rebuildTeams(){
  const sel=$("#teamsel"),ts=allTeams();
  sel.innerHTML='<option value="all">All teams</option>'+
    ts.map(t=>`<option value="${t}">${t}</option>`).join("");
  if(teamMode!=="all"&&!ts.includes(teamMode))teamMode="all";
  sel.value=teamMode;
}

/* One team's whole offence, priced off every board at once.

   The scoreboard estimate is the one number here that is not simply read off a
   board, so it is worth being explicit about. Fitted on 254 team-seasons,
   2018-2025:  points/gm = 6.76 x (offensive TDs/gm) + 6.43,  r = +0.955.

   The slope is near seven because a touchdown carries the extra point with it.
   The intercept is field goals, defensive and special-teams scores — points no
   fantasy roster contains, which is why a pile of skill players can never add
   up to a Vegas total by itself and why the intercept is not optional.

   A passing touchdown and the receiving touchdown that scores it are ONE event.
   Offensive TDs are passing plus rushing. Counting receiving as well would
   double every one of them. */
function teamOffence(team){
  const out={team:team,pos:{},td:0,n:0};
  for(const p of ORDER){
    const bd=SITE.boards[p]; if(!bd)continue;
    const men=(bd.qbs||[]).filter(x=>x.team===team);
    // Score each man on his OWN board's weights, not the tab you happen to be
    // looking at, so a Bills receiver reads the same whether you got here from
    // the WR tab or the QB one.
    const ctx=ctxFor(p);
    const rows=men.map(x=>({name:x.name,rank:x.rank,
      p:rateIn(x,ctx),g:num(x.avail_games)})).sort((a,b)=>b.p-a.p);
    out.pos[p]=rows; out.n+=rows.length;
  }
  return out;
}
function num(v){const n=Number(v);return isFinite(n)?n:0;}

/* Touchdowns per game for one team, backed out of the boards.

   The boards carry fantasy points, not scores, so the scores have to be
   recovered: pay for the catches and the yards at the league's scoring, and
   whatever fantasy points are left over are touchdowns.

     receivers, tight ends   carry a season TD figure outright — divide by 17
     backs                   catches = targets x catch rate, yards = catches x
                             yards-per-catch; what the receiving line still owes
                             after paying for those is receiving touchdowns, and
                             the same trick on carries gives rushing touchdowns
     quarterbacks            rushing only, carries x yards-per-carry

   A RECEIVING touchdown and the PASSING touchdown that threw it are one event
   and one score. Counting the quarterback's passing touchdowns on top of his
   receivers' would double every one of them, so the passing line is left out
   entirely and the receivers stand in for it. Offensive TDs = receiving +
   rushing, which is the same number as passing + rushing, counted from the end
   the boards actually measure. */
function teamTDs(team){
  const S=TENV.scoring||{}, R=TENV.rates||{}, GM=TENV.games||17;
  const sc=(k,d)=>{const v=Number(S[k]);return isFinite(v)?v:d;};
  const REC=sc("reception",0.5), RECY=sc("receiving_yards",0.1), RECTD=sc("receiving_td",6);
  const RUSHY=sc("rushing_yards",0.1), RUSHTD=sc("rushing_td",6);
  const CR=R.rb_catch_rate||0.75, YPRR=R.rb_ypc_rec||7.6;
  const RYPC=R.rb_ypc||4.35, QYPC=R.qb_ypc||5.20;
  let rec=0,rush=0;
  const of=p=>((SITE.boards[p]||{}).qbs||[]).filter(x=>x.team===team);

  ["WR","TE"].forEach(p=>of(p).forEach(x=>{rec+=num(x.td)/GM;}));
  of("RB").forEach(r=>{
    const catches=num(r.targets_pg)*CR, yds=catches*YPRR;
    const paid=catches*REC+yds*RECY;
    rec+=Math.max(0,(num(r.rec_fpg)-paid)/RECTD);
    rush+=Math.max(0,(num(r.rush_fpg)-num(r.carries_pg)*RYPC*RUSHY)/RUSHTD);
  });
  of("QB").forEach(q=>{
    rush+=Math.max(0,(num(q.rush_fpg)-num(q.rush_att_pg)*QYPC*RUSHY)/RUSHTD);
  });
  return {rec:rec,rush:rush,off:rec+rush};
}

function teamStrip(){
  const box=$("#teamstrip");
  if(teamMode==="all"){box.hidden=true;box.innerHTML="";return;}
  box.hidden=false;
  const t=teamMode, off=teamOffence(t), tds=teamTDs(t);
  const env=(TENV.implied||{})[t];
  const slope=TENV.slope||6.76, base=TENV.base||6.43;
  const ours=tds.off*slope+base;
  const vegas=env?env.implied:null;
  const gap=vegas==null?null:ours-vegas;
  const cls=gap==null?"":(gap>1.5?"over":(gap<-1.5?"under":""));

  const numBlock=(k,v,s,c)=>`<div class="tsnum"><div class="k">${k}</div>`+
    `<div class="v${c?" "+c:""}">${v}</div><div class="s">${s||"&nbsp;"}</div></div>`;

  let bar="";
  if(vegas!=null){
    const hi=Math.max(ours,vegas,1), w=x=>Math.round(100*x/(hi*1.15));
    bar=`<div class="tsbar"><i style="width:${w(ours)}%"></i>`+
        `<u style="left:${w(vegas)}%" title="Vegas ${vegas.toFixed(1)}"></u></div>`+
        `<div class="s" style="font-size:11.5px;color:var(--muted)">`+
        `bar = what our boards imply · tick = the market's number</div>`;
  }

  const grid=ORDER.map(p=>{
    const rows=off.pos[p]||[];
    const body=rows.length
      ? rows.slice(0,6).map(r=>`<div class="tsrow${p===POS?" here":""}">`+
          `<span class="n">${r.name}</span>`+
          `<span class="p"><b>${fmt(r.p)}</b> ppg · ${fmt(r.g,0)}g</span></div>`).join("")
      : `<div class="tsnone">nobody from ${t} on this board</div>`;
    const extra=rows.length>6?`<div class="tsnone">+${rows.length-6} more</div>`:"";
    return `<div class="tspos"><h4>${p}</h4>${body}${extra}</div>`;
  }).join("");

  box.innerHTML=`<div class="tshead">${teamCell(t)}<h3>${t} — the whole offence</h3></div>`+
    `<div class="tsnums">`+
      numBlock("Our boards imply",ours.toFixed(1)+" pts/gm",
        `${tds.off.toFixed(2)} offensive TDs/gm`,cls)+
      numBlock("Vegas implies",vegas==null?"—":vegas.toFixed(1)+" pts/gm",
        env?`${env.n} game${env.n===1?"":"s"} priced · ${env.lo.toFixed(1)}–${env.hi.toFixed(1)}`
           :"no line posted yet")+
      numBlock("Gap",gap==null?"—":(gap>=0?"+":"")+gap.toFixed(1),
        gap==null?"":"points per game",cls)+
      numBlock("On the boards",String(off.n),"players across all four")+
    `</div>${bar}<div class="tsgrid">${grid}</div>`+
    `<p class="tswarn">The scoreboard estimate converts touchdowns to points at
     <b>6.76 × offensive TDs/gm + 6.43</b>, fitted on 254 team-seasons from 2018–2025
     (r = +0.955). The intercept is kicking, defence and special teams — points no
     fantasy roster contains, which is why the skill players alone can never reach a
     Vegas total. Every rate here is per game that player <i>plays</i>, so adding a
     roster up quietly assumes nobody misses a week; across all 32 teams that lands
     <b>+0.5</b> pts/gm of Vegas at the median, so treat a big gap as a real
     disagreement and a small one as noise. ${env?`Vegas here is an average of the
     <b>${env.n}</b> ${t} game${env.n===1?"":"s"} that already have a posted line, out
     of 17 — a real market view of an early-season schedule, not a season
     projection.`:""}</p>`;
}

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
      cost=c.cost!=null?`${POS}${c.cost}`:"undrafted"; cls="same"; tip="no price to compare";
    }else if(c.later>=1){
      cost=`${POS}${c.cost} · ${c.later} ${sp(c.later)} later`; cls="later";
      tip=`Goes ${c.later} ${POS} ${sp(c.later)} later than ${q.name} on ${where} — you can still get him`;
    }else if(c.later<=-1){
      cost=`${POS}${c.cost} · ${-c.later} ${sp(-c.later)} earlier`; cls="earlier";
      tip=`Off the board ${-c.later} ${POS} ${sp(-c.later)} before ${q.name} on ${where}`;
    }else{
      cost=`${POS}${c.cost} · same spot`; cls="same"; tip="drafted in the same range";
    }
    return `<button class="simcard" type="button" data-goto="${c.x.rank}" title="${tip}">
      ${shot(c.x,"xs")}<span class="siminfo">
      <span class="nm">${c.x.name}<span class="tm">${c.x.team||""}</span></span>
      <span class="mt">${styleLabel(c.x)||"—"} · ${fmt(c.x._p)} pts/gm${meter}</span>
      <span class="cost ${cls}">${cost}</span></span></button>`;
  }).join("");
  /* The caption earns its keep but the rail is narrow, so it's kept to two lines:
     what the list is for, and the one thing that isn't obvious from the cards
     (whoever you can still get is listed first). */
  return `<div class="sim"><h3>Similar ${POSPL}</h3>
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
  const pts0=ptsAt(50), s=sumW(), SL=slopeAt(composite(q));
  const contribs=GROUPS.map(g=>({g,c:SL*((weights[g]||0)/s)*((q.indices[g]??50)-50),idx:q.indices[g]??50}));
  const mA=Math.max(1,...contribs.map(x=>Math.abs(x.c)));
  const rows=contribs.map(x=>{const col=x.c>=0?"var(--pos)":"var(--neg)";
    const half=Math.max(2,Math.round(46*Math.abs(x.c)/mA));
    const st=x.c>=0?`left:50%;width:${half}%;background:${col}`:`right:50%;width:${half}%;background:${col}`;
    return `<div class="lab">${x.g}</div><div class="idx">${x.idx.toFixed(0)}</div>
      <div class="wtk"><div class="wmid"></div><div class="wb" style="${st}"></div></div>
      <div class="v" style="color:${col}">${x.c>=0?"+":""}${fmt(x.c)}</div>`;}).join("");
  const feats=Object.entries(q.signals||{}).map(([k,v])=>`<tr><td class="k">${k}</td><td class="v">${fmt(v,2)}</td></tr>`).join("");
  return `<div class="dhead"><div class="who">${shot(q)}<div><h3>${q.name}${styleLabel(q)?" — "+styleLabel(q):""}</h3>
      <div style="font-size:12.5px;color:var(--muted)">index 50 = league-average ${POS} · bars are points added vs. average at the current weights</div></div></div>
    <div style="text-align:right"><div class="big">${fmt(q._p)}<span style="font-size:13px;color:var(--muted);font-weight:400"> pts/gm</span></div>
      <div style="font-size:12px;color:var(--muted)">avg ${POS} ≈ ${fmt(pts0)}</div></div></div>
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
  /* _p is the RATE (what he scores in a game he plays) and _v is the SEASON
     VALUE (that rate, times the share of the year we expect to get out of him).
     The board ranks on _v, because a draft pick buys a season, not a rate. The
     Proj column and the bar still print _p -- a back who misses a month is the
     same player in the games he does play, and hiding that would make his row
     lie about him. His row says how many games instead. */
  const rows=DATA.qbs.map(x=>{x._p=projOf(x);x._v=valOf(x);x._lw=lwMatch(x);return x;})
    .filter(x=>!q||x.name.toLowerCase().includes(q))
    .filter(x=>teamMode==="all"||x.team===teamMode);
  /* `all` stays the WHOLE board on purpose. It is what the rank column and
     replacement level are read off, so filtering to one team leaves the Bills'
     receiver showing the rank he holds in the league — WR14 — instead of being
     renumbered WR1 because he is the best Bill. A team view that renumbers
     everyone is a different board, not a filter. */
  const all=DATA.qbs.slice().sort((a,b)=>b._v-a._v);
  const replPts=all.length?all[Math.min(REPL,all.length-1)]._v:0;
  rows.sort(sortCmp(sortMode));
  // Matches float to the top. Array.sort is stable, so whichever sort you picked above
  // still holds inside each group: the filter reorders the board without overruling it.
  if(lwMode!=="all")rows.sort((a,b)=>(b._lw?1:0)-(a._lw?1:0));
  const nlw=rows.filter(x=>x._lw).length;
  $("#lwcount").innerHTML=lwMode==="all"?"":
    `<b>${nlw}</b> of ${rows.length} ${lwNote(lwMode)}. The rest stay on the board, dimmed.`;
  tiers(all);
  const maxP=Math.max(...DATA.qbs.map(x=>x._p),1);
  // Which panels are open right now. The tbody is rebuilt from scratch on every
  // slider move, so without carrying this across, a panel would slam shut the
  // instant you touched a weight — exactly when you most want to watch the bars
  // and the comps re-sort under it.
  const wasOpen=new Set([...document.querySelectorAll("tr.detail")]
    .filter(d=>d.style.display!=="none").map(d=>d.dataset.for));
  let dimSeen=false;   // the first non-match gets the labelled divider above it
  /* Tier dividers only go in when the board is IN tier order. Sort by ADP or
     float the filter matches to the top and the tiers interleave, so a divider
     would be heading a group whose members are scattered ten rows apart -- a
     label that isn't true of what's under it. The rail and the softened rank
     stay on in every view, because those are facts about the player. */
  const showTiers=sortMode==="proj"&&lwMode==="all";
  let tSeen=null;
  $("#tbody").innerHTML=rows.map((x)=>{
    const rank=all.indexOf(x)+1, vor=x._v-replPts, w=Math.max(2,Math.round(90*x._p/maxP));
    const isOpen=wasOpen.has(String(x.rank));
    const dim=lwMode!=="all"&&!x._lw, edge=dim&&!dimSeen; if(dim)dimSeen=true;
    const big=((TIERINFO[x._tier]||{}).n||1)>=5;
    const tsep=(showTiers&&x._tier!==tSeen)
      ? (tSeen=x._tier,`<tr class="tiersep"><td colspan="${NCOL}">${tierSep(x._tier)}</td></tr>`) : "";
    x._vor=vor; x._rank=rank;   // the panel compares this to the outside guide's rank
    // The divider is its own row, deliberately without class "row" — that selector is
    // what binds the click-to-open handler below, so a separator can never be clicked
    // open into a panel it has no QB for.
    return tsep+(edge?`<tr class="lwsep"><td colspan="${NCOL}">${lwSep(lwMode)}</td></tr>`:"")+
      `<tr class="row${isOpen?" open":""}${dim?" dim":""}${edge?" edge":""}" data-id="${x.rank}">
      <td class="rank num${big?" soft":""}" style="border-left-color:${tierColor(x._tier)}">${rank}</td>
      <td class="qb"><b>${x.name}</b>${teamCell(x.team)}
        <span class="archtag">${styleLabel(x)}</span>${x.mover?'<span class="move">NEW</span>':''}${valueTag(x)}</td>
      <td class="num"><span class="bartrack"><span class="bar" style="width:${w}px"></span></span>${fmt(x._p)}</td>
      ${PLATS.map(p=>`<td class="num pf">${pfRank(x,p)}</td>`).join("")}
      ${SHOW_MKT?`<td class="num mkt">${x._market?(POS+x._market):'<span style="color:var(--muted)">—</span>'}</td>`:""}
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
  teamStrip();
}

function header(){
  const pf=PLATS.map(p=>`<th class="num${p===draftPlatform?" selcol":""}" title="${PLABEL[p]||p} ADP, as a ${POS} rank — green where he falls later than the market, red where he goes earlier">${PLABEL[p]||p}</th>`).join("");
  const mkt=SHOW_MKT?`<th class="num mkt" title="Market = average of ${mktWords()} ${POS} ranks, re-ranked 1..N. The site columns are scored against this.">Market</th>`:"";
  $("#thead").innerHTML=`<tr><th class="num">#</th><th>${POSLONG}</th><th class="num">Proj</th>${pf}${mkt}`+
    `<th>Floor</th><th>Ceiling</th><th>Risk</th><th>Why</th><th></th></tr>`;
}
$("#search").oninput=refresh;
$("#sortsel").onchange=e=>{sortMode=e.target.value;refresh();};
$("#lwsel").onchange=e=>{lwMode=e.target.value;refresh();};
$("#platsel").onchange=e=>{draftPlatform=e.target.value;header();refresh();};
$("#teamsel").onchange=e=>{teamMode=e.target.value;refresh();};
$("#reset").onclick=()=>{Object.assign(weights,DATA.weights);sliders();refresh();};

/* --- switching boards -----------------------------------------------------
   Everything the page derives from a board gets rebuilt here, in one place, in
   dependency order: identity, then the scale, then the ADP columns, then the
   controls, then the table. The rule that makes this safe to extend is that
   nothing outside this function may cache a value read off DATA -- if you find
   yourself writing `const something = DATA.…` at the top level, it belongs in
   here as a `let` instead.

   The one thing deliberately NOT reset is the weights. Those live in WSTATE,
   one set per position, so tuning the RB board, checking a quarterback and
   coming back hands you your board and not the factory defaults. */
function loadBoard(pos){
  if(!SITE.boards[pos])return;
  POS=pos; DATA=SITE.boards[pos];
  POSLONG=DATA.long||POS; POSPL=DATA.plural||POSPL_MAP[POS]||(POS+"s");
  GROUPS=(DATA.groups&&DATA.groups.length)?DATA.groups:Object.keys(DATA.weights||{});
  const cal=DATA.calib||{a:0,b:0.25};
  A=cal.a??0; B=cal.b??0.25; KN=cal.knots||[];
  weights=weightsFor(pos);

  RMETA=DATA.ratings_meta||{};
  LWB=RMETA.lw_bars||{fpg:5,value_fpg:2,att_floor:55,att_high:100,rush_fpg:5};
  CURVE=RMETA.curve||null;
  BOOM=RMETA.boom||[25,30];
  REPL=replIndex(pos);
  TEAMS=RMETA.teams||12;
  RD10=TEAMS*10;

  // The ADP columns come and go with the data, so the count is worked out here
  // rather than written down: 8 fixed columns, one per site, plus Market if it's
  // being drawn. It's the colspan the detail row opens across.
  PLATS=(DATA.qbs.length&&DATA.qbs[0].adp_platforms)?Object.keys(DATA.qbs[0].adp_platforms):[];
  /* Preferred market = Underdog (best-ball) + FFC (season-long): two sites you
     don't draft on, spanning both formats. When a position isn't priced by both
     of them, fall back to blending every site that DOES price it rather than
     collapsing to a single site and losing the Market column — a two-site
     average is still a market, and the leave-one-out above keeps it honest even
     when one of those sites is the one you're drafting on. */
  MKT_SRC=["underdog","ffc"].filter(p=>PLATS.includes(p));
  if(MKT_SRC.length<2)MKT_SRC=PLATS.slice();   // same order as the columns
  SHOW_MKT=MKT_SRC.length>1;
  NCOL=8+PLATS.length+(SHOW_MKT?1:0);
  PF=PLATS.map(p=>[p,PLABEL[p]||p]);
  computeMarket();

  // Controls that describe the board reset with it: "Drafting on Sleeper" is
  // meaningless on a board Sleeper doesn't price, and the screens are different
  // questions at each position, so the filter always comes back to All.
  /* teamMode is deliberately NOT in that list. Every other control here
     describes the board and so dies with it; the team choice describes the
     OFFENCE, and carrying it across tabs is the entire feature -- pick Buffalo
     on the WR tab and walking to RB should still be Buffalo, or you are just
     re-picking the same team four times to answer one question. If the new
     board has nobody from that team, rebuildTeams() drops it back to All. */
  draftPlatform="consensus"; sortMode="proj"; lwMode="all";
  $("#search").value=""; $("#lwcount").innerHTML="";
  rebuildSelects();
  applyPosGates();

  $("#seasonPill").textContent=(DATA.meta&&DATA.meta.season_label)||"";
  const sub=[(DATA.meta&&DATA.meta.subline)||"",BUILT_LABEL].filter(Boolean).join(" · ");
  $("#subline").textContent=sub;
  if(BUILT_TITLE)$("#subline").title=BUILT_TITLE;
  $("#rnote").textContent=(DATA.meta&&DATA.meta.note)||"";
  backtestStat();

  syncPosChips();
  header(); sliders(); weightBars(); refresh();
}

/* The two dropdowns whose options are made of data. Rebuilt on every switch:
   the site list is per-position, and a leftover "Sleeper ADP" option on a board
   Sleeper doesn't price sorts every row to the same 999. */
function rebuildSelects(){
  const sel=$("#sortsel");
  [...sel.querySelectorAll("option[data-pf]")].forEach(o=>o.remove());
  const mk=[...sel.options].find(o=>o.value==="market");
  if(mk){mk.hidden=!SHOW_MKT; mk.textContent="Market ("+mktWords()+")";}
  const anchor=[...sel.options].find(o=>o.value==="floor");
  PLATS.forEach(p=>{const o=document.createElement("option");
    o.value=p; o.dataset.pf="1"; o.textContent=(PLABEL[p]||p)+" ADP";
    sel.insertBefore(o,anchor);});
  sel.value=sortMode;
  $("#platsel").innerHTML='<option value="consensus">Consensus</option>'+
    PLATS.map(p=>`<option value="${p}">${PLABEL[p]||p}</option>`).join("");
  $("#platsel").value=draftPlatform;
  rebuildFilter();
  rebuildTeams();
}
/* Blocks written for one position only -- the archetype cards, Heath's screen --
   are marked data-pos in the HTML and shown or hidden here. This is what lets a
   single "How it works" tab explain whichever board you're on. */
function applyPosGates(){
  document.querySelectorAll("[data-pos]").forEach(el=>{el.hidden=el.dataset.pos!==POS;});
}

/* --- the shared explainer's position switcher ---------------------------- */
function posChips(el,cb){
  el.innerHTML=ORDER.map(p=>`<button type="button" data-p="${p}">${p}</button>`).join("");
  el.querySelectorAll("button").forEach(b=>b.onclick=()=>cb(b.dataset.p));
}
function syncPosChips(){
  document.querySelectorAll("#ovpos button").forEach(b=>
    b.setAttribute("aria-pressed",String(b.dataset.p===POS)));
  document.querySelectorAll("#tabs .tab").forEach(b=>b.setAttribute("aria-selected",
    String(b.dataset.tab===activeTab && (!b.dataset.board || b.dataset.board===POS))));
}

/* ==========================================================================
   THE BIG BOARD — every position in one ranking.

   Ranked on value over replacement, because points per game are not comparable
   across positions: the same 17 pts/gm is a middling quarterback and a top-three
   running back, so ranking on the projection would hand you eight rounds of
   quarterbacks before the first back. Replacement is the first unstartable
   player at each position in a league this size -- QB12, RB30 -- which is
   published per board in ratings_meta.repl_rank.

   All of it is computed in the browser, on purpose. Projections move when you
   drag a weight slider, so a cross-position ranking baked in at build time would
   be wrong the moment you tuned anything.
   ====================================================================== */
let bigSort="vor", bigPos="ALL";
function bigTeams(){
  for(const p of ORDER){const t=(SITE.boards[p].ratings_meta||{}).teams; if(t)return t;}
  return 12;
}
/* Overall pick, averaged over whichever sites price him. Overall pick and not a
   positional rank because that is the only ADP unit that means the same thing at
   every position -- QB12 and RB12 are nowhere near each other on a draft board. */
function overallPick(x){
  const v=Object.values(x.adp_picks||{}).filter(n=>n!=null);
  return v.length?v.reduce((a,b)=>a+b,0)/v.length:null;
}
function bigRows(){
  const out=[];
  ORDER.forEach(pos=>{
    const ctx=ctxFor(pos), qs=(ctx.bd.qbs||[]);
    const priced=qs.map(x=>({x,p:projIn(x,ctx)})).sort((a,b)=>b.p-a.p);
    const ri=Math.min(replIndex(pos),Math.max(0,priced.length-1));
    const repl=priced.length?priced[ri].p:0;
    priced.forEach(r=>out.push({pos,x:r.x,proj:r.p,vor:r.p-repl,repl,pick:overallPick(r.x)}));
  });
  out.sort((a,b)=>b.vor-a.vor);
  out.forEach((r,i)=>{r.rank=i+1; r.edge=r.pick==null?null:r.pick-r.rank;});
  return out;
}
function bigHeader(){
  $("#bighead").innerHTML=`<tr><th class="num">#</th><th>Player</th><th class="num">Proj</th>`+
    `<th class="num" title="Points per game over the best player you could get for free at his position">Over replacement</th>`+
    `<th class="num" title="Average overall pick across the sites in this file">Market pick</th>`+
    `<th title="Where the market takes him against where this board ranks him">Vs market</th></tr>`;
}
function bigRefresh(){
  const teams=bigTeams(), q=($("#bigsearch").value||"").trim().toLowerCase();
  const all=bigRows();
  const rows=all.filter(r=>(bigPos==="ALL"||r.pos===bigPos)&&(!q||r.x.name.toLowerCase().includes(q)));
  const cmp={
    vor:(a,b)=>b.vor-a.vor,
    proj:(a,b)=>b.proj-a.proj,
    adp:(a,b)=>((a.pick==null?999:a.pick)-(b.pick==null?999:b.pick))||(b.vor-a.vor),
    // Biggest gap first: he lasts furthest past where this board wants him.
    edge:(a,b)=>((b.edge==null?-999:b.edge)-(a.edge==null?-999:a.edge))||(b.vor-a.vor),
  }[bigSort]||((a,b)=>b.vor-a.vor);
  rows.sort(cmp);

  // What replacement level actually is at each position, in points, right now.
  const repl=ORDER.map(p=>{
    const r=all.find(z=>z.pos===p);
    const rm=SITE.boards[p].ratings_meta||{};
    return r?`<b>${p}${rm.repl_rank||"–"}</b> at ${fmt(r.repl,1)}`:null;
  }).filter(Boolean);
  $("#bigrepl").innerHTML=`Replacement level right now — ${repl.join(", ")} pts/gm. `+
    `Everything above is measured against those, in a ${teams}-team half-PPR league. `+
    `Move a weight slider on any position tab and these move with it.`;

  // Round rules, but only in the board's own order. Under any other sort the rows
  // aren't in pick order, so a "ROUND 3" bar across them would be a lie.
  const rule=(bigSort==="vor"&&bigPos==="ALL"&&!q);
  let seen=0;
  $("#bigbody").innerHTML=rows.map(r=>{
    const rd=Math.ceil(r.rank/teams);
    const bar=(rule&&rd>seen)?(seen=rd,`<tr class="rdsep"><td colspan="6">Round ${rd}</td></tr>`):"";
    const ecls=r.edge==null?"":r.edge>=teams?"val":r.edge<=-teams?"rch":"";
    const eword=r.edge==null?'<span class="mut">—</span>'
      :r.edge>=teams?`<span class="vt g">▲ lasts ${Math.round(r.edge)} picks longer</span>`
      :r.edge<=-teams?`<span class="vt r">▼ goes ${Math.round(-r.edge)} picks earlier</span>`
      :`<span class="mut">about where he's drafted</span>`;
    // data-bpos, NOT data-pos: data-pos is the show/hide gate for position-specific
    // explainer blocks, and applyPosGates() would hide every row on this board that
    // isn't the position you last had open.
    return bar+`<tr class="row" data-bpos="${r.pos}" data-id="${r.x.rank}">
      <td class="rank num">${r.rank}</td>
      <td class="qb"><span class="pc ${r.pos}">${r.pos}</span> <b>${r.x.name}</b>${teamCell(r.x.team)}</td>
      <td class="num">${fmt(r.proj,1)}</td>
      <td class="num vor${r.vor<0?" neg":""}">${r.vor>0?"+":""}${fmt(r.vor,1)}</td>
      <td class="num">${r.pick==null?'<span class="mut">—</span>':Math.round(r.pick)}</td>
      <td class="rd ${ecls}">${eword}</td></tr>`;
  }).join("")||`<tr><td colspan="6" class="note">Nobody matches that search.</td></tr>`;

  $("#bigbody").querySelectorAll("tr.row").forEach(tr=>tr.onclick=()=>
    jumpTo(tr.dataset.bpos,tr.dataset.id));
  $("#bignote").textContent=`${rows.length} players across ${ORDER.join(", ")}. `+
    `Projections are per game. Market pick is the average overall pick across the sites in this file, `+
    `so a player nobody prices shows a dash rather than a guess.`;
}
/* Row click on the big board: open him where the full breakdown lives. */
function jumpTo(pos,id){
  if(pos!==POS)loadBoard(pos);
  showTab("rankings");
  const tr=document.querySelector(`#tbody tr.row[data-id="${id}"]`);
  if(!tr)return;
  const d=document.querySelector(`tr.detail[data-for="${id}"]`);
  if(d&&d.style.display==="none")openPanel(tr,d);
  tr.scrollIntoView({block:"center",behavior:"smooth"});
}
$("#bigsort").onchange=e=>{bigSort=e.target.value;bigRefresh();};
$("#bigsearch").oninput=bigRefresh;

/* --- boot ---------------------------------------------------------------- */
posChips($("#ovpos"),p=>{loadBoard(p);});
posChips($("#bigpos"),p=>{bigPos=(bigPos===p?"ALL":p);
  document.querySelectorAll("#bigpos button").forEach(b=>
    b.setAttribute("aria-pressed",String(b.dataset.p===bigPos)));
  bigRefresh();});
// "All" reads better as the un-pressed state of every chip than as a sixth chip.
$("#bigpos").insertAdjacentHTML("afterbegin",'<span class="note" style="margin:0;padding:0 6px">Only&nbsp;</span>');
bigHeader();
buildTabs();
loadBoard(POS);
showTab("rankings");
</script>
</body>
</html>
"""
