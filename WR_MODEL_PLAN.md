# Building the WR model

A plan to talk through before we write any code. Same shape as
`RB_MODEL_PLAN.md`: your factor list checked one at a time, then what Ryan
Heath's article adds, then the traps, then a four-tier build.

Everything with a number attached below was measured on the data already sitting
in `data\raw\` — 998 receiver seasons from 2018 to 2025, and just over 600 cases
where the same receiver played a full-ish season two years running. Nothing here is a guess
about how receivers behave; where I couldn't measure something I say so.

---

## The short version

Three things are worth knowing before the detail.

**One, the machinery is nearly all there.** The QB and RB models already taught
the project how to pull weekly stats, snap counts, Vegas lines, depth charts,
ADP, headshots and logos, and how to turn all of it into 0-100 factor scores you
retune with sliders. `src\ratings.py` already has a WR row in its settings table
(replacement level WR36, big-game bars at 20 and 25 points). `scripts\15_pull_adp.py`
already keeps receivers when it scrapes. `src\current_roster.py` is
position-agnostic. The receiver board is mostly assembly, not invention.

**Two, there is exactly one real data problem, and I've solved it.** Every
receiver stat you asked for that starts with "per route" needs a count of routes
run, and routes run is the one thing the free data doesn't have. I built an
estimate and checked it against Heath's own published numbers — it lands within
about one hundredth. Details in its own section, because it's the load-bearing
assumption of the whole model and you should be able to poke at it.

**Three, two items on your list are going to disappoint you and one is already
done.** Yards after catch and yards per catch are, measured honestly, the two
weakest things on the list — near-zero ability to predict next season. And the
Vegas spread you asked me to add is already in the model: it has been baked into
the implied team total since the QB build. I'll show the arithmetic rather than
just assert it.

---

## Your factor list, checked one at a time

| What you asked for | Can we get it? | Verdict |
|---|---|---|
| Yards per route run | Estimated, not measured | Yes — but read the routes section first |
| Route share | Estimated | Yes, but as a **gate**, not a scoring factor |
| Route share trend | Estimated | Measured it. Doesn't predict. Show it, don't weight it |
| Target share | Yes, free | **The best factor in the whole set.** Backbone of the model |
| Target share trend | Yes, free | Same as route trend — display only |
| YAC | Yes, free | Weakest thing on your list. See below |
| Yards per catch | Yes, free | Same. Keep as a descriptor |
| TDs, and will they regress | Yes, free | Yes — and the regression is bigger than you'd think |
| Vegas implied points | Already built | Free, and it matters **more** at WR than at RB |
| Vegas spread / game script | Already built | Already in the model. See the last section |

Six are free. One needs an estimate. Two need to be demoted. One is done.

---

## The routes problem, and how I solved it

Yards per route run, route share, route share trend and Heath's favourite stat
all divide by the same number: how many pass plays did this receiver actually run
a route on. That number is sold by FantasyPointsData and PFF. It is not in the
free nflverse feed — I checked `data\raw\player_weekly_stats.csv` (no routes
column), `data\raw\pbp_slim.csv` (13 columns, and crucially no receiver on the
row, so per-play attribution is impossible), and the `ff_opportunity` files
(every download returns 404).

So I built it from two things we do have:

```
team dropbacks   = pass plays per team per week, from pbp_slim.csv
estimated routes = the receiver's offensive snap share x his team's dropbacks
route share      = his offensive snap share
```

The logic is that a receiver who is on the field for 80% of snaps is on the field
for roughly 80% of dropbacks, and modern receivers run a route on nearly every
dropback they're out there for. Snap counts run 2018-2025 with no gaps, and after
adding a name-matching fallback (first initial plus surname, so "C.Watson" finds
"Christian Watson") **99.2% of weekly receiver rows match to a snap row.**

Then I checked it, twice, against Heath's own article — which is the best
possible test, because his numbers come from real counted routes.

**Test one, his 2025 first-downs-per-route leaderboard.** My estimate reproduces
his top ten with an average error of **0.010** and a correlation of **+0.92**,
and the ordering barely moves:

| | Heath | Mine |
|---|---|---|
| Puka Nacua | 0.179 | 0.186 |
| Jaxon Smith-Njigba | 0.165 | 0.179 |
| Amon-Ra St. Brown | 0.135 | 0.126 |
| Terry McLaurin | 0.135 | 0.129 |
| Davante Adams | 0.134 | 0.138 |
| Drake London | 0.131 | 0.115 |
| Jaylen Waddle | 0.128 | 0.117 |
| Stefon Diggs | 0.127 | 0.146 |
| George Pickens | 0.125 | 0.120 |
| Ja'Marr Chase | 0.119 | 0.112 |

**Test two, his count of receivers clearing a 75% route share.** He gives one
number per season. Mine, on eight-plus games:

| | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|
| Heath | 53 | 48 | 46 | 43 | 40 |
| Mine | 48 | 49 | 44 | 44 | 39 |

Off by about two a year, and it reproduces his headline point — the number of
usable fantasy receivers has shrunk by roughly a quarter since 2021.

**What this means for you: no manual work.** I don't need you to buy or paste a
routes file. What you should know is that this is an *estimate*. It will be
slightly wrong for a receiver whose snap share and route share genuinely differ —
a blocking-heavy X receiver in a run-first offence, or someone who plays special
teams snaps that get counted oddly. That's a handful of players a year, and the
model will show the estimated route count on every player's detail panel so you
can see when it looks off.

---

## The three findings that should change how we build this

### One: target share, not yards per route run, is the backbone

I took every case of a receiver playing back-to-back seasons — 614 of them — and
asked, for each candidate stat, how well it predicts **next** season's points per
game, and how reliably the stat itself repeats.

| Signal | Predicts next year | Repeats year to year |
|---|---|---|
| Receiving yards per game | **0.69** | 0.70 |
| Points per game | 0.68 | 0.68 |
| Targets per game | **0.66** | 0.73 |
| **Target share** | **0.64** | **0.74** |
| WOPR (target share + air yards share) | 0.63 | 0.73 |
| Yards per route run | 0.56 | 0.55 |
| First downs per route run | 0.55 | 0.57 |
| Air yards share | 0.55 | 0.70 |
| Touchdowns | 0.52 | 0.43 |
| Route share | 0.49 | 0.60 |
| Estimated routes | 0.44 | 0.43 |
| **Yards per catch** | **0.13** | 0.38 |
| Explosive catch rate | 0.13 | 0.26 |
| **Yards after catch per catch** | **0.10** | 0.47 |
| Touchdown rate | 0.10 | 0.20 |
| Average depth of target | 0.01 | 0.61 |

Volume wins. Target share is both a top-four predictor *and* the single stickiest
thing a receiver does — it repeats at 0.74, better than his own scoring does. So
target share is the spine of the model, with WOPR next to it because it adds the
"and they're deep targets" half.

Efficiency still matters, and I'll come to where. But if we build this model
around yards per route run because it's the fashionable number, we build a worse
model than if we build it around target share.

Worth being straight about the tension with Heath here: he says first downs per
route run is the most predictive receiver stat in fantasy. He isn't wrong and I'm
not contradicting him — he's answering "who **beats their draft price**", I'm
answering "who **scores the most points**". Those are different questions and
different answers, exactly like the running back target-share trap in the RB plan.
The next section is where his version pays off.

### Two: the efficiency stat is a quality gate at the top, not a breakout finder

I replicated his screen on my own numbers. Receivers clearing 0.116 first downs
per route on 250+ routes:

| Screen | Next year's PPG | Reached 12+ PPG |
|---|---|---|
| 1D/RR at or above 0.116 | **12.6** | **58%** |
| Below it | 8.6 | 19% |
| At or above 0.125 | 13.3 | 67% |

That's a big, real gap and it validates his 43%-become-league-winners claim in
spirit. But then I split it by how good the receiver already was, and the edge
concentrates almost entirely at the top:

| Prior season's PPG | Edge from clearing 0.116 |
|---|---|
| 13+ | **+1.7 points a game** |
| 10-13 | -0.9 |
| 7-10 | +0.6 (only one player in the sample) |
| Under 7 | -1.7 (only three players) |

So: among receivers who were already good, it tells you which ones stay good, and
that's worth +1.7 a game. Below that, almost nobody clears the bar, so it can't
find you a breakout in my sample the way it does in his. The difference is that
his test is against ADP over four years and mine is against prior production over
seven — both can be true. My conclusion is to **use it, weight it moderately, and
show it as a badge rather than build the model on it.**

### Three: touchdowns regress hard, and targets predict them better than touchdowns do

This is the "will they regress positively or negatively" question you asked, and
the answer is emphatic. Splitting receivers into five groups by touchdown rate:

| Touchdown rate group | TDs that year | TDs the next year |
|---|---|---|
| Highest | 7.5 | **5.0** |
| High | 5.7 | 4.5 |
| Middle | 4.7 | 4.5 |
| Low | 3.4 | 3.9 |
| Lowest | 1.1 | **2.9** |

The top group loses a third of its touchdowns. The bottom group nearly triples.
And touchdown *rate* barely repeats at all — 0.20, the lowest number in the whole
stickiness table. Meanwhile **targets per game predicts next year's touchdowns
(0.41) about as well as touchdowns themselves do (0.43)**.

So the model does what the QB model already does: it throws away the raw
touchdown count and rebuilds an expected touchdown number from volume and field
position, then shows the gap. A receiver who scored fourteen on modest volume gets
marked down; one who scored three on heavy volume gets marked up. Names that fall
out of 2025 immediately: Davante Adams scored 14 touchdowns on 370 routes, and
Terry McLaurin scored 3 while ranking fifth in first downs per route.

---

## Where YAC and yards per catch actually belong

You asked for both and I don't want to just delete them, so here's the honest
version. As standalone factors they're close to useless — 0.10 and 0.13 against
next season's scoring, versus 0.64 for target share. The reason is that both are
*consequences* of a role rather than descriptions of a player. A slot receiver has
high YAC because he catches the ball five yards downfield; a deep threat has a
high yards per catch because he only gets targeted at twenty. Neither tells you
he's going to score more.

Two places they earn their keep anyway:

They already live inside the stats that do work. Yards per route run is
(catch rate x yards per catch x target rate); first downs per route quietly
rewards the YAC receiver who turns a six-yard catch into a first down. We're not
throwing the information away, we're just not double-counting it.

And they're the best *explanation* on the detail panel. When the board likes
someone you didn't expect, "9.2 targets a game, 5.3 yards after the catch, 78%
route share" is the sentence that makes it make sense. So both go in the signals
list that renders under each player, and neither gets a slider.

Same treatment for the two trend numbers you asked about. I measured second-half
minus first-half route share and target share against next season, and both came
back at essentially zero (-0.02 and -0.01). A receiver finishing strong tells you
almost nothing about the following September — the offseason resets too much.
They're genuinely useful for reading a situation, so they render as a little
arrow on the player card, but they don't move the ranking.

---

## What Heath adds that isn't on your list

### The 75% route share gate

His framing: "138 of the 163 WRs (85%) to average 12.0 or more FPG since 2021
have run a route on at least 75% of their team's dropbacks." On my estimate it's
**88%** — near-identical. And the receivers clearing it averaged **10.3** points
the next season against **6.8** for those who didn't.

This is the right shape for a gate rather than a factor: below it you're
essentially not a fantasy asset, above it the exact number stops mattering much.
So a hard flag on the board, not a slider.

### Year three is the year

His claim is that 53% of league-winning receivers were in years three through
five, with year three the single most common. My data agrees on the shape.
Average change in points per game going into each season:

| Season of career | Change in PPG |
|---|---|
| Year 2 | **+0.6** |
| Year 3 | **+0.6** |
| Year 4 | -0.1 |
| Year 5 | -0.1 |
| Year 6 | -1.4 |
| Year 7+ | -0.8 to -1.6 |

Years two and three are the only ones that go up. From year six the decline is
steep and consistent. `data\raw\players.csv` already carries `rookie_season`, so
this is free. It becomes a career-window factor, peaked at years two to four and
falling away after five — a bit earlier than Heath's three-to-five, because I'm
measuring points and he's measuring league-winners.

### Draft capital, which we skipped at running back

Also free in `players.csv`, and unlike at running back it separates cleanly:
first, second and third round receivers averaged 9.9, 8.7 and 9.7 points the next
season; fourth and fifth rounders 7.0 and 6.3. It's a *level* indicator, not a
breakout indicator — the year-over-year change is flat across all rounds — so it
belongs in the talent factor for young receivers and should fade out once a
player has three seasons of real evidence.

### The things I could not reproduce, and am flagging rather than hiding

**Crowded rooms.** He finds 48% of league-winning receivers played on a team with
two-plus pass catchers going in the top 60, versus only five teams in 2026
(Cincinnati, the Rams, Detroit, Dallas, Chicago). I tested the nearest thing I
can measure — how many teammates run routes on 60%+ of dropbacks — and found no
benefit: two-, three- and four-man rooms produced 8.5, 8.9 and 7.7 points the next
year. His claim is about *ADP*, which is a much narrower and more specific thing
than my test, so I'd implement it as a small named flag on those five teams
rather than a weighted factor, and revisit once we have receiver ADP loaded.

**Team WR2 beats team WR1 inside the top 100 picks.** Can't test it without
historical receiver ADP. Worth building the flag anyway because it's cheap once
the ADP is in.

**Heavy personnel.** His point is that receivers get roughly a 32% efficiency
bump when there are two or fewer of them on the field, and that the league is
trending that way — teams running 3+ receivers on 75% of dropbacks fell from 18 in
2024 to 13 in 2025, and 22 tight ends went in the 2026 draft. I can't count
personnel groupings from `pbp_slim.csv`. What I *can* do is watch the trend
indirectly: a receiver whose route share is rising while his team's dropbacks fall
is the Jaxon Smith-Njigba pattern. That goes on the card as context.

**Red zone target share.** Heath singles out Drake London as the two-year leader.
`pbp_slim.csv` has no receiver on the row, so I can't compute it. This is the one
place a manual pull would genuinely help, and it's small — a single leaderboard
rather than a per-player file. Low priority; the touchdown regression already
covers most of the ground.

### The receiver cliff, and what it means for the board

"We've never seen a league-winning WR drafted after Round 12", only 4.5% of
league-winners from rounds 10-17 are receivers, and the WR40 goes at pick 107.
This isn't a factor, it's a shape the board should show: past roughly pick 110 the
receiver curve should flatten into the floor rather than keep sloping, so the
"worth the pick?" number stops promising value that has never historically
existed. The running back model has the same idea implemented as the dead zone;
this is the receiver version and it sits at the other end.

---

## Four things that will bite us

**1. We have no receiver ADP yet.** `data\adp.csv` has 53 running backs and 32
quarterbacks and no receivers. Good news: `scripts\15_pull_adp.py` already keeps
WR and TE when it scrapes, so ESPN and the pasted-board path work unchanged. It
just has to be run. The one thing I'll need from you, same as last time, is the
**FFC receiver ADP** — current year for the board, and 2020-2024 for the
historical curve that the "worth the pick?" number is fitted to. Without it the
value column is guesswork.

**2. We have no Mike Clay receiver projections.** There's `clay_qb_2026.csv` and
`clay_rb_2026.csv` in `data\`, and no receiver equivalent. That matters more than
it sounds, because the RB build uses Clay's games-played column as the injury
signal, and without it every receiver silently projects a full 17 games. You
offered his receiver and tight end pages a while back — that's the ask.

**3. Anything applied only in Python gets undone by the website.** This one cost
us real time on the running backs. `src\report.py` recomputes every projection in
the browser each time you drag a slider, so a correction applied in the Python
build vanishes on the first slider move. Whatever the receiver model clips,
caps or adjusts has to be published on the row and re-applied in the page's
JavaScript. It's now a rule, not a lesson.

**4. Name matching.** Exact name matching lost 6% of receiver rows and dropped
Luther Burden entirely. The first-initial-plus-surname fallback got it to 99.2%,
but it will collide eventually — two receivers on the same team in the same week
with the same initial and surname. The build should print a warning when it
happens rather than silently picking one.

---

## The build, in four tiers

Same approach that worked twice already: something on screen early, then make it
smart.

### Tier 1 — a receiver board on screen

New `src\wr_blend.py`, copied from `src\rb_blend.py`. New
`scripts\16_build_wr_model.py`. Both boards' plumbing already handles a third
position, so the site work is close to zero.

Factors in this tier, in the order I'd weight them:

| Factor | What's in it |
|---|---|
| Volume | Target share and targets per game, the two best predictors we have |
| Opportunity quality | WOPR — target share plus air yards share |
| Efficiency | First downs per route run and yards per route run |
| Role | Route share, plus the 75% gate as a flag |
| Vegas | Implied team points. Weighted **higher than on the RB board** — see below |
| Scoring | Touchdowns, regressed to a volume expectation |
| Career window | Peaked at years two to four, falling after five |
| Talent | Draft capital, fading out after three seasons |
| Availability | Games played, same treatment as the other two boards |

Replacement level starts at **WR36** — three receivers a week across twelve teams
— which is what `src\ratings.py` already has. It's a setting, not a fact, and
worth revisiting once we can see the board.

**One thing I'd carry over from the running backs on day one, not later:** the
workload ceiling. The projection scale is a percentile map, so without a cap it
hands a fourth receiver the same seven points a game it hands a starter's floor,
and a team's receiving room sums to more points than any real offence produces.
The running back version is `1.0 + 1.10 x expected touches`; the receiver version
would be fitted the same way, against targets. Cheap to add now, annoying to
retrofit.

### Tier 2 — the Heath layer

The first-downs-per-route badge with his 0.115 threshold. The 75% route share
gate. The career-window flag on years three to five. The five crowded-offence
teams. The receiver filter dropdown, matching the quarterback one — same rule
that non-matches go grey and sort below the line rather than disappearing,
because mid-draft the row you suddenly need is the one a real filter would hide.

### Tier 3 — the things that need receiver ADP

The "worth the pick?" number on a receiver curve fitted to five years of FFC
prices. The team-WR2-versus-WR1 flag. The cliff shape past pick 110. All blocked
on the ADP arriving.

### Tier 4 — testing it honestly

`scripts\17_backtest_wr.py`, the mirror of the running back one: hold out a
season, rebuild, compare. The bar to beat is the same naive baseline — last
year's points per game, which on this data correlates 0.68 with next year's. If
the model can't beat that it isn't earning its complexity.

---

## The Vegas spread, and game script — for all three positions

You asked me to factor spreads into the receivers and to add them to the
quarterbacks and running backs too. I measured it before building anything, on
every regular-season game since 2019, and the answer is that **the spread is
already in the model**.

Here's why. The number the model already uses is the implied team total, and it's
computed as `(total line + spread) / 2`. The spread is literally one of its two
ingredients. So the question isn't "should we use the spread" but "does the spread
tell us anything the implied total hasn't already said". I ran that directly:

| | Implied total alone | Adding the spread on top |
|---|---|---|
| QB | 0.1187 | 0.1230 |
| RB | 0.0228 | 0.0230 |
| WR | 0.0273 | 0.0284 |

Essentially nothing. And the leftover spread coefficient comes out *negative* on
all three — once you know how many points a team is expected to score, being a
bigger favourite is very slightly worse, because that's the blowout where the
starters sit in the fourth quarter.

The season-level version, which is the one that matters for drafting, says the
same thing more clearly. Implied total beats spread at every position:

| | Team's average spread | Team's implied total |
|---|---|---|
| QB | +0.61 | **+0.73** |
| WR | +0.50 | **+0.62** |
| RB | +0.27 | **+0.34** |

So I'm not adding a spread factor. It would be double-counting, and the model
would look more sophisticated while being slightly worse.

**But three real things came out of the same work, and they do change the build.**

**Receivers are far more game-script sensitive than running backs.** Everyone
believes the opposite. Season-long, a team's implied total correlates +0.62 with
what its receivers score and only +0.34 with what its backs score. Forward-looking
on the early lines the model actually uses, it's +0.41 against +0.25. **Vegas
should carry more weight on the receiver board than it does on the running back
board** — the RB board currently has it at 10, and the receiver board should be
meaningfully higher.

**Game script barely moves volume at all.** This surprised me. Comparing heavy
favourites to heavy underdogs: running back carries go 14.3 to 13.9, and receiver
targets 7.2 to 6.9. Almost nothing. What actually moves is scoring — quarterback
passing touchdowns go 1.93 to 1.15, and a running back's rushing touchdowns go
0.57 to 0.35, a 63% difference. So game script isn't a volume story, it's a
touchdown story, and the right place to apply it is inside the touchdown
expectation on all three boards rather than as a new slider.

**The one genuine spread effect at running back is archetype, not points.**
Backs in favourable scripts take 25.3% of their fantasy points through the air;
backs playing from behind take 29.4%. That's small but it's real and it's exactly
the axis Heath's three archetype buckets sit on — a back on a heavy-favourite
team drifts toward the non-pass-catcher bucket. Worth folding into the archetype
assignment when tier 2 of the running back model gets built, and it costs nothing
because the data's already loaded.

Heath's own framing supports the direction: "One of our best forward-looking
signals of offensive quality is Vegas implied team totals... there was a 0.51
correlation between actual and implied points per game for the 2025 season." He
uses implied totals, not spreads, for exactly the reason above. He also puts
Detroit top of the league at 26.4 implied points a game for 2026, and flags
Miami and the Jets under 20.0, with the Giants, Saints, Falcons, Steelers, Titans
and Panthers in a 20-to-22 danger band. Those are useful sanity checks for the
receiver board once it's up.

---

## What I've assumed, so you can overrule it

**Half PPR**, same as the other two boards. It matters more at receiver than
anywhere else — full PPR would push target share's weight up further still.

**Twelve teams, three receivers started**, giving replacement level WR36. If your
league starts two plus a flex that usually goes to a receiver, WR30 might be
closer.

**The route estimate is good enough to build on.** I've shown my working; if you'd
rather buy a real routes file at some point, swapping it in is a one-line change
because everything downstream divides by the same column.

**Efficiency gets moderate weight, volume gets heavy weight.** This is the biggest
judgement call in the plan and it's the one place I'm knowingly weighting against
the fashionable view. If you'd rather lean into yards per route run I'll do it,
but the measurement above is what it is.

**No red zone data.** Skipping it for now rather than asking you to type in a
leaderboard. Say the word if you want it.

---

## What I need from you

Three things, none of them big:

**The FFC receiver ADP** — this year for the board, and 2020 through 2024 for the
historical curve, same as you sent for the running backs. This is the only real
blocker; tier 3 can't start without it.

**Mike Clay's receiver page** from the same projection document you already sent.
Without it the model assumes everybody plays seventeen games.

**A decision on route share versus snap share**, if you have a strong view. I'm
treating them as the same number. If you know of receivers where that's badly
wrong, tell me and I'll special-case them.
