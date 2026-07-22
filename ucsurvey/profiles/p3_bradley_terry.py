"""P3 — Bradley-Terry preference utilities.

The Bradley-Terry model (the logic behind chess Elo) assigns each item a
strength pi such that P(i beats j) = pi/(pi+pj), and finds the strengths
that best explain every implied pairwise win in the pooled archive. It
handles sparse, incomplete, unequal-length sessions in one coherent model,
and its utilities are ratio-scaled: a share of 8 vs 4 means "twice the
preference weight," which plain rank numbers cannot say.

Fitting uses the `choix` library (Maystre & Grossglauser's I-LSR, NeurIPS
2015) when it is installed. When it is not — restricted corporate Python,
say — the bundled minorization-maximization fit below (Hunter 2004, the
classic textbook algorithm) produces the same maximum-likelihood answer;
the test suite asserts the two agree. Both paths add `alpha` pseudo-
observations per pair (regularization): mandatory at this scale because a
small respondent pool can leave the comparison graph disconnected, where
the unregularized MLE does not exist.

Two variants are reported:
  pooled     — every implied pair counts once (heavy contributors weigh more)
  equalized  — each pair weighted 1/(screens that respondent answered), so
               every person contributes equally, matching P1's philosophy
"""

from __future__ import annotations

import numpy as np
import pandas as pd

try:
    import choix  # optional
except ImportError:  # pragma: no cover - environment-dependent
    choix = None

from .p2_copeland import win_matrix


def fit_mm(w: np.ndarray, alpha: float, tol: float = 1e-9,
           max_iter: int = 20_000) -> np.ndarray:
    """Hunter's MM algorithm for Bradley-Terry on a win-count matrix."""
    k = w.shape[0]
    w = w + alpha  # alpha pseudo-wins in both directions keep the graph connected
    np.fill_diagonal(w, 0.0)
    n = w + w.T
    wins = w.sum(axis=1)
    pi = np.full(k, 1.0 / k)
    for _ in range(max_iter):
        denom = (n / (pi[:, None] + pi[None, :])).sum(axis=1)
        new_pi = wins / denom
        new_pi /= new_pi.sum()
        if np.abs(new_pi - pi).max() < tol:
            return new_pi
        pi = new_pi
    return pi


def fit(pairs: pd.DataFrame, item_ids: list[str], alpha: float,
        weights: pd.Series | None = None) -> pd.Series:
    """Bradley-Terry strengths as 0-100 preference shares."""
    if weights is None and choix is not None and not pairs.empty:
        idx = {item: i for i, item in enumerate(item_ids)}
        data = [(idx[w], idx[l]) for w, l in zip(pairs["winner"], pairs["loser"])
                if w in idx and l in idx]
        params = choix.ilsr_pairwise(len(item_ids), data, alpha=alpha)
        pi = np.exp(params)
    else:
        pi = fit_mm(win_matrix(pairs, item_ids, weights), alpha)
    shares = 100.0 * pi / pi.sum()
    return pd.Series(shares, index=item_ids)


def equalized_weights(pairs: pd.DataFrame, sets_per_resp: pd.Series) -> pd.Series:
    """Weight each implied pair by 1/(screens its respondent answered)."""
    return pairs["email"].map(1.0 / sets_per_resp).astype(float)


def connectivity_report(pairs: pd.DataFrame, item_ids: list[str]) -> int:
    """Number of connected components in the pooled comparison graph.
    1 = fully connected (ideal); more means regularization is doing real work."""
    parent = {i: i for i in item_ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for w, l in zip(pairs["winner"], pairs["loser"]):
        if w in parent and l in parent:
            parent[find(w)] = find(l)
    return len({find(i) for i in item_ids})
