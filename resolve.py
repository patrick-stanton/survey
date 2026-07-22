#!/usr/bin/env python3
"""Resolve the pooled archive into prioritization scores through every profile.

Usage:
    python resolve.py                     # full run (bootstrap included)
    python resolve.py --fast              # quick look: 200 bootstrap draws
    python resolve.py --lineage inherit   # count votes for merged predecessors

Outputs:
    data/out/use_cases_enriched.csv   <- import this into Cameo (see README)
    data/out/resolve_report.txt       <- rankings, uncertainty, group agreement

Deterministic: same archive + config + seed => byte-identical outputs.
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

import pandas as pd
import yaml

from ucsurvey import archive as arc
from ucsurvey import catalog as cat
from ucsurvey.explode import exploded_pairs, sets_per_respondent
from ucsurvey.profiles import p1_counts, p2_copeland, p3_bradley_terry, p4_bayes_bt, p5_bootstrap
from ucsurvey.report import write_enriched_csv, write_report

HERE = Path(__file__).parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=HERE / "data" / "use_cases.csv", type=Path)
    ap.add_argument("--config", default=HERE / "config.yaml", type=Path)
    ap.add_argument("--archive", default=HERE / "data" / "archive", type=Path)
    ap.add_argument("--out", default=HERE / "data" / "out", type=Path)
    ap.add_argument("--lineage", choices=["strict", "inherit"], default=None,
                    help="override the config's lineage mode")
    ap.add_argument("--fast", action="store_true", help="200 bootstrap draws instead of full")
    args = ap.parse_args(argv)

    with open(args.config, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    rcfg = cfg.get("resolve", {})
    alpha = float(rcfg.get("bt_alpha", 0.05))
    n_boot = 200 if args.fast else int(rcfg.get("bootstrap_samples", 2000))
    seed = int(rcfg.get("bootstrap_seed", 20260722))
    top_n = int(rcfg.get("top_n", 10))
    lineage = args.lineage or str(rcfg.get("lineage", "strict"))

    df = cat.load_catalog(args.csv)
    item_ids = list(df["id"])
    mapping = cat.lineage_map(df)

    raw = arc.load_archive(args.archive)
    if raw.empty:
        print("Archive is empty — run ingest.py first.")
        return 1
    long_df = arc.apply_lineage(raw, mapping, set(item_ids), lineage)
    dropped = raw.shape[0] - long_df.shape[0]
    if dropped:
        print(f"Lineage mode '{lineage}': {dropped} answer rows referenced items "
              f"outside the current catalog and were "
              f"{'re-mapped where possible, rest ' if lineage == 'inherit' else ''}dropped.")
    if long_df.empty or dropped > raw.shape[0] * 0.5:
        print("\nERROR: most or all archived answers no longer match the catalog's ids."
              "\nAlmost always this means the use-case CSV lost its id column (ids were"
              "\nre-minted and shifted). Restore the ids the archive was collected"
              "\nagainst — see data/use_cases_with_ids.csv from the original build, or"
              "\nthe 'shown' ids inside any data/archive/*.json file.")
        return 1

    pairs = exploded_pairs(long_df)
    spr = sets_per_respondent(long_df)
    n_resp = long_df["email"].nunique()
    print(f"Resolving {n_resp} respondents, "
          f"{long_df.drop_duplicates(['email','session_id','set_index']).shape[0]} screens, "
          f"{len(pairs)} implied pairwise comparisons "
          f"(lineage={lineage}, bootstrap={n_boot}).")

    components = p3_bradley_terry.connectivity_report(pairs, item_ids)
    if components > 1:
        print(f"NOTE: comparison graph has {components} components (sparse data); "
              f"regularization (alpha={alpha}) keeps estimates defined — treat "
              "cross-component comparisons cautiously until more data arrives.")

    results = {
        "p1_scores": p1_counts.scores(long_df, item_ids),
        "p2": p2_copeland.scores_and_ranks(pairs, item_ids),
        "p3_pooled": p3_bradley_terry.fit(pairs, item_ids, alpha),
        "p3_equalized": p3_bradley_terry.fit(
            pairs, item_ids, alpha,
            weights=p3_bradley_terry.equalized_weights(pairs, spr)),
        "p4": p4_bayes_bt.credible_intervals(pairs, item_ids, alpha) if p4_bayes_bt.available else None,
        "boot": p5_bootstrap.bootstrap(long_df, pairs, item_ids, alpha, n_boot, seed, top_n),
        "role_ranks": p5_bootstrap.group_rankings(long_df, item_ids, "role"),
        "org_ranks": p5_bootstrap.group_rankings(long_df, item_ids, "organization"),
        "meta": {
            "n_respondents": n_resp,
            "n_screens": int(long_df.drop_duplicates(["email", "session_id", "set_index"]).shape[0]),
            "n_pairs": len(pairs),
            "components": components,
            "alpha": alpha, "n_boot": n_boot, "seed": seed, "top_n": top_n,
            "lineage": lineage,
            "catalog_hash": cat.catalog_hash(df),
            "resolved_at": datetime.date.today().isoformat(),
        },
    }
    if not p4_bayes_bt.available:
        print("NOTE: 'choix' not installed — P4 Bayesian intervals skipped "
              "(P5 bootstrap intervals still cover uncertainty). pip install choix to enable.")

    args.out.mkdir(parents=True, exist_ok=True)
    csv_path = write_enriched_csv(df, long_df, results, args.out / "use_cases_enriched.csv")
    rpt_path = write_report(df, long_df, results, args.out / "resolve_report.txt")
    print(f"Wrote {csv_path}\nWrote {rpt_path}")
    print("Import the CSV into Cameo via the generic table's 'Read From File' (README).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
