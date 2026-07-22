import json
from pathlib import Path

import pytest

from ucsurvey import archive as arc


def response(session="s1", email="a@x.com", n_sets=2, hash_="cathash123", items=None):
    items = items or ["A", "B", "C", "D"]
    return {
        "schemaVersion": 1, "tool": "ucsurvey", "sessionId": session,
        "respondent": {"name": "A", "email": email, "role": "Op",
                       "organization": "OrgA", "familiarity": 3},
        "catalogVersionHash": hash_, "arm": "short", "designSeed": "x",
        "startedAt": "2026-01-01T00:00:00Z",
        "sets": [
            {"index": i, "shown": items, "best": items[0], "worst": items[-1],
             "skipped": False, "answeredAt": "", "responseMs": 3000}
            for i in range(n_sets)
        ],
    }


def drop(tmp_path, data, name="r.json"):
    p = tmp_path / name
    p.write_text(json.dumps(data))
    return p


KNOWN = {"A", "B", "C", "D"}


def test_accept_then_supersede_then_refuse_older(tmp_path):
    inbox, archive = tmp_path / "inbox", tmp_path / "archive"
    inbox.mkdir()
    rep = arc.IngestReport()

    arc.ingest_file(drop(inbox, response(n_sets=2)), archive, "cathash123", KNOWN, rep)
    assert len(rep.accepted) == 1

    # same session, more screens (respondent kept going) -> replaces
    arc.ingest_file(drop(inbox, response(n_sets=5), "r2.json"),
                    archive, "cathash123", KNOWN, rep)
    assert len(rep.replaced) == 1

    # stale smaller export shows up later -> refused, archive untouched
    arc.ingest_file(drop(inbox, response(n_sets=1), "r3.json"),
                    archive, "cathash123", KNOWN, rep)
    assert len(rep.rejected) == 1 and "older" in rep.rejected[0][1]

    long_df = arc.load_archive(archive)
    assert long_df.drop_duplicates(["email", "session_id", "set_index"]).shape[0] == 5


def test_catalog_mismatch_refused_unless_allowed(tmp_path):
    archive = tmp_path / "archive"
    rep = arc.IngestReport()
    f = drop(tmp_path, response(hash_="oldhash"))
    arc.ingest_file(f, archive, "newhash", KNOWN, rep)
    assert "catalog version mismatch" in rep.rejected[0][1]

    rep2 = arc.IngestReport()
    arc.ingest_file(f, archive, "newhash", KNOWN, rep2, allow_hashes={"oldhash"})
    assert rep2.accepted


def test_corrupt_answers_refused(tmp_path):
    archive = tmp_path / "archive"
    bad = response()
    bad["sets"][0]["best"] = "NOT-SHOWN"
    rep = arc.IngestReport()
    arc.ingest_file(drop(tmp_path, bad), archive, "cathash123", KNOWN, rep)
    assert "best/worst not among shown" in rep.rejected[0][1]


def test_lineage_inherit_and_strict(tmp_path):
    archive = tmp_path / "archive"
    rep = arc.IngestReport()
    old = response(items=["OLD-1", "B", "C", "D"], hash_="oldhash")
    arc.ingest_file(drop(tmp_path, old), archive, "oldhash", KNOWN | {"OLD-1"}, rep)
    long_df = arc.load_archive(archive)

    # OLD-1 was merged into NEW-9
    current = {"NEW-9", "B", "C", "D"}
    strict = arc.apply_lineage(long_df, {"OLD-1": "NEW-9"}, current, "strict")
    assert "OLD-1" not in set(strict["item_id"])
    assert "NEW-9" not in set(strict["item_id"])  # strict drops, never remaps

    inherit = arc.apply_lineage(long_df, {"OLD-1": "NEW-9"}, current, "inherit")
    assert "NEW-9" in set(inherit["item_id"])
    # OLD-1 was the 'best' pick; its vote now belongs to NEW-9
    assert (inherit[inherit["item_id"] == "NEW-9"]["pick"] == "best").all()


def test_lineage_merge_collapse_keeps_one_row(tmp_path):
    archive = tmp_path / "archive"
    rep = arc.IngestReport()
    old = response(items=["OLD-1", "OLD-2", "C", "D"], hash_="h")
    old["sets"] = old["sets"][:1]
    old["sets"][0]["best"] = "OLD-1"
    old["sets"][0]["worst"] = "D"
    arc.ingest_file(drop(tmp_path, old), archive, "h",
                    {"OLD-1", "OLD-2", "C", "D"}, rep)
    long_df = arc.load_archive(archive)
    # both OLD-1 and OLD-2 merged into NEW-9: the set can only keep one row
    merged = arc.apply_lineage(
        long_df, {"OLD-1": "NEW-9", "OLD-2": "NEW-9"}, {"NEW-9", "C", "D"}, "inherit")
    per_set = merged[merged["item_id"] == "NEW-9"]
    assert len(per_set) == 1
    assert per_set.iloc[0]["pick"] == "best"  # the informative row wins
