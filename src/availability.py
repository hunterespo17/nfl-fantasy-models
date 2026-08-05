"""
Who do we actually expect to be on the field?

Every factor in every position model describes a player's JOB -- how big it is,
how good he is at it, how good his team is around him. None of that knows whether
he is healthy enough to hold the job in week one, and for a long time this board
simply assumed everybody played all seventeen. That assumption is the reason it
had Zach Charbonnet at RB16 in August 2026 while the market had him RB42: the
model could see he was Seattle's listed starter and could not see the knee.

This module is the one place that gap gets filled, and it is shared by every
position so a quarterback and a running back are treated the same way.

THE RULE: EVERYBODY PLAYS A FULL SEASON UNTIL SOMETHING SAYS OTHERWISE.

That is deliberate, and it is a reversal of how this file used to work. There was
a version that gave every player a fitted "how many games does a body like his
normally last" number, so nobody got seventeen and the healthiest quarterback in
the league opened at 14.2. It measured better on paper and it was the wrong tool.
Docking every single row by roughly the same amount does not change anybody's
rank -- it just shrinks the whole board -- while docking a specific player for a
thin injury history quietly buries a genuine top-five talent for something that
has not happened yet. Joe Burrow is not a worse bet than Bo Nix. He is a riskier
one, and those are different sentences that belong in different columns.

So there are two questions here now, and keeping them apart is the whole point.

FIRST -- HOW MANY GAMES (proj_games). Starts at seventeen for everyone. It comes
down only when something specific says so, from three sources that get MIXED
rather than ranked:

  1. data/<pos>_availability.csv -- yours. Hand-typed, deliberately tiny. A
     number, an injury, a week he's back, or any combination.
  2. the injury he is carrying -- INJURY_RECOVERY below turns "acl" or "high
     ankle" into how long that actually takes and how many games players have
     really gone on to play the following season.
  3. data/clay_<pos>_<season>.csv -- the outside guide, written once a year by
     scripts/import_clay.py.

Nothing about a player's PAST availability enters here. Missing eight games in
2024 is not a report that he will miss games in 2026.

SECOND -- HOW RISKY (avail_games / avail_risk). This is where an injury history
goes, and it is the reason the reversal above costs nothing. The fitted model
that used to set games still runs, unchanged and still accurate; it just writes
to a different column now. A quarterback whose last three seasons say "a body
like this lasts about ten games" is projected for a full seventeen and marked as
one of the riskiest picks on the board. See BASE_FIT.

News REPLACES rather than discounts. If you type 11, he is priced against 11 --
not 11/17ths of some baseline, which would punish him twice.

Two things this module deliberately does NOT do.

It does not touch a completed season. Only rows for the upcoming season move off
a full slate, so nothing a 2026 guide says can leak backwards into a backtest
scored on 2019 information.

And it does not use the guide's games column below GUIDE_FLOOR. That column
answers two different questions with one number -- "hurt, will miss time" and
"third on the depth chart, will get mop-up work" -- and only the first is news.
The second is a job description, already priced through Role and depth-chart
share, and taking it again here would charge a backup twice for being a backup.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config

# Below this, a guide's games number is a depth-chart statement rather than an
# injury report, and is ignored. Anything hand-typed is always taken.
GUIDE_FLOOR = 8.0

# The season opens in SEPTEMBER. This sounds obvious and it is the single most
# common way a games estimate goes wrong: a back "back in eight weeks" from a
# June operation has not missed anything at all, and one "back in eight weeks"
# from an injury in camp has missed the first month of the year. Everything below
# that talks in weeks is counted from week one, never from today.
SEASON_WEEKS = 17.0

# CARRYING AN INJURY IS NOT THE SAME WORRY AS HAVING A HISTORY OF THEM, so it
# gets its own 0-to-1 score instead of being jammed into the history one. It is
# read straight off how long the injury takes -- INJURY_RECOVERY's `weeks` over
# a year -- because time out is the best single proxy anyone has for how much of
# him is still missing. A torn ACL scores 1, a bruised rib scores 0.08.
INJURY_RISK_WEEKS = 48.0

# Once he is practising in full the recovery window is behind him, and what is
# left is the chance of a setback: real, but not the same thing. Mahomes took
# every first-team rep in August; pricing him as though the December knee were
# still open would be silly. So a cleared man carries half the score.
CLEARED_RISK = 0.5


# ---------------------------------------------------------------------------
# WHAT AN INJURY ACTUALLY COSTS
# ---------------------------------------------------------------------------
# "He's coming off a torn ACL" and "he's coming off a hamstring" are not the same
# sentence, and until now this model could not tell them apart -- an injury was a
# note in a file and a number you typed next to it. This table is what makes the
# type of injury mean something on its own.
#
# Every figure here is lifted from published NFL return-to-play research. None of
# it is estimated, and where the literature genuinely has no NFL-specific answer
# the entry says so rather than inventing one. Two fields per injury:
#
#   weeks   typical return-to-play window, counted from the injury or the
#           operation. Used with `back_week` to work out how much of a SEASON is
#           actually gone -- see above.
#   games   how many of seventeen players have really gone on to play the
#           following season. This is the number the model wants and the one the
#           literature is thinnest on; where a study measured games directly it
#           is marked MEASURED, where it had to be derived from time-loss totals
#           it is marked DERIVED.
#
# `pos` overrides the games figure where the evidence shows the position matters
# more than the injury does. There is exactly one injury where that effect is
# overwhelming, and it is worth stating plainly because it decides real picks:
#
#   ACL. Across 312 NFL players, 55.8% returned at all, and those who did played
#   8.7 games a season over the next three against 13.7 before. But the position
#   split is enormous. Quarterbacks returned at 92.9% and lost 2% of their
#   approximate value. Everyone else returned at 53.7%, and running backs lost
#   90.5%. A passer coming off a knee and a back coming off the same knee are not
#   the same bet and this table does not pretend they are.
#
# The honest health warning on all of it: sample sizes vary from 1,354 (hamstring
# recurrence, solid) to 4 (running backs after an Achilles, which is the entire
# statistical basis for a belief the whole industry treats as fact). Confidence
# is noted per row. Where a row is thin the model still uses it -- a thin real
# number beats a confident invented one -- but it is flagged here so that when
# one of these decides a pick you know what it is resting on.
INJURY_RECOVERY: dict[str, dict] = {
    # --- knee ---------------------------------------------------------------
    # MEASURED, n=312. Games 8.7 vs 13.7 pre-injury over the first three seasons
    # back. RTP 55.8% overall; QB 92.9% (AV -2%), RB AV -90.5%.
    # pubmed.ncbi.nlm.nih.gov/35284583 + journals.sagepub.com/doi/pdf/10.1177/2325967120974743
    "acl": {"weeks": 48, "games": 8.7, "pos": {"QB": 14.0, "RB": 8.0},
            "label": "ACL", "conf": "strong"},
    # DERIVED. Knee, all types: 326 injuries / 1,815 games missed 2017-22 = 5.6
    # games an episode. A bare "knee" is a body part, not a diagnosis -- if you
    # know it was the ACL or the meniscus, say so, because they are miles apart.
    "knee": {"weeks": 6, "games": 11.5, "label": "knee", "conf": "fair"},
    # NON-NFL SOURCE. No NFL-specific MCL study found; these are college and high
    # school football figures. Grade I 10.6 days, grade II 19.5 days, grade III
    # non-operative 64.4 days. Treat as a rough shape, not a measurement.
    "mcl": {"weeks": 3, "games": 14.5, "label": "MCL", "conf": "weak"},
    # MEASURED (return rate), n=77. Partial LATERAL meniscectomy: 8.5 months,
    # 61% RTP, and speed positions -- backs, receivers, backs of the defence --
    # were 4x LESS likely to return than linemen. Medial is far more common and
    # far quicker; no NFL figure exists for it, so this is the pessimistic case.
    # pubmed.ncbi.nlm.nih.gov/24914032
    "meniscus": {"weeks": 36, "games": 11.0, "label": "meniscus", "conf": "fair"},

    # --- lower leg, ankle, foot ---------------------------------------------
    # MEASURED, n=98 repairs. 339.8 days to return, 72.4% RTP. Among those who do
    # come back, games per season are NOT significantly different from controls;
    # the damage is in the 28% who never return and a career about a season
    # shorter. The four running backs in the study did significantly worse -- an
    # n of four is the entire evidence base for "an Achilles ends a back", so it
    # is applied here, gently, and flagged.
    # journals.sagepub.com/doi/full/10.1177/1071100717718131
    "achilles": {"weeks": 48, "games": 10.5, "pos": {"RB": 8.5},
                 "label": "Achilles", "conf": "fair"},
    # MEASURED, n=33. Median 11.0 months, 81.8% RTP -- and games came back
    # essentially untouched, 15 before and 15 after. The best news in this table:
    # a Lisfranc costs a year, then stops costing anything.
    # journals.sagepub.com/doi/full/10.1177/23259671231159935
    "lisfranc": {"weeks": 48, "games": 15.0, "label": "Lisfranc", "conf": "strong"},
    # MEASURED (time loss), n=533. 89.7% RTP. Mean 80.5 days out, 90.1 for
    # offensive players -- but the standard deviation is 132.9, larger than the
    # mean, so this is the least reliable point estimate here even though the
    # sample is big. Ankle injuries broadly cost significantly more fantasy
    # points the FOLLOWING season for backs, receivers and tight ends.
    # pubmed.ncbi.nlm.nih.gov/33906554
    "high_ankle": {"weeks": 13, "games": 13.0, "label": "high ankle", "conf": "fair"},
    # DERIVED. Ankle, all grades: 255 injuries / 907 games = 3.6 games an episode.
    "ankle": {"weeks": 4, "games": 13.5, "label": "ankle", "conf": "fair"},
    # MEASURED, n=53. The cleanest operative-vs-not split in the literature.
    # Non-operative: 100% RTP, 86% return the same season, and returners play 82%
    # of the following season's games. Operative: 80% RTP, 221 days, and ZERO
    # returned the same season -- and only 27% of them got back to their prior
    # level. If it was operated on, say so in the note and dock him further.
    # orthojournalhms.org/22/2021article20_25.html
    "turf_toe": {"weeks": 11, "games": 14.0, "label": "turf toe", "conf": "strong"},
    # MEASURED, n=27. Jones fracture: 9.7 weeks post-op, 93% RTP, 7.4% refracture.
    # Prospects who arrived with one scored significantly lower in fantasy over
    # their first three years -- backs and defensive linemen especially.
    # DERIVED cross-check: foot, all types, 90 injuries / 527 games = 5.9 games.
    "foot": {"weeks": 10, "games": 11.0, "label": "foot", "conf": "fair"},
    # MEASURED, n=95. Tibia: median 44.6 weeks closed, 79.5 weeks open -- a full
    # season and then some. Two of nine open-fracture returners missed the entire
    # following season outright. The worst entry in this table by a distance.
    # smrj.scholasticahq.com/article/87846
    "tibia": {"weeks": 45, "games": 6.0, "label": "broken leg", "conf": "fair"},

    # --- soft tissue --------------------------------------------------------
    # MEASURED, n=1,354. 2.4 weeks on the injury report, and the highest
    # confirmed recurrence rate of anything here: 33% reinjure, 27% of those in
    # the same season. The games cost of one episode is small; the reason it is
    # docked at all is that it very often is not one episode.
    # journals.sagepub.com/doi/full/10.1177/23259671241298622
    "hamstring": {"weeks": 3, "games": 13.5, "label": "hamstring", "conf": "strong"},
    # MEASURED, n=349. 1.97 games missed, 83.7% return the same season, and no
    # significant performance change among those who do. But 20.7% went on to
    # suffer another calf strain or an Achilles later in their career.
    "calf": {"weeks": 3, "games": 14.5, "label": "calf", "conf": "fair"},
    # THIN. Quadriceps is 8.3% of NFL lower-extremity strains; the underlying
    # study never breaks out its time loss. All such strains had a median of 12
    # days. No NFL games-after figure exists.
    "quad": {"weeks": 3, "games": 14.0, "label": "quad", "conf": "weak"},
    # MEASURED, n=56. Sports hernia / athletic pubalgia: 94.7% RTP, and games per
    # season went 13.6 before to 12.0 after against 14.0 for controls. Careers
    # were shorter and only 52.6% were still active three years later.
    "groin": {"weeks": 9, "games": 12.0, "label": "groin", "conf": "strong"},
    # DERIVED. Hip: 53 injuries / 182 games = 3.4 games an episode.
    "hip": {"weeks": 4, "games": 13.5, "label": "hip", "conf": "fair"},
    # MEASURED, n=63. Surgical 146.7 days, 85.7% RTP, and no significant
    # performance decline afterwards. The cohort is nearly all linemen and
    # linebackers, so the 100% skill-position return rate is a small-n artifact.
    "pec": {"weeks": 21, "games": 13.0, "label": "pec", "conf": "fair"},

    # --- upper body ---------------------------------------------------------
    # MEASURED. Labrum: operative 140.2 days (8.4 games), non-operative 21.5 days
    # (2.6 games), and about 42% get operated on -- which is what this blended
    # figure reflects. Players drafted with a prior repair went on to play 33.7
    # career games against 48.3 for controls.
    "shoulder": {"weeks": 8, "games": 12.0, "label": "shoulder", "conf": "fair"},
    # MEASURED. 9.8 days missed on average, 17 for quarterbacks; 96% are grade
    # I-II and only 1.7% ever need surgery. Barely an injury in games terms --
    # and the literature explicitly says nobody has ever studied what it does to
    # performance afterwards.
    "ac_joint": {"weeks": 2, "games": 15.5, "label": "AC joint", "conf": "fair"},
    # MEASURED, n=~200. Non-operative 244.6 days, plated 211.3 days, RTP 97% and
    # 94%. Only 28% and 44% get back the same season -- so a collarbone broken in
    # November is largely a NEXT-season problem, which is exactly this column.
    "clavicle": {"weeks": 31, "games": 14.0, "label": "collarbone", "conf": "fair"},
    # MEASURED. Hand: 1.7 games missed on average, 97.4% RTP. Thumb is 22.9% of
    # hand injuries. Small in games -- but the deviation is twice the mean, and
    # for a quarterback a throwing hand is not a hand.
    "hand": {"weeks": 2, "games": 15.5, "pos": {"QB": 14.5},
             "label": "hand", "conf": "fair"},
    # MEASURED. 2.5 games missed -- but 28.6% land on injured reserve, the
    # highest rate of any hand or wrist location.
    "wrist": {"weeks": 3, "games": 14.5, "label": "wrist", "conf": "fair"},
    # MEASURED, n=643+. Median 9 days to full participation, mean 15; 59% miss at
    # least one game, average 0.99 games. Quarterbacks miss about one game more
    # than everyone else, and each previous concussion adds roughly a quarter of
    # a game to the next one.
    "concussion": {"weeks": 2, "games": 15.5, "pos": {"QB": 15.0},
                   "label": "concussion", "conf": "fair"},
    # DERIVED for the non-surgical case: central axis, 127 injuries / 407 games =
    # 3.2 games. Surgery is a different animal entirely -- lumbar 61% RTP and
    # cervical only 47%, with an average of 1.3 seasons left afterwards. If it
    # was operated on, type the games yourself; this row is not that case.
    "back": {"weeks": 4, "games": 13.0, "label": "back", "conf": "fair"},
    # VERY THIN. Two case reports and a survey of 23 team physicians; the stated
    # guidance is three to four weeks with symptoms often outlasting that.
    "rib": {"weeks": 4, "games": 14.5, "label": "ribs", "conf": "weak"},

    # DERIVED fallback for an injury this table does not name. Across 2,523
    # time-loss injuries to offensive skill players 2017-22, excluding the 619
    # logged as undisclosed, the average episode cost 4.0 games.
    # assets.cureus.com/uploads/original_article/pdf/438997
    "other": {"weeks": 4, "games": 13.0, "label": "injury", "conf": "weak"},
}

# What you are allowed to type in the injury column. The point is that you write
# the word you would actually say out loud and the model finds the row.
INJURY_ALIASES: dict[str, str] = {
    "acl": "acl", "torn acl": "acl", "acl tear": "acl",
    "knee": "knee", "knee surgery": "knee", "patella": "knee",
    "mcl": "mcl", "pcl": "mcl", "lcl": "mcl",
    "meniscus": "meniscus", "torn meniscus": "meniscus", "cartilage": "meniscus",
    "achilles": "achilles", "torn achilles": "achilles",
    "lisfranc": "lisfranc",
    "high ankle": "high_ankle", "high ankle sprain": "high_ankle",
    "syndesmotic": "high_ankle", "syndesmosis": "high_ankle",
    "ankle": "ankle", "ankle sprain": "ankle", "sprained ankle": "ankle",
    "turf toe": "turf_toe", "toe": "turf_toe",
    "foot": "foot", "jones": "foot", "jones fracture": "foot",
    "broken foot": "foot", "metatarsal": "foot", "navicular": "foot",
    "heel": "foot", "plantar": "foot", "plantar fasciitis": "foot",
    "tibia": "tibia", "fibula": "tibia", "broken leg": "tibia",
    "leg": "tibia", "shin": "tibia", "tib fib": "tibia",
    "hamstring": "hamstring", "hammy": "hamstring", "hamstrings": "hamstring",
    "calf": "calf", "achilles tendinitis": "calf",
    "quad": "quad", "quadriceps": "quad", "thigh": "quad",
    "groin": "groin", "sports hernia": "groin", "hernia": "groin",
    "pubalgia": "groin", "adductor": "groin", "core muscle": "groin",
    "hip": "hip", "hip flexor": "hip", "labrum hip": "hip",
    "pec": "pec", "pectoral": "pec", "torn pec": "pec",
    "shoulder": "shoulder", "labrum": "shoulder", "slap": "shoulder",
    "rotator cuff": "shoulder", "shoulder surgery": "shoulder",
    "ac joint": "ac_joint", "ac": "ac_joint", "acromioclavicular": "ac_joint",
    "clavicle": "clavicle", "collarbone": "clavicle",
    "broken collarbone": "clavicle",
    "hand": "hand", "thumb": "hand", "finger": "hand", "knuckle": "hand",
    "broken hand": "hand", "broken thumb": "hand",
    "wrist": "wrist",
    "concussion": "concussion", "head": "concussion",
    "back": "back", "neck": "back", "lumbar": "back", "disc": "back",
    "herniated disc": "back", "spine": "back", "stinger": "back",
    "rib": "rib", "ribs": "rib", "oblique": "rib",
}


def injury_games(injury, pos: str = "RB"):
    """(expected games, weeks out, printable label) for an injury, or Nones.

    `injury` is whatever got typed in the availability file. Unrecognised words
    fall through to the generic entry rather than being ignored -- somebody
    bothered to write it down, so something is wrong with him.
    """
    if injury is None or (isinstance(injury, float) and pd.isna(injury)):
        return None, None, None
    raw = str(injury).strip().lower()
    if not raw:
        return None, None, None
    key = INJURY_ALIASES.get(raw)
    if key is None:                       # try the longest phrase that appears
        hits = [(len(a), k) for a, k in INJURY_ALIASES.items() if a in raw]
        key = max(hits)[1] if hits else "other"
    row = INJURY_RECOVERY.get(key, INJURY_RECOVERY["other"])
    g = float(row.get("pos", {}).get(str(pos).upper(), row["games"]))
    return g, float(row["weeks"]), str(row["label"])


# ---------------------------------------------------------------------------
# HOW RISKY, NOT HOW MANY GAMES
# ---------------------------------------------------------------------------
# This fit used to set proj_games for every player on the board and it does not
# any more -- see the rule at the top of the file. It is kept, unchanged, because
# it is genuinely accurate and because "this man's body has a history" is real
# information that belongs somewhere. It just belongs in the risk column.
#
#     games_a_body_like_this_lasts
#         = intercept + a * (games a season over his last 3 / 17) + b * (job size)
#
# where job size is 0 to 1 -- a back's carries per game over 18, a quarterback's
# throws per game over 32. Fitted on 2019-2023 and checked on 2024-2025, which
# the fit never saw, over players already carrying the career games each board
# requires (6 for backs, 8 for passers). Average games missed:
#
#                                  backs   quarterbacks
#     3 years of games + job        3.92       3.38     <- this one
#     last year's games + job       3.97       3.67
#     last year's games alone       4.11       3.72
#     one flat average              4.82       5.15
#     "everybody plays 17"          5.56       7.89
#
# Reading three seasons instead of one is the whole ballgame at quarterback, and
# it is there to stop the model doing something plainly unfair. One season is a
# very small sample to judge a body on. Read only the most recent one and a
# quarterback who started 17 games twice and then broke a toe is filed next to a
# man who has never been healthy -- they both "played 9 games last year." Among
# passers who played 11 or fewer, the ones with a strong three-year record came
# back for 10.8 games; the ones without came back for 5.1.
#
# The job-size term fixes a second confusion. "Played 11 games" describes both a
# starter who missed six weeks hurt and a backup who got six weeks of mop-up
# duty. Among backs who played 11 or fewer, the ones carrying a real load when
# active came back for 11.1 games; the ones who were never more than a backup
# came back for 7.9. Without it everyone in that bucket gets the same number and
# the hurt starter eats the backup's discount.
#
# Note what the top of the range says: a full season last year does NOT predict a
# full season this year, it predicts about 14.7, because almost nobody repeats it
# (11.7% of backs, 12.5% of passers). That is why RISK_CEILING below is 15 and
# not 17 -- being as available as it is possible to be should score as no risk,
# not as slightly risky.
#
# Receivers were fitted the same way and they need their own line, not the backs'.
# Job size is targets per game over 9 -- an alpha's load. Fitted on 757 receiver
# seasons in 2019-2023 and checked on the 329 in 2024-2025 the fit never saw, over
# receivers already carrying the board's 8 career games. Average games missed:
#
#     3 years of games + job    3.82     <- this one
#     3 years of games alone    3.95
#     one flat average          4.51
#     "everybody plays 17"      5.39
#
# Falling back to the backs' line here was doing real damage. It carries a bigger
# job term than the receivers' does, and nothing on the receiver frame was filling
# `job` in at all, so every receiver was priced as though he had no role. The best
# a perfectly healthy one could reach was 12.5 games -- a 0.36 risk, above the
# "misses games most years" bar -- and 110 of 128 receivers wore that chip,
# including four projected for all 17. A warning that fires on 86% of a board is
# not a warning.
#
# Receivers are also plainly more durable than backs, which the line now says: on
# a near-perfect three-year record a receiver comes back for 14.4 games and
# repeats 17 in 37% of cases, against 11.7% for backs.
#
#                  intercept  3yr avail   job
BASE_FIT = {"RB": (3.66, 8.80, 2.77),
            "QB": (0.56, 13.08, 1.18),
            "WR": (4.18, 7.96, 3.45)}
BASE_DEFAULT = (3.66, 8.80, 2.77)
BASE_MIN, BASE_MAX = 4.0, 17.0

# Where the risk scale starts and ends. 15 games is as durable as anybody gets
# (see above); 8 is a man who has spent half of every year hurt.
RISK_CEILING, RISK_FLOOR = 15.0, 8.0

# A rookie has no games played, so the line above has nothing to read. Feeding it
# a zero would price every first-year player as a career injury risk, which is
# exactly backwards -- measured over 2019-2025, a rookie who actually got a job
# played MORE than a veteran coming off a full season:
#
#     rookie backs with 50+ carries       n=79   13.8 games   (median 15)
#     rookie passers with 100+ attempts   n=44   10.8 games   (median 10)
#     rookie receivers with 30+ targets   n=115  14.7 games   (median 15)
#
# which makes sense. They are the freshest bodies in the league, and the reason
# they got the job in the first place is usually that they were available for it.
# The receivers are the most available of the three, and by some distance.
ROOKIE_GAMES = {"RB": 13.5, "QB": 10.5, "WR": 14.5}
ROOKIE_DEFAULT = 13.5

_HAND: dict[str, dict] = {}
_GUIDE: dict[str, dict] = {}


def history_games(avail3, pos: str = "RB", job=None) -> float:
    """How many games a body with this history normally lasts.

    NOT the projection -- see the rule at the top of the file. This feeds the
    risk column only. `avail3` is games a season over his last three divided by
    17; `job` is how big last season's workload was, 0 to 1. A missing `avail3`
    means no NFL season behind him at all -- see ROOKIE_GAMES.
    """
    pos = str(pos).upper()
    if avail3 is None or pd.isna(avail3):
        return float(ROOKIE_GAMES.get(pos, ROOKIE_DEFAULT))
    b0, b1, b2 = BASE_FIT.get(pos, BASE_DEFAULT)
    j = 0.0 if job is None or pd.isna(job) else float(np.clip(job, 0.0, 1.0))
    return float(np.clip(b0 + b1 * np.clip(float(avail3), 0.0, 1.0) + b2 * j,
                         BASE_MIN, BASE_MAX))


def durability_risk(hist_games) -> float:
    """0 to 1, where 1 is a player whose availability record is a real worry."""
    if hist_games is None or pd.isna(hist_games):
        return 0.0
    span = max(RISK_CEILING - RISK_FLOOR, 1e-6)
    return float(np.clip((RISK_CEILING - float(hist_games)) / span, 0.0, 1.0))


# ---------------------------------------------------------------------------
# DURABILITY -- how much of a season this body has been good for
# ---------------------------------------------------------------------------
# This used to be last season alone, on the argument that fresh news should move
# a rank faster than a mean does. That argument was right about the direction
# and wrong about the size. One season is seventeen games, and a single broken
# bone in it wipes out a quarter of a player's Availability score no matter what
# the two years either side of it say -- CeeDee Lamb played 13, 15 and 17 and
# was being scored as though 13 were the whole story.
#
# So it is three years now, weighted toward the recent one rather than averaged
# flat, which keeps most of what the old argument wanted:
#
#     last season          0.50     <- still half the vote, so news still moves
#     the season before    0.30
#     three years back     0.20
#
# Missing years are dropped and the rest re-weighted, so a second-year player is
# scored on the one season he has rather than punished for not having three.
DUR_WEIGHTS = (0.50, 0.30, 0.20)


def durability(games_recent_first) -> float:
    """Share of a season this player has been available for, 0 to 1.

    Takes games played in each of the last three seasons, MOST RECENT FIRST.
    """
    if games_recent_first is None:
        return float("nan")
    vals, wts = [], []
    for g, w in zip(list(games_recent_first)[:len(DUR_WEIGHTS)], DUR_WEIGHTS):
        if g is None or pd.isna(g):
            continue
        vals.append(float(g))
        wts.append(w)
    if not vals:
        return float("nan")
    return float(np.clip(np.average(vals, weights=wts) / SEASON_WEEKS, 0.0, 1.0))


def clear_cache() -> None:
    """Forget both files. Only needed by tests and weight sweeps."""
    _HAND.clear()
    _GUIDE.clear()


def hand_notes(pos: str) -> dict:
    """{normalized name: dict} from data/<pos>_availability.csv.

    `player` is the only required column. Everything else is optional and any
    combination is legal: a games count, an injury, the week you think he's back,
    a note. They get mixed rather than ranked -- see resolve().
    """
    pos = str(pos).lower()
    if pos in _HAND:
        return _HAND[pos]
    out: dict = {}
    _HAND[pos] = out
    try:
        path = config.DATA_DIR / f"{pos}_availability.csv"
        if not path.exists():
            return out
        from .adp import norm

        df = pd.read_csv(path, comment="#")
        if "player" not in df.columns:
            return out
        blank = pd.Series([np.nan] * len(df), index=df.index)
        gms = (pd.to_numeric(df["expected_games"], errors="coerce")
               if "expected_games" in df.columns else blank)
        bwk = (pd.to_numeric(df["back_week"], errors="coerce")
               if "back_week" in df.columns else blank)
        inj = df["injury"] if "injury" in df.columns else blank
        notes = (df["note"] if "note" in df.columns
                 else pd.Series([""] * len(df), index=df.index))
        for name, g, w, ij, note in zip(df["player"], gms, bwk, inj, notes):
            if not str(name).strip():
                continue
            if pd.isna(g) and pd.isna(w) and (pd.isna(ij) or not str(ij).strip()):
                continue                      # a row that says nothing
            out[norm(str(name))] = {
                "games": None if pd.isna(g) else float(np.clip(g, 0.0, 17.0)),
                "back_week": None if pd.isna(w) else float(np.clip(w, 1.0, 18.0)),
                "injury": None if pd.isna(ij) else str(ij).strip(),
                "note": "" if pd.isna(note) else str(note).strip(),
            }
    except Exception:      # noqa: BLE001 -- an outside file must never fail a build
        pass
    return out


def guide_ranks(pos: str) -> dict:
    """{player_id: {"rank": float, "games": float}} from the guide CSV."""
    pos = str(pos).lower()
    if pos in _GUIDE:
        return _GUIDE[pos]
    out: dict = {}
    _GUIDE[pos] = out
    try:
        path = config.DATA_DIR / f"clay_{pos}_{config.UPCOMING_SEASON}.csv"
        if not path.exists():
            return out
        df = pd.read_csv(path)
        if not {"player_id", "clay_rank", "clay_games"}.issubset(df.columns):
            return out
        for row in df.to_dict("records"):
            out[str(row["player_id"])] = {"rank": float(row["clay_rank"]),
                                          "games": float(row["clay_games"])}
    except Exception:      # noqa: BLE001
        pass
    return out


def ratio(expected: float | None, news_w: float, floor: float) -> float:
    """Turn "we think he plays N games" into a multiplier on his season value.

    news_w is 1.0 everywhere today, i.e. the number goes in at face value. The
    dial survives because it is the honest place to turn a source down if one
    ever earns it -- see the long note above NEWS_W in rb_blend.py for why
    hedging a stated games count is the wrong instinct.
    """
    if expected is None or pd.isna(expected):
        return 1.0
    return float(np.clip(1.0 - news_w * (1.0 - float(expected) / 17.0), floor, 1.0))


# How much each source counts when more than one of them speaks. These are not
# fitted -- there is nothing to fit them on, since two of the three sources are
# published once a year by people rather than measured. They are an ordering, and
# the ordering is the argument:
#
#   you (3)      you are reading this week's news and the other two are not.
#   injury (2)   what players actually did after this injury, from the studies
#                cited in INJURY_RECOVERY. Beats a guide because it is measured,
#                loses to you because it is an average and you can see the man.
#   guide (1)    one analyst's preseason estimate, useful and directional and
#                the only one of the three with no evidence behind it at all.
#
# Only sources that actually SAY something get a vote, so a guide with him down
# for a full season never dilutes an injury you typed. And note the guide is the
# only one that can be outvoted -- if you type a number it wins the average
# outright unless the injury table disagrees, which is the point.
SOURCE_W = {"hand": 3.0, "injury": 2.0, "guide": 1.0}


def resolve(pos: str, player_id, name: str, is_upcoming: bool,
            news_w: float, floor: float) -> dict:
    """One player's availability: guide rank, expected games, ratio, and why.

    The three sources get MIXED, weighted by SOURCE_W. Nobody with nothing said
    about him leaves here on anything other than a full season.
    """
    from .adp import norm

    g = guide_ranks(pos).get(str(player_id)) if is_upcoming else None
    out = {"clay_rank": g["rank"] if g else np.nan,
           "clay_games": g["games"] if g else np.nan,
           "news_games": np.nan, "games_ratio": 1.0, "games_note": "",
           "injury": "", "injury_risk": 0.0, "cleared": False}
    if not is_upcoming:
        return out

    vals: list[float] = []
    wts: list[float] = []
    why: list[str] = []
    mine = hand_notes(pos).get(norm(str(name))) or {}

    # WEEK ONE IS A DIFFERENT KIND OF STATEMENT FROM ANY OTHER WEEK. Every other
    # back_week is your estimate of a date that has not happened yet, and the
    # injury table is entitled to argue with it. "Back for week one" is not an
    # estimate -- it is a thing you can see: off the PUP list, taking first-team
    # reps, no restriction. The table exists to guess that outcome, so once the
    # outcome is visible the table has nothing left to say and he keeps all
    # seventeen games. The injury is still recorded; it just goes where "cleared,
    # but it was an ACL in December" actually belongs, which is the risk column.
    cleared = mine.get("back_week") == 1.0
    out["cleared"] = bool(cleared)

    # 1. YOU. A games count and a week-he's-back are both direct statements, so
    #    if you gave both they average at your weight rather than fighting.
    yours = [v for v in (mine.get("games"),
                         (SEASON_WEEKS - (mine["back_week"] - 1.0)
                          if mine.get("back_week") else None)) if v is not None]
    if yours:
        vals.append(float(np.mean(yours)))
        wts.append(SOURCE_W["hand"])

    # 2. THE INJURY HE IS CARRYING. Always sets the risk score and the label. It
    #    only moves his GAMES if he is not already cleared to play.
    ig, iw, ilabel = injury_games(mine.get("injury"), pos)
    if ig is not None:
        out["injury"] = ilabel
        risk = float(np.clip(float(iw) / INJURY_RISK_WEEKS, 0.0, 1.0))
        out["injury_risk"] = risk * CLEARED_RISK if cleared else risk
        if not cleared:
            vals.append(ig)
            wts.append(SOURCE_W["injury"])
            why.append(f"coming off a {ilabel}")

    # 3. THE GUIDE -- news only, never a depth-chart statement, and never over
    #    the top of a man you have watched practise.
    if g is not None and GUIDE_FLOOR <= g["games"] < 17 and not cleared:
        vals.append(float(g["games"]))
        wts.append(SOURCE_W["guide"])
        why.append(f"the guide has him down for {int(round(g['games']))}")

    exp = np.nan
    if vals:
        exp = float(np.clip(np.average(vals, weights=wts), 0.0, 17.0))

    r = ratio(exp, news_w, floor)
    out["news_games"] = exp
    out["games_ratio"] = r
    if r < 1.0:                                   # a full slate isn't news
        hand_note = str(mine.get("note") or "").strip()
        out["games_note"] = hand_note or ", ".join(why)
    return out


def attach(p: pd.DataFrame, pos: str, news_w: float = 1.0,
           floor: float = 0.35) -> pd.DataFrame:
    """Add clay_rank / clay_games / games_ratio / games_note / proj_games,
    plus the two risk columns avail_games and avail_risk.

    Four columns come out of here doing three different jobs, which is worth
    being precise about because mixing them up double-counts a player's health.

    `games_ratio` is NEWS ONLY -- 1.0 for everyone nobody has reported anything
    about. It is what the Availability index multiplies by, and that index
    already has last season's games in it, so putting a history-based number here
    too would charge a player twice for the same missed time.

    `proj_games` is how many games the board expects, and it is the one that
    turns a per-game rate into a season. SEVENTEEN for everybody unless something
    specific was reported. Completed seasons always keep a full slate so the
    backtest still scores this model on the information it always had.

    `avail_games` and `avail_risk` are the history: how long a body like his
    normally lasts, and that expressed as a 0-to-1 worry score. They move his
    RISK rating and nothing else -- see the rule at the top of the file.

    `injury_risk` is the fifth, and it is the one that stops a cleared player
    reading as a healthy one. A man who tore an ACL in December and is taking
    every rep in August gets all seventeen games -- there is nothing to dock --
    but he is not the same bet as a man who never got hurt, and this is where
    that difference lives.
    """
    if p.empty:
        return p
    up = pd.to_numeric(p["season"], errors="coerce") == config.UPCOMING_SEASON
    rows = [resolve(pos, pid, nm, bool(u), news_w, floor)
            for pid, nm, u in zip(p["player_id"], p["player_name"], up)]
    for col, typ in (("clay_rank", float), ("clay_games", float),
                     ("news_games", float), ("games_ratio", float),
                     ("games_note", object), ("injury", object),
                     ("injury_risk", float), ("cleared", bool)):
        p[col] = pd.Series([r[col] for r in rows], index=p.index, dtype=typ)

    # A full season until something says otherwise. `news_games` is the mixed
    # number from resolve() and is NaN for everyone nobody has reported on.
    p["proj_games"] = [
        float(np.clip(n, 0.0, 17.0)) if (u and pd.notna(n)) else 17.0
        for u, n in zip(up, p["news_games"])
    ]

    # Three seasons of availability, not one. `durability` is last year only and
    # is left alone deliberately -- it does a different job in the Availability
    # index, where recency is the point.
    if "prev_games3" in p.columns:
        av3 = pd.to_numeric(p["prev_games3"], errors="coerce") / 17.0
    elif "durability" in p.columns:
        av3 = pd.to_numeric(p["durability"], errors="coerce")
    else:
        av3 = pd.Series(np.nan, index=p.index)
    job = (p["prev_role"] if "prev_role" in p.columns
           else pd.Series(np.nan, index=p.index))
    hist = [history_games(d, pos, j) for d, j in zip(av3, job)]
    p["avail_games"] = [round(h, 1) for h in hist]
    p["avail_risk"] = [durability_risk(h) for h in hist]
    return p
