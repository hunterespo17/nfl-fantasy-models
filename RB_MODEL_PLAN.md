# Building the RB model

A plan to talk through before we write any code.

> **Status, updated Aug 4.** Tier 1 is built and working — there's an RB board on
> screen. Your league is set to **half PPR**, `data\win_totals.csv` has its 2025
> rows, and **the FFC running-back ADP is now in**: 53 backs priced for 2026 and
> 276 historical picks across 2020-2024. That was the last thing blocking the
> tier-4 backtest. See "Where this stands" at the bottom.

---

## The short version

About two thirds of what you asked for is already sitting in the project. The QB
model taught the pipeline how to pull weekly stats, team situation, Vegas numbers,
ADP and photos, and how to turn all of it into 0-100 factor scores you can retune
with sliders. Running backs reuse all of that. The genuinely new work is smaller
than it looks: backfield competition, the pass-catching archetype, and a screen
that answers "is this the kind of back who wins leagues" rather than "how many
points will he score."

There is one trap, and it's worth reading before anything else, because it's
hiding inside a factor you specifically asked for. **Target share, used the
obvious way, will make the model worse at the exact job you want it for.** More
on that below — it's the longest section here for a reason.

The other thing worth saying up front: the running back model is the one that
matters most. Heath's own numbers put the gap between a top running back and a
replacement-level starter at **+8.9 points a game**, versus +7.0 at receiver,
+5.0 at tight end and **+4.1 at quarterback**. Getting this position right is
worth more than everything we did on the QB side.

---

## Your factor list, checked one at a time

| What you asked for | Can we get it? | Verdict |
|---|---|---|
| YPC | Yes, but | Keep the idea, change the measure — see below |
| Target share | Yes | **Needs rethinking.** Read the next section |
| Yards | Yes, free | Use it, but split rushing and receiving |
| TDs | Yes, free | Use it *regressed*, same as we did for QBs |
| Backfield share | Yes | Central to the model. Use snap share, not carry share |
| Backfield competition | Partly | The hardest one. Needs a small file you maintain by hand |
| Vegas implied team total | Yes, already built | Free — it's already in the pipeline |
| Defensive ranks / game script | Yes | Right instinct, but it overlaps with the two Vegas factors |
| Vegas implied win total | Yes, already built | Free — `data\win_totals.csv` already exists |

Six of the nine are essentially free. Three need real thought.

---

### The one that needs rethinking: target share

Your instinct is that catching passes is good for a running back, and for
*scoring points* that is completely right — Heath measures a target as worth
**2.55x** the fantasy points of a carry in full PPR. In your half-PPR league a
catch is worth half a point instead of a whole one, so that multiplier comes down
to about **1.8x**. Still a lot — a target is still worth nearly two carries — but
not 2.55. The model uses 1.8 (`TARGET_MULT` in `src\rb_blend.py`). If we only
cared about projecting points, "more targets is better" would be a fine factor
and we'd move on.

But that isn't the question the model is actually being asked. The board's job is
to tell you who beats their draft price. And on that question the relationship is
not a straight line — it's a **U**.

Heath sorts backs by what share of their expected fantasy points comes from
receiving, and finds three groups:

- **Non-pass-catchers** (under 30% from receiving) — beat expectation
- **Average bellcows** (30-40%) — **the worst group in the sample**
- **Elite pass-catchers** (over 40%) — beat expectation

Both ends win. The middle loses. A model with a plain "target share is good"
factor gets this backwards twice over: it penalises the Derrick Henry / Jonathan
Taylor archetype, which is a real and repeatable way to win a league, and it
rewards the 30-40% group, which is precisely the dead zone Heath is warning
about. That group is where most of this year's fourth-through-sixth-round backs
live — Barkley, Jacobs, Hall, Etienne, Javonte Williams, Bucky Irving, Skattebo,
Henderson, Swift.

So target share belongs in the model **twice, doing two different jobs**:

1. **In the points projection**, as receiving volume, straight and linear. A back
   who catches 70 balls will score more than one who catches 20. That's just
   true, and the 1.8x figure tells us how much to weight it in half PPR.
