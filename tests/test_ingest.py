"""Ingest + archive behavior on the CSV/active-archive pipeline."""

import copy
from pathlib import Path

import pytest

from build_survey import build_payload, load_config
from tests.simulate import simulate_respondent, true_utilities
from ucsurvey import archive as arc
from ucsurvey import catalog as cat
from ucsurvey import csv_result

ROOT = Path(__file__).parent.parent
SAMPLE = ROOT / "data" / "use_cases.sample.csv"


@pytest.fixture(scope="module")
def payload():
    return build_payload(cat.load_catalog(SAMPLE), load_config(ROOT / "config.yaml"))


@pytest.fixture(scope="module")
def env(payload):
    ids = [it["id"] for it in payload["catalog"]]
    util = true_utilities(ids)
    return {
        "payload": payload, "ids": ids, "util": util,
        "hash": payload["catalogVersionHash"], "known": set(ids),
    }


def a_response(env, email="a@corp.com", seed=1, arm="short", n=None):
    r = simulate_respondent(env["payload"], email, "Operator", "Org A", arm,
                            env["util"], seed=seed, abort_after=n)
    return r


def test_ingest_writes_csv_and_loads_back(tmp_path, env):
    archive = tmp_path / "archive"
    report = arc.IngestReport()
    r = a_response(env)
    arc.validate_response(r, env["hash"], env["known"], items_per_screen=4)
    arc.verify_screens_against_design(r, env["payload"])
    arc.ingest_result(r, arc.active_dir(archive), report, "a.csv")
    assert report.accepted
    # stored as CSV
    stored = list((archive / "active").glob("*.csv"))
    assert len(stored) == 1
    long_df = arc.load_archive(archive)
    assert long_df["email"].nunique() == 1


def test_append_only_supersede(tmp_path, env):
    archive = tmp_path / "archive"
    active = arc.active_dir(archive)
    report = arc.IngestReport()
    short = a_response(env, seed=2, n=6)
    arc.ingest_result(short, active, report, "s.csv")
    assert report.accepted

    longer = a_response(env, seed=2, n=12)   # same person+session, more screens
    longer["sessionId"] = short["sessionId"]
    arc.ingest_result(longer, active, report, "l.csv")
    assert report.replaced
    assert len(arc.load_archive(archive).drop_duplicates(
        ["email", "session_id", "set_index"])) == 12

    stale = a_response(env, seed=2, n=3)
    stale["sessionId"] = short["sessionId"]
    arc.ingest_result(stale, active, report, "stale.csv")
    assert any("older than archived" in why for _, why in report.rejected)


def test_tampered_reexport_rejected(tmp_path, env):
    archive = tmp_path / "archive"
    active = arc.active_dir(archive)
    report = arc.IngestReport()
    orig = a_response(env, seed=3, n=6)
    arc.ingest_result(orig, active, report, "a.csv")

    tampered = copy.deepcopy(orig)
    tampered["sets"].append(a_response(env, seed=3)["sets"][6])  # one more screen
    # flip an earlier screen's picks
    tampered["sets"][0]["best"], tampered["sets"][0]["worst"] = (
        tampered["sets"][0]["worst"], tampered["sets"][0]["best"])
    arc.ingest_result(tampered, active, report, "t.csv")
    assert any("not an append-only" in why for _, why in report.rejected)
    stored = csv_result.parse_csv(next((archive / "active").glob("*.csv")).read_text())
    assert len(stored["sets"]) == 6  # original preserved


def test_full_cli_ingest_csv_and_email_body(tmp_path, env):
    import ingest as ingest_mod
    ws_csv = tmp_path / "use_cases.csv"
    cat.write_catalog_with_ids(cat.load_catalog(SAMPLE), ws_csv)
    inbox = tmp_path / "inbox"
    inbox.mkdir()

    # one CSV file, one CSV pasted in an email body (.txt)
    r1 = a_response(env, email="p1@corp.com", seed=11)
    (inbox / "p1.csv").write_text(csv_result.build_csv(r1))
    r2 = a_response(env, email="p2@corp.com", seed=12)
    (inbox / "p2_email.txt").write_text(
        "From: p2\nSubject: results\n\nhere:\n\n" + csv_result.build_csv(r2))

    rc = ingest_mod.main([str(inbox), "--csv", str(ws_csv),
                          "--config", str(ROOT / "config.yaml"),
                          "--archive", str(tmp_path / "archive")])
    assert rc == 0
    assert arc.load_archive(tmp_path / "archive")["email"].nunique() == 2


def test_fabricated_screens_rejected(env):
    r = a_response(env, seed=4)
    r["sets"][0]["shown"] = list(env["ids"][:4])  # not what this respondent saw
    r["sets"][0]["best"], r["sets"][0]["worst"] = env["ids"][0], env["ids"][3]
    with pytest.raises(arc.ResponseError, match="never presented"):
        arc.verify_screens_against_design(r, env["payload"])


def test_checksum_mismatch_flagged(env):
    r = a_response(env, seed=5)
    text = csv_result.build_csv(r)
    tampered = text.replace("Operator", "Manager")  # edit a field, checksum now stale
    parsed = csv_result.parse_csv(tampered)
    assert parsed["checksumOk"] is False
