# Methodology

Why this tool asks what it asks, and how the numbers are computed. Every
choice below follows published practice; sources at the end.

## Why best/worst screens (MaxDiff)?

Asking anyone to hand-rank 50–70 items produces unreliable orderings and
takes far too long; rating scales suffer scale-use bias ("everything is a 5").
Best-worst scaling — show ~4 items, pick the most and least important, repeat
with varied sets — is the market-research standard for prioritizing large
item lists (Louviere's BWS; Sawtooth Software's MaxDiff):

- Each answered screen implies **2k−3 = 5 pairwise preferences** (best beats
  the other 3; the 2 middles beat worst) — five times the information of a
  single "which of these two?" vote, decisive at small sample sizes.
- Every screen is a **self-contained observation**, so a respondent who quits
  after 6 screens still contributed 6 usable data points (the tool's
  abort-resilience rests on this).
- Choice tasks resist fatigue: Bansak et al. found answer quality flat through
  30+ consecutive choice tasks. We still insert break screens every 12 and
  keep the short arm well inside attention limits.

**Screen size 4** follows Sawtooth guidance (4–5 optimal, never more than half
the item count). **Time budgets**: the ~10-minute arm is a *Sparse MaxDiff* —
each item shown once per person (ceil(K/4) screens ≈ 15 at K=60), which
Sawtooth's simulations favor over per-person subsets for 50+ items; it yields
group-level data only. The ~30–60-minute arm shows each item 3× (≈45 screens),
the accepted floor for individual-level estimates, extendable to 5× in
optional keep-going blocks.

**Design balance**: every item appears equally often (±1) and pairs of items
co-appear near-equally (hill-climbed two-way balance), with a penalty that
mixes categories on each screen. An exact balanced incomplete block design
does not exist at arbitrary K; near-balance is the industry approach. Each
respondent gets a personal variant via a seeded permutation of item labels
plus screen-order shuffle — preserving balance, decorrelating position
effects, and making early aborts item-neutral. The browser's derivation is
bit-identical to the Python mirror (verified in tests), so analyses can
reconstruct exactly what any respondent saw.

## The resolution profiles

Different audiences trust different arguments, so resolve.py computes several
"lenses" over the same raw answers and reports where they disagree instead of
hiding it.