2. **In the value screen**, as a three-way *label* — non-pass-catcher, bellcow,
   elite pass-catcher — that isn't averaged into anything. It's a tag on the
   player, the same way the QB archetypes are.

Keeping these separate is the whole point. Blending them produces a number that's
wrong at both ends of the curve and confidently average in the middle.

Two supporting numbers that show how badly a smooth target-share factor would
fit: the top-6 scoring backs average 68.4 targets, the top-20 league winners
average 79.1 — but **55% of the top 20 by win rate fall outside the 60-100 target
range entirely.** The winners are at the edges, not the average.

One caveat that matters: Heath measured all of this in **full PPR**, and your
league is **half PPR** (`"reception": 0.5` in `src\config.py`). That doesn't
throw the section out, but it does bend it, and here's exactly how:

- **The U is still a U, but it tilts.** Halving the value of a catch takes some
  of the edge off the elite-pass-catcher end without touching the pure runners at
  all. So the left side of the curve comes up relative to the right. The middle
  is still the worst place to be. A three-way label is still the right shape.
- **Keep the 30% / 40% cutoffs where they are.** They're stated in PPR terms, and
  that's deliberate — those buckets describe a back's *role*, not his scoring.
  Whether a guy is a two-down runner or a passing-down weapon is a fact about
  how his team uses him, and it doesn't change because your league scores catches
  differently.
- **The +5.0 / +2.0 bars do move.** Half-PPR running back scoring runs about
  88-90% of full PPR, so those become roughly **+4.4** and **+1.8**. The board
  currently prints the full-PPR numbers with a note saying they're a shade
  generous in half PPR. Tier 4 derives the exact ratio from your own data and
  replaces them.

---

### The three Vegas-ish factors are really one factor

You named implied team total, implied win total, and defensive ranks. Your
parenthetical — *"will they be leading / need to run the clock out"* — shows you
already know why all three matter, and you're right. Heath backs it hard:
**every back who beat his ADP expectation by 5+ points a game was on a team that
won at least 8 games.** Jonathan Taylor averages 13.8 points a game in losses over
five seasons. Game script is not a small effect at this position.

But those three inputs are all measuring the same underlying thing — *is this
team going to be ahead a lot* — and if we make each one its own weighted factor,
the model quietly becomes a team-quality ranking with a running back's name
attached. Good backs on bad teams disappear, which is the opposite of an edge.

So: one factor group, three inputs. And a note on "defensive rank" specifically —
for a season-long draft model, the defense that matters is **your own**, not the
opponent's. Your defense being good is what creates the leads that create the
carries. And the forward-looking version of "will my defense be good" is already
priced into the Vegas win total. Opponent defensive rank is a *weekly* input;
we'd add it later if we ever do in-season lineup calls.

There's a second, more interesting move available here. Heath's game-script
finding isn't uniform — it's much stronger for non-pass-catchers than for
receiving backs, because a back who catches passes still eats when his team is
behind. So game script shouldn't be a flat factor at all. It should apply
**harder to the non-pass-catchers and barely at all to the elite pass-catchers.**
That's slightly more code, and it's the difference between a factor that's
directionally right and one that's actually correct.

This is also exactly Heath's checklist for when to trust a non-pass-catcher. He
wants at least **two of three**: drafted outside the top 18 picks; on a team good
enough for frequent positive game script (8+ wins minimum); and the market is
wrong about how many passes he'll catch (most often true of younger backs). The
first two we can compute today. The third needs the archetype label from the
previous section.

---

### YPC and TDs measure the outcome, not the cause

Yards per carry is the weakest thing on your list, and it's weak for a specific
reason: it mostly measures the offensive line and a couple of long runs, and it
does not repeat year to year. A back with a great YPC last season is not reliably
a great YPC back this season.

The stable version of the same idea is **explosive run rate** — the share of
carries that go for 10+ (or 15+) yards. That's the measure Heath uses when he
wants to say a back is actually good rather than well-blocked: D'Andre Swift at
15.1% last year, fifth in the league; J.K. Dobbins at 14.9% over two seasons. So
we keep your instinct and swap the measure.

