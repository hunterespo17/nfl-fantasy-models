# The play-caller file: how to build it and keep it, with the least possible work

**Status: step 1 is already done.** `data/playcallers.csv` is in the repo, filled in for
2026, all 32 teams, cross-checked against two independent sources. You don't have to type
it. What follows is why it looks the way it does, the ~15 lines of code that turn it on,
and the calendar that keeps it alive for about 25 minutes a year.

---

## Why this file has to be hand-maintained at all

Everything else the model eats comes from nflverse, which means it refreshes itself. Who
calls the plays does not exist as a clean field in any free feed — nflverse gives you the
head coach, and the head coach is the play-caller only about half the time. In 2026 fifteen
of the thirty-two offenses are run by a coordinator, not the head coach, so "use the head
coach" would be wrong for nearly half the league. That's the whole reason for a CSV: it is
the smallest possible hand-maintained bridge over a gap the automated pipeline can't cross.

The good news is that this is the *same* problem `data/win_totals.csv` already solved, so
the file, the loader, and the git treatment are all deliberate copies of that pattern. If
you already understand win totals, you already understand this.

## What's in the file

```
season,team,playcaller,role,tree
2026,ARI,Mike LaFleur,OC,mcshanahan
2026,ATL,Tommy Rees,OC,other
...
```

Five columns, 32 rows per season, and only one of them the model actually reads.

`season` and `team` are the join key, and the team codes are not a new vocabulary — they
are literally whatever `win_totals.csv` already uses (`LA` for the Rams, `LV`, `JAX`,
`WAS`), because both files get joined to the same `team` column inside
`entering_profiles()`. A code that works in one has to work in the other.

`tree` is the only column the model consumes. It takes exactly two values, `mcshanahan` or
`other`. It is binary on purpose: the research finding is binary. Over the past two
seasons, **22.2%** of drafted McShanahan-tree QBs beat their ADP expectation by 5+ FPG,
against **6.5%** of everyone else. Nothing in that finding asks you to rank Shanahan above
McVay, or to grade a third tree, and inventing gradations you can't validate is how a
maintenance chore turns into a research project.

`playcaller` and `role` are there for you, not for the model. The name is what makes the
file auditable a year later when you can't remember why Miami was tagged McShanahan, and it
is what lets the checker below compute year-over-year churn for free. `role` (`HC` or `OC`)
costs nothing to record because you can't look up the play-caller without learning it, and
it earns its place because HC play-callers are far more durable than OC play-callers — an
OC gets fired in October, a head coach almost never does.

Notably **there is no `since` or `is_new` column.** Once the file has two seasons in it,
"this team changed play-callers" is derivable by comparing them, and a column you can
compute is a column you can get wrong.

### The 2026 seed, and how I know it's right

Two sources that don't share a byline agree on all 32 teams: Acme Packing Company's
play-callers-are-set piece and Fantasy Index's play-caller rankings. Where they overlap
they don't disagree once, which is a much stronger signal than either alone.

