"""Resolution profiles — the closed set of aggregation methods.

P1 counts        hand-checkable headline (numpy/pandas only)
P2 copeland      election logic: majority head-to-head wins (numpy only)
P3 bradley_terry probabilistic utilities (choix when installed, else the
                 bundled, tested minorization-maximization fit)
P4 bayes_bt      Bayesian credible intervals (needs choix; skipped otherwise)
P5 bootstrap     uncertainty certification + group agreement diagnostics

Deliberately excluded (see METHODOLOGY.md for the evidence): hierarchical
Bayes below ~100 respondents, exact Kemeny-Young at this item count,
instant-runoff voting, and mean-rating/rank averaging. Do not add them here.
"""