Touchdowns have the same problem, worse. Goal-line work is a coaching decision
that flips from year to year, and raw TD totals are the noisiest number on a
running back's stat line. We already solved this on the QB side — `src\qb_blend.py`
regresses touchdowns toward what a player's yardage predicts, with a constant
called `K_TD`. We do the same here, plus we add the thing that actually causes
running back touchdowns: **share of the team's carries inside the 5-yard line**,
weighted by the team's implied point total. That's the cause. The TD count is the
symptom.

---

## What Heath adds that isn't on your list

### The early-round disqualifier

This is the RB equivalent of the two-path QB gate we built, but it's structured
the opposite way, and that difference matters for how we show it.

Verbatim from the article: *"every RB to ever become a league-winner with an ADP
inside the first six rounds was either 1) in one of their first four seasons in
the NFL, or 2) had already reached league-winning status in a previous season."*

The QB gate is a **qualifier** applied to **cheap** quarterbacks — clear one of
two paths and you're interesting. This is a **disqualifier** applied to
**expensive** running backs — fail both conditions and history says you have
never once returned a league-winning season at that price. Same research shape,
mirrored.

Four backs in this year's top six rounds fail it: **Kenneth Walker, Breece Hall,
Javonte Williams, David Montgomery.** That's a genuinely useful thing for the
board to say out loud, and it's a red flag rather than a green badge, so it needs
different styling from the QB gate.

Scope matters as much as it did on the QB side. This claim is about picks
*inside* the first six rounds. Applying it to a 12th-round flier would be
inventing a rule the research doesn't contain, exactly the way running the QB
two-path screen against Josh Allen tells you nothing.

### Age and contract year

Both are strong and both are cheap to compute — we already pull birth dates via
`get_players()` for the QB availability factor.

The league-winning back averages **25.1 years old**. **85% were 27 or younger** on
December 31 of their league-winning season. Past 29 the dropoff risk escalates
sharply. McCaffrey, Barkley, Henry and Jacobs are all 28+ by the end of 2026.

Contract year is the same signal from a different angle: **64% of league-winning
running back seasons came from players on rookie contracts** — 9% rookies, 19%
second year, 21% third, 15% fourth. The workload follows the cheap contract.

Age we get free from the player table. Contract year we can approximate from
draft year, which is also in there.

### The RB dead zone is back

Rounds four through six produced 0.6 league-winning backs a season from 2017-2021,
then 1.8 a season from 2022-2025 as the position got cheap. Heath's read is that
2026 undoes that — running backs are being drafted early again. His count of
backs inside the first 40 ESPN picks: 19 in 2017, then 17, 19, 17, 19, 18, 15, 16,
16 — and **19 again as of July 10, 2026.** Back to where it started.

That's a claim about *this* draft specifically, so it belongs on the board as
context on the middle rounds, not as a permanent factor.

Related and worth building toward: **21.7% of running backs drafted in rounds 1-4
became league winners**, and the window at this position stays open through about
round 6 — versus round 9 at receiver. Zero-RB is a much narrower path than it's
sold as: only 11 undrafted-free-agent league-winning backs across nine seasons,
and only **2 since 2022**.

### Late round: ambiguous backfields, not handcuffs

Heath's late-round advice is specific and a little counterintuitive. Don't draft
pure handcuffs (his examples: Tank Bigsby, Pacheco). Draft **ambiguous
backfields** — situations where nobody knows the split yet, because Week 1 snap
share will tell you the answer while the price is still low. Kenneth Gainwell took
51.9% of snaps in Week 1 of 2025 and averaged 17.8 points a game over the final
eight weeks.

This has a direct implication for the model: **a wide-open backfield should score
as opportunity, not as risk.** The naive version of a "backfield competition"
factor punishes uncertainty. Heath's finding is that late in the draft,
uncertainty is the whole edge. So competition needs to cut two different ways
depending on draft cost — a crowded backfield is a real problem for a
third-round pick and a reason to be interested in a thirteenth-round one.

