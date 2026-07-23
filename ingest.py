#!/usr/bin/env python3
"""Ingest returned survey results into the append-only archive.

    python ingest.py                          # everything in data/survey_inbox/
    python ingest.py path/to/file.csv ...     # or specific files/folders
    python ingest.py --roster data/roster.txt # only accept invited emails
    python ingest.py --allow-catalog <hash>   # accept an older catalog wording

Accepted inputs (mix freely — however results reached you):
  *.csv   the survey's downloaded results file (the normal case)
  *.txt   a saved email whose body contains the CSV (or a legacy UCS1 code)
  *.json  a legacy downloaded results file

Each response is validated (schema, catalog version, screen sanity) AND checked
against the design it claims to come from (fabricated screens are rejected).
Valid responses are written into data/archive/active/ as canonical CSV. A
re-submission of the same session may only ADD screens; it can never overwrite
recorded picks. Run as often as you like — results pool across days at resolve.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from ucsurvey import archive as arc
from ucsurvey import catalog as cat
from ucsurvey import compact, csv_result

HERE = Path(__file__).parent


def results_from_file(path: Path) -> list[dict]:
    """Turn one input file into zero or more raw result dicts."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return [csv_result.parse_csv(path.read_text(encoding="utf-8", errors="replace"))]
    if suffix == ".json":
        import json
        return [json.loads(path.read_text(encoding="utf-8"))]
    if suffix == ".txt":
        text = path.read_text(encoding="utf-8", errors="replace")
        blocks = csv_result.find_csv_blocks(text)
        if blocks:
            return [csv_result.parse_csv(b) for b in blocks]
        # Legacy: an emailed UCS1 code. Needs the payload to decode — handled
        # by the caller via a sentinel so we don't rebuild the payload here.
        codes = compact.find_codes(text)
        return [{"__ucs1__": c} for c in codes]
    raise arc.ResponseError(f"unsupported file type '{suffix}'")


def collect_inputs(sources: list[Path]) -> list[Path]:
    files: list[Path] = []
    for src in sources:
        if src.is_dir():
            for ext in ("*.csv", "*.txt", "*.json"):
                files += sorted(src.glob(ext))
        elif src.is_file():
            files.append(src)
        else:
            print(f"WARNING: {src} not found, skipping")
    return files


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="*", type=Path,
                    help="result files or folders (default: data/survey_inbox/)")
    ap.add_argument("--csv", default=HERE / "data" / "use_cases.csv", type=Path)
    ap.add_argument("--config", default=HERE / "config.yaml", type=Path)
    ap.add_argument("--archive", default=HERE / "data" / "archive", type=Path)
    ap.add_argument("--allow-catalog", action="append", default=[], metavar="HASH")
    ap.add_argument("--roster", type=Path, default=None, metavar="FILE",
                    help="file of invited emails (one per line); others rejected")
    args = ap.parse_args(argv)

    df = cat.load_catalog(args.csv)
    current_hash = cat.catalog_hash(df)
    known_ids = set(df["id"])
    allow = set(args.allow_catalog)

    # Payload (design) for re-derivation and legacy code decoding.
    from build_survey import build_payload, load_config
    payload = build_payload(df, load_config(args.config))
    try:
        items_per_screen = int(yaml.safe_load(args.config.read_text())
                               .get("survey", {}).get("items_per_screen", 4))
    except Exception:
        items_per_screen = 4

    roster = None
    if args.roster:
        roster = {ln.strip().lower() for ln in args.roster.read_text(encoding="utf-8")
                  .splitlines() if ln.strip() and not ln.startswith("#")}
        print(f"Roster: {len(roster)} invited addresses; others will be rejected.")

    default_inbox = HERE / "data" / "survey_inbox"
    files = collect_inputs(args.sources or [default_inbox])
    if not files:
        print(f"No result files found. Drop CSVs into {default_inbox}/ or pass paths.")
        return 1

    report = arc.IngestReport()
    active = arc.active_dir(args.archive)

    for f in files:
        try:
            raw_results = results_from_file(f)
        except (csv_result.CsvResultError, arc.ResponseError, ValueError) as exc:
            report.rejected.append((f.name, str(exc)))
            continue
        except Exception as exc:
            report.rejected.append((f.name, f"unreadable ({type(exc).__name__})"))
            continue
        if not raw_results:
            report.rejected.append((f.name, "no results found in file"))
            continue

        for data in raw_results:
            label = f.name if len(raw_results) == 1 else f"{f.name}#{raw_results.index(data)}"
            try:
                if "__ucs1__" in data:  # legacy emailed code
                    data = compact.decode(data["__ucs1__"], payload)
                if data.get("checksumOk") is False:
                    report.warnings.append(
                        f"{label}: checksum did not match — file may have been "
                        "edited or corrupted (kept only if screens re-derive)")
                arc.validate_response(data, current_hash, known_ids, allow,
                                      items_per_screen=items_per_screen)
                arc.verify_screens_against_design(data, payload)
                if roster is not None:
                    email = str(data["respondent"]["email"]).strip().lower()
                    if email not in roster:
                        report.rejected.append(
                            (label, f"'{email}' is not on the invited roster"))
                        continue
                arc.ingest_result(data, active, report, label)
            except (arc.ResponseError, compact.CodeError) as exc:
                report.rejected.append((label, str(exc)))
            except Exception as exc:
                report.rejected.append((label, f"error ({type(exc).__name__}: {exc})"))

    for name in report.accepted:
        print(f"  + {name}")
    for name in report.replaced:
        print(f"  ^ {name} (added screens to an existing session)")
    for name in report.unchanged:
        print(f"  = {name} (already archived)")
    for w in report.warnings:
        print(f"  ~ {w}")
    for name, reason in report.rejected:
        print(f"  ! {name} REJECTED: {reason}")

    long_df = arc.load_archive(args.archive)
    n_resp = long_df["email"].nunique() if not long_df.empty else 0
    n_screens = (long_df.drop_duplicates(["email", "session_id", "set_index"]).shape[0]
                 if not long_df.empty else 0)
    print(f"\nArchive (active) now holds {n_resp} respondents, {n_screens} answered screens.")
    excluded = arc.excluded_summary(args.archive)
    if excluded:
        print("Excluded (not counted): "
              + ", ".join(f"{n} in {r}" for r, n in excluded.items()))
    if not long_df.empty:
        sess = long_df.groupby("email")["session_id"].nunique().sort_values(ascending=False)
        multi = sess[sess > 1]
        if len(multi):
            print(f"NOTE: {len(multi)} respondent(s) submitted more than one session "
                  f"(top: {multi.index[0]} ×{multi.iloc[0]}). Reconcile against your "
                  "invite list before treating results as decision-grade (SECURITY.md).")
    print("Next: python resolve.py")
    return 2 if report.rejected else 0


if __name__ == "__main__":
    sys.exit(main())
