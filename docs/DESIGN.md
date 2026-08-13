# Use-Case Prioritization System — Design & Trade Study

**Purpose.** This document details the design of the use-case prioritization
system, the alternatives considered at each decision point, why each choice was
made, and how the whole pipeline enables us to select the right capabilities to
build. It is the authoritative technical companion to the one-page summary
([ONE_PAGER.md](ONE_PAGER.md)) and the methods reference
([../METHODOLOGY.md](../METHODOLOGY.md)).

---

## 1. Problem statement and goal

We maintain 50–70 use cases (function-like elements with a custom stereotype) in
a Cameo Systems Modeler 2026x model. To direct limited development capacity we
need a **prioritization of those use cases** that is:

- **Nuanced** — reflecting genuine stakeholder preference, not a show of hands.
- **Asynchronous & low-friction** — gathered from up to ~200 people without
  scheduling interviews, on a restricted corporate network.
- **Adaptable** — respondents give as little as ten or as much as sixty minutes;
  use cases can be reworded, merged, or added between rounds.
- **Defensible** — grounded in established method, reproducible from raw data,
  and honest about uncertainty.
- **Multi-perspective** — viewable through "lenses" (role, organization — when
  those are collected) so we see agreement and conflict, not just an average.

The operating decision this serves is blunt: **however we rank them, we intend to
build the top-ranked capability next.** That raises the stakes on two things the
design treats as first-class — being *right about the ordering at the top*, and
being *honest about how sure we are*.

---

## 2. Pipeline overview

```
  Cameo model
      │  export (generic table → CSV)
      ▼
  use_cases.csv ──► build_survey.py ──► survey.html   (one self-contained file)
                                            │  distributed by email / SharePoint
                                            ▼
                                     respondents answer  (10–60 min, abort-safe)
                                            │  "Send Your Results" → email + .csv attached
                                            ▼
   pull_email.py / manual ──► data/inbox/ ──► ingest.py ──► data/archive/  (append-only)
                                                                │  pooled across all rounds
                                                                ▼
                                                           resolve.py
                                                                │
                          ┌─────────────────────────────────────┼───────────────────────┐
                          ▼                                     ▼                          ▼
              use_cases_enriched.csv                   resolve_report.txt          (raw archive
              (scores, ranks, CIs) ──► Cameo             (lenses, conflicts,          = audit trail)
                                                          coverage, quality)
```

Each stage is a separate, independently runnable step. Nothing depends on a
server, a database, or network access beyond the operator's own mailbox.

---

## 3. Decision: how to elicit preference

### Options considered

| Option | How it works | Verdict |
|---|---|---|
| **Direct ranking** | Drag 60 items into order | Rejected — unreliable past ~7 items, slow, high abandonment |
| **Rating scales** | Rate each use case 1–5 | Rejected — scale-use bias (everything is a 4–5); ratings not comparable across people |
| **Pairwise voting** | "Which of these two matters more?" | Viable but weak — 1 comparison per screen; needs far more responses than we'll get from small panels |
| **Best-worst scaling (MaxDiff)** ✓ | Pick most & least important of 4 | **Chosen** — 5 comparisons per screen; fatigue-resistant; every screen is self-contained data |

### Why best-worst scaling

Best-worst scaling (a.k.a. MaxDiff) is the market-research standard for
prioritizing large item lists (Louviere; Sawtooth Software). Three properties
decide it for us:

1. **Information density.** A best/worst answer over four items *logically
   implies five pairwise preferences* (best beats the other three; the two
   middles beat worst). With only 5–200 respondents, that 5× density is the
   difference between a defensible ranking and a mushy one.
2. **Abort resilience.** Each screen is a complete, independent observation, so a
   respondent who quits after six screens still contributed six usable data
   points. This is what lets us promise "stop anytime — your answers still count"
   and mean it.
3. **Fatigue resistance.** Published research (Bansak et al., *Political
   Analysis*) shows answer quality on repeated choice tasks stays flat through
   30+ screens — unlike rating grids, which degrade quickly.

### Sizing the time budgets

- **~10-minute arm:** each use case shown once (≈15 screens at 60 items). This is
  a *sparse* design — it yields reliable **group-level** data but not individual
  profiles. Sawtooth's research favors sparse-everyone-sees-all over
  random-subsets for 50+ item lists.
- **~60-minute arm:** each use case shown three times (≈45 screens), the accepted
  floor for **individual-level** estimates, extendable to 5× in optional
  keep-going blocks.

