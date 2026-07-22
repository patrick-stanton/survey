"""Turn best/worst screens into implied pairwise preferences.

A screen of k items where the respondent picked best b and worst w implies
2k-3 pairwise wins (the standard MaxDiff "explosion"):

    b beats each of the other k-1 items
    each middle item beats w            (k-2 pairs; b-beats-w already counted)

The respondent told us nothing about how the middle items compare to each
other — no pairs are invented for those. If lineage filtering removed the
best (or worst) item of a set, the remaining implied pairs are still valid
preferences and are kept.
"""

from __future__ import annotations

import pandas as pd


def exploded_pairs(long_df: pd.DataFrame) -> pd.DataFrame:
    """Long answer table -> one row per implied pairwise win.

    Returns columns: email, session_id, set_index, winner, loser.
    """
    rows = []
    answered = long_df[~long_df["skipped"]]
    for (email, session_id, set_index), grp in answered.groupby(
        ["email", "session_id", "set_index"], sort=False
    ):
        best = grp.loc[grp["pick"] == "best", "item_id"]
        worst = grp.loc[grp["pick"] == "worst", "item_id"]
        best = best.iloc[0] if len(best) else None
        worst = worst.iloc[0] if len(worst) else None
        items = list(grp["item_id"])
        for item in items:
            if best is not None and item != best:
                rows.append((email, session_id, set_index, best, item))
            if worst is not None and item != worst and item != best:
                rows.append((email, session_id, set_index, item, worst))
    return pd.DataFrame(
        rows, columns=["email", "session_id", "set_index", "winner", "loser"]
    )


def sets_per_respondent(long_df: pd.DataFrame) -> pd.Series:
    """Answered (non-skipped) screens per respondent — the basis for the
    respondent-equalized weighting of heavy vs light participants."""
    answered = long_df[~long_df["skipped"]]
    return (
        answered.drop_duplicates(["email", "session_id", "set_index"])
        .groupby("email").size()
    )