---

## Four things in the project that will bite us

I checked these rather than assuming, because each one fails quietly rather than
loudly.

**1. The play-by-play cache doesn't have the columns we need.** `src\data.py`
trims play-by-play down to 13 columns to keep the file small (the list is called
`_PBP_COLUMNS`, around line 159). It keeps pass/rush/EPA/down but drops
`yards_gained`, `yardline_100` and `rusher_player_id`. Without those we cannot
compute explosive run rate *or* goal-line carry share — two of the things this
plan leans on. We need to widen that list.

**And then delete `data\raw\pbp_slim.parquet`.** This is the part that will waste
an afternoon if we forget it: the loader returns the cached file whenever it
exists, so widening the column list changes nothing at all until that file is
gone and the data is pulled again. It'll look like the code doesn't work.

**2. ~~The ADP history file has no position column.~~ — FIXED.** It used to be
quarterbacks only, 2021-2024, with columns `year, name, adp`, and the function
that fits the "what should a pick this expensive be worth" curve read the whole
file and fit **one** curve across every row. Appending running backs to that
would have blended the two into a single curve, and because backs score more,
every one of them would have shown up as a huge value. It would have looked like
the model found an edge. It wouldn't have.

Both ADP files now carry a `pos` column and the fitter filters by position first,
so quarterbacks and running backs get their own curves and never see each other's
rows. There's a test that specifically guards this: it fits the QB curve with 276
running backs sitting in the same file and checks the QB answer comes out
unchanged.

For reference, Heath's RB curve runs from about **16.7 points a game expected at
pick 10** down to **9.4 at pick 80**. The curve fitted on your actual FFC rows
lands close to that shape. His thresholds — **+5.0 over expectation is
league-winner territory, +2.0 is ordinary value** — are full-PPR numbers, so on
your half-PPR settings they become roughly **+4.4** and **+1.8**.

**3. `data\win_totals.csv` was missing 2025. ~~Gap~~ — FIXED.** It had 2021,
2022, 2023, 2024 and 2026 but no 2025, which mattered because the 8+ wins
condition is load-bearing in Heath's game-script finding and 2025 is the most
recent completed season we'd test against. All 32 teams' 2025 lines are in the
file now, so the backtest has an unbroken run of seasons to work with.

**4. Expected fantasy points loads optionally and fails silently.**
`get_ff_opportunity()` in `src\data.py` is the loader that gives us expected
fantasy points — the exact input the pass-catcher buckets need, and the good news
is it's already being pulled by `scripts\01_pull_data.py`. The catch is that when
it fails it prints one `[warn]` line and returns nothing, and the rest of the
pipeline carries on. That's the right behaviour for a QB model where it's a
nice-to-have. It's the wrong behaviour for an RB model where the archetype
buckets depend on it. It needs to become a hard check in
`scripts\10_preflight.py` so a missing file stops the run instead of quietly
producing a board with no archetypes on it.

---

## The build, in four tiers

Same approach that worked on the QB side: get something on screen early, then
make it smart. Each tier ends with something you can look at.

### Tier 1 — an RB board on screen, using only what already works — **BUILT**

New file `src\rb_blend.py`, copied from `src\qb_blend.py` and adapted. New script
`scripts\11_build_rb_model.py`, copied from `scripts\06_build_qb_model.py`.

Factors in this tier are the free ones: rushing production, receiving production,
snap share, team implied total, team win total, age and durability. Touchdowns
regressed the same way the QB model does it. No archetype, no screen, no
backfield file yet.

The one new number we have to pick is **replacement level**. The QB model uses
QB12 because you start one quarterback in a 12-team league. Running backs are
messier: you start two, plus a flex that goes to a back maybe 40-50% of the time.
That works out to about **RB30**. It's a setting, not a fact, and it's worth
revisiting once we see the board.

Output is an RB tab on the existing page. I'd keep it on the same page rather
than making a second one, because the most valuable thing in Heath's positional
work is the *cross-position* comparison — RB +8.9 against QB +4.1 — and that only
helps you if both are on one screen. It's also one file for GitHub Pages to
publish instead of two. Easy to reverse if you'd rather have separate pages.

