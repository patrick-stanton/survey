"""Retroactive exclusion: quarantine (never delete), restore, and resolve
reads only active/."""

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

ROOT = Path(__file__).parent.parent
SAMPLE = ROOT / "data" / "use_cases.sample.csv"


def run_cli(script, *args, expect=0):
    proc = subprocess.run([sys.executable, str(ROOT / script), *map(str, args)],
                          capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == expect, f"{script}:\n{proc.stdout}\n{proc.stderr}"
    return proc.stdout


@pytest.fixture()
def seeded(tmp_path):
    (tmp_path / "data").mkdir()
    csv = tmp_path / "data" / "use_cases.csv"
    cat.write_catalog_with_ids(cat.load_catalog(SAMPLE), csv)
    shutil.copy(ROOT / "config.yaml", tmp_path / "config.yaml")
    archive = tmp_path / "data" / "archive"
    df = cat.load_catalog(csv)
    payload = build_payload(df, load_config(tmp_path / "config.yaml"))
    util = true_utilities([r["id"] for _, r in df.iterrows()])
    people = []
    for i in range(8):
        p = simulate_respondent(payload, f"p{i}@corp.com", "Operator", "Org A",
                                "short", util, seed=300 + i)
        p["startedAt"] = "2026-06-15T10:00:00Z" if i < 4 else "2026-07-15T10:00:00Z"
        people.append(p)
    write_inbox(people, tmp_path / "inbox")
    run_cli("ingest.py", tmp_path / "inbox", "--csv", csv, "--archive", archive,
            "--config", tmp_path / "config.yaml")
    return tmp_path, csv, archive


def test_exclude_by_email_then_restore(seeded):
    ws, csv, archive = seeded
    assert arc.load_archive(archive)["email"].nunique() == 8

    run_cli("exclude.py", "--archive", archive, "--email", "p3@corp.com",
            "--reason", "known-bad-actor")
    assert arc.load_archive(archive)["email"].nunique() == 7
    assert "p3@corp.com" not in set(arc.load_archive(archive)["email"])
    # File preserved, not deleted.
    assert arc.excluded_summary(archive) == {"known-bad-actor": 1}

    run_cli("exclude.py", "--archive", archive, "--restore", "known-bad-actor")
    assert arc.load_archive(archive)["email"].nunique() == 8


def test_exclude_by_date_range(seeded):
    ws, csv, archive = seeded
    # Exclude the first "week" (before July).
    run_cli("exclude.py", "--archive", archive, "--before", "2026-07-01",
            "--reason", "week1-bad-link")
    remaining = arc.load_archive(archive)
    assert remaining["email"].nunique() == 4  # only the July respondents remain
    assert arc.excluded_summary(archive)["week1-bad-link"] == 4


def test_resolve_ignores_excluded(seeded):
    ws, csv, archive = seeded
    run_cli("exclude.py", "--archive", archive, "--email", "p0@corp.com",
            "--reason", "test")
    out = run_cli("resolve.py", "--csv", csv, "--archive", archive, "--config",
                  ws / "config.yaml", "--out", ws / "out", "--fast",
                  "--as-of", "2026-01-01")
    assert "7 respondents" in out  # excluded one is not counted
