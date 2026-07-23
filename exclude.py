#!/usr/bin/env python3
"""Remove suspect responses from the analysis WITHOUT deleting them.

    python exclude.py --list                        # show what's in the archive
    python exclude.py --email bob@corp.com --reason known-bad-actor
    python exclude.py --session s1a2b3 --reason duplicate
    python exclude.py --before 2026-07-01 --reason week1-bad-link
    python exclude.py --after  2026-07-14 --reason pre-briefing
    python exclude.py --restore known-bad-actor     # move a reason group back

Matching responses move from data/archive/active/ to
data/archive/excluded/<reason>/. They are NEVER deleted, so the exclusion is
auditable and reversible, and every past result stays reproducible. resolve.py
reads only active/ and reports what is excluded.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from ucsurvey import archive as arc

HERE = Path(__file__).parent


def _load(path: Path):
    try:
        return arc.load_result_file(path)
    except Exception:
        return None


def list_archive(archive: Path) -> None:
    active = arc.active_dir(archive)
    files = sorted(active.glob("*.csv")) + sorted(active.glob("*.json")) if active.exists() else []
    print(f"ACTIVE ({len(files)} responses in {active}):")
    for f in files:
        d = _load(f)
        if d:
            answered = sum(1 for s in d["sets"] if not s["skipped"])
            print(f"  {d['respondent']['email']:<32} session {d['sessionId']:<20} "
                  f"{answered:>3} screens  {d.get('startedAt', '')[:10]}  [{f.name}]")
    excluded = arc.excluded_summary(archive)
    if excluded:
        print("\nEXCLUDED (not counted):")
        for reason, n in excluded.items():
            print(f"  {n:>3} in '{reason}'")


def matches(data: dict, args) -> bool:
    if args.email and str(data["respondent"]["email"]).lower() != args.email.lower():
        return False
    if args.session and str(data["sessionId"]) != args.session:
        return False
    started = str(data.get("startedAt", ""))[:10]
    if args.before and not (started and started < args.before):
        return False
    if args.after and not (started and started > args.after):
        return False
    return any([args.email, args.session, args.before, args.after])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archive", default=HERE / "data" / "archive", type=Path)
    ap.add_argument("--list", action="store_true", help="list the archive and exit")
    ap.add_argument("--email"); ap.add_argument("--session")
    ap.add_argument("--before", metavar="YYYY-MM-DD"); ap.add_argument("--after", metavar="YYYY-MM-DD")
    ap.add_argument("--reason", help="folder name to file the excluded responses under")
    ap.add_argument("--restore", metavar="REASON", help="move a reason group back to active")
    args = ap.parse_args(argv)

    active = arc.active_dir(args.archive)
    excluded_root = Path(args.archive) / arc.EXCLUDED

    if args.list:
        list_archive(args.archive)
        return 0

    if args.restore:
        src = excluded_root / args.restore
        if not src.exists():
            print(f"No excluded group '{args.restore}'.")
            return 1
        active.mkdir(parents=True, exist_ok=True)
        moved = 0
        for f in list(src.glob("*.csv")) + list(src.glob("*.json")):
            shutil.move(str(f), str(active / f.name))
            moved += 1
        try:
            src.rmdir()
        except OSError:
            pass
        print(f"Restored {moved} response(s) from '{args.restore}' to active.")
        return 0

    if not args.reason:
        print("Give --reason (a short folder name) with your match criteria, "
              "or use --list / --restore.")
        return 1
    if not any([args.email, args.session, args.before, args.after]):
        print("Give at least one of --email / --session / --before / --after.")
        return 1

    dest = excluded_root / re_slug(args.reason)
    files = (sorted(active.glob("*.csv")) + sorted(active.glob("*.json"))
             if active.exists() else [])
    moved = 0
    for f in files:
        data = _load(f)
        if data and matches(data, args):
            dest.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(dest / f.name))
            moved += 1
            print(f"  excluded {f.name} -> {dest.name}/")
    print(f"\nMoved {moved} response(s) to excluded/{re_slug(args.reason)}/. "
          "Re-run resolve.py. (Reverse with --restore.)")
    return 0


def re_slug(text: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")[:60] or "excluded"


if __name__ == "__main__":
    sys.exit(main())