| Profile | Method | The defensibility story |
|---|---|---|
| **P1 counts** | Per respondent: (times best − times worst) ÷ times shown, then averaged with each **person weighted equally**; rescaled 0–100 | Anyone can recheck it from the raw files in a spreadsheet. Exposure normalization makes aborted sessions unbiased; per-person weighting stops one enthusiast from outvoting five colleagues. Tracks logit utilities almost linearly on balanced designs (Orme). |
| **P2 Copeland** | Explode screens into pairwise wins, count majority head-to-head victories minus losses; Schulze beatpath breaks ties/cycles | Election logic: "a majority preferred A over B." No statistical model to defend in a review board. |
| **P3 Bradley-Terry** | Maximum-likelihood strengths s.t. P(i beats j) = πᵢ/(πᵢ+πⱼ), on the exploded pairs, with regularization α; reported as 0–100 preference shares, in pooled and per-person-equalized variants | The standard probabilistic choice model (chess Elo's ancestor). Pools sparse, unequal-length sessions into one ratio-scaled ranking — "twice the share" means twice the preference weight. Uses `choix` (I-LSR, Maystre & Grossglauser) when installed; otherwise the bundled Hunter-MM fit, tested to agree with choix. |
| **P4 Bayesian BT** | `choix.ep_pairwise` posterior → credible intervals, P(A outranks B) | Honest probability statements at small n, without the ~100+ respondents a hierarchical Bayes model needs to be identifiable. Skipped (with notice) if choix is absent. |
| **P5 bootstrap** | Resample **respondents** with replacement (cluster bootstrap, fixed seed), recompute P1 and P3 each time → 90% rank intervals and P(top-10) per item; plus Kendall τ-b / Kendall's W / top-10 overlap between stakeholder groups | Answers the question leadership actually asks: *which items are securely top-tier vs statistically interchangeable*. Assumption-light; makes small samples visible (intervals labeled indicative at n≤10) instead of feigning precision. |

The enriched CSV carries P1 as the headline (with its bootstrap interval),
P2 and P3 as cross-checks, and a `consensus_flag` marking items where methods
diverge by >10 ranks or stakeholder groups conflict — those are agenda items
for discussion, not numbers to average away.

## Methods deliberately excluded

- **Mean rating / rank averaging** — scale-use bias, treats ordinal as
  interval, and means aren't comparable when respondents saw different
  subsets (which our adaptive budgets guarantee). P1's normalized counting is
  the sound version of this instinct.
- **Instant-runoff / ranked-choice (IRV)** — a single-winner election method:
  discards most ballot information, non-monotonic, and cannot produce a
  defensible 70-item priority scale. P2's Condorcet layer is the sound version
  of the voting instinct.
- **Exact Kemeny-Young** — NP-hard; exact solvers become unreliable well
  below 50–70 items.
- **Hierarchical Bayes** — the commercial gold standard *above* ~100–150
  respondents; below that the population covariance is unidentifiable and
  results depend on priors. P3+P5 deliver the defensible subset of its value
  at this scale. Revisit only if a single collection round exceeds ~150
  respondents.
- **Borda on truncated rankings** — rewards bullet-voting on partial data.

## Data integrity rules

- `data/archive/` is **append-only**; an answer, once ingested, is never
  edited. Resolution is a pure function of (archive, config, seeds) — same
  inputs, same outputs, so any published number can be regenerated.
- Every response file carries the **catalog hash** of the exact wording the
  respondent saw; ingest refuses mismatched files unless explicitly allowed.
- Use-case merges/renames are declared in the CSV (`supersedes`) and applied
  only at resolve time (`--lineage strict|inherit`), keeping raw data intact
  and the mapping decision explicit in the outputs.
- Respondents with median answer times under 2 s/screen are flagged in the
  report (never silently dropped); random answering is statistically
  detectable only at ≥3× exposure, another reason the short arm is
  group-level only.
- Coverage accounting: the report tracks pooled exposures per item against
  the ~500+ guideline and widens (never hides) intervals when data is thin.

## Sources

- Sawtooth Software, *MaxDiff Technical Paper* and Lighthouse Studio manual
  (design balance, 3× exposure rule, items-per-screen, sample-size guidance).
- Sawtooth Software, *Sparse/Express/… Making Sense of All Those MaxDiffs*
  (sparse designs for 50+ items).
- B. Orme, *MaxDiff Analysis: Simple Counting, Individual-Level Logit, and HB*.
- J. Louviere et al., *Best-Worst Scaling* (Cambridge, 2015).
- K. Bansak et al., *The Number of Choice Tasks and Survey Satisficing in
  Conjoint Experiments*, Political Analysis.
- L. Maystre & M. Grossglauser, *Fast and Accurate Inference of Plackett-Luce
  Models*, NeurIPS 2015 (the `choix` library).
- D. Hunter, *MM Algorithms for Generalized Bradley-Terry Models*, Annals of
  Statistics 2004 (the bundled fallback fit).
- M. Schulze, *A New Monotonic, Clone-Independent, Reversal Symmetric, and
  Condorcet-Consistent Single-Winner Election Method* (beatpath tie-break).
- M. Salganik & K. Levy, *Wiki Surveys: Open and Quantifiable Social Data
  Collection*, PLOS ONE 2015 (pairwise wiki-survey UX and greedy collection).
- Displayr, *Creating Pairwise Balanced MaxDiff Designs* (per-respondent
  permutation method).
- No Magic / Dassault documentation, MagicDraw 2024x–2026x: *Sync with Excel
  or CSV files*, *Excel and CSV Import*, *Generic tables* (the Cameo
  integration click-paths and identification-property behavior).
