"""The proof: simulate stakeholders with a KNOWN ground-truth priority order
answering the survey exactly as browsers would (same seeded designs), push
their files through the real CLI scripts (build -> ingest -> resolve), and
verify the pipeline recovers the truth — including with aborted sessions, a
random clicker, rolling multi-day ingest, and a catalog refactor."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from build_survey import build_payload, load_config
from tests.simulate import simulate_respondent, true_utilities, write_inbox
from ucsurvey import catalog as cat

ROOT = Path(__file__).parent.parent


@pytest.fixture()
def workspace(tmp_path):
    """Isolated copy of the project data layout driven via the real CLIs."""
    ws = tmp_path
    (ws / "data").mkdir()
    # Persist minted ids, as the real workflow does (ids pasted into Cameo
    # after the first build, then present in every later export).
    df = cat.load_catalog(ROOT / "data" / "use_cases.csv")
    cat.write_catalog_with_ids(df, ws / "data" / "use_cases.csv")
    shutil.copy(ROOT / "config.yaml", ws / "config.yaml")
    return ws


def run_cli(script, *args):
    proc = subprocess.run(
        [sys.executable, str(ROOT / script), *map(str, args)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert proc.returncode == 0, f"{script} failed:\n{proc.stdout}\n{proc.stderr}"
    return proc.stdout


def simulate_population(ws, n_short=22, n_long=6):
    df = cat.load_catalog(ws / "data" / "use_cases.csv")
    payload = build_payload(df, load_config(ws / "config.yaml"))
    util = true_utilities([r["id"] for _, r in df.iterrows()])

    roles = ["Operator", "Maintainer", "Systems Engineer"]
    files = []
    n = 0
    for i in range(n_short):
        n += 1
        files.append(simulate_respondent(
            payload, f"r{n:03d}@example.com", roles[i % 3], "Organization A",
            "short", util, seed=1000 + n,
            abort_after=6 if i % 5 == 0 else None,  # every 5th person quits early
        ))
    for i in range(n_long):
        n += 1
        files.append(simulate_respondent(
            payload, f"r{n:03d}@example.com", roles[i % 3], "Organization B",
            "long", util, seed=1000 + n))
    n += 1
    files.append(simulate_respondent(  # one random clicker
        payload, f"clicker@example.com", "Operator", "Organization A",
        "short", util, seed=1000 + n, random_clicker=True))
    return util, files


def test_pipeline_recovers_ground_truth(workspace):
    ws = workspace
    util, files = simulate_population(ws)

    # rolling collection: two batches ingested on different "days"
    write_inbox(files[:10], ws / "day1")
    write_inbox(files[10:], ws / "day2")
    common = ["--csv", ws / "data" / "use_cases.csv", "--archive", ws / "data" / "archive"]
    run_cli("ingest.py", ws / "day1", *common)
    out = run_cli("ingest.py", ws / "day2", *common)
    assert "29 respondents" in out

    run_cli("resolve.py", *common, "--config", ws / "config.yaml",
            "--out", ws / "out", "--fast")
    enriched = pd.read_csv(ws / "out" / "use_cases_enriched.csv")

    # 1) structure: one row per catalog item, passthrough intact, all columns
    assert len(enriched) == 60
    assert set(["surveyId", "name", "owner", "status", "p1_score", "p1_rank",
                "p2_copeland", "p2_rank", "p3_bt_share", "p3_rank", "rank_low90",
                "rank_high90", "p_top10", "n_respondents", "n_exposures",
                "consensus_flag", "last_aggregated", "profiles_used"]
               ).issubset(enriched.columns)
    assert (enriched["n_exposures"] > 0).all()

    # 2) recovery: every profile's ranking correlates strongly with the truth
    truth_rank = pd.Series(util).rank(ascending=False)
    for col in ["p1_rank", "p3_rank", "p2_rank"]:
        got = enriched.set_index("surveyId")[col]
        rho = truth_rank.corr(got, method="spearman")
        assert rho > 0.85, f"{col} only reached spearman {rho:.2f}"

    # 3) the true top item should be recognized as securely top-tier
    best_true = max(util, key=util.get)
    row = enriched.set_index("surveyId").loc[best_true]
    assert row["p1_rank"] <= 3
    assert row["p_top10"] > 0.9

    # 4) report exists, flags the random clicker, notes group agreement
    report = (ws / "out" / "resolve_report.txt").read_text()
    assert "clicker@example.com" in report
    assert "STAKEHOLDER AGREEMENT BY ROLE" in report

    # 5) determinism: resolve again -> byte-identical outputs
    first = (ws / "out" / "use_cases_enriched.csv").read_bytes()
    run_cli("resolve.py", *common, "--config", ws / "config.yaml",
            "--out", ws / "out2", "--fast")
    assert (ws / "out2" / "use_cases_enriched.csv").read_bytes() == first


def test_catalog_refactor_with_lineage(workspace):
    ws = workspace
    util, files = simulate_population(ws, n_short=10, n_long=2)
    write_inbox(files, ws / "inbox")
    common = ["--csv", ws / "data" / "use_cases.csv", "--archive", ws / "data" / "archive"]
    run_cli("ingest.py", ws / "inbox", *common)

    # Refactor: merge two use cases into one new one, keep everything else.
    df = pd.read_csv(ws / "data" / "use_cases.csv")
    merged_ids = ["UC-001", "UC-002"]
    df = df[~df["id"].isin(merged_ids)]
    new_row = {c: "" for c in df.columns}
    new_row.update({"id": "UC-101", "name": "Plan and route missions",
                    "description": "Merged planning use case.",
                    "category": "Mission Planning",
                    "supersedes": ";".join(merged_ids)})
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df.to_csv(ws / "data" / "use_cases.csv", index=False)

    # strict: runs, new item simply has no data yet
    run_cli("resolve.py", *common, "--config", ws / "config.yaml",
            "--out", ws / "strict", "--fast", "--lineage", "strict")
    strict = pd.read_csv(ws / "strict" / "use_cases_enriched.csv").set_index("surveyId")
    assert strict.loc["UC-101", "n_exposures"] == 0
    assert strict.loc["UC-101", "consensus_flag"] == "no_data"

    # inherit: predecessors' votes flow to the successor
    run_cli("resolve.py", *common, "--config", ws / "config.yaml",
            "--out", ws / "inherit", "--fast", "--lineage", "inherit")
    inherit = pd.read_csv(ws / "inherit" / "use_cases_enriched.csv").set_index("surveyId")
    assert inherit.loc["UC-101", "n_exposures"] > 0
    assert len(inherit) == 59
