"""Compact results codes: Python round-trip, JS<->Python parity, ingest of
codes, and guards against decoding under a changed catalog/build."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from build_survey import build_payload, load_config
from tests.simulate import simulate_respondent, true_utilities
from ucsurvey import archive as arc
from ucsurvey import catalog as cat
from ucsurvey import compact

ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def payload():
    df = cat.load_catalog(ROOT / "data" / "use_cases.sample.csv")
    return build_payload(df, load_config(ROOT / "config.yaml"))


@pytest.fixture(scope="module")
def result(payload):
    util = true_utilities([it["id"] for it in payload["catalog"]])
    return simulate_respondent(payload, "codec@example.com", "Operator",
                               "Organization A", "short", util, seed=777,
                               abort_after=9)


def test_python_roundtrip(payload, result):
    code = compact.encode(result, payload)
    assert re.fullmatch(r"UCS1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", code)
    assert len(code) < 900  # must fit comfortably in a mailto: body

    decoded = compact.decode(code, payload)
    assert decoded["respondent"] == result["respondent"]
    assert decoded["sessionId"] == result["sessionId"]
    assert decoded["arm"] == result["arm"]
    # the decoder re-derives the shown screens; they must match exactly
    for orig, dec in zip(result["sets"], decoded["sets"]):
        assert dec["shown"] == orig["shown"]
        assert dec["best"] == orig["best"]
        assert dec["worst"] == orig["worst"]
        assert dec["skipped"] == orig["skipped"]
        assert abs(dec["responseMs"] - orig["responseMs"]) <= 50  # 100ms buckets


def test_skip_and_long_session_roundtrip(payload):
    util = true_utilities([it["id"] for it in payload["catalog"]])
    r = simulate_respondent(payload, "long@example.com", "Maintainer",
                            "Organization B", "long", util, seed=778)
    r["sets"][5]["skipped"] = True
    r["sets"][5]["best"] = r["sets"][5]["worst"] = None
    code = compact.encode(r, payload)
    assert len(code) < 1200  # 45 screens still fits mailto limits
    decoded = compact.decode(code, payload)
    assert decoded["sets"][5]["skipped"] is True
    assert decoded["sets"][5]["best"] is None
    assert [s["best"] for s in decoded["sets"]] == [s["best"] for s in r["sets"]]


def test_wrong_build_is_refused(payload, result):
    code = compact.encode(result, payload)
    tampered = dict(payload, continuationMaster=payload["continuationMaster"][::-1])
    with pytest.raises(compact.CodeError, match="different survey build"):
        compact.decode(code, tampered)


def test_ingest_reads_codes_from_txt(tmp_path, payload, result):
    import ingest as ingest_mod

    ws_csv = tmp_path / "use_cases.csv"
    df = cat.load_catalog(ROOT / "data" / "use_cases.sample.csv")
    cat.write_catalog_with_ids(df, ws_csv)

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    code = compact.encode(result, payload)
    (inbox / "saved_email.txt").write_text(
        f"From: someone\nSubject: results\n\nHello,\n\n{code}\n\nthanks!\n")

    rc = ingest_mod.main([str(inbox), "--csv", str(ws_csv),
                          "--config", str(ROOT / "config.yaml"),
                          "--archive", str(tmp_path / "archive")])
    assert rc == 0
    long_df = arc.load_archive(tmp_path / "archive")
    assert long_df["email"].nunique() == 1
    n_screens = long_df.drop_duplicates(["email", "session_id", "set_index"]).shape[0]
    assert n_screens == len(result["sets"])
