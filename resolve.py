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
from ucsurvey import lineage as lin
from ucsurvey.explode import exploded_pairs, sets_per_respondent
from ucsurvey.profiles import p1_counts, p2_copeland, p3_bradley_terry, p4_bayes_bt, p5_bootstrap
from ucsurvey.report import write_enriched_csv, write_report, write_cameo_import
from ucsurvey.report_web import write_web_report

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
    ap.add_argument("--as-of", default=None, metavar="YYYY-MM-DD",
                    help="date to stamp in outputs (default: today). Set this to "
                    "make the whole run byte-for-byte reproducible.")
    ap.add_argument("--drop-unmapped", action="store_true",
                    help="proceed even if some historical use cases are unmapped "
                    "(their votes are dropped). Default is to refuse — run reconcile.py.")
    args = ap.parse_args(argv)

    with open(args.config, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    rcfg = cfg.get("resolve", {})
    alpha = float(rcfg.get("bt_alpha", 0.05))
    n_boot = 200 if args.fast else int(rcfg.get("bootstrap_samples", 2000))
    seed = int(rcfg.get("bootstrap_seed", 20260722))
    top_n = int(rcfg.get("top_n", 10))
    lineage = args.lineage or str(rcfg.get("lineage", "inherit"))

    df = cat.load_catalog(args.csv)
    item_ids = list(df["id"])
    current_ids = set(item_ids)
    data_dir = args.csv.parent
    raw_map = lin.raw_map(df, lin.default_path(data_dir))

    raw = arc.load_archive(args.archive)
    if raw.empty:
        print("Archive is empty — run ingest.py first.")
        return 1

    # Refuse to run if history references use cases we don't know how to handle,
    # so real votes are never silently dropped.
    hist = lin.historical_ids(raw)
    orphans = lin.unmapped_orphans(hist, current_ids, raw_map)
    if orphans and not args.drop_unmapped:
        counts = raw[raw["item_id"].isin(orphans)].groupby("item_id")["email"].nunique()
        print("\nSTOP: these historical use cases are no longer in the catalog and "
              "you haven't told the tool how to handle them:")
        for oid in orphans:
            print(f"  {oid}  ({int(counts.get(oid, 0))} respondents' votes at stake)")
        print("\nRun:  python reconcile.py     (map each one: renamed / split / "
              "merged / dropped / revived)\nor add --drop-unmapped to drop their "
              "votes and proceed anyway.")
        return 1

    dangling = lin.dangling_targets(raw_map, current_ids)
    if dangling:
        print(f"WARNING: lineage for {dangling} points to use cases that don't "
              "exist in the current catalog — those votes will be dropped.")

    mapping = lin.closure(raw_map, current_ids)
    long_df = arc.apply_lineage(raw, mapping, current_ids, lineage)

    for w in lin.name_drift_warnings(long_df, df, data_dir):
        print(f"DRIFT? {w}")

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
            "resolved_at": args.as_of or datetime.date.today().isoformat(),
        },
    }
    if not p4_bayes_bt.available:
        print("NOTE: 'choix' not installed — P4 Bayesian intervals skipped "
              "(P5 bootstrap intervals still cover uncertainty). pip install choix to enable.")

    args.out.mkdir(parents=True, exist_ok=True)
    csv_path = write_enriched_csv(df, long_df, results, args.out / "use_cases_enriched.csv")
    rpt_path = write_report(df, long_df, results, args.out / "resolve_report.txt")
    cameo_path = write_cameo_import(df, long_df, results, args.out / "cameo_import.csv")
    web_path = write_web_report(df, long_df, results, args.out / "report.html")
    print(f"Wrote {csv_path}")
    print(f"Wrote {rpt_path}")
    print(f"Wrote {web_path}  <- shareable deep-dive dashboard (open in a browser)")
    print(f"Wrote {cameo_path}  <- import THIS into Cameo (surveyId + rank only)")
    print("The enriched CSV, report, and dashboard keep the full detail for analysis.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
