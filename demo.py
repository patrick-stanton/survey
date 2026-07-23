#!/usr/bin/env python3
"""One-command end-to-end demo — no real data, no survey-taking required.

    python demo.py

Runs the entire pipeline against a temporary workspace so you can show a
colleague the whole loop in ~30 seconds:

  1. builds a survey from the example catalog
  2. SIMULATES a small population of respondents (some quitting early, one
     random-clicker) answering exactly as a browser would
  3. writes their results as the two real return formats (.json downloads and
     UCS1 email codes in .txt files) into an inbox
  4. ingests them into an append-only archive
  5. resolves the pooled archive into the enriched CSV + report
  6. prints the resulting ranking and points you at the output files

Nothing here touches your real data/ directory — everything lands in a fresh
temp folder that is printed at the end. Delete it whenever.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tests"))


def main() -> int:
    from build_survey import build_payload, load_config
    from simulate import simulate_respondent, true_utilities, write_inbox
    from ucsurvey import catalog as cat
    from ucsurvey import compact

    ws = Path(tempfile.mkdtemp(prefix="ucsurvey-demo-"))
    (ws / "data").mkdir()
    sample = HERE / "data" / "use_cases.sample.csv"
    cat.write_catalog_with_ids(cat.load_catalog(sample), ws / "data" / "use_cases.csv")
    shutil.copy(HERE / "config.yaml", ws / "config.yaml")
    csv = ws / "data" / "use_cases.csv"
    archive = ws / "data" / "archive"
    inbox = ws / "inbox"

    print("=" * 70)
    print("USE-CASE PRIORITIZATION — END-TO-END DEMO (simulated data)")
    print("=" * 70)

    def run(script, *args):
        print(f"\n$ python {script} {' '.join(str(a) for a in args)}")
        r = subprocess.run([sys.executable, str(HERE / script), *map(str, args)],
                           capture_output=True, text=True, cwd=HERE)
        print(r.stdout.rstrip())
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr)
            raise SystemExit(f"{script} failed")

    # 1. Build the survey.
    run("build_survey.py", "--csv", csv, "--out", ws / "dist")

    # 2. Simulate a population answering it (known ground-truth priorities).
    df = cat.load_catalog(csv)
    payload = build_payload(df, load_config(ws / "config.yaml"))
    util = true_utilities([r["id"] for _, r in df.iterrows()])
    roles = ["Operator", "Maintainer", "Systems Engineer"]
    orgs = ["Organization A", "Organization B"]
    print(f"\n[simulating 16 respondents answering the {len(df)}-use-case survey…]")

    json_people, code_people = [], []
    for i in range(16):
        person = simulate_respondent(
            payload, f"person{i:02d}@example.com", roles[i % 3], orgs[i % 2],
            "short" if i < 12 else "long", util, seed=5000 + i,
            abort_after=5 if i % 6 == 0 else None,          # some quit early
            random_clicker=(i == 15),                        # one careless clicker
        )
        (json_people if i % 2 == 0 else code_people).append(person)

    # 3a. Half return the downloaded .json file…
    write_inbox(json_people, inbox)
    # 3b. …half click "Email my results" — a UCS1 code in an email body.
    for person in code_people:
        code = compact.encode(person, payload)
        (inbox / f"email_{person['sessionId']}.txt").write_text(
            f"From: {person['respondent']['email']}\nSubject: Use case survey results\n"
            f"\nHere are my results:\n\n{code}\n", encoding="utf-8")
    print(f"[wrote {len(json_people)} .json downloads and {len(code_people)} "
          f"emailed codes into the inbox]")

    # 4. Ingest everything (both formats, one command).
    run("ingest.py", inbox, "--csv", csv, "--archive", archive,
        "--config", ws / "config.yaml")

    # 5. Resolve (fixed --as-of so the demo output is reproducible).
    run("resolve.py", "--csv", csv, "--archive", archive,
        "--config", ws / "config.yaml", "--out", ws / "out",
        "--fast", "--as-of", "2026-01-01")

    # 6. Show the headline ranking.
    import pandas as pd
    enriched = pd.read_csv(ws / "out" / "use_cases_enriched.csv")
    top = enriched.sort_values("p1_rank").head(10)
    print("\n" + "=" * 70)
    print("TOP 10 BY POOLED RANKING (P1 counts; 90% rank interval shown)")
    print("=" * 70)
    print(f"{'rank':>4}  {'90% range':>9}  {'P(top10)':>8}  use case")
    for _, r in top.iterrows():
        print(f"{int(r['p1_rank']):>4}  {f'{int(r.rank_low90)}-{int(r.rank_high90)}':>9}  "
              f"{r['p_top10']:>8.2f}  {r['name'][:44]}")

    print("\n" + "=" * 70)
    print("Full outputs (delete this folder whenever you like):")
    print(f"  enriched CSV : {ws / 'out' / 'use_cases_enriched.csv'}")
    print(f"  report       : {ws / 'out' / 'resolve_report.txt'}")
    print(f"  survey        : {ws / 'dist' / 'survey.html'}")
    print(f"  workspace    : {ws}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
