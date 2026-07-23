"""Cross-version lineage: closure, orphan detection, and the split/merge
carryover proven end-to-end through the real scripts."""

import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from build_survey import build_payload, load_config
from tests.simulate import simulate_respondent, true_utilities, write_inbox
from ucsurvey import archive as arc
from ucsurvey import catalog as cat
from ucsurvey import lineage as lin

ROOT = Path(__file__).parent.parent
SAMPLE = ROOT / "data" / "use_cases.sample.csv"


# ---------- unit: closure & orphans ----------

def test_transitive_closure_and_split():
    raw = {"UC-005": ["UC-061", "UC-062"], "UC-062": ["UC-070"]}  # split then rename
    current = {"UC-061", "UC-070", "UC-001"}
    clo = lin.closure(raw, current)
    assert set(clo["UC-005"]) == {"UC-061", "UC-070"}  # both branches, transitively
    assert clo["UC-062"] == ["UC-070"]


def test_dropped_and_orphans():
    raw = {"UC-005": []}  # explicitly dropped
    current = {"UC-001"}
    assert lin.closure(raw, current)["UC-005"] == []
    # UC-009 is historical, not current, not mapped -> unmapped orphan
    assert lin.unmapped_orphans({"UC-001", "UC-005", "UC-009"}, current, raw) == ["UC-009"]


def test_cycle_guard():
    raw = {"A": ["B"], "B": ["A"]}
    assert lin.resolve_to_current("A", raw, {"C"}) == []  # no crash, no current reached


def test_lineage_csv_roundtrip(tmp_path):
    p = tmp_path / "lineage.csv"
    lin.append_lineage_row(p, "UC-005", "split", ["UC-061", "UC-062"], "split in v2")
    lin.append_lineage_row(p, "UC-009", "dropped", [])
    rows = lin.load_lineage_rows(p)
    assert {r["old_id"] for r in rows} == {"UC-005", "UC-009"}
    df = cat.load_catalog(SAMPLE)
    raw = lin.raw_map(df, p)
    assert raw["UC-005"] == ["UC-061", "UC-062"] and raw["UC-009"] == []


# ---------- end-to-end: a split carries the parent's priority to both children ----------

def run_cli(script, *args):
    proc = subprocess.run([sys.executable, str(ROOT / script), *map(str, args)],
                          capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, f"{script} failed:\n{proc.stdout}\n{proc.stderr}"
    return proc.stdout


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "data").mkdir()
    cat.write_catalog_with_ids(cat.load_catalog(SAMPLE), tmp_path / "data" / "use_cases.csv")
    shutil.copy(ROOT / "config.yaml", tmp_path / "config.yaml")
    return tmp_path


def test_split_carries_priority_to_children(ws):
    csv = ws / "data" / "use_cases.csv"
    archive = ws / "data" / "archive"
    df = cat.load_catalog(csv)
    payload = build_payload(df, load_config(ws / "config.yaml"))
    ids = [r["id"] for _, r in df.iterrows()]
    util = true_utilities(ids)

    # Pick a genuinely high-priority use case to split.
    target = max(util, key=util.get)

    # Week 1: survey against v1, ingest.
    people = [simulate_respondent(payload, f"p{i:02d}@corp.com",
              ["Operator", "Maintainer", "Systems Engineer"][i % 3], "Org A",
              "short", util, seed=900 + i) for i in range(14)]
    write_inbox(people, ws / "inbox")
    run_cli("ingest.py", ws / "inbox", "--csv", csv, "--archive", archive,
            "--config", ws / "config.yaml")

    # v1 rank of the target.
    run_cli("resolve.py", "--csv", csv, "--archive", archive, "--config",
            ws / "config.yaml", "--out", ws / "v1", "--fast", "--as-of", "2026-01-01")
    v1 = pd.read_csv(ws / "v1" / "use_cases_enriched.csv").set_index("surveyId")
    target_rank = int(v1.loc[target, "p1_rank"])
    assert target_rank <= 5  # it's a top item

    # Week 2: split the target into two NEW ids, each superseding it; remove target.
    df2 = df[df["id"] != target].copy()
    for new_id, suffix in [("UC-201", "(variant A)"), ("UC-202", "(variant B)")]:
        row = {c: "" for c in df2.columns}
        row.update({"id": new_id, "name": f"{v1.loc[target, 'name']} {suffix}",
                    "description": "split child", "category": "Split",
                    "supersedes": target})
        df2 = pd.concat([df2, pd.DataFrame([row])], ignore_index=True)
    df2.to_csv(csv, index=False)

    # Resolve v2 with inherit: both children inherit the parent's votes.
    run_cli("resolve.py", "--csv", csv, "--archive", archive, "--config",
            ws / "config.yaml", "--out", ws / "v2", "--fast", "--lineage", "inherit",
            "--as-of", "2026-01-01")
    v2 = pd.read_csv(ws / "v2" / "use_cases_enriched.csv").set_index("surveyId")
    assert target not in v2.index  # parent gone
    # Both children inherited the parent's data and rank near where it was.
    assert v2.loc["UC-201", "n_respondents"] > 0
    assert v2.loc["UC-202", "n_respondents"] > 0
    assert int(v2.loc["UC-201", "p1_rank"]) <= target_rank + 3
    assert int(v2.loc["UC-202", "p1_rank"]) <= target_rank + 3

    # Strict mode instead: children have no data of their own.
    run_cli("resolve.py", "--csv", csv, "--archive", archive, "--config",
            ws / "config.yaml", "--out", ws / "v2s", "--fast", "--lineage", "strict",
            "--as-of", "2026-01-01")
    v2s = pd.read_csv(ws / "v2s" / "use_cases_enriched.csv").set_index("surveyId")
    assert v2s.loc["UC-201", "n_respondents"] == 0


def test_resolve_refuses_unmapped_orphan(ws):
    csv = ws / "data" / "use_cases.csv"
    archive = ws / "data" / "archive"
    df = cat.load_catalog(csv)
    payload = build_payload(df, load_config(ws / "config.yaml"))
    ids = [r["id"] for _, r in df.iterrows()]
    util = true_utilities(ids)
    people = [simulate_respondent(payload, f"p{i}@corp.com", "Operator", "Org A",
              "short", util, seed=700 + i) for i in range(6)]
    write_inbox(people, ws / "inbox")
    run_cli("ingest.py", ws / "inbox", "--csv", csv, "--archive", archive,
            "--config", ws / "config.yaml")

    # Remove a use case WITHOUT declaring what happened to it -> unmapped orphan.
    df2 = df[df["id"] != ids[0]].copy()
    df2.to_csv(csv, index=False)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "resolve.py"), "--csv", str(csv),
         "--archive", str(archive), "--config", str(ws / "config.yaml"),
         "--out", str(ws / "out"), "--fast"],
        capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 1
    assert "STOP" in proc.stdout and ids[0] in proc.stdout

    # --drop-unmapped lets it proceed.
    run_cli("resolve.py", "--csv", csv, "--archive", archive, "--config",
            ws / "config.yaml", "--out", ws / "out", "--fast", "--drop-unmapped",
            "--as-of", "2026-01-01")
