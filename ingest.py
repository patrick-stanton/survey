#!/usr/bin/env python3
"""Ingest returned survey results into the append-only archive.

Usage:
    python ingest.py                        # takes everything in data/inbox/
    python ingest.py path/to/file.json ...  # or specific files/folders
    python ingest.py --allow-catalog a1b2c3d4e5f60708   # accept an older wording

Two input forms are accepted from data/inbox/ (or the paths you pass):
  *.json — the survey's downloaded results files
  *.txt  — anything containing UCS1... results codes (from "Email my results"
           bodies): save the email as text, or paste codes into a .txt file.
           pull_email.py writes these automatically.

Files are validated (schema, catalog version, answer sanity) before entering
data/archive/. A re-submitted session replaces its older, smaller copy;
nothing else in the archive is ever modified. Run this as often as you like —
today's five interviews and tomorrow's ten all pool at resolve time.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from ucsurvey import archive as arc
from ucsurvey import catalog as cat
from ucsurvey import compact

HERE = Path(__file__).parent


def expand_codes_to_json(txt_files: list[Path], df, config_path: Path,
                         staging: Path, report: arc.IngestReport) -> list[Path]:
    """Decode every UCS1 code found in the .txt files into staged .json files."""
    codes = []
    for f in txt_files:
        try:
            if f.stat().st_size > 5_000_000:  # match the .json size guard
                report.rejected.append((f.name, "over 5 MB — real code files are tiny"))
                continue
            found = compact.find_codes(f.read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            report.rejected.append((f.name, f"unreadable: {exc}"))
            continue
        if not found:
            report.rejected.append((f.name, "no UCS1 results code found in file"))
        codes += [(f.name, c) for c in found]
    if not codes:
        return []

    # Re-deriving screens needs the same designs the survey was built with.
    from build_survey import build_payload, load_config
    payload = build_payload(df, load_config(config_path))

    staged = []
    staging.mkdir(parents=True, exist_ok=True)
    for src_name, code in codes:
        try:
            data = compact.decode(code, payload)
        except compact.CodeError as exc:
            report.rejected.append((src_name, str(exc)))
            continue
        except Exception as exc:  # a malformed code can never abort the batch
            report.rejected.append((src_name, f"undecodable ({type(exc).__name__})"))
            continue
        p = staging / arc.archive_filename(data)
        if p.exists():  # same session coded twice: keep the longer export
            old = json.loads(p.read_text(encoding="utf-8"))
            if len(old["sets"]) >= len(data["sets"]):
                continue
        p.write_text(json.dumps(data, indent=1), encoding="utf-8")
        if p not in staged:
            staged.append(p)
    return staged


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sources", nargs="*", type=Path,
                    help="result .json files or folders (default: data/inbox/)")
    ap.add_argument("--csv", default=HERE / "data" / "use_cases.csv", type=Path)
    ap.add_argument("--config", default=HERE / "config.yaml", type=Path)
    ap.add_argument("--archive", default=HERE / "data" / "archive", type=Path)
    ap.add_argument("--allow-catalog", action="append", default=[],
                    metavar="HASH", help="also accept responses collected against "
                    "this older catalog version (repeatable)")
    ap.add_argument("--roster", type=Path, default=None, metavar="FILE",
                    help="optional file of invited respondent emails (one per "
                    "line); responses from any other address are rejected")
    args = ap.parse_args(argv)

    df = cat.load_catalog(args.csv)
    current_hash = cat.catalog_hash(df)
    known_ids = set(df["id"])

    # Design width (bounds screen size at validation) and optional roster.
    try:
        cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
        items_per_screen = int(cfg.get("survey", {}).get("items_per_screen", 4))
    except (OSError, yaml.YAMLError, ValueError, TypeError):
        items_per_screen = None
    roster = None
    if args.roster:
        roster = {ln.strip().lower() for ln in args.roster.read_text(
            encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")}
        print(f"Roster: {len(roster)} invited addresses; others will be rejected.")

    sources = args.sources or [HERE / "data" / "inbox"]
    files: list[Path] = []
    txt_files: list[Path] = []
    for src in sources:
        if src.is_dir():
            files += sorted(src.glob("*.json"))
            txt_files += sorted(src.glob("*.txt"))
        elif src.is_file():
            (txt_files if src.suffix.lower() == ".txt" else files).append(src)
        else:
            print(f"WARNING: {src} not found, skipping")
    if not files and not txt_files:
        print("No .json result files or .txt code files found. Drop returned "
              "files into data/inbox/ or pass paths explicitly.")
        return 1

    report = arc.IngestReport()
    if txt_files:
        files += expand_codes_to_json(txt_files, df, args.config,
                                      args.archive.parent / "decoded_codes", report)
    for f in files:
        arc.ingest_file(f, args.archive, current_hash, known_ids, report,
                        allow_hashes=set(args.allow_catalog),
                        items_per_screen=items_per_screen, roster=roster)

    for name in report.accepted:
        print(f"  + {name}")
    for name in report.replaced:
        print(f"  ^ {name} (replaced an earlier export of the same session)")
    for name in report.unchanged:
        print(f"  = {name} (already archived)")
    for name, reason in report.rejected:
        print(f"  ! {name} REJECTED: {reason}")

    long_df = arc.load_archive(args.archive)
    n_resp = long_df["email"].nunique() if not long_df.empty else 0
    print(f"\nArchive now holds {n_resp} respondents, "
          f"{long_df.drop_duplicates(['email','session_id','set_index']).shape[0] if not long_df.empty else 0} "
          f"answered screens.")
    if not long_df.empty:
        exposures = long_df[~long_df["skipped"]].groupby("item_id").size()
        exposures = exposures.reindex(sorted(known_ids)).fillna(0).astype(int)
        low = exposures[exposures < 10]
        print(f"Per-item exposures: min {exposures.min()}, median "
              f"{int(exposures.median())}, max {exposures.max()}."
              + (f" {len(low)} items under 10 exposures." if len(low) else ""))
        # Identity is self-declared and unauthenticated. Surface how many
        # distinct sessions each respondent submitted so an operator can spot
        # one person impersonating a crowd (see SECURITY.md).
        sess = long_df.groupby("email")["session_id"].nunique().sort_values(ascending=False)
        multi = sess[sess > 1]
        if len(multi):
            print(f"NOTE: {len(multi)} respondent(s) submitted more than one session "
                  f"(top: {multi.index[0]} ×{multi.iloc[0]}). Reconcile against your "
                  "invite list before treating the ranking as decision-grade.")
    print("Next: python resolve.py")
    return 2 if report.rejected else 0


if __name__ == "__main__":
    sys.exit(main())
