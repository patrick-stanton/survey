# Prioritizing Our Use Cases — How It Works

**The goal.** We have ~50–70 use cases in our Cameo model and limited capacity to
build them. We need a prioritization that is *trustworthy* — one we can defend to
leadership and revisit as our understanding evolves — gathered from many
stakeholders without booking everyone into interviews.

**The problem with the obvious approaches.** Asking someone to rank 60 items by
hand is slow and produces unreliable orderings past the first few. Asking people
to rate each use case 1–5 just yields a wall of 4s and 5s. Both fail exactly when
the list is long, which is our situation.

**What we do instead: quick best/worst choices.** Each respondent gets a web
survey (a single file — no install, no server, works on a locked-down machine).
On each screen they see **four** use cases and make two fast taps: the **most**
important and the **least** important. That's it. A screen takes about twenty
seconds, and a respondent can stop whenever they want — every screen they finish
is usable, so a half-finished survey still helps. They choose a time budget up
front: about ten minutes covers all the use cases once; about an hour covers each
one three times and produces a personal profile.

**Why four-at-a-time is powerful.** When someone says "A is best and D is worst"
out of {A, B, C, D}, they've told us more than one fact — they've told us A beats
B, A beats C, A beats D, B beats D, and C beats D. **One screen implies five
head-to-head comparisons.** That is five times the information of a single "which
of these two?" question, which is what makes the method work even with a handful
of respondents.

**Turning choices into a ranking.** We pool every screen from everyone — collected
over days or weeks, it all combines — and compute the ranking three independent
ways: a transparent **count** (how often each use case was picked best minus
worst, which anyone can re-check in Excel), an **election-style majority** tally
(was A preferred over B by most people?), and a **statistical choice model** (the
same class of model behind chess ratings, which handles sparse and uneven
participation cleanly). When all three agree, we're confident. The few use cases
where they *disagree* are flagged for discussion rather than quietly averaged.

**Being honest about certainty.** The tool doesn't just emit a rank number. By
resampling our respondents thousands of times it reports, for each use case, a
**90% rank range** and the **probability it belongs in the top 10**. This is the
difference between "#1 by a hair in a noisy average" and "securely the top
priority" — and it tells us when we simply need more responses before deciding.

**Seeing it from different angles.** Because every response is tied to a named
respondent, we can view the same data through **lenses** (grouping respondents
by role or organization from our invite list): do operators and maintainers
agree? Where do organizations diverge? Contested use cases become deliberate
conversations, not statistical noise.

**Where it lands.** Results flow back onto the use cases in our Cameo model —
each one carrying its score, rank, confidence range, and how many people weighed
in. When we commit to building the top-ranked capability, we can show it is
genuinely separated from the alternatives, backed by a method drawn from
established preference-measurement science and an audit trail from raw answer to
final number.

---
*Method basis: best–worst scaling / MaxDiff (Louviere; Sawtooth Software) ·
Bradley–Terry choice model (Maystre & Grossglauser, NeurIPS 2015) · respondent
bootstrap for uncertainty. Full detail in the system design report.*
