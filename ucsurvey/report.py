"""Assemble the two resolve outputs: the enriched CSV for Cameo and the
human-readable resolve report."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .catalog import SPECIAL_COLUMNS
from .profiles import p1_counts, p5_bootstrap


def _exposure_stats(long_df: pd.DataFrame, item_ids: list[str]) -> pd.DataFrame:
    answered = long_df[~long_df["skipped"]]
    exp = answered.groupby("item_id").size().reindex(item_ids).fillna(0).astype(int)
    resp = (answered.groupby("item_id")["email"].nunique()
            .reindex(item_ids).fillna(0).astype(int))
    return pd.DataFrame({"n_exposures": exp, "n_respondents": resp})


def _consensus_flags(results: dict, item_ids: list[str],
                     exposure: pd.DataFrame) -> pd.Series:
    p1_rank = p1_counts.ranks(results["p1_scores"])
    p3_rank = results["p3_equalized"].rank(ascending=False, method="min").astype(int)
    diverge = (p1_rank - p3_rank).abs() > 10

    spread = p5_bootstrap.contested_items(results["role_ranks"])
    if spread.max() > 0:
        threshold = spread.quantile(0.75)
        group_contested = spread >= max(threshold, 10)
    else:
        group_contested = pd.Series(False, index=item_ids)

    flags = pd.Series("agreed", index=item_ids)
    flags[diverge | group_contested.reindex(item_ids).fillna(False)] = "contested"
    flags[exposure["n_exposures"] == 0] = "no_data"
    return flags


def write_enriched_csv(df: pd.DataFrame, long_df: pd.DataFrame, results: dict,
                       out_path: Path) -> Path:
    item_ids = list(df["id"])
    exposure = _exposure_stats(long_df, item_ids)
    p1 = results["p1_scores"]
    p3 = results["p3_equalized"]
    boot_p1 = results["boot"]["p1"]
    meta = results["meta"]

    out = df.copy()
    out = out.rename(columns={"id": "surveyId"})
    idx = pd.Index(item_ids)

    def col(series, digits=None):
        s = series.reindex(idx) if hasattr(series, "reindex") else series
        if digits is not None:
            s = s.round(digits)
        return s.to_numpy()

    has_data = exposure["n_exposures"].to_numpy() > 0
    out["p1_score"] = np.where(has_data, col(p1, 1), np.nan)
    out["p1_rank"] = col(p1_counts.ranks(p1))
    out["p2_copeland"] = col(results["p2"]["copeland"])
    out["p2_rank"] = col(results["p2"]["rank_strict"])
    out["p3_bt_share"] = np.where(has_data, col(p3, 2), np.nan)
    out["p3_rank"] = col(p3.rank(ascending=False, method="min").astype(int))
    out["rank_low90"] = col(boot_p1["rank_lo"])
    out["rank_high90"] = col(boot_p1["rank_hi"])
    out[f"p_top{meta['top_n']}"] = col(boot_p1["p_top_n"], 3)
    out["n_respondents"] = exposure["n_respondents"].to_numpy()
    out["n_exposures"] = exposure["n_exposures"].to_numpy()
    out["consensus_flag"] = col(_consensus_flags(results, item_ids, exposure))
    out["last_aggregated"] = meta["resolved_at"]
    out["profiles_used"] = "P1,P2,P3,P5" + (",P4" if results["p4"] is not None else "")

    ordered = (["surveyId", "name"]
               + [c for c in df.columns if c not in ("id", "name")]
               + [c for c in out.columns if c not in df.columns and c != "surveyId"])
    out[ordered].to_csv(out_path, index=False)
    return out_path


def write_cameo_import(df: pd.DataFrame, long_df: pd.DataFrame, results: dict,
                       out_path: Path) -> Path:
    """The minimal file to import into Cameo: surveyId + rank only.

    The ranking is the decision; the full detail (scores, intervals,
    disagreement) lives in the enriched CSV and the web report so the model
    stays uncluttered. One row per catalog item, always.
    """
    item_ids = list(df["id"])
    p1_rank = p1_counts.ranks(results["p1_scores"]).reindex(item_ids)
    exposure = _exposure_stats(long_df, item_ids)
    out = pd.DataFrame({
        "surveyId": item_ids,
        "rank": p1_rank.to_numpy().astype(int),
        "n_respondents": exposure["n_respondents"].to_numpy(),
    })
    out.to_csv(out_path, index=False)
    return out_path


def write_report(df: pd.DataFrame, long_df: pd.DataFrame, results: dict,
                 out_path: Path) -> Path:
    item_ids = list(df["id"])
    names = dict(zip(df["id"], df["name"]))
    meta = results["meta"]
    exposure = _exposure_stats(long_df, item_ids)
    p1 = results["p1_scores"]
    p1_rank = p1_counts.ranks(p1)
    p3 = results["p3_equalized"]
    p3_rank = p3.rank(ascending=False, method="min").astype(int)
    p3_pooled_rank = results["p3_pooled"].rank(ascending=False, method="min").astype(int)
    boot = results["boot"]
    top_n = meta["top_n"]

    L: list[str] = []
    L.append("USE-CASE PRIORITIZATION — RESOLVE REPORT")
    L.append("=" * 72)
    L.append(f"Resolved:      {meta['resolved_at']}   catalog {meta['catalog_hash']}   "
             f"lineage={meta['lineage']}")
    L.append(f"Data pool:     {meta['n_respondents']} respondents · {meta['n_screens']} screens · "
             f"{meta['n_pairs']} implied pairwise comparisons")
    L.append(f"Settings:      alpha={meta['alpha']}  bootstrap={meta['n_boot']} (seed {meta['seed']})")
    if meta["components"] > 1:
        L.append(f"CAUTION:       comparison graph in {meta['components']} components — "
                 "collect more responses before treating cross-group order as settled.")
    if boot["indicative_only"]:
        L.append(f"CAUTION:       only {boot['n_respondents']} respondents — intervals are "
                 "indicative, not statistical guarantees. Collect more responses.")
    L.append("")

    L.append(f"RANKING (P1 counts, hand-checkable; 90% rank interval from {meta['n_boot']}-draw")
    L.append(" respondent bootstrap; P3 = Bradley-Terry model rank as cross-check)")
    L.append("-" * 72)
    L.append(f"{'rank':>4} {'score':>6} {'90% rank':>9} {'P(top' + str(top_n) + ')':>8} "
             f"{'P3':>4}  {'id':<8} name")
    order = p1_rank.sort_values().index
    for item in order:
        lo, hi = boot["p1"].loc[item, "rank_lo"], boot["p1"].loc[item, "rank_hi"]
        pt = boot["p1"].loc[item, "p_top_n"]
        score = p1.get(item)
        L.append(f"{p1_rank[item]:>4} {score:>6.1f} {f'{lo}–{hi}':>9} {pt:>8.2f} "
                 f"{p3_rank[item]:>4}  {item:<8} {names[item][:44]}")
    L.append("")

    diverging = [(item, p1_rank[item], int(p3_rank[item]))
                 for item in item_ids if abs(p1_rank[item] - p3_rank[item]) > 10]
    L.append("PROFILE DISAGREEMENTS (counts vs model rank differ by >10 — discuss, don't average)")
    L.append("-" * 72)
    if diverging:
        for item, r1, r3 in sorted(diverging, key=lambda x: x[1]):
            L.append(f"  {item}  P1 rank {r1} vs P3 rank {r3}  — {names[item][:48]}")
    else:
        L.append("  none — counting and model-based methods agree within 10 positions")
    pooled_vs_eq = [(item, int(p3_pooled_rank[item]), int(p3_rank[item]))
                    for item in item_ids
                    if abs(p3_pooled_rank[item] - p3_rank[item]) > 10]
    if pooled_vs_eq:
        L.append("  Heavy-contributor sensitivity (pooled vs per-person-equalized BT):")
        for item, rp, re_ in pooled_vs_eq:
            L.append(f"    {item}  pooled {rp} vs equalized {re_}  — {names[item][:44]}")
    L.append("")

    for dim, key in [("role", "role_ranks"), ("organization", "org_ranks")]:
        ranks = results[key]
        L.append(f"STAKEHOLDER AGREEMENT BY {dim.upper()} "
                 f"({ranks.shape[1]} groups with ≥2 respondents)")
        L.append("-" * 72)
        if ranks.shape[1] < 2:
            L.append("  not enough groups yet — needs ≥2 groups with ≥2 respondents each")
        else:
            w = p5_bootstrap.kendalls_w(ranks)
            L.append(f"  Kendall's W concordance: {w:.2f}  (1 = identical priorities)")
            agree = p5_bootstrap.pairwise_agreement(ranks, top_n)
            for _, row in agree.iterrows():
                L.append(f"  {row['group_a']} vs {row['group_b']}: tau {row['kendall_tau']:+.2f}, "
                         f"top-{top_n} overlap {row[f'top{top_n}_overlap']:.0%}")
            spread = p5_bootstrap.contested_items(ranks).sort_values(ascending=False)
            L.append(f"  Most contested between {dim} groups:")
            for item in spread.head(5).index:
                if spread[item] > 0:
                    L.append(f"    {item}  rank spread {int(spread[item])}  — {names[item][:44]}")
        L.append("")

    if results["p4"] is not None:
        widest = (results["p4"]["rank_hi"] - results["p4"]["rank_lo"]).sort_values(ascending=False)
        L.append("BAYESIAN CHECK (P4, choix expectation propagation)")
        L.append("-" * 72)
        L.append("  Widest posterior rank intervals (least settled items):")
        for item in widest.head(5).index:
            r = results["p4"].loc[item]
            L.append(f"    {item}  rank {int(r['rank_lo'])}–{int(r['rank_hi'])}, "
                     f"share {r['share_mean']:.2f}  — {names[item][:40]}")
        L.append("")

    low = exposure[exposure["n_exposures"] < 100]
    L.append("COVERAGE")
    L.append("-" * 72)
    L.append(f"  exposures per item: min {exposure['n_exposures'].min()}, "
             f"median {int(exposure['n_exposures'].median())}, max {exposure['n_exposures'].max()}"
             f"  (guideline: 500+ pooled exposures for tight estimates)")
    if len(low) == len(item_ids):
        L.append("  all items under 100 exposures — expect wide intervals; keep collecting")
    elif len(low):
        L.append(f"  {len(low)} items under 100 exposures: "
                 + ", ".join(low.index[:10]) + (" …" if len(low) > 10 else ""))
    L.append("")

    answered = long_df[~long_df["skipped"]].drop_duplicates(
        ["email", "session_id", "set_index"])
    med_ms = answered.groupby("email")["response_ms"].median()
    fast = med_ms[med_ms < 2000]
    L.append("RESPONSE QUALITY")
    L.append("-" * 72)
    if len(fast):
        # Report a count, not individual emails — this file is meant to be
        # circulated, and naming respondents next to a "random clicking" label
        # would disclose PII plus a reputational judgement. The per-respondent
        # detail (for a sensitivity re-run) lives in the operator-only archive.
        L.append(f"  {len(fast)} of {len(med_ms)} respondent(s) had a median under "
                 "2 s/screen (possibly random clicking). Data kept; consider a")
        L.append("  sensitivity re-run without them. Identities are in data/archive/, "
                 "not this shareable report.")
    else:
        L.append("  no respondents flagged (all median response times ≥ 2 s/screen)")
    L.append("")
    L.append("Methods and their justification: METHODOLOGY.md. Raw data: data/archive/.")

    out_path.write_text("\n".join(L) + "\n", encoding="utf-8")
    return out_path