### Design balance (why the questions are fair)

A naive random selection would show some use cases more than others and pair some
combinations more than others, biasing the result. The build step constructs a
**balanced design**: every use case appears equally often (±1), every pair of
use cases co-appears about equally, positions are rotated, and categories are
mixed across each screen. An exact "balanced incomplete block design" doesn't
exist at arbitrary catalog sizes, so we use the industry-standard near-balanced
construction (round-robin deal + pairwise-balance hill-climb, per Sawtooth /
Displayr). Each respondent receives a personally shuffled variant so that
position effects wash out and early exits are item-neutral.

---

## 4. Decision: delivery mechanism (no server)

The survey is a **single self-contained HTML file** — all logic and data inline,
zero external requests, runs from a double-click on a locked-down machine. This
was chosen over a hosted web app or an internal server because:

- It clears the network-restriction bar trivially: nothing to host, nothing to
  get through IT, no data leaving the browser until the respondent chooses to
  send it.
- It is auditable: one file, no moving backend, no database of record beyond the
  files respondents return.

**Trade accepted:** without a backend there is no central collection point, so
returns must be gathered from email/SharePoint. We mitigate the friction of that
in Section 5. See [DEPLOYMENT_OPTIONS.md](DEPLOYMENT_OPTIONS.md) for the full
menu of ways to host/distribute the file and their trade-offs.

---

## 5. Decision: getting results back

### The compact-code insight

A respondent's entire session is *reconstructable* from a tiny seed (their
identity + which time budget + the survey build), because the survey layout is
derived deterministically. This means we don't need to send back the full data —
only the **picks**, which compress to two bytes per screen. A whole session fits
in a short text code that lives **in the email body itself**.

**What we ship instead.** The compact code is retained on the *reading* side
(`ingest.py` still decodes legacy `UCS1` codes) but is no longer what respondents
send. The **"Send Your Results"** button downloads the legible results `.csv` and
opens the respondent's own mail client, pre-addressed to us (an address we set at
build time), with a body that says only ATTACH .CSV THAT DOWNLOADED TO EMAIL plus
a prompt for their own comments. They attach the file and press Send.

**Why the file rather than the body:** a `mailto:` body is subject to
mail-client length limits that vary by tenant and version, and a truncated body
is a lost response. An attachment has no such limit, and the body stays ~230
characters no matter how long the session ran. The cost is one drag-and-drop,
which the finish screen and the email both call out in capitals.

### Return paths (all funnel to the same archive)

| Path | Respondent does | We do |
|---|---|---|
| **Email + attachment** ✓ | Presses "Send Your Results", attaches the `.csv`, presses Send | `pull_email.py` saves attachments (IMAP), or save them by hand |
| **Download file** | Clicks "Download results file" | Drop the file into the inbox folder |

`ingest.py` accepts all forms interchangeably. See
[DEPLOYMENT_OPTIONS.md](DEPLOYMENT_OPTIONS.md) §"Getting data back" for the
trade-offs among these and smarter alternatives (shared mailbox, SharePoint drop).

**Trade accepted:** compact codes are decodable only against the exact survey
build they came from — guarded by an embedded design fingerprint. The full
downloaded `.json` remains the archival format and works regardless of build.

---

## 6. Decision: pooling and integrity

- **Unit of observation is one completed screen**, so partial sessions pool with
  complete ones with no special handling and no minimum-completion threshold.
- **Rolling collection:** the archive is append-only; every `resolve` run
  recomputes from the *entire* pool. Five interviews today and ten tomorrow
  simply combine.
- **De-duplication:** a resubmitted session replaces its earlier, shorter copy;
  multiple sessions from one person merge as one respondent for weighting.
- **Catalog drift:** every response carries a fingerprint of the exact wording the
  respondent saw. Reword freely — ingest flags mismatches and you decide whether
  old answers still apply. Merge or replace use cases via a `supersedes` column,
  then choose at analysis time whether predecessor votes carry forward
  (`--lineage inherit`) or not (`strict`). **Raw answers are never rewritten** —
  the mapping is applied at analysis time and recorded in the outputs.
- **Determinism:** resolution is a pure function of (archive, config, seeds), so
  any published number regenerates exactly — the backbone of "auditable."

---

## 7. Decision: how to resolve rankings ("profiles")

Different audiences trust different arguments, so we compute the ranking several
ways and *report where they disagree* rather than hiding it behind one number.

