"""P5 — bootstrap certification and group-agreement diagnostics.

The question leadership actually asks is not "what is the ranking?" but
"which items are securely top-tier and which are statistically
interchangeable?" A cluster bootstrap answers it with almost no modeling
assumptions: resample RESPONDENTS (not individual answers — people, the
natural unit of opinion) with replacement, recompute P1 and P3 on each
replicate, and read off how much the ranks wobble.

Also computes agreement between stakeholder groups (roles, organizations):
Kendall tau-b between group rankings, Kendall's W concordance, and top-N
overlap — surfacing the *contested* items for discussion instead of
averaging disagreement away.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

try:
    from scipy import stats as scipy_stats
except ImportError:  # pragma: no cover - environment-dependent
    scipy_stats = None

from . import p1_counts, p3_bradley_terry
from .p2_copeland import win_matrix


def _ranks(values: np.ndarray) -> np.ndarray:
    """1 = best, ties get the same (min) rank, NaN ranks last."""
    s = pd.Series(values)
    return s.rank(ascending=False, method="min", na_option="bottom").to_numpy()


def bootstrap(long_df: pd.DataFrame, pairs: pd.DataFrame, item_ids: list[str],
              alpha: float, n_boot: int, seed: int, top_n: int,
              level: float = 0.90) -> dict:
    """Returns per-item DataFrames of rank intervals for P1 and P3 + p_top_n."""
    emails = sorted(long_df["email"].unique())
    n_resp = len(emails)
    k = len(item_ids)

    # Precompute each respondent's contribution once; a bootstrap replicate is
    # then just a weighted combination — fast enough for thousands of draws.
    resp_scores = p1_counts.respondent_scores(long_df, item_ids)  # resp x item
    resp_w = {
        email: win_matrix(pairs[pairs["email"] == email], item_ids)
        for email in emails
    }

    rng = np.random.default_rng(seed)
    p1_rank_draws = np.empty((n_boot, k))
    p3_rank_draws = np.empty((n_boot, k))
    score_mat = resp_scores.reindex(emails).to_numpy()  # aligned to `emails`

    for b in range(n_boot):
        sample_idx = rng.integers(0, n_resp, size=n_resp)
        with np.errstate(invalid="ignore"):
            p1_scores = np.nanmean(score_mat[sample_idx], axis=0)
        p1_rank_draws[b] = _ranks(p1_scores)

        w = np.zeros((k, k))
        for i in sample_idx:
            w += resp_w[emails[i]]
        pi = p3_bradley_terry.fit_mm(w, alpha, tol=1e-7, max_iter=3000)
        p3_rank_draws[b] = _ranks(pi)

    lo, hi = (1 - level) / 2 * 100, (1 + level) / 2 * 100

    def interval(draws):
        return pd.DataFrame({
            "rank_lo": np.floor(np.percentile(draws, lo, axis=0)).astype(int),
            "rank_hi": np.ceil(np.percentile(draws, hi, axis=0)).astype(int),
            "p_top_n": (draws <= top_n).mean(axis=0),
        }, index=item_ids)

    return {
        "p1": interval(p1_rank_draws),
        "p3": interval(p3_rank_draws),
        "n_respondents": n_resp,
        "indicative_only": n_resp <= 10,
    }


# ---------------------------------------------------------------------------
# Group agreement
# ---------------------------------------------------------------------------

def group_rankings(long_df: pd.DataFrame, item_ids: list[str], by: str,
                   min_group_size: int = 2) -> pd.DataFrame:
    """P1 ranking per stakeholder group (columns) with >= min_group_size people."""
    out = {}
    for group, sub in long_df.groupby(by):
        if sub["email"].nunique() >= min_group_size and str(group).strip():
            out[str(group)] = _ranks(
                p1_counts.scores(sub, item_ids).to_numpy()
            )
    return pd.DataFrame(out, index=item_ids)


def kendalls_w(rank_matrix: pd.DataFrame) -> float | None:
    """Concordance across groups: 1 = identical priorities, 0 = no agreement."""
    m = rank_matrix.shape[1]
    n = rank_matrix.shape[0]
    if m < 2 or n < 2:
        return None
    r_sums = rank_matrix.sum(axis=1)
    s = ((r_sums - r_sums.mean()) ** 2).sum()
    return float(12 * s / (m ** 2 * (n ** 3 - n)))


def pairwise_agreement(rank_matrix: pd.DataFrame, top_n: int) -> pd.DataFrame:
    """Kendall tau-b + top-N overlap for every pair of stakeholder groups."""
    rows = []
    groups = list(rank_matrix.columns)
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            a, b = rank_matrix[groups[i]], rank_matrix[groups[j]]
            if scipy_stats is not None:
                tau = float(scipy_stats.kendalltau(a, b).statistic)
            else:
                tau = float(a.corr(b, method="kendall"))
            top_a = set(a.nsmallest(top_n).index)
            top_b = set(b.nsmallest(top_n).index)
            rows.append({
                "group_a": groups[i], "group_b": groups[j],
                "kendall_tau": round(tau, 3),
                f"top{top_n}_overlap": len(top_a & top_b) / top_n,
            })
    return pd.DataFrame(rows)


def contested_items(rank_matrix: pd.DataFrame, quantile: float = 0.75) -> pd.Series:
    """Between-group rank spread per item; large spread = contested."""
    if rank_matrix.shape[1] < 2:
        return pd.Series(0.0, index=rank_matrix.index)
    return rank_matrix.max(axis=1) - rank_matrix.min(axis=1)
