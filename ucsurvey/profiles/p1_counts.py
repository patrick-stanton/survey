"""P1 — exposure-normalized best-minus-worst counts.

For each respondent and item:  (times picked best − times picked worst)
                               ────────────────────────────────────────
                                        times shown to them

then averaged across respondents with every respondent weighted equally —
someone who answered 8 screens counts exactly as much as someone who
answered 60, and aborted sessions introduce no bias because the denominator
is what they actually saw. Rescaled so 0 = always picked worst, 50 =
neutral, 100 = always picked best. Anyone can recheck this from the raw
archive with a spreadsheet, which is the point of the headline profile.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def respondent_scores(long_df: pd.DataFrame, item_ids: list[str]) -> pd.DataFrame:
    """Matrix of per-respondent normalized scores in [-1, 1]; NaN = never shown."""
    answered = long_df[~long_df["skipped"]]
    if answered.empty:
        return pd.DataFrame(columns=item_ids)
    shown = answered.pivot_table(index="email", columns="item_id",
                                 values="set_index", aggfunc="count")
    best = (answered[answered["pick"] == "best"]
            .pivot_table(index="email", columns="item_id",
                         values="set_index", aggfunc="count"))
    worst = (answered[answered["pick"] == "worst"]
             .pivot_table(index="email", columns="item_id",
                          values="set_index", aggfunc="count"))
    shown = shown.reindex(columns=item_ids)
    best = best.reindex(index=shown.index, columns=item_ids).fillna(0)
    worst = worst.reindex(index=shown.index, columns=item_ids).fillna(0)
    return (best - worst) / shown


def scores(long_df: pd.DataFrame, item_ids: list[str]) -> pd.Series:
    """Aggregate 0-100 score per item (NaN-aware mean over respondents)."""
    per_resp = respondent_scores(long_df, item_ids)
    if per_resp.empty:
        return pd.Series(np.nan, index=item_ids)
    with np.errstate(invalid="ignore"):
        mean = per_resp.mean(axis=0, skipna=True)
    return (mean + 1.0) * 50.0


def ranks(score_series: pd.Series) -> pd.Series:
    """1 = highest priority. Items nobody ever saw rank last."""
    return score_series.rank(ascending=False, method="min", na_option="bottom").astype(int)