| Profile | Method | Role | Trade |
|---|---|---|---|
| **P1 Counts** | Exposure-normalized best-minus-worst, each person weighted equally, 0–100 | **Headline** — anyone can re-check it in a spreadsheet | Descriptive, not model-based |
| **P2 Copeland** | Majority head-to-head wins; Schulze tie-break | Election logic a review board already trusts | Ties on sparse data |
| **P3 Bradley-Terry** | Maximum-likelihood choice model (chess-rating family), pooled + per-person-equalized | Statistical backbone; ratio-scaled | Needs regularization at small n |
| **P4 Bayesian BT** | Posterior over utilities | "We're X% sure A outranks B" | Requires optional library |
| **P5 Bootstrap** | Resample respondents 2000×; 90% rank ranges, P(top-10); group agreement | **The honesty layer** | Wide intervals at small n — by design |

### Methods deliberately excluded (and why)

- **Mean rating / rank averaging** — scale bias; means incomparable across
  different item subsets. P1 is the sound version of the averaging instinct.
- **Instant-runoff (ranked-choice)** — single-winner, discards information; can't
  produce a defensible 60-item scale. P2 is the sound version of the voting
  instinct.
- **Exact Kemeny-Young** — NP-hard; unreliable at this item count.
- **Hierarchical Bayes** — the gold standard *above* ~100–150 respondents; below
  that its population parameters are unidentifiable. P3+P5 deliver the defensible
  subset of its value at our scale. (Revisit if a single round exceeds ~150.)

Documenting the exclusions is itself part of defensibility: it shows the method
set was chosen against the alternatives, not by default.

### Robustness to bad actors and thin data

Each person is weighted equally regardless of how many screens they answered, so
one enthusiast cannot dominate; the model is run both pooled and
respondent-equalized and discrepancies are reported. Suspiciously fast responders
(median under 2 s/screen) are flagged, never silently dropped. Under-observed use
cases are called out, and every published ranking carries its confidence
interval, so thin data shows up as *wide ranges*, never false precision.

---

## 8. The lenses — prioritization from multiple perspectives

The results format carries role and organization fields (the streamlined survey
leaves them blank — it asks only name and email — but they can be filled from an
invite roster or a future build), so the same pooled data yields multiple views:

- **Overall ranking** — the primary priority order with confidence intervals.
- **By role** (operators vs. maintainers vs. engineers…) and **by organization** —
  each group's ranking, plus formal agreement measures (Kendall's τ and W,
  top-10 overlap) between groups.
- **Contested items** — the use cases where groups or methods most disagree,
  surfaced explicitly as discussion items for facilitated resolution.

This is what turns a single number into a decision aid: leadership sees not only
*what* ranks first but *who* wants it and *how much consensus* stands behind it.

---

## 9. How this enables building the right capability

The chain from stakeholder to decision is:

1. Stakeholders express preference through many small, low-effort, fatigue-
   resistant choices — capturing nuance a headcount vote cannot.
2. Those choices pool into a ranking computed three independent, established ways,
   with cross-method agreement as the confidence signal.
3. Uncertainty is quantified, so we can distinguish a **secure #1** from a
   statistical tie that needs more data before we commit.
4. Lenses expose whether the top priority is broadly shared or a single group's
   preference — informing not just *what* to build but *how to socialize it*.
5. The result lands back in the Cameo model against the actual use cases, with a
   full audit trail from raw answer to final rank.

When we then commit to the top-ranked capability, we can state — and defend — that
it is the priority most preferred across our stakeholders, by a margin the data
supports, using a method drawn from established preference-measurement science.

---

## 10. Risks and mitigations (summary)

| Risk | Mitigation |
|---|---|
| Small panels → thin per-item data | Bootstrap intervals make thinness visible; long arm pushes exposure to 3–5× |
| A few careless/random responses | Equal per-person weighting; response-time flags; sensitivity re-runs |
| Catalog changes mid-collection | Wording fingerprint + explicit lineage modes; raw data immutable |
| Corporate email blocks the survey | Distribute as `.zip`/SharePoint link; results return as in-body codes |
| Method disagreement | Reported, not hidden; contested items become discussion agenda |
| Over-reaching on statistics | Closed, documented method set; excludes methods that mislead at our scale |

---

*References for every method and mechanism are collected in
[../METHODOLOGY.md](../METHODOLOGY.md). Operating instructions are in
[../README.md](../README.md).*
