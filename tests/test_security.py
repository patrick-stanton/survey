"""Security / abuse-resistance regression tests.

Each test encodes one adversarial scenario from the red-team review and proves
the pipeline rejects it cleanly (a REJECTED line, never a crash or a hang, and
never poisoned data in the archive). These are the edge-case resilience proofs.
"""

import json
import time
from pathlib import Path

import pytest

from build_survey import build_payload, load_config
from tests.simulate import simulate_respondent, true_utilities
from ucsurvey import archive as arc
from ucsurvey import catalog as cat
from ucsurvey import compact

ROOT = Path(__file__).parent.parent
SAMPLE = ROOT / "data" / "use_cases.sample.csv"


@pytest.fixture(scope="module")
def payload():
    return build_payload(cat.load_catalog(SAMPLE), load_config(ROOT / "config.yaml"))


@pytest.fixture(scope="module")
def known_ids():
    return set(cat.load_catalog(SAMPLE)["id"])


@pytest.fixture(scope="module")
def chash():
    return cat.catalog_hash(cat.load_catalog(SAMPLE))


def valid_response(chash, ids, sets=2):
    ids = list(ids)[:4]
    return {
        "schemaVersion": 1, "tool": "ucsurvey", "sessionId": "sVALID",
        "respondent": {"name": "A", "email": "a@corp.com", "role": "Operator",
                       "organization": "Org A", "familiarity": 3},
        "catalogVersionHash": chash, "arm": "short", "designSeed": "x",
        "sets": [{"index": i, "shown": ids, "best": ids[0], "worst": ids[-1],
                  "skipped": False, "answeredAt": "", "responseMs": 3000}
                 for i in range(sets)],
    }


# ---------- untrusted result-file validation ----------

def test_wide_screen_injection_rejected(chash, known_ids):
    """One respondent listing all 60 items on a screen would explode into a
    full ordering and dominate the models — must be rejected."""
    bad = valid_response(chash, known_ids)
    all_ids = list(known_ids)
    bad["sets"][0]["shown"] = all_ids
    bad["sets"][0]["best"], bad["sets"][0]["worst"] = all_ids[0], all_ids[-1]
    with pytest.raises(arc.ResponseError, match="not a genuine survey screen"):
        arc.validate_response(bad, chash, known_ids, items_per_screen=4)


@pytest.mark.parametrize("field,value", [
    ("email", "a@corp.com\x1b[31mRED"), ("role", "Op\x07"),
    ("organization", "Org\x00A")])
def test_control_characters_rejected(chash, known_ids, field, value):
    bad = valid_response(chash, known_ids)
    bad["respondent"][field] = value
    with pytest.raises(arc.ResponseError, match="control characters"):
        arc.validate_response(bad, chash, known_ids, items_per_screen=4)


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(sets=5),                      # sets not a list
    lambda d: d.update(respondent=["not", "a", "dict"]),
    lambda d: d["sets"][0].update(index="oops"),     # non-int index
    lambda d: d["sets"][0].update(shown="ABCD"),     # shown not a list
])
def test_type_confusion_becomes_clean_rejection(chash, known_ids, mutate):
    bad = valid_response(chash, known_ids)
    mutate(bad)
    with pytest.raises(arc.ResponseError):  # never a bare TypeError/KeyError
        arc.validate_response(bad, chash, known_ids, items_per_screen=4)


# ---------- compact code decode hardening ----------

def test_huge_extrablocks_rejected_not_hung(payload):
    """A forged code with extraBlocks=10^11 must be rejected instantly, not
    spin an unbounded loop."""
    code = compact.encode(valid_response(payload["catalogVersionHash"],
                                         [it["id"] for it in payload["catalog"]]), payload)
    header_b64, body_b64 = code.split(".")[1], code.split(".")[2]
    header = json.loads(compact._b64url_decode(header_b64))
    header["x"] = 100_000_000_000
    forged = f"UCS1.{compact._b64url_encode(json.dumps(header).encode())}.{body_b64}"
    start = time.time()
    with pytest.raises(compact.CodeError, match="out of range"):
        compact.decode(forged, payload)
    assert time.time() - start < 1.0  # rejected fast, no allocation blowup


@pytest.mark.parametrize("x", ["abc", [1, 2], None, -1])
def test_bad_extrablocks_types_rejected(payload, x):
    ids = [it["id"] for it in payload["catalog"]]
    code = compact.encode(valid_response(payload["catalogVersionHash"], ids), payload)
    header = json.loads(compact._b64url_decode(code.split(".")[1]))
    header["x"] = x
    forged = f"UCS1.{compact._b64url_encode(json.dumps(header).encode())}.{code.split('.')[2]}"
    with pytest.raises(compact.CodeError):
        compact.decode(forged, payload)


