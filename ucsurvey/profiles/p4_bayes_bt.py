"""P4 — Bayesian Bradley-Terry (approximate posterior via choix).

Where P3 gives one best-fit utility per item, this profile gives a posterior
distribution, enabling honest statements like "we are 92% sure use case A
outranks use case B" at small sample sizes — without the ~100+ respondents
that a full hierarchical Bayes model needs to be identifiable.

Requires the optional `choix` library (expectation propagation). When choix
is missing this profile is skipped with a notice; P5's bootstrap intervals
cover the uncertainty story in that case.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

try:
    import choix
except ImportError:  # pragma: no cover - environment-dependent
    choix = None

available = choix is not None


def credible_intervals(pairs: pd.DataFrame, item_ids: list[str], alpha: float,
                       n_draws: int = 4000, seed: int = 7,
                       level: float = 0.90) -> pd.DataFrame | None:
    """Posterior mean shares + credible intervals + P(rank <= 10) per item."""
    if choix is None or pairs.empty:
        return None
    idx = {item: i for i, item in enumerate(item_ids)}
    data = [(idx[w], idx[l]) for w, l in zip(pairs["winner"], pairs["loser"])
            if w in idx and l in idx]
    mean, cov = choix.ep_pairwise(len(item_ids), data, alpha)

    rng = np.random.default_rng(seed)
    draws = rng.multivariate_normal(mean, cov, size=n_draws)  # log-strengths
    shares = 100.0 * np.exp(draws) / np.exp(draws).sum(axis=1, keepdims=True)
    rank_draws = (-shares).argsort(axis=1).argsort(axis=1) + 1

    lo, hi = (1 - level) / 2 * 100, (1 + level) / 2 * 100
    return pd.DataFrame({
        "share_mean": shares.mean(axis=0),
        "share_lo": np.percentile(shares, lo, axis=0),
        "share_hi": np.percentile(shares, hi, axis=0),
        "rank_lo": np.percentile(rank_draws, lo, axis=0).astype(int),
        "rank_hi": np.percentile(rank_draws, hi, axis=0).astype(int),
    }, index=item_ids)
