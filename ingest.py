#!/usr/bin/env python3
"""Ingest returned survey results into the append-only archive.

Usage:
    python ingest.py                        # takes everything in data/inbox/
    python ingest.py path/to/file.json ...  # or specific files/folders
    python ingest.py --allow-catalog a1b2c3d4e5f60708   # accept an older wording

Files are validated (schema, catalog version, answer sanity) before entering
data/archive/. A re-submitted session replaces its older, smaller copy;
nothing else in the archive is ever modified. Run this as often as you like —
today's five interviews and tomorrow's ten all pool at resolve time.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ucsurvey import archive as arc
from ucsurvey import catalog as cat

HERE = Path(__file__).parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sources", nargs="*", type=Path,
                    help="result .json files or folders (default: data/inbox/)")
    ap.add_argument("--csv", default=HERE / "data" / "use_cases.csv", type=Path)
    ap.add_argument("--archive", default=HERE / "data" / "archive", type=Path)
    ap.add_argument("--allow-catalog", action="append", default=[],
                    metavar="HASH", help="also accept responses collected against "
                    "this older catalog version (repeatable)")
    args = ap.parse_args(argv)

    df = cat.load_catalog(args.csv)
    current_hash = cat.catalog_hash(df)
    known_ids = set(df["id"])

    sources = args.sources or [HERE / "data" / "inbox"]
    files: list[Path] = []
    for src in sources:
        if src.is_dir():
            files += sorted(src.glob("*.json"))
        elif src.is_file():
            files.append(src)
        else:
            print(f"WARNING: {src} not found, skipping")
    if not files:
        print("No .json result files found. Drop returned files into data/inbox/ "
              "or pass paths explicitly.")
        return 1

    report = arc.IngestReport()
    for f in files:
        arc.ingest_file(f, args.archive, current_hash, known_ids, report,
                        allow_hashes=set(args.allow_catalog))

    for name in report.accepted:
        print(f"  + {name}")
    for name in report.replaced:
        print(f"  ^ {name} (replaced an earlier export of the same session)")
    for name in report.unchanged:
        print(f"  = {name} (already archived)")
    for name, reason in report.rejected:
        print(f"  ! {name} REJECTED: {reason}")

    long_df = arc.load_archive(args.archive)
    print(f"\nArchive now holds {long_df['email'].nunique() if not long_df.empty else 0} "
          f"respondents, "
          f"{long_df.drop_duplicates(['email','session_id','set_index']).shape[0] if not long_df.empty else 0} "
          f"answered screens.")
    if not long_df.empty:
        exposures = long_df[~long_df["skipped"]].groupby("item_id").size()
        exposures = exposures.reindex(sorted(known_ids)).fillna(0).astype(int)
        low = exposures[exposures < 10]
        print(f"Per-item exposures: min {exposures.min()}, median "
              f"{int(exposures.median())}, max {exposures.max()}."
              + (f" {len(low)} items under 10 exposures." if len(low) else ""))
    print("Next: python resolve.py")
    return 2 if report.rejected else 0


if __name__ == "__main__":
    sys.exit(main())