def test_unknown_arm_rejected(payload):
    ids = [it["id"] for it in payload["catalog"]]
    code = compact.encode(valid_response(payload["catalogVersionHash"], ids), payload)
    header = json.loads(compact._b64url_decode(code.split(".")[1]))
    header["a"] = "no-such-arm"
    forged = f"UCS1.{compact._b64url_encode(json.dumps(header).encode())}.{code.split('.')[2]}"
    with pytest.raises(compact.CodeError, match="unknown arm"):
        compact.decode(forged, payload)


# ---------- batch resilience: one bad file can't sink the rest ----------

def test_one_poisoned_file_does_not_abort_batch(tmp_path, chash, known_ids):
    archive = tmp_path / "archive"
    report = arc.IngestReport()
    # 000 sorts first and is poison; 111 is a good file after it.
    (tmp_path / "000_poison.json").write_text("[" * 100000)  # deep/garbage
    good = valid_response(chash, known_ids)
    (tmp_path / "111_good.json").write_text(json.dumps(good))
    for f in sorted(tmp_path.glob("*.json")):
        arc.ingest_file(f, archive, chash, known_ids, report, items_per_screen=4)
    assert any("111_good" in n for n in report.accepted)   # good file survived
    assert any("000_poison" in n for n, _ in report.rejected)


def test_type_confusion_file_rejected_not_crash(tmp_path, chash, known_ids):
    archive = tmp_path / "archive"
    report = arc.IngestReport()
    (tmp_path / "r.json").write_text(json.dumps(
        {"sessionId": "s", "respondent": {"name": "a", "email": "a@b.com",
         "role": "r", "organization": "o", "familiarity": 1},
         "catalogVersionHash": chash, "arm": "short", "sets": 5}))
    arc.ingest_file(tmp_path / "r.json", archive, chash, known_ids, report,
                    items_per_screen=4)
    assert report.rejected and "list" in report.rejected[0][1]


# ---------- integrity: no silent overwrite of a recorded session ----------

def test_supersede_requires_append_only(tmp_path, chash, known_ids):
    archive = tmp_path / "archive"
    report = arc.IngestReport()
    original = valid_response(chash, known_ids, sets=2)
    arc.ingest_file(_drop(tmp_path, original, "a.json"), archive, chash,
                    known_ids, report, items_per_screen=4)
    assert report.accepted

    # Tampered: same session, MORE sets, but flips an earlier screen's picks.
    tampered = valid_response(chash, known_ids, sets=3)
    ids = tampered["sets"][0]["shown"]
    tampered["sets"][0]["best"], tampered["sets"][0]["worst"] = ids[-1], ids[0]  # flipped
    arc.ingest_file(_drop(tmp_path, tampered, "b.json"), archive, chash,
                    known_ids, report, items_per_screen=4)
    assert any("not an append-only" in reason for _, reason in report.rejected)
    # archive still holds the honest 2-set original
    stored = json.loads(next(archive.glob("*.json")).read_text())
    assert len(stored["sets"]) == 2


def test_genuine_longer_reexport_accepted(tmp_path, chash, known_ids):
    archive = tmp_path / "archive"
    report = arc.IngestReport()
    arc.ingest_file(_drop(tmp_path, valid_response(chash, known_ids, sets=2), "a.json"),
                    archive, chash, known_ids, report, items_per_screen=4)
    arc.ingest_file(_drop(tmp_path, valid_response(chash, known_ids, sets=4), "b.json"),
                    archive, chash, known_ids, report, items_per_screen=4)
    assert report.replaced  # honest superset accepted
    stored = json.loads(next(archive.glob("*.json")).read_text())
    assert len(stored["sets"]) == 4


# ---------- Sybil control: roster allowlist ----------

def test_roster_rejects_uninvited_email(tmp_path, chash, known_ids):
    archive = tmp_path / "archive"
    report = arc.IngestReport()
    roster = {"invited@corp.com"}
    outsider = valid_response(chash, known_ids)
    outsider["respondent"]["email"] = "fake17@corp.com"
    arc.ingest_file(_drop(tmp_path, outsider, "x.json"), archive, chash,
                    known_ids, report, items_per_screen=4, roster=roster)
    assert any("not on the invited roster" in r for _, r in report.rejected)


def _drop(tmp_path, data, name):
    p = tmp_path / name
    p.write_text(json.dumps(data))
    return p
