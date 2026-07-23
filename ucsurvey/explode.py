"""Turn best/worst screens into implied pairwise preferences.

A screen of k items where the respondent picked best b and worst w implies
2k-3 pairwise wins (the standard MaxDiff "explosion"):

    b beats each of the other k-1 items
    each middle item beats w            (k-2 pairs; b-beats-w already counted)

The respondent told us nothing about how the middle items compare to each
other — no pairs are invented for those. If lineage filtering removed the
best (or worst) item of a set, the remaining implied pairs are still valid
preferences and are kept.

When a use case was SPLIT, apply_lineage duplicates the parent's slot into
several children that share an 'ancestor'. We never emit a pair between two
items sharing an ancestor (a child-vs-child phantom the respondent never
expressed) — so a split correctly gives each child the parent's comparisons
against OTHER items, and nothing else.
"""

from __future__ import annotations

import pandas as pd


def exploded_pairs(long_df: pd.DataFrame) -> pd.DataFrame:
    """Long answer table -> one row per implied pairwise win.

    Returns columns: email, session_id, set_index, winner, loser.
    """
    has_ancestor = "ancestor" in long_df.columns
    rows = []
    answered = long_df[~long_df["skipped"]]
    for (email, session_id, set_index), grp in answered.groupby(
        ["email", "session_id", "set_index"], sort=False
    ):
        best_rows = grp[grp["pick"] == "best"]
        worst_rows = grp[grp["pick"] == "worst"]
        best = best_rows["item_id"].iloc[0] if len(best_rows) else None
        worst = worst_rows["item_id"].iloc[0] if len(worst_rows) else None
        best_anc = best_rows["ancestor"].iloc[0] if (has_ancestor and len(best_rows)) else object()
        worst_anc = worst_rows["ancestor"].iloc[0] if (has_ancestor and len(worst_rows)) else object()
        for _, r in grp.iterrows():
            item = r["item_id"]
            item_anc = r["ancestor"] if has_ancestor else object()
            if best is not None and item != best and item_anc != best_anc:
                rows.append((email, session_id, set_index, best, item))
            if (worst is not None and item != worst and item != best
                    and item_anc != worst_anc):
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