**What actually got built.** Six files, and one decision worth knowing about:

| File | What changed |
|---|---|
| `src\rb_blend.py` | New. Nine factors, touchdowns regressed, a target counted as 1.8 carries |
| `src\current_roster.py` | Keeps the top three backs on each depth chart, not just the starter |
| `src\ratings.py` | Learned about positions — replacement level, boom bars and flags all differ by spot |
| `src\report.py` | **One page template, both positions** — see below |
| `scripts\11_build_rb_model.py` | New. The command you run: `py scripts\11_build_rb_model.py` |
| `.github\workflows\deploy.yml` | Builds and publishes the RB board alongside the QB one |

**On your website.** Both boards go up at
`hunterespo17.github.io/nfl-fantasy-models/` — one page, a tab per position, plus
a Big Board that ranks every player against replacement and one shared How-it-works
tab. The running-back build runs *first* and is allowed to fail: it leans on depth
charts and snap counts that can be thin in the offseason, and a bad day for the
backs must never take the QB board — the page you actually draft from — off the
internet. If it does fail, the site still deploys with no RB tab rather than an
empty one, and the Actions tab shows a warning saying so.

Each position build saves its own finished board into `outputs\boards\`, and
`scripts\12_build_site.py` folds whatever is in that folder into the one page. That
split is what makes a failed running-back run harmless: it never touched the
quarterbacks' saved board.

The decision: rather than copying the 1,100-line quarterback page into a second
running-back page that would immediately start drifting out of sync, the page
template now reads which position it's building and swaps the parts that differ.
That's the labels ("Search a RB…", "RB12" instead of "QB12"), the numbers behind
them (replacement level RB30 not QB12, big-game bars 20 and 25 points instead of
25 and 30), and whole blocks that only belong on one board — the QB archetype
chips and the league-winner filter don't appear on the RB page at all, because
both are claims about quarterbacks.

Every fix you've made to the quarterback page over the last few weeks — the logos,
the headshots, the ADP-as-rows table, the comps rail, the league-winner filter —
now applies to running backs for free, and to receivers and tight ends whenever we
get there.

Two more things that fall out of tier 1 being done. The board shows **no
league-winner gate for running backs**, on purpose: Heath's RB screen needs
contract year and expected-points share, which are tier 2, and grading backs
against quarterback bars would be worse than showing nothing. And the "worth the
pick?" numbers, which were thin while the ADP was missing, now sit on a real
running-back curve fitted to five seasons of actual FFC prices — see the bottom of
this document.

### Tier 2 — the Heath layer

This is where the model stops being a points projection and starts answering the
draft question.

The three archetype buckets, computed from expected fantasy points share and
shown as a label. The early-round disqualifier, styled as a warning rather than a
badge, and only applied to picks inside the first six rounds. The RB version of
the points-space value number, with its own fitted curve and the +5.0 / +2.0
thresholds. Age and contract-year flags.

Then the filter, matching the one we just built for quarterbacks — same dropdown,
same rule that non-matches get greyed out and sorted below the line rather than
disappearing, because mid-draft the row you suddenly need is exactly the one a
real filter would have hidden.

### Tier 3 — backfield competition

The genuinely new one, and the one that can't be fully automated.

Depth charts get us the roster, but they don't tell us what we actually need to
know: is this a settled backfield or an open competition, and does the guy behind
him have draft capital. That's a judgement call about 32 situations, which is
exactly the shape of problem `data\playcallers.csv` already solves on the QB side.

So: `data\backfields.csv`, one row per team, with the same discipline — a
validation script (`scripts\14_check_backfields.py`, mirroring
`scripts\09_check_playcallers.py`) that you run after every edit, and a preflight
entry so a typo can't ship. About 32 rows to fill in once, then touched only when
news breaks.

And per Heath's late-round finding, the factor has to cut both ways: crowded
backfield as a penalty for expensive backs, as *interest* for cheap ones.

### Tier 4 — testing it honestly

Carrying forward the lesson from the QB work, because it applies even more here:
**backtest error is the wrong test for this.** Mean absolute error measures the
middle of the distribution. Everything in tiers 2 and 3 is about the tails —
about finding the four or five backs a year who win leagues. A change that nails
every league-winner and is slightly worse on the other sixty backs will make the
error number go *up*, and it will have made the model better at its actual job.

So we need a second script that asks the real question: run the screen against
2022, 2023, 2024 and 2025, and check whether it flagged the backs who actually
returned +5.0 over expectation — and, just as importantly, how many backs it
flagged who didn't. A screen that lights up half the board isn't a screen.

That's `scripts\13_backtest_rb.py`, and it's the thing that tells us whether any
of this is real.

---

## What I've assumed, so you can overrule it

- ~~**Full PPR.**~~ **Half PPR** — you confirmed this, and `src\config.py` is set
  to it (`"reception": 0.5`). Heath's work is measured in full PPR, so the
  target-share section above now spells out which of his numbers survive the
  change unaltered and which get adjusted.
- **12 teams, 2 RB + 1 flex.** Already in `src\config.py`.
- **Replacement level around RB30.** My estimate, not a fact. Easy to change.
- **RB board as a new tab on the existing page**, not a separate page.
- **Tier 1 uses only data we already pull**, so you can see a board before we
  touch the play-by-play columns or start typing CSVs.

---

## Where this stands

**Done:** half-PPR scoring, 2025 win totals, all of tier 1 — there's a
running-back board you can open and click around in — and **the FFC ADP is in**.

### The ADP, and what came of it

You pasted six FFC tables. I pulled them apart into rows and then checked the
result rather than trusting it, because a mangled ADP file is worse than no ADP
file: it produces a board that looks confident and is quietly wrong. The checks
were that ranks run 1, 2, 3 with no gaps; that ADP never goes backwards down a
table; that no name accidentally swallowed a number from the next column; that
nobody appears twice; and that not one character of what you sent was left
unparsed. Then I rebuilt 30 rows at random from the parsed data and went looking
for each one, word for word, in your original paste. All of it came back clean —
**329 rows across six seasons, nothing dropped.**

Where it went:

- **`data\adp.csv`** — 53 backs priced for 2026, in draft order. Your 32
  quarterback rows are untouched; I checked every price individually rather than
  comparing the files as text, because the column order changed and that would
  have produced pages of meaningless noise.
- **`data\adp_history.csv`** — 276 running-back picks: 56 from 2020, 65 from
  2021, 43 from 2022, 59 from 2023, 53 from 2024. Prices span pick 1.3 to 175.7,
  so the curve is fitted across the whole draft rather than just the early rounds.

**Two things worth knowing.** First, **2025 is missing** from what you sent — the
paste has 2026, 2024, 2023, 2022, 2021 and 2020, and 2025 just isn't in there. It
isn't a blocker; five seasons is a real fit. But 2025 is the most recent finished
season and therefore the most relevant one, so if it's easy to grab, it's worth
grabbing. Second, your **quarterback** history only runs 2021-2024, so 2025 FFC
quarterback ADP would improve that board too. Same trip, if you're already there.

**One honest limit.** The join between your ADP rows and the scoring data happens
**by player name**, and this sandbox can't open the nflverse files, so I can't yet
confirm every name matches. A name that doesn't match doesn't error — it just
quietly drops that player out of the fit. So I added a printout: when you run the
build, it now lists everyone who didn't make it into the curve. Most of those will
be legitimate (hurt, benched, third on a depth chart). If you see a name there who
obviously played a full season, that's a spelling difference — send it to me and
it's a one-line fix.

**Also still open, both small:**

- `scripts\08_factor_stability.py` needs to run on your machine — the sandbox
  can't read the data files. Send back `outputs\factor_stability.csv` when you
  have it. Diagnostic, not a blocker.
- There's a leftover file, `scripts\10_preflight.py.txt`, that you can delete.
  It's a stray copy from a download that went sideways.
