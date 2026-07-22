"""P2 — Copeland majority scores with a Schulze tie-break.

Election logic on the implied head-to-head contests: item A "beats" item B
if, pooling every implied pairwise comparison, A was preferred by a majority.
Copeland score = (majority wins) − (majority losses); the most defensible
sentence in the room is "A was preferred over B by a majority of responses."

Sparse data produces ties and occasional preference cycles; ties in the
Copeland ordering are broken by Schulze beatpath strength (the standard
cycle-robust Condorcet completion), computed here directly — it is a
15-line Floyd-Warshall, so no external voting library is required.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def win_matrix(pairs: pd.DataFrame, item_ids: list[str],
               weights: pd.Series | None = None) -> np.ndarray:
    """W[i, j] = (weighted) number of times item i beat item j."""
    idx = {item: i for i, item in enumerate(item_ids)}
    w = np.zeros((len(item_ids), len(item_ids)))
    if pairs.empty:
        return w
    wt = weights if weights is not None else pd.Series(1.0, index=pairs.index)
    for (winner, loser), grp in pairs.groupby(["winner", "loser"]):
        if winner in idx and loser in idx:
            w[idx[winner], idx[loser]] += float(wt.loc[grp.index].sum())
    return w


def copeland_scores(w: np.ndarray) -> np.ndarray:
    """Majority wins minus majority losses per item (never-compared pairs tie)."""
    beats = (w > w.T).astype(int)
    return beats.sum(axis=1) - beats.sum(axis=0)


def schulze_beatpath_wins(w: np.ndarray) -> np.ndarray:
    """Number of opponents each item defeats via strongest beatpaths."""
    k = w.shape[0]
    p = np.where(w > w.T, w, 0.0)  # direct link strength: winning votes
    for m in range(k):
        # strongest path i->j may route through m; strength = weakest link
        p = np.maximum(p, np.minimum(p[:, m][:, None], p[m, :][None, :]))
    np.fill_diagonal(p, 0.0)
    return (p > p.T).sum(axis=1)


def scores_and_ranks(pairs: pd.DataFrame, item_ids: list[str]) -> pd.DataFrame:
    w = win_matrix(pairs, item_ids)
    cope = copeland_scores(w)
    schulze = schulze_beatpath_wins(w)
    df = pd.DataFrame({"copeland": cope, "schulze_wins": schulze}, index=item_ids)
    order = df.sort_values(["copeland", "schulze_wins"], ascending=False)
    ranked = order["copeland"].rank(ascending=False, method="min").astype(int)
    # break Copeland ties using the Schulze ordering position
    tie_broken = pd.Series(range(1, len(order) + 1), index=order.index)
    df["rank_strict"] = tie_broken.reindex(df.index)
    df["rank"] = ranked.reindex(df.index)
    return df
