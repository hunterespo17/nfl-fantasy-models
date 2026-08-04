# What's left on the RB model

Measured against the four tiers in `RB_MODEL_PLAN.md`. Short version: tier 1 is
done and then some, tier 2 is the next real chunk of work, tier 3 needs about an
hour of your time typing a file, and tier 4 can't start until tier 2 exists.

---

## Done

**All of tier 1**, plus several things that were supposed to come later.

There is a running-back board you can open, sort, filter and click into. Nine
factors feed it — talent, volume, receiving, backfield share, Vegas, availability,
efficiency, situation, matchup — with touchdowns regressed so one lucky red-zone
season doesn't set a player's price for the next one. Scoring is half PPR.
Replacement level is RB30. A target counts as 1.8 carries.

The FFC prices you pasted are in, all 329 rows across six seasons, and the
"expectation curve" is fitted to five of them. That's what lets the board say
whether a back is worth his cost rather than just how many points he'll score.
Floor, ceiling, risk, boom-game odds and the value tags all work on backs with
their own bars, not the quarterback ones.

**Since the plan was written**, four more things landed. The site is now one page
with a tab per position instead of two separate pages. There's a Big Board that
ranks quarterbacks and running backs against each other. The ADP columns on the RB
board were showing up empty and now don't. And the whole thing is set up so
receivers and tight ends slot in as new tabs without touching anything that exists.

---

## Tier 2 — the Heath layer

This is the big one, and it's the one that turns a points projection into a draft
tool. Four pieces, and three of them are waiting on the same missing ingredient.

**The missing ingredient is expected fantasy points share.** Heath's running-back
work is built on it: not what a back scored, but what his *usage* was worth
regardless of whether the touchdowns fell his way. It's computable from the
play-by-play we already download — carries inside the ten, target depth, share of
the team's red-zone work — but it's a new layer of code, not a setting to flip.
Call it the biggest single piece of work left.

**The three archetype buckets** come straight off that number, the same way the
quarterback archetypes work. A label on each back saying what kind of back he is.

**The early-round disqualifier** is Heath's screen for backs going in the first six
rounds — the profile that keeps failing at that price. It needs the usage-share
number *and* contract year. Styled as a warning, not a badge, and only applied
early, because it says nothing useful about a round-nine pick.

**Contract year** is the other gap. We have age, games played and durability. We
don't have who's in a contract year, and no free source hands it over cleanly. The
realistic answer is a small file you fill in — probably 30-40 rows covering the
backs that actually get drafted — the same shape as `data\playcallers.csv`.

**Then the filter**, matching the league-winner dropdown on the quarterback board,
with the same rule that non-matches grey out and drop below the line rather than
disappearing. That one's quick once the three above exist. Right now the RB board
shows no gate at all, on purpose — grading backs against quarterback bars would be
worse than showing nothing.

One tier-2 item is already finished ahead of schedule: the running-back version of
the points-space value number, with its own curve and thresholds. That shipped with
the ADP work.

---

## Tier 3 — backfield competition

The genuinely new factor, and the one that can't be automated.

The board already knows each back's share of his own team's carries and targets.
What it doesn't know is whether that's a settled job or a fight — whether the guy
behind him is a camp body or a second-round rookie. Depth charts won't tell you;
that's a judgement call about 32 situations.

So: a file called `data\backfields.csv`, one row per team, that you fill in once
and touch when news breaks. Same discipline as the play-caller file — a checking
script (`scripts\14_check_backfields.py`) you run after every edit so a typo can't
reach the board, and an entry in the preflight check.

Per Heath's late-round finding, the factor has to cut both ways: a crowded
backfield is a penalty on an expensive back and a *reason to be interested* in a
cheap one. Same fact, opposite meaning depending on price.

Your part is about an hour of typing. My part is the loader, the factor and the
checking script.

---

## Tier 4 — testing it honestly

`scripts\13_backtest_rb.py`, and it can't start until tier 2 exists, because there's
no screen to test yet.

The thing to keep in mind: the error number the build already prints is the wrong
test for this work. It measures the middle of the board. Everything in tiers 2 and
3 is about the four or five backs a year who win leagues. A change that nails every
one of them and is slightly worse on the other sixty will make that error number go
*up* and will have made the model better at its job.

So the real test is different: run the screen against 2022 through 2025 and ask
whether it flagged the backs who actually beat their price by a wide margin — and
how many it flagged who didn't. A screen that lights up half the board isn't a
screen.

---

## Two open questions that aren't tiers

**The bottom of the board reads too rich.** The cheapest backs on the board are
projected about four points a game higher than they should be. The cause is that
the scale was taught using drafted players only, so the cheapest *drafted* back
becomes a floor that gets handed to all 36 backs nobody drafts. Patrick Ricard
reads 6.6 points a game; he's really worth about 1.2.

This does not affect your draft. Replacement level is RB30 at about 8.4 points, and
every affected player sits below that, so none of them are ever the pick. But the
season-total column is meaningless for half the board, and that will bother you if
you look at it.

Two ways to fix it, and I'd like your call: extend the scale below the last drafted
pick so it keeps falling, or stop printing a season total for anyone with no draft
price at all. The first is more honest, the second is more obvious.

**2025 prices are missing.** The FFC paste has 2026, 2024, 2023, 2022, 2021 and
2020 — 2025 just isn't in it. Five seasons is a real fit so it isn't a blocker, but
2025 is the most recent finished season and therefore the most relevant one. The
quarterback history has the same hole. Same trip if you're already there.

---

## Small things still on your list

Run `py scripts\08_factor_stability.py` and send back
`outputs\factor_stability.csv` — it's a diagnostic, not a blocker.

Delete the stray file `scripts\10_preflight.py.txt`.

Move `deploy.yml` from the top of your project folder into `.github\workflows\` and
choose Replace, then commit and push in GitHub Desktop.