The `tree` column then comes from the article's own explicit 2026 McShanahan QB list —
Purdy, Stafford, Love, Murray, Willis, Stroud, Lawrence, Burrow, Brissett, Herbert,
Mendoza, Darnold, Mayfield, Hurts — mapped back to the teams those quarterbacks play for.
That gives twelve teams directly; Minnesota (Kevin O'Connell, McVay's Rams OC) and Miami
(Bobby Slowik, Shanahan's 49ers passing-game coordinator) are the two the QB list doesn't
reach but the lineage obviously does.

Here is the check that matters: that derivation lands on **14 of 32 teams, 43.8%**, and the
article independently states that McShanahan play-callers control **44%** of league
offenses. Those two numbers were arrived at separately and agree. The checker prints this
every time you run it, so if a future edit drifts the count wildly you'll see it.

## Turning it on — two edits, about fifteen lines

**1. The loader.** Add this to `src/qb_blend.py`, directly under `win_totals()`. It is that
function with the names changed, right down to the bare `except`, which is deliberate: a
hand-typed file must never be able to take the site down.

```python
_PC_CACHE = None


def playcallers() -> dict:
    """{(season, team): {"playcaller": str, "role": str, "tree": str}} from
    data/playcallers.csv (empty if missing).

    Hand-maintained -- see PLAYCALLER_PLAN.md. Same swallow-everything contract as
    win_totals(): a broken file degrades the play-caller check to "not tracked yet"
    rather than breaking the build. Run scripts/09_check_playcallers.py after edits,
    because that contract also means typos fail silently.
    """
    global _PC_CACHE
    if _PC_CACHE is None:
        from . import config
        try:
            pc = pd.read_csv(config.DATA_DIR / "playcallers.csv")
            _PC_CACHE = {
                (int(r.season), str(r.team)): {
                    "playcaller": str(r.playcaller), "role": str(r.role), "tree": str(r.tree)
                }
                for r in pc.itertuples()
            }
        except Exception:
            _PC_CACHE = {}
    return _PC_CACHE
```

**2. The fourth checklist box.** In `src/ratings.py`, inside the league-winner checklist
loop (around line 358), the fourth entry is currently a placeholder reserving the slot.

First add the import next to the existing `from . import adp as adp_mod`:

```python
from . import qb_blend
```

That direction is safe — `qb_blend` imports `archetype`, `rankings` and `scoring`, none of
which import `ratings`, so there's no cycle. I've confirmed the two modules import together
cleanly.

Then, just above the `for q in payload:` that builds the checks:

```python
    season = int(getattr(cfg, "UPCOMING_SEASON", latest + 1))
    pcs = qb_blend.playcallers()
```

`cfg` is already a parameter of `attach()` and already carries `UPCOMING_SEASON = 2026`,
`latest` is already computed a few lines up, and every `q` already carries `team` — so
nothing new has to be plumbed through.

```python
        }, {
            "label": "McShanahan play-caller",
            "pass": (pc["tree"] == "mcshanahan") if pc else None,
            "detail": (f'{pc["playcaller"]} ({pc["role"]})' if pc else "not tracked"),
            "why": "Drafted QBs in this tree beat ADP by 5+ pts/gm 22.2% of the time vs 6.5% elsewhere.",
        }]
```

with `pc = pcs.get((season, q.get("team")))` fetched alongside `pace` and `rfpg` at the top
of the loop. `lw_score` and `lw_max` already count themselves correctly — `lw_max` only
counts boxes whose `pass` is not `None`, so a missing file cleanly drops the checklist back
to three boxes instead of scoring everyone 0-for-4.

I applied both of these edits to a scratch copy and ran the full harness: the loader
resolves correctly (`(2026, 'SF') -> Kyle Shanahan / HC / mcshanahan`, `(2026, 'LA') ->
Sean McVay`, an unknown code returns `None`), and every check stayed green except one —
`test_tier1.py` line 204 asserts `c[3]["pass"] is None`, the assertion that pins the slot as
deliberately-not-yet-measured. When you wire this up for real, that assertion is the thing
you update, and it should become a check that the box resolves for a known team. Then I
reverted the scratch edits, so what's in the repo is still the untouched version at 47/47.

**One thing to decide when you wire it up, because it changes how the box reads.** The
research states two *alternative* paths to a league-winning late-round QB — 100+ rush
attempts **or** a McShanahan play-caller — and says every late-round QB at a 45%+ playoff
rate since 2021 satisfies one of them. Your checklist currently presents its boxes as
additive, so a pocket passer in a McShanahan offense will score 1-of-4 and look weak when
the research would call him a live shot. My suggestion is to leave the arithmetic alone but
have the report treat "clears box 2 **or** box 4" as its own highlighted line, since that
disjunction is the actual published claim. Worth its own conversation before you build it.

## The maintenance calendar

**One pass in late February, about 20 minutes.** This is the only appointment that matters.
The hiring cycle is finished by then and the whole league's list gets published in one
place. Duplicate the previous season's 32 rows, bump the year, and correct the names that
changed. Don't underestimate this step out of optimism — 2026 was a heavy carousel, with
seventeen of thirty-two teams changing the person calling plays, five of them because the
head coach changed. Then set `tree` for anyone new by asking one question: did this person
coach under Kyle Shanahan, Sean McVay, or somebody who did? Then run
`python scripts/09_check_playcallers.py`.

**One five-minute check when camp opens in late July.** Occasionally a team announces in
June that the head coach is taking over play-calling duties, and that's a `role` and
sometimes a `tree` change. Re-run the checker and you're done.

**In season: do nothing.** This is the part that saves you the most time and it's the part
that feels wrong. When a coordinator gets fired in week 10, resist touching the file. The
board is a *draft* tool — it exists to price players in August, and a November firing
cannot retroactively change what you should have paid. Chasing in-season changes is pure
effort with zero effect on any decision you actually make.

**Back-filling old seasons is optional and I'd skip it.** The model only ever reads the
upcoming season. The one genuine reason to back-fill would be to verify the 22.2%-vs-6.5%
claim against your own data instead of taking it on faith — and if you want that, do 2024
and 2025 only, because those are the exact two seasons the published figure covers. That's
64 rows and an hour, and it's a research errand, not maintenance.

## The trap to watch for

The loader swallows every error and returns `{}`. That is correct for a live site and it is
also the one genuinely dangerous property of this design: fat-finger `TB` as `TP` and
nothing crashes, nothing warns, the box just quietly reads "not tracked" for Tampa Bay all
season. This is precisely the failure you'd discover in November.

So `scripts/09_check_playcallers.py` isn't optional polish — it's the thing that makes a
hand-typed file safe. It validates the team codes against `win_totals.csv`, catches
duplicates and blanks, rejects any `tree` value outside the two allowed ones, and prints
both the McShanahan share and the year-over-year churn so a bad edit is visible at a glance.
It exits non-zero, so when you're ready it drops straight into your GitHub Action as a
pre-build gate. Run it after every edit; it takes a second.

## Files

| File | What it is |
|---|---|
| `data/playcallers.csv` | The data. 32 rows for 2026, already filled in. |
| `scripts/09_check_playcallers.py` | The validator. Run after every edit. |
| `.gitignore` | Updated with `!data/playcallers.csv` so it commits like the other hand-maintained inputs. |
| `src/qb_blend.py` | Where the `playcallers()` loader goes — not yet added. |
| `src/ratings.py` | Where the fourth checklist box gets wired — not yet added, slot reserved at line ~358. |

Sources for the 2026 seed: [Acme Packing Company](https://www.acmepackingcompany.com/green-bay-packers-coaching-staff/79405/the-nfls-play-callers-are-set-for-2026-only-4-new-names-get-a-chance) and [Fantasy Index](https://fantasyindex.com/2026/02/20/around-the-nfl/ranking-the-offensive-play-callers); the tree assignments and the 22.2%/6.5%/44% figures come from Fantasy Points' *2026 Anatomy of a League Winner*. For future Februaries, ESPN publishes the same all-32 list annually.
