#!/usr/bin/env python3
"""Interactively map retired use cases to the current catalog.

    python reconcile.py

When you change the use-case list in Cameo (rename, split, merge, drop, or
revive a use case) and rebuild the survey, older responses reference ids that
are no longer in the catalog. This walks you through each such "orphan" and
records your decision in data/lineage.csv, so you only answer once and every
future resolve is automatic. Nothing about the raw responses is changed.

For each orphan it shows the old name and how many people's votes are at stake,
then offers: renamed / split / merged / dropped / revived-under-new-id.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ucsurvey import archive as arc
from ucsurvey import catalog as cat
from ucsurvey import lineage as lin
from ucsurvey import versions

HERE = Path(__file__).parent


def pick_ids(prompt: str, current_ids: list[str], names: dict, multi: bool):
    """Prompt for one or more current ids by number; returns a list of ids."""
    print(prompt)
    for i, cid in enumerate(current_ids, 1):
        print(f"    [{i:>2}] {cid}  {names.get(cid, '')[:50]}")
    while True:
        raw = input("    number(s)" + (" (comma-separated)" if multi else "") + ": ").strip()
        try:
            nums = [int(x) for x in raw.replace(",", " ").split()]
            chosen = [current_ids[n - 1] for n in nums if 1 <= n <= len(current_ids)]
            if chosen and (multi or len(chosen) == 1):
                return chosen
        except (ValueError, IndexError):
            pass
        print("    please enter valid number(s).")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default=HERE / "data" / "use_cases.csv", type=Path)
    ap.add_argument("--archive", default=HERE / "data" / "archive", type=Path)
    args = ap.parse_args(argv)

    data_dir = args.csv.parent
    df = cat.load_catalog(args.csv)
    current_ids = list(df["id"])
    names = dict(zip(df["id"], df["name"]))
    lineage_path = lin.default_path(data_dir)

    long_df = arc.load_archive(args.archive)
    if long_df.empty:
        print("Archive is empty — nothing to reconcile.")
        return 0
    raw_map = lin.raw_map(df, lineage_path)
    orphans = lin.unmapped_orphans(lin.historical_ids(long_df), set(current_ids), raw_map)
    if not orphans:
        print("No unmapped use cases — everything reconciles. You're good to resolve.")
        return 0

    counts = long_df.groupby("item_id")["email"].nunique()
    # Gather all past version hashes to look up old names.
    version_hashes = [p.stem for p in versions.snapshot_dir(data_dir).glob("*.csv")] \
        if versions.snapshot_dir(data_dir).exists() else []

    print(f"{len(orphans)} retired use case(s) need a decision.\n")
    for oid in orphans:
        old_name = versions.known_name(data_dir, oid, version_hashes)
        n = int(counts.get(oid, 0))
        print("=" * 68)
        print(f"{oid}  —  \"{old_name}\"")
        print(f"{n} respondent(s) answered screens with this use case.")
        print("How should its votes be handled?")
        print("  [1] Renamed / replaced by ONE current use case")
        print("  [2] Split into SEVERAL current use cases (each inherits its votes)")
        print("  [3] Merged INTO an existing current use case")
        print("  [4] Dropped — its votes no longer count")
        print("  [5] Skip for now (decide later)")
        choice = input("  choice [1-5]: ").strip()

        if choice in ("1", "3"):
            ids = pick_ids("  Which current use case?", current_ids, names, multi=False)
            disp = "renamed" if choice == "1" else "merged"
            lin.append_lineage_row(lineage_path, oid, disp, ids)
            print(f"  -> {oid} {disp} to {ids[0]}\n")
        elif choice == "2":
            ids = pick_ids("  Which current use cases? (its votes go to each)",
                           current_ids, names, multi=True)
            lin.append_lineage_row(lineage_path, oid, "split", ids)
            print(f"  -> {oid} split into {', '.join(ids)}\n")
        elif choice == "4":
            note = input("  reason (optional): ").strip()
            lin.append_lineage_row(lineage_path, oid, "dropped", [], note)
            print(f"  -> {oid} dropped\n")
        else:
            print(f"  (skipped {oid})\n")

    remaining = lin.unmapped_orphans(
        lin.historical_ids(long_df), set(current_ids), lin.raw_map(df, lineage_path))
    if remaining:
        print(f"Still unmapped: {', '.join(remaining)}. Re-run reconcile.py when ready.")
    else:
        print(f"All reconciled. Decisions saved to {lineage_path}. Run: python resolve.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
