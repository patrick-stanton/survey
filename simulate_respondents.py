#!/usr/bin/env python3
"""Populate data/survey_inbox/ with simulated respondent CSVs — for testing the
pipeline against your REAL data folders without hand-filling browser surveys.

    python simulate_respondents.py 20                 # 20 fake respondents
    python simulate_respondents.py 20 --seed 5        # a different random draw
    python simulate_respondents.py 5 --clickers 1     # include 1 random-clicker

They answer with a hidden 'true' priority order (printed at the end) so you can
check the resolved ranking recovers it. This is a TEST helper — delete it (and
data/survey_inbox/*, data/archive, data/out) before a real engagement.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tests"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("n", type=int, nargs="?", default=16, help="number of respondents")
    ap.add_argument("--csv", default=HERE / "data" / "use_cases.csv", type=Path)
    ap.add_argument("--config", default=HERE / "config.yaml", type=Path)
    ap.add_argument("--inbox", default=HERE / "data" / "survey_inbox", type=Path)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--clickers", type=int, default=1, help="how many random-clickers")
    args = ap.parse_args()

    from build_survey import build_payload, load_config
    from simulate import simulate_respondent, true_utilities, write_inbox
    from ucsurvey import catalog as cat

    if not args.csv.exists():
        sample = args.csv.with_name("use_cases.sample.csv")
        print(f"{args.csv} not found. Run: cp {sample} {args.csv}")
        return 1

    df = cat.load_catalog(args.csv)
    payload = build_payload(df, load_config(args.config))
    ids = [r["id"] for _, r in df.iterrows()]
    util = true_utilities(ids, seed=args.seed)

    roles = ["Operator", "Maintainer", "Systems Engineer", "Program Office", "Leadership"]
    orgs = ["Organization A", "Organization B", "Organization C"]
    people = []
    for i in range(args.n):
        people.append(simulate_respondent(
            payload, f"person{i:02d}@example.com", roles[i % len(roles)],
            orgs[i % len(orgs)], "short" if i % 3 else "long", util,
            seed=args.seed * 1000 + i,
            abort_after=6 if i % 7 == 0 else None,
            random_clicker=(i < args.clickers),
        ))
    write_inbox(people, args.inbox)

    true_order = sorted(ids, key=lambda x: -util[x])
    names = dict(zip(df["id"], df["name"]))
    print(f"Wrote {len(people)} respondent CSV(s) to {args.inbox}"
          + (f" (incl. {args.clickers} random-clicker)" if args.clickers else ""))
    print("Hidden 'true' top 5 the ranking should recover:")
    for r, i in enumerate(true_order[:5], 1):
        print(f"  {r}. {i}  {names[i]}")
    print("\nNext: python ingest.py   then   python resolve.py --fast")
    return 0


if __name__ == "__main__":
    sys.exit(main())
